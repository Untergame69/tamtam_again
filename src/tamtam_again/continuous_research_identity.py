"""Trading evidence identities independent of receipts, policies and other markets."""
import json
import re
from .engine import fingerprint

ECONOMIC_DETAIL_FIELDS = ('execution_activity', 'position_path', 'by_utc_day', 'fees_signed_by_token')


def market_content(packet, market):
    details = packet.get('observations', {}).get('market_execution_detail_v1', {})
    detail = details.get(market) if isinstance(details, dict) else None
    if not isinstance(detail, dict) or detail.get('market') != market:
        raise ValueError('Exact per-market execution detail required for semantic identity')
    if not all(key in detail for key in ECONOMIC_DETAIL_FIELDS):
        raise ValueError('Complete per-market economic projection required')
    # Coverage receipt counts, duplicate counts, reference indices and provenance
    # fingerprints must not turn an equivalent page receipt into market evidence.
    return {key: detail[key] for key in ECONOMIC_DETAIL_FIELDS}


def wake_identities(packet):
    """Identities of provenance-checked account-wide requested-history proofs.

    ``packet_for_account`` obtains these from ``export_wakes``, which verifies
    persisted plans, reservations, raw pages and request intervals. References
    and the proof hash are checked again here: arbitrary added wake text cannot
    act as new evidence. Request contracts currently have account scope, so a
    complete pagination proof also establishes coverage/absence for each market.
    """
    wakes = packet.get('observations', {}).get('completed_observation_requests', [])
    if not isinstance(wakes, list):
        raise ValueError('Verified completed observation requests required')
    pool = packet.get('evidence_refs', [])
    identities = set()
    for wake in wakes:
        if not isinstance(wake, dict):
            raise ValueError('Verified wake record required')
        evidence = wake.get('evidence')
        pages = wake.get('pages')
        if (not isinstance(evidence, dict) or fingerprint(evidence) != wake.get('evidence_fingerprint')
                or evidence.get('promotion_authorized') is not False
                or evidence.get('economic_completeness_proven') is not False
                or 'research_observation_wakes:' + str(wake.get('request_id')) not in pool
                or not isinstance(pages, list) or not pages):
            raise ValueError('Wake identity lacks verified proof and packet provenance')
        proofs = evidence.get('proofs')
        if not isinstance(proofs, list) or not proofs:
            raise ValueError('Complete requested-history proofs required')
        page_refs = {page.get('evidence_ref') for page in pages if isinstance(page, dict)}
        expected_refs = set()
        for proof in proofs:
            if not isinstance(proof, dict) or not isinstance(proof.get('source_request'), dict):
                raise ValueError('Verified source request required')
            request = proof['source_request']
            if (request.get('source') != 'public_rest_history'
                    or request.get('endpoint') not in {'userFillsByTime', 'userFunding', 'userNonFundingLedgerUpdates'}
                    or request.get('proof') != 'pagination_coverage'
                    or proof.get('pagination_status') != 'covered'
                    or not isinstance(proof.get('evidence_refs'), list)):
                raise ValueError('Verified supported pagination proof required')
            expected_refs.update(proof['evidence_refs'])
        if not expected_refs or page_refs != expected_refs or not page_refs <= set(pool):
            raise ValueError('Wake pages must match verified proof references in packet')
        identities.add(wake['evidence_fingerprint'])
    return sorted(identities)


def evaluation_evidence_identity(packet):
    """Stable terminal evaluation facts from reservation-checked typed export.

    Publication times, lifecycle diagnostics, descriptive conclusions and next
    directives are metadata. Only a completed validation evaluation constitutes
    new evidence here. ``export_memory`` owns account/source-period authority.
    """
    records = packet.get('research_evaluation_memory', [])
    if not isinstance(records, list):
        raise ValueError('Typed exported evaluation memory required')
    outcomes = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError('Typed exported evaluation memory record required')
        item = record.get('item')
        if not isinstance(item, dict):
            raise ValueError('Typed exported evaluation memory item required')
        evaluations = item.get('evidence', {}).get('evaluations', [])
        if not evaluations:
            continue
        event_id = record.get('event_id')
        if (item.get('version') != 'research-evaluation-memory-v1'
                or item.get('profitability_proven') is not False
                or not isinstance(event_id, str) or not event_id
                or item.get('evaluation_event_id') != event_id
                or {'kind': 'research_evaluation', 'id': event_id} not in record.get('evidence_refs', [])
                or not isinstance(evaluations, list)):
            raise ValueError('Verified typed evaluation proof required')
        for evaluation in evaluations:
            if not isinstance(evaluation, dict):
                raise ValueError('Typed validation evaluation required')
            identity, status = evaluation.get('evaluation_id'), evaluation.get('status')
            if status in {'passed', 'failed', 'error'}:
                if not isinstance(identity, str) or not identity:
                    raise ValueError('Terminal evaluation identity required')
                outcomes.add((identity, status))
    return sorted(outcomes)


def inactive_paper_evidence_identity(packet):
    """Economic/diagnostic facts of inactive paper sessions from typed export.

    Source-period authority is checked by ``export_memory``. Its end timestamp
    and publication metadata are not a change in economic observations.
    """
    from .engine import canonical
    outcomes = set()
    fields = ('session_id','status','position','pending','pending_count','complete_flat_state',
              'diagnostics','net_pnl','realized_pnl','fees','funding','cash')
    for record in packet.get('research_evaluation_memory', []):
        if not isinstance(record, dict) or not isinstance(record.get('item'), dict):
            raise ValueError('Typed exported paper feedback required')
        item = record['item']
        sessions = item.get('evidence', {}).get('sessions', [])
        if not sessions:
            continue
        event_id = record.get('event_id')
        if (item.get('version') != 'research-evaluation-memory-v1'
                or item.get('profitability_proven') is not False
                or not isinstance(event_id, str) or not event_id
                or item.get('evaluation_event_id') != event_id
                or {'kind': 'research_evaluation', 'id': event_id} not in record.get('evidence_refs', [])
                or not isinstance(sessions, list)):
            raise ValueError('Verified typed paper feedback proof required')
        for session in sessions:
            if not isinstance(session, dict):
                raise ValueError('Typed paper session required')
            if session.get('status') == 'active':
                continue
            if not isinstance(session.get('status'), str) or not session['status'] or not session.get('session_id'):
                raise ValueError('Exact inactive paper session identity required')
            outcomes.add(canonical({key:session[key] for key in fields if key in session}))
    return sorted(outcomes)


def semantic_identity(packet, market):
    content = market_content(packet, market)
    detail = packet['observations']['market_execution_detail_v1'][market]
    checksum = detail.get('observed_fill_content_fingerprint')
    if not isinstance(checksum, str) or not checksum:
        raise ValueError('Exact deduplicated per-market fill-content fingerprint required')
    identity = {'network': packet['network'], 'address': packet['address'].lower(),
        'market': market, 'question_version': 'observable-mechanism-v1',
        'fill_content': checksum, 'market_content': content, 'observation_wakes': wake_identities(packet)}
    evaluations = evaluation_evidence_identity(packet)
    if evaluations:identity['evaluation_outcomes'] = evaluations
    paper = inactive_paper_evidence_identity(packet)
    if paper:identity['inactive_paper_outcomes'] = paper
    return fingerprint(identity)


def _legacy_fill_identity(store, packet, market):
    """Reconstruct exact legacy fill content from its sealed page references only.

    Old adapters did not include a per-market fill checksum. Reopening those
    pages requires current reservation authorization; failure falls back to the
    conservative aggregate comparison, never a speculative inference retry.
    """
    from .discovery import protected_addresses
    from .research_memory import authorized_account_history
    detail = packet.get('observations', {}).get('market_execution_detail_v1', {}).get(market, {})
    cutoff = detail.get('cutoff_ms')
    network, address = packet.get('network'), str(packet.get('address', '')).lower()
    if address in protected_addresses(store) or not authorized_account_history(store, network, address, cutoff):
        return None
    refs = detail.get('evidence_refs')
    if refs is None:
        pool = packet.get('evidence_refs', [])
        indices = detail.get('evidence_ref_indices', [])
        if not indices or any(type(i) is not int or not 0 <= i < len(pool) for i in indices):
            return None
        refs = [pool[i] for i in indices]
    if not isinstance(refs, list) or not refs:
        return None
    from .population_descriptive import _decode_verified, _get_fill_array
    from .account_adapter import millis
    variants = {}
    from .engine import canonical
    for ref in refs:
        match = re.fullmatch(r'raw_observations:(\d+)#sha256:([a-f0-9]{64})', ref) if isinstance(ref, str) else None
        if not match:
            return None
        row = store.connection.execute('select * from raw_observations where observation_id=?', (int(match[1]),)).fetchone()
        if (not row or row['response_sha256'] != match[2] or row['network'] != network
                or row['entity_id'].lower() != address or row['entity_type'] != 'account'
                or row['source'] != 'hyperliquid-population-rest-v1'
                or millis(row['observed_at']) > cutoff
                or (row['window_end_ms'] is not None and row['window_end_ms'] > cutoff)
                or row['endpoint'] not in {'userFills', 'userFillsByTime'}):
            return None
        for fill in _get_fill_array(_decode_verified(row)):
            if not isinstance(fill, dict) or fill.get('tid') is None or type(fill.get('time')) is not int or fill['time'] > cutoff:
                continue
            variants.setdefault(str(fill['tid']), {})[canonical(fill)] = fill
    fills = [next(iter(v.values())) for v in variants.values() if len(v) == 1]
    fills = [f for f in fills if f.get('coin') == market]
    fills.sort(key=lambda f: (f['time'], str(f['coin']), str(f['tid'])))
    return fingerprint(fills)


def prior_equivalent(store, network, address, market, packet):
    """Return a matching preserved job (including failed attempts), or None.

    Both continuous and historical pilot jobs are inspected. Every comparison
    uses one instrument only. Missing legacy hashes trigger exact source-page
    reconstruction where permitted, otherwise conservative aggregate dedup.
    """
    current = semantic_identity(packet, market)
    has_continuous = bool(store.connection.execute(
        "select 1 from sqlite_master where name='continuous_research_tasks'").fetchone())
    if has_continuous:
        # This permanent unique index is the authoritative identity for every
        # continuous attempt. Do not deserialize years of 225k-character packets
        # merely to rediscover the identity already stored at admission.
        exact = store.connection.execute('select t.request_id,j.status from continuous_research_tasks t '
            'join population_research_jobs j using(request_id) '
            'where t.network=? and t.address=? and t.market=? and t.semantic_fingerprint=?',
            (network, address.lower(), market, current)).fetchone()
        if exact:
            return {'request_id': exact['request_id'], 'source_status': exact['status'],
                'semantic_fingerprint': current, 'legacy_aggregate_fallback': False}
    projection = market_content(packet, market)
    current_hash = packet['observations']['market_execution_detail_v1'][market]['observed_fill_content_fingerprint']
    current_wakes = wake_identities(packet)
    current_evaluations = evaluation_evidence_identity(packet)
    current_paper = inactive_paper_evidence_identity(packet)
    legacy_filter = (' and not exists(select 1 from continuous_research_tasks t '
        'where t.request_id=j.request_id)' if has_continuous else '')
    for row in store.connection.execute('select j.request_id,j.status,j.packet_json from population_research_jobs j '
            'where j.network=? and j.address=?' + legacy_filter + ' order by j.created_ms,j.request_id',
            (network, address.lower())):
        try:
            old = json.loads(row['packet_json'])
            old_projection = market_content(old, market)
            old_wakes = wake_identities(old)
            old_evaluations = evaluation_evidence_identity(old)
            old_paper = inactive_paper_evidence_identity(old)
        except (TypeError, ValueError, KeyError):
            continue
        if (old_projection != projection or old_wakes != current_wakes
                or old_evaluations != current_evaluations or old_paper != current_paper):
            continue
        old_hash = old['observations']['market_execution_detail_v1'][market].get('observed_fill_content_fingerprint')
        if old_hash is None:
            try:
                old_hash = _legacy_fill_identity(store, old, market)
            except (ValueError, PermissionError, KeyError):
                old_hash = None
        if old_hash is not None and old_hash != current_hash:
            continue
        return {'request_id': row['request_id'], 'source_status': row['status'],
            'semantic_fingerprint': current, 'legacy_aggregate_fallback': old_hash is None}
    return None
