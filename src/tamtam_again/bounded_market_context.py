"""Bounded strict-prefill public context, with lossless cached descriptive proofs.

The source clock join is descriptive. A quote before an exchange fill does not
establish what either the trader or a follower knew before making a decision.
"""
from bisect import bisect_left
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import json
import sqlite3
import time
import zlib

from .engine import canonical, fingerprint
from .population_descriptive import _load_fills
from . import population_descriptive
from .population_local_join import _decode_verified, _event_iso, _ms, _quote_values, _ranked
from .research_memory import authorized_account_history
from .validation import now_ms

VERSION = 'bounded-market-context-v3'
DEFAULT_LIMITS = {
    'fill_window_ms': 86_400_000, 'quote_lookback_ms': 300_000,
    'max_fill_pages': 2_000, 'max_fill_records': 500_000,
    'max_fill_decoded_bytes': 64_000_000, 'max_fills_in_window': 30_000,
    'max_quote_lots_per_feed': 300_000, 'max_quote_events_per_feed': 1_500_000,
    'max_quote_decoded_bytes_per_feed': 256_000_000,
    'max_decoded_bytes_per_lot': 4_000_000, 'max_duration_ms': 60_000,
}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS bounded_market_context_fill_cache (
 input_fingerprint TEXT PRIMARY KEY, payload BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS bounded_market_context_results (
 result_fingerprint TEXT PRIMARY KEY, input_fingerprint TEXT UNIQUE NOT NULL,
 semantic_fingerprint TEXT NOT NULL, summary_json TEXT NOT NULL, payload BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS bounded_market_context_scopes (
 result_fingerprint TEXT PRIMARY KEY, network TEXT NOT NULL, address TEXT NOT NULL,
 market TEXT NOT NULL, evidence_cutoff_ms INTEGER NOT NULL);
'''


class ContextBoundError(ValueError):
    """A resource refusal; no partial context statistics are published."""


class _Budget:
    def __init__(self, duration_ms):
        self.deadline = time.monotonic() + duration_ms/1000

    def expired(self):
        return time.monotonic() >= self.deadline

    def check(self):
        if self.expired():
            raise ContextBoundError('Market-context time limit exceeded; no partial context was retained')


def _limits(overrides):
    value = {**DEFAULT_LIMITS, **(overrides or {})}
    if set(value) != set(DEFAULT_LIMITS) or any(type(v) is not int or v < 1 for v in value.values()):
        raise ValueError('Positive explicit bounded context limits required')
    return value


def _rows(store, where, params, limit, budget):
    budget.check()
    # Metadata scans can span a high-rate archive even when few lots match.
    # Interrupt SQLite itself at the same wall-clock resource boundary.
    store.connection.set_progress_handler(lambda: int(budget.expired()), 10_000)
    try:
        rows = store.connection.execute(
            'select observation_id,response_sha256,observed_at,requested_at,window_start_ms,'
            'window_end_ms,record_count,complete,endpoint from raw_observations where '
            + where + ' order by observation_id limit ?', (*params, limit + 1)).fetchall()
    except sqlite3.OperationalError as exc:
        if budget.expired():
            raise ContextBoundError('Market-context metadata time limit exceeded; no partial context was retained') from exc
        raise
    finally:
        store.connection.set_progress_handler(None, 0)
    budget.check()
    if len(rows) > limit:
        raise ContextBoundError('Archived lot limit exceeded; no partial context was retained')
    return [dict(row) for row in rows]


def _raw(store, meta):
    row = store.connection.execute('select * from raw_observations where observation_id=?',
        (meta['observation_id'],)).fetchone()
    if row is None or row['response_sha256'] != meta['response_sha256']:
        raise ValueError('Context archive identity changed')
    return row


def _fill_sources(store, network, address, cutoff, limits, budget):
    return _rows(store,
        "network=? and source='hyperliquid-population-rest-v1' and entity_type='account' "
        "and entity_id=? and endpoint in ('userFills','userFillsByTime') and observed_at<=? "
        'and (window_end_ms is null or window_end_ms<=?)',
        (network, address, _event_iso(cutoff), cutoff), limits['max_fill_pages'], budget)


def _fills(store, network, address, market, cutoff, limits, sources, budget):
    budget.check()
    key = fingerprint({'version': VERSION, 'kind': 'fills', 'network': network,
        'address': address, 'sources': sources, 'limits': limits})
    row = store.connection.execute('select payload from bounded_market_context_fill_cache '
        'where input_fingerprint=?', (key,)).fetchone()
    if row:
        cached = json.loads(zlib.decompress(row[0]))
        # An unchanged page may contain an event later than an older cutoff.
        # Cache reuse is valid only until the next such event becomes eligible.
        until = cached.get('valid_through_ms')
        if cached['prepared_cutoff_ms'] <= cutoff and (until is None or cutoff <= until):
            budget.check()
            return cached, True
    # Bound decompression before reusing the existing account-wide deduplicator.
    # The duplicate decoding is intentional: the legacy helper has no byte cap.
    size = records = 0
    receipts = {}
    next_future_event = None
    for meta in sources:
        budget.check()
        payload, decoded = _decode_verified(_raw(store, meta),
            max_decoded_bytes=limits['max_decoded_bytes_per_lot'], with_size=True)
        size += decoded
        values = (payload if isinstance(payload, list) else payload.get('data', {}).get('fills', [])
            if isinstance(payload, dict) and isinstance(payload.get('data'), dict)
            else payload.get('fills', payload.get('data', [])) if isinstance(payload, dict) else [])
        records += len(values) if isinstance(values, list) else 0
        for index, fill in enumerate(values if isinstance(values, list) else []):
            if index % 256 == 0: budget.check()
            if (isinstance(fill, dict) and fill.get('tid') is not None
                    and isinstance(fill.get('coin'), str) and type(fill.get('time')) is int):
                if fill['time'] > cutoff:
                    next_future_event = min(next_future_event or fill['time'], fill['time'])
                    continue
                receipt = {'rest_page_request_started_ms': _ms(meta['requested_at']),
                    'rest_page_received_ms': None,
                    'rest_page_received_status': 'unknown; requested_at starts the request, observed_at bounds availability',
                    'rest_page_archived_ms': _ms(meta['observed_at']),
                    'rest_page_available_upper_bound_ms': _ms(meta['observed_at']),
                    'fill_source_ref': 'raw_observations:' + str(meta['observation_id']),
                    'fill_source_sha256': meta['response_sha256']}
                identity = fingerprint(fill)
                if (identity not in receipts or receipt['rest_page_archived_ms']
                        < receipts[identity]['rest_page_archived_ms']):
                    receipts[identity] = receipt
        if size > limits['max_fill_decoded_bytes'] or records > limits['max_fill_records']:
            raise ContextBoundError('Fill decoding limit exceeded; no partial context was retained')
    fills, coverage, refs = _load_fills(store, network, address, cutoff)
    budget.check()
    # Bind each receipt to the exact usable canonical fill, after conflict and
    # cutoff rejection by the shared loader, not merely to an arbitrary TID.
    selected_receipts = {str(fill['tid']): receipts[fingerprint(fill)] for fill in fills
        if fingerprint(fill) in receipts}
    payload = {'fills': fills, 'coverage': coverage, 'source_refs': refs,
        'receipts': selected_receipts, 'prepared_cutoff_ms': cutoff,
        'valid_through_ms': next_future_event-1 if next_future_event is not None else None}
    encoded = zlib.compress(canonical(payload).encode(), 6)
    budget.check()
    with store.connection:
        store.connection.execute('insert into bounded_market_context_fill_cache values(?,?) '
            'on conflict(input_fingerprint) do update set payload=excluded.payload', (key, encoded))
    return payload, False


def _research_fills(store, network, address, cutoff, ws_start, limits, budget):
    """Cache typed bounded evidence against its exact source/window witness."""
    ws_limits = {'max_rest_pages': limits['max_fill_pages'],
        'max_rest_records': limits['max_fill_records'],
        'max_ws_lots': 20_000, 'max_ws_records': 500_000,
        'max_decoded_bytes_per_source': limits['max_fill_decoded_bytes'],
        'max_decoded_bytes_per_lot': limits['max_decoded_bytes_per_lot'],
        'max_duration_ms': limits['max_duration_ms']}
    budget.check()
    ws_limits['max_duration_ms'] = max(1, int((budget.deadline-time.monotonic())*1000))
    manifest = population_descriptive.research_fill_source_manifest(
        store, network, address, cutoff, ws_start_ms=ws_start, limits=ws_limits)
    budget.check()
    manifest['resource_limits']['max_duration_ms'] = limits['max_duration_ms']
    key = fingerprint({'version': VERSION, 'kind': 'rest-ws-descriptive-fills',
        'network': network, 'address': address, 'sources': manifest})
    cached = store.connection.execute(
        'select payload from bounded_market_context_fill_cache where input_fingerprint=?',
        (key,)).fetchone()
    if cached:
        payload = json.loads(zlib.decompress(cached[0]))
        budget.check()
        return payload, manifest
    ws_limits['max_duration_ms'] = max(1, int((budget.deadline-time.monotonic())*1000))
    fills, coverage, refs, receipts = population_descriptive.load_research_fill_evidence(
        store, network, address, cutoff, ws_start_ms=ws_start, limits=ws_limits)
    budget.check()
    payload = {'fills': fills, 'coverage': coverage, 'source_refs': refs,
        'receipts': {tid: {'fill_evidence_receipts': proofs} for tid, proofs in receipts.items()}}
    encoded = zlib.compress(canonical(payload).encode(), 6)
    budget.check()
    with store.connection:
        store.connection.execute('insert or ignore into bounded_market_context_fill_cache values(?,?)',
            (key, encoded))
    return payload, manifest


def _semantic_rows(rows):
    # Later duplicate receipts enrich provenance without a semantic retry.
    selected = []
    for row in rows:
        value = dict(row)
        if 'fill_evidence_receipts' in value:
            earliest = {}
            for proof in value['fill_evidence_receipts']:
                key = (proof['source'], canonical(proof.get('is_snapshot')), proof.get('snapshot_status'))
                rank = lambda p: (p['available_ms'], p.get('frame_received_ms') or p['available_ms'],
                    str(p['observation_id']), p.get('frame_index') or 0)
                if key not in earliest or rank(proof) < rank(earliest[key]):
                    earliest[key] = proof
            value['fill_evidence_receipts'] = sorted(earliest.values(), key=canonical)
        selected.append(value)
    return selected


def _quote_sources(store, network, market, cutoff, start, end, feed, limits, budget):
    # Source event bounds come from the collector's min/max frame timestamps.
    # They exclude wholly post-fill lots. Unknown bounds are decoded explicitly;
    # a bounded scan refusal never masquerades as absent market observations.
    # Keep the event-overlap scan covered by the existing receipt index. A
    # single flat SELECT makes SQLite seek historical payload-table pages before
    # rejecting their event bounds; that exceeded the worker deadline. The IN
    # list first filters IDs inside the index, then reads only matching metadata
    # through ordered INTEGER PRIMARY KEY lookups. No receipt-time lower bound
    # is invented, and null source bounds are still included for validation.
    return _rows(store,
        "observation_id in (select observation_id from raw_observations indexed by uq_raw_receipt "
        "where network=? and source='hyperliquid-websocket-v1' and entity_type='market' "
        'and entity_id=? and endpoint=? and ifnull(window_start_ms,-1)<=? '
        'and (ifnull(window_end_ms,-1)>=? or ifnull(window_start_ms,-1)=-1 '
        'or ifnull(window_end_ms,-1)=-1) order by observation_id) and observed_at<=?',
        (network, market, feed, end, start, _event_iso(cutoff)),
        limits['max_quote_lots_per_feed'], budget)


def _quotes(store, sources, market, cutoff, start, end, limits, budget):
    values = []
    diagnostics = Counter()
    decoded = events = 0
    for meta in sources:
        budget.check()
        payload, size = _decode_verified(_raw(store, meta),
            max_decoded_bytes=limits['max_decoded_bytes_per_lot'], with_size=True)
        decoded += size
        feed = 'bbo' if meta['endpoint'] == 'bbo' else 'l2book'
        rows, rejects, count, batched = _quote_values(feed, payload, market,
            lot_received_ms=_ms(meta['observed_at']), cutoff_ms=cutoff)
        events += count
        if (decoded > limits['max_quote_decoded_bytes_per_feed']
                or events > limits['max_quote_events_per_feed']):
            raise ContextBoundError('Quote decoding limit exceeded; no partial context was retained')
        diagnostics.update(rejects)
        for index, quote in enumerate(rows):
            if index % 256 == 0: budget.check()
            if quote['event_received_ms'] > _ms(meta['observed_at']):
                diagnostics['local_receipt_after_archive'] += 1
                continue
            if not start <= quote['event_ms'] <= end:
                diagnostics['outside_declared_context_window'] += 1
                continue
            try:
                bid, ask = Decimal(quote['bid']), Decimal(quote['ask'])
                bid_size, ask_size = Decimal(quote['bid_size']), Decimal(quote['ask_size'])
                if not all(v.is_finite() for v in (bid, ask, bid_size, ask_size)):
                    raise ValueError('nonfinite quote')
                if not 0 < bid <= ask or min(bid_size, ask_size) < 0:
                    raise ValueError('invalid quote')
            except (InvalidOperation, ValueError):
                diagnostics['invalid_numeric_quote'] += 1
                continue
            values.append({**quote, 'local_receipt_exact': batched,
                'local_receipt_status': 'frame.received_at' if batched else 'archive-time upper bound; exact receipt unknown',
                'archived_ms': _ms(meta['observed_at']),
                'source_ref': 'raw_observations:' + str(meta['observation_id']),
                'source_sha256': meta['response_sha256']})
    unique = {}
    for index, quote in enumerate(values):
        if index % 256 == 0: budget.check()
        key = tuple(quote[k] for k in ('event_ms','bid','ask','bid_size','ask_size'))
        old = unique.get(key)
        rank = lambda q: (q['event_received_ms'],q['archived_ms'],q['source_ref'],q['event_index'])
        if old is None or rank(quote) < rank(old):
            unique[key] = quote
    diagnostics['identical_source_quote_duplicates'] += len(values)-len(unique)
    values = list(unique.values())
    values.sort(key=lambda q: (q['event_ms'], q['event_received_ms'], q['archived_ms'],
        q['source_ref'], q['event_index']))
    budget.check()
    return values, {'lots_decoded': len(sources), 'frames_decoded': events,
        'decoded_bytes': decoded, 'accepted_events': len(values),
        'rejected_or_excluded': dict(diagnostics)}


def _fill_classification(fill):
    role = 'taker' if fill.get('crossed') is True else 'maker' if fill.get('crossed') is False else 'unknown'
    try:
        size, pre = Decimal(str(fill['sz'])), Decimal(str(fill['startPosition']))
        if fill.get('side') not in ('A', 'B') or not size.is_finite() or size <= 0 or not pre.is_finite():
            raise ValueError('invalid position')
        delta = size if fill['side'] == 'B' else -size
        close = min(abs(pre), size) if pre * delta < 0 else Decimal(0)
        effect = 'opening' if not close else 'reversal' if size > close else 'closing'
        return role, effect, str(close), str(size-close)
    except (KeyError, InvalidOperation, ValueError):
        return role, 'unknown', None, None


def _join(fills, quotes, start, end, receipts, budget):
    times = [q['event_ms'] for q in quotes]
    rows = []
    for fill_index, fill in enumerate(fills):
        if fill_index % 128 == 0: budget.check()
        index = bisect_left(times, fill['time']) - 1
        previous = quotes[index] if index >= 0 else None
        same_ms = bisect_left(times, fill['time'] + 1) - bisect_left(times, fill['time'])
        context = None
        if previous:
            bid, ask = Decimal(previous['bid']), Decimal(previous['ask'])
            midpoint = (bid+ask)/2
            context = {**previous, 'event_age_ms': fill['time']-previous['event_ms'],
                'source_timestamp_distinct_quote_count': bisect_left(times,previous['event_ms']+1)-bisect_left(times,previous['event_ms']),
                'source_timestamp_tie_order': 'last local receipt; relative source order within millisecond unknown',
                'spread_bps': str((ask-bid)/midpoint*10_000),
                'midpoint': str(midpoint),
                'received_before_fill_event': (previous['event_received_ms'] < fill['time']
                    if previous['local_receipt_exact'] else None),
                'archived_before_fill_event': previous['archived_ms'] < fill['time']}
            before = bisect_left(times, previous['event_ms'] - 60_000 + 1)-1
            if before >= 0:
                earlier = quotes[before]
                earlier_mid = (Decimal(earlier['bid'])+Decimal(earlier['ask']))/2
                context['at_least_60s_move_bps'] = str((midpoint/earlier_mid-1)*10_000)
                context['prior_move_anchor_age_ms'] = previous['event_ms']-earlier['event_ms']
                context['prior_move_anchor'] = earlier
            else:
                context['at_least_60s_move_bps'] = None
            try:
                price = Decimal(str(fill['px']))
                if fill.get('side') not in ('A','B') or not price.is_finite() or price <= 0:
                    raise ValueError('invalid fill price')
                context['fill_cost_vs_prior_midpoint_bps'] = str(
                    (price/midpoint-1)*10_000*(1 if fill['side']=='B' else -1))
            except (KeyError, InvalidOperation, ValueError):
                context['fill_cost_vs_prior_midpoint_bps'] = None
        role, effect, closing, opening = _fill_classification(fill)
        rows.append({'tid': str(fill['tid']), 'fill_event_ms': fill['time'],
            **receipts.get(str(fill['tid']), {}),
            'side': fill.get('side'), 'size': fill.get('sz'), 'price': fill.get('px'),
            'start_position': fill.get('startPosition'), 'role': role, 'position_effect': effect,
            'closing_quantity': closing, 'opening_quantity': opening,
            'same_millisecond_event_count': same_ms, 'strict_prefill_quote': context})
    unique_times = sorted({t for t in times if start <= t <= end})
    gaps = [b-a for a,b in zip([start, *unique_times], [*unique_times, end])]
    return rows, {'event_gap_ms_including_window_edges': _ranked(gaps),
        'strict_prefill_matched': sum(r['strict_prefill_quote'] is not None for r in rows),
        'unmatched': sum(r['strict_prefill_quote'] is None for r in rows),
        'fills_with_same_millisecond_events': sum(r['same_millisecond_event_count'] > 0 for r in rows),
        'source_event_age_ms': _ranked([r['strict_prefill_quote']['event_age_ms'] for r in rows if r['strict_prefill_quote']]),
        'freshness_sensitivity': {str(ms): {'matched': sum(bool(r['strict_prefill_quote']
            and r['strict_prefill_quote']['event_age_ms'] <= ms) for r in rows),
            'total_fills':len(rows)} for ms in (1000,5000,30000,60000,300000)},
        'quote_locally_received_before_fill_event': sum(bool(r['strict_prefill_quote'] and r['strict_prefill_quote']['received_before_fill_event']) for r in rows),
        'quote_archived_before_fill_event': sum(bool(r['strict_prefill_quote'] and r['strict_prefill_quote']['archived_before_fill_event']) for r in rows)}


def _groups(rows, budget):
    grouped = defaultdict(list)
    for index, row in enumerate(rows):
        if index % 256 == 0: budget.check()
        day = _event_iso(row['fill_event_ms'])[:10]
        grouped[(day, row['role'], row['position_effect'], row['side'] or 'unknown')].append(row)
    result = []
    for (day, role, effect, side), values in sorted(grouped.items()):
        budget.check()
        matches = [r['strict_prefill_quote'] for r in values if r['strict_prefill_quote']]
        result.append({'utc_day': day, 'role': role, 'position_effect': effect, 'fill_side':side,
            'fills': len(values), 'matched': len(matches),
            'spread_bps': _ranked([Decimal(q['spread_bps']) for q in matches]),
            'at_least_60s_move_bps': _ranked([Decimal(q['at_least_60s_move_bps']) for q in matches
                if q['at_least_60s_move_bps'] is not None]),
            'prior_move_anchor_age_ms': _ranked([q['prior_move_anchor_age_ms'] for q in matches
                if q['at_least_60s_move_bps'] is not None]),
            'near_60s_move_bps': _ranked([Decimal(q['at_least_60s_move_bps']) for q in matches
                if q['at_least_60s_move_bps'] is not None and 55_000 <= q['prior_move_anchor_age_ms'] <= 65_000]),
            'near_60s_anchor_age_ms': _ranked([q['prior_move_anchor_age_ms'] for q in matches
                if q['at_least_60s_move_bps'] is not None and 55_000 <= q['prior_move_anchor_age_ms'] <= 65_000]),
            'near_60s_move_coverage': {'matched': sum(q['at_least_60s_move_bps'] is not None
                and 55_000 <= q['prior_move_anchor_age_ms'] <= 65_000 for q in matches),
                'quote_matched_fills':len(matches),'anchor_age_window_ms':[55_000,65_000]},
            'fill_cost_vs_prior_midpoint_bps': _ranked([Decimal(q['fill_cost_vs_prior_midpoint_bps'])
                for q in matches if q['fill_cost_vs_prior_midpoint_bps'] is not None]),
            'event_age_ms': _ranked([q['event_age_ms'] for q in matches])})
    return result


def prepare_market_context(store, *, network, address, market, cutoff_ms, limits=None,
        include_ws=False, ws_start_ms=None):
    """Persist a bounded descriptive proof; unchanged manifests skip decoding.

    Refusals raise ContextBoundError/ValueError with no partial result published.
    Root callers can mark that subject technical and continue their queue.
    WS observations require an explicit frozen window and remain descriptive,
    including snapshots; REST-only callers retain the legacy path.
    """
    bounds = _limits(limits)
    budget = _Budget(bounds['max_duration_ms'])
    address = address.lower()
    if type(cutoff_ms) is not int or cutoff_ms < 0 or not isinstance(market, str) or not market:
        raise ValueError('Explicit context scope and nonnegative cutoff required')
    if type(include_ws) is not bool or (include_ws and (type(ws_start_ms) is not int
            or not 0 <= ws_start_ms <= cutoff_ms)):
        raise ValueError('WS context requires an explicit nonnegative descriptive window start')
    if not authorized_account_history(store, network, address, cutoff_ms):
        raise PermissionError('Context includes an unreleased reserved account period')
    budget.check()
    store.connection.executescript(SCHEMA)
    if include_ws:
        fill_data, fill_sources = _research_fills(
            store, network, address, cutoff_ms, ws_start_ms, bounds, budget)
    else:
        fill_sources = _fill_sources(store, network, address, cutoff_ms, bounds, budget)
        fill_data, _ = _fills(store, network, address, market, cutoff_ms, bounds, fill_sources, budget)
    all_market = [f for f in fill_data['fills'] if f.get('coin') == market]
    if not all_market:
        return {'version': VERSION, 'status': 'data_absent', 'market': market,
            'reason': 'No authorized archived market fill; no context statistics computed'}
    end = max(f['time'] for f in all_market)
    start = max(0, end-bounds['fill_window_ms'])
    fills = [f for f in all_market if start <= f['time'] <= end]
    if len(fills) > bounds['max_fills_in_window']:
        raise ContextBoundError('Context-window fill limit exceeded; no partial context was retained')
    quote_start = max(0, start-bounds['quote_lookback_ms'])
    quote_sources = {feed: _quote_sources(store, network, market, cutoff_ms, quote_start,
        end, feed, bounds, budget) for feed in ('bbo', 'l2Book')}
    ws_identity = ({'include_ws': True, 'ws_start_ms': ws_start_ms,
        'selected_fill_receipts': {str(f['tid']): fill_data['receipts'].get(str(f['tid']), {})
            for f in fills}} if include_ws else {})
    input_fp = fingerprint({**ws_identity, 'version': VERSION, 'network': network, 'address': address,
        'market': market, 'fill_sources': fill_sources, 'quote_sources': quote_sources,
        'selected_fill_fingerprint': fingerprint(all_market), 'limits': bounds})
    budget.check()
    prior = store.connection.execute('select summary_json from bounded_market_context_results '
        'where input_fingerprint=?', (input_fp,)).fetchone()
    if prior:
        return {**json.loads(prior[0]), 'cache': 'unchanged', 'recalculated': False}
    result = {'version': VERSION, 'network': network, 'address': address, 'market': market,
        'evidence_cutoff_ms': cutoff_ms, 'scope': {'fill_start_ms': start, 'fill_end_ms_inclusive': end,
            'quote_start_ms': quote_start, 'quote_end_ms_inclusive': end,
            'included_market_fills': len(fills), 'outside_window_market_fills': len(all_market)-len(fills),
            'other_market_fills': len(fill_data['fills'])-len(all_market),
            'selection_rule': 'all observed market fills in the final 24h (configured maximum), anchored to latest fill, never PnL'},
        'fill_coverage': fill_data['coverage'], 'fill_source_refs': fill_data['source_refs'],
        'quote_source_manifest': quote_sources, 'limits': bounds, 'feeds': {}}
    if include_ws:
        result['fill_source_manifest'] = fill_sources
        result['descriptive_fill_policy'] = {'include_ws': True, 'ws_start_ms': ws_start_ms,
            'ws_end_ms_inclusive': cutoff_ms, 'live_follower_signal': False,
            'snapshots': 'descriptive observations only; never live follower signals'}
    for feed, sources in quote_sources.items():
        quotes, decoding = _quotes(store, sources, market, cutoff_ms, quote_start, end, bounds, budget)
        rows, coverage = _join(fills, quotes, start, end, fill_data['receipts'], budget)
        result['feeds'][feed] = {'rows': rows, 'coverage': coverage, 'decoding': decoding,
            'groups': _groups(rows, budget)}
    result['limitations'] = [
        'Descriptive association only; no placement policy, causal explanation, counterfactual fill or profitability claim.',
        'Strict source-event predecessor excludes same-millisecond ordering; local receipt and archival clocks remain separate.',
        'REST fill availability is page receipt, not fill event time; this result creates no live follower signal.',
        'Only the declared final fill window and quote lookback are studied; all other historical statistics remain separate.',
        'Missing/stale quotes, source-clock offset and selective coverage remain unknown, never zero movement.',
        'Quotes describe executed-fill contexts only; orders without fills and decisions to abstain remain unobserved.',
        'Fills and overlapping market windows are dependent observations; no inferential significance is claimed.',
        'at_least_60s_move_bps uses the latest observed anchor at or before quote time minus 60s; its age may be much longer. Only near_60s_move_bps restricts anchor ages to 55–65s, with separate coverage.',
    ]
    # Economic identity excludes cutoff/serialization/provenance churn. It changes
    # for actual selected prefill facts, not for wholly post-fill market updates.
    semantic = fingerprint({'version': VERSION,
        'scope': {k:v for k,v in result['scope'].items() if k != 'other_market_fills'}, 'market': market,
        'feeds': {feed: {'rows': _semantic_rows(data['rows']) if include_ws else data['rows'],
            'coverage': data['coverage'], 'groups': data['groups']}
            for feed, data in result['feeds'].items()}})
    result_fp = fingerprint(result)
    budget.check()
    summary = {'version': VERSION, 'status': 'complete_bounded_descriptive', 'market': market,
        'scope': result['scope'], 'semantic_fingerprint': semantic,
        'evidence_ref': 'bounded_market_context_results:' + result_fp,
        'result_fingerprint': result_fp, 'evidence_cutoff_ms': cutoff_ms,
        'feeds': {feed: {'coverage': data['coverage'], 'groups': data['groups']}
            for feed, data in result['feeds'].items()}, 'limitations': result['limitations']}
    encoded = zlib.compress(canonical(result).encode(), 6)
    budget.check()
    with store.connection:
        store.connection.execute('insert or ignore into bounded_market_context_results values(?,?,?,?,?)',
            (result_fp, input_fp, semantic, canonical(summary), encoded))
        store.connection.execute('insert or ignore into bounded_market_context_scopes values(?,?,?,?,?)',
            (result_fp, network, address, market, cutoff_ms))
    return {**summary, 'cache': 'created', 'recalculated': True}


def load_result(store, result_fingerprint, *, as_of_ms=None):
    """Load a proof only after its separately stored account scope is authorized.

    Availability at the historical evidence cutoff does not grant access through
    a newly protected evaluation period at the caller's present decision time.
    """
    as_of = now_ms() if as_of_ms is None else as_of_ms
    if type(as_of) is not int or as_of < 0:
        raise ValueError('Explicit nonnegative market-context access time required')
    if not store.connection.execute("select 1 from sqlite_master where name='bounded_market_context_scopes'").fetchone():
        raise PermissionError('Market-context proof has no verified scope metadata')
    scope = store.connection.execute('select network,address,market,evidence_cutoff_ms '
        'from bounded_market_context_scopes where result_fingerprint=?',(result_fingerprint,)).fetchone()
    if scope is None:
        raise PermissionError('Market-context proof has no verified scope metadata')
    if (scope['evidence_cutoff_ms'] > as_of or not authorized_account_history(
            store, scope['network'], scope['address'], as_of)):
        raise PermissionError('Market-context proof is unavailable or intersects a reserved account period')
    row = store.connection.execute('select payload from bounded_market_context_results where result_fingerprint=?',
        (result_fingerprint,)).fetchone()
    if row is None:
        raise ValueError('Known market-context proof required')
    result = json.loads(zlib.decompress(row[0]))
    if fingerprint(result) != result_fingerprint:
        raise ValueError('Market-context proof integrity mismatch')
    if any(result[key] != scope[column] for key,column in (
            ('network','network'),('address','address'),('market','market'),
            ('evidence_cutoff_ms','evidence_cutoff_ms'))):
        raise ValueError('Market-context scope metadata disagrees with its proof')
    return result
