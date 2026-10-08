"""Bounded, resumable public history pages; pagination is not retention proof."""
from __future__ import annotations
import json
from typing import Any
from .storage import Store, utc_now
from .discovery import protected_addresses

ENDPOINTS = ('userFillsByTime', 'userFunding', 'userNonFundingLedgerUpdates')
SCHEMA = '''CREATE TABLE IF NOT EXISTS population_history_cursors (
 network TEXT NOT NULL,address TEXT NOT NULL,endpoint TEXT NOT NULL,
 cursor_ms INTEGER NOT NULL,target_end_ms INTEGER,status TEXT NOT NULL,
 updated_at TEXT NOT NULL,evidence_json TEXT NOT NULL,
 PRIMARY KEY(network,address,endpoint));'''

def collect_history(store: Store, client: Any, job: dict[str, Any], endpoint: str,
                    end_ms: int, *, cursor_scope: str | None = None,
                    requested_start_ms: int | None = None, as_of_ms: int | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Keep boundary timestamps inclusive; never skip a saturated timestamp.

    Each endpoint retains its own backlog target. A new endpoint starts with
    the configured lookback, independently of an old fill-only job's success.
    Raw pages commit before cursors: a crash may replay a page, never lose it.
    """
    if endpoint not in ENDPOINTS:
        raise ValueError('Unsupported population history endpoint')
    address = job['address'].lower()
    if address in protected_addresses(store):
        raise ValueError('Reserved pilot account excluded from history research')
    if cursor_scope is not None:
        if not isinstance(cursor_scope,str) or len(cursor_scope)!=64 or any(c not in '0123456789abcdef' for c in cursor_scope):raise ValueError('Immutable scoped history identity required')
        if type(requested_start_ms) is not int or not 0<=requested_start_ms<end_ms:raise ValueError('Explicit scoped history interval required')
        from .research_memory import authorized_period
        period={'network':job['network'],'address':address,'market':'*','start_ms':requested_start_ms,'end_ms':end_ms}
        if type(as_of_ms) is not int or not authorized_period(store,period,as_of_ms,end_inclusive=True):raise ValueError('Authorized available scoped history period required')
    elif requested_start_ms is not None:raise ValueError('History start requires scoped cursor')
    cursor_key=endpoint if cursor_scope is None else 'need:'+cursor_scope+':'+endpoint
    max_pages = job['policy'].get('history_max_pages_per_endpoint', 3)
    if type(max_pages) is not int or not 1 <= max_pages <= 6:
        raise ValueError('History page budget must be between one and six')
    store.connection.executescript(SCHEMA)
    row = store.connection.execute(
        'select * from population_history_cursors where network=? and address=? and endpoint=?',
        (job['network'], address, cursor_key)).fetchone()
    cursor = row['cursor_ms'] if row else requested_start_ms if cursor_scope is not None else max(0, end_ms-job['policy']['initial_lookback_seconds']*1000)
    target = row['target_end_ms'] if row and row['target_end_ms'] is not None else end_ms
    if not 0 <= cursor <= target <= end_ms:
        raise ValueError('History window must end no later than current request time')
    start = cursor
    phase = 'incremental' if row and row['status'] == 'pagination_exhausted' else 'history_backfill'
    collected = []; pages = []; status = 'page_budget_exhausted'
    for page_number in range(max_pages):
        # A stale worker must not change cursors after another worker took its lease.
        lease = store.connection.execute(
            'select lease_token from population_accounts where network=? and address=?',
            (job['network'], address)).fetchone()
        if not lease or lease['lease_token'] != job['lease_token']:
            raise ValueError('Stale population history lease')
        query = {'type': endpoint, 'user': address, 'startTime': cursor, 'endTime': target}
        requested = utc_now()
        previous_task = getattr(client, 'task', None)
        if previous_task is not None:
            client.task = 'population-rest-' + phase
        try:
            rows = client.post_info(query)
        finally:
            if previous_task is not None: client.task = previous_task
        if not isinstance(rows, list):
            raise ValueError('Invalid public history response')
        valid = all(isinstance(r, dict) and type(r.get('time')) is int
                    and cursor <= r['time'] <= target for r in rows)
        stamps = [r['time'] for r in rows] if valid else []
        # General API limit is 500 elements OR blocks; fills may contain 2000.
        # Treat >=500 as potentially saturated even when below the fill row cap.
        saturated = len(rows) >= 500
        next_cursor = max(stamps) if stamps else cursor
        if not valid:
            status = 'invalid_response_window'
        elif not saturated:
            status = 'pagination_exhausted'; next_cursor = target
        elif next_cursor <= cursor:
            status = 'saturated_timestamp_unresolvable'
        else:
            status = 'page_budget_exhausted'
        request_meta = {**query, 'transport': 'rest', 'phase': phase,
                        'history_version': 3, 'page_number': page_number,
                        'coverage_status': 'pagination_only_retention_unknown',
                        'pagination_status': status,
                        'covered_until_ms': next_cursor if status in ('pagination_exhausted', 'page_budget_exhausted') else None}
        if cursor_scope is not None:request_meta['research_need_id']=cursor_scope
        store.save_observation(network=job['network'], source='hyperliquid-population-rest-v1',
            entity_type='account', entity_id=address, endpoint=endpoint, payload=rows,
            request_payload=request_meta, requested_at=requested, window_start_ms=cursor,
            window_end_ms=target, record_count=len(rows), complete=False)
        evidence = {'request': query, 'requested_at': requested, 'rows': len(rows),
                    'status': status, 'next_cursor_ms': next_cursor}
        # Check ownership under a write lock after saving the raw observation.
        store.connection.execute('begin immediate')
        try:
            current = store.connection.execute(
                'select lease_token from population_accounts where network=? and address=?',
                (job['network'], address)).fetchone()
            if not current or current['lease_token'] != job['lease_token']:
                raise ValueError('Stale population history lease')
            store.connection.execute('insert into population_history_cursors values (?,?,?,?,?,?,?,?) '
                'on conflict(network,address,endpoint) do update set cursor_ms=excluded.cursor_ms,'
                'target_end_ms=excluded.target_end_ms,status=excluded.status,'
                'updated_at=excluded.updated_at,evidence_json=excluded.evidence_json',
                (job['network'], address, cursor_key, next_cursor,
                 None if status == 'pagination_exhausted' else target,
                 status, utc_now(), json.dumps(evidence, sort_keys=True)))
            store.connection.commit()
        except BaseException:
            store.connection.rollback(); raise
        pages.append(evidence)
        if valid: collected.extend(rows)
        cursor = next_cursor
        if status != 'page_budget_exhausted': break
    # Repeated inclusive boundary rows remain archived, but count activity once.
    unique = {json.dumps(r, sort_keys=True, separators=(',', ':')): r for r in collected}
    return list(unique.values()), {'endpoint': endpoint, 'start_ms': start, 'end_ms': target,
        'cursor_ms': cursor, 'phase': phase, 'pagination_status': status, 'pages': pages,
        'coverage_status': 'unknown', 'retention_proven': False,
        'reason': 'Pagination cannot prove absent historical events or retained prefix completeness'}
