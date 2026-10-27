"""Bounded strict-prefill public context, with lossless cached descriptive proofs.

The source clock join is descriptive. A quote before an exchange fill does not
establish what either the trader or a follower knew before making a decision.
"""
from bisect import bisect_left
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import json
import zlib

from .engine import canonical, fingerprint
from .population_descriptive import _load_fills
from .population_local_join import _decode_verified, _event_iso, _ms, _quote_values, _ranked
from .research_memory import authorized_account_history

VERSION = 'bounded-market-context-v1'
DEFAULT_LIMITS = {
    'fill_window_ms': 86_400_000, 'quote_lookback_ms': 300_000,
    'max_fill_pages': 2_000, 'max_fill_records': 500_000,
    'max_fill_decoded_bytes': 64_000_000, 'max_fills_in_window': 30_000,
    'max_quote_lots_per_feed': 300_000, 'max_quote_events_per_feed': 1_500_000,
    'max_quote_decoded_bytes_per_feed': 256_000_000,
    'max_decoded_bytes_per_lot': 4_000_000,
}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS bounded_market_context_fill_cache (
 input_fingerprint TEXT PRIMARY KEY, payload BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS bounded_market_context_results (
 result_fingerprint TEXT PRIMARY KEY, input_fingerprint TEXT UNIQUE NOT NULL,
 semantic_fingerprint TEXT NOT NULL, summary_json TEXT NOT NULL, payload BLOB NOT NULL);
'''


class ContextBoundError(ValueError):
    """A resource refusal; no partial context statistics are published."""


def _limits(overrides):
    value = {**DEFAULT_LIMITS, **(overrides or {})}
    if set(value) != set(DEFAULT_LIMITS) or any(type(v) is not int or v < 1 for v in value.values()):
        raise ValueError('Positive explicit bounded context limits required')
    return value


def _rows(store, where, params, limit):
    rows = store.connection.execute(
        'select observation_id,response_sha256,observed_at,requested_at,window_start_ms,'
        'window_end_ms,record_count,complete,endpoint from raw_observations where '
        + where + ' order by observation_id limit ?', (*params, limit + 1)).fetchall()
    if len(rows) > limit:
        raise ContextBoundError('Archived lot limit exceeded; no partial context was retained')
    return [dict(row) for row in rows]


def _raw(store, meta):
    row = store.connection.execute('select * from raw_observations where observation_id=?',
        (meta['observation_id'],)).fetchone()
    if row is None or row['response_sha256'] != meta['response_sha256']:
        raise ValueError('Context archive identity changed')
    return row


def _fill_sources(store, network, address, cutoff, limits):
    return _rows(store,
        "network=? and source='hyperliquid-population-rest-v1' and entity_type='account' "
        "and entity_id=? and endpoint in ('userFills','userFillsByTime') and observed_at<=? "
        'and (window_end_ms is null or window_end_ms<=?)',
        (network, address, _event_iso(cutoff), cutoff), limits['max_fill_pages'])


def _fills(store, network, address, market, cutoff, limits, sources):
    key = fingerprint({'version': VERSION, 'kind': 'fills', 'network': network,
        'address': address, 'sources': sources, 'limits': limits})
    row = store.connection.execute('select payload from bounded_market_context_fill_cache '
        'where input_fingerprint=?', (key,)).fetchone()
    if row:
        return json.loads(zlib.decompress(row[0])), True
    # Bound decompression before reusing the existing account-wide deduplicator.
    # The duplicate decoding is intentional: the legacy helper has no byte cap.
    size = records = 0
    receipts = {}
    for meta in sources:
        payload, decoded = _decode_verified(_raw(store, meta),
            max_decoded_bytes=limits['max_decoded_bytes_per_lot'], with_size=True)
        size += decoded
        values = (payload if isinstance(payload, list) else payload.get('data', {}).get('fills', [])
            if isinstance(payload, dict) and isinstance(payload.get('data'), dict)
            else payload.get('fills', payload.get('data', [])) if isinstance(payload, dict) else [])
        records += len(values) if isinstance(values, list) else 0
        for fill in values if isinstance(values, list) else []:
            if isinstance(fill, dict) and fill.get('tid') is not None:
                receipt = {'earliest_rest_page_received_ms': _ms(meta['requested_at']),
                    'earliest_rest_page_archived_ms': _ms(meta['observed_at']),
                    'fill_source_ref': 'raw_observations:' + str(meta['observation_id']),
                    'fill_source_sha256': meta['response_sha256']}
                key_tid = str(fill['tid'])
                if (key_tid not in receipts or receipt['earliest_rest_page_archived_ms']
                        < receipts[key_tid]['earliest_rest_page_archived_ms']):
                    receipts[key_tid] = receipt
        if size > limits['max_fill_decoded_bytes'] or records > limits['max_fill_records']:
            raise ContextBoundError('Fill decoding limit exceeded; no partial context was retained')
    fills, coverage, refs = _load_fills(store, network, address, cutoff)
    payload = {'fills': fills, 'coverage': coverage, 'source_refs': refs, 'receipts': receipts}
    with store.connection:
        store.connection.execute('insert or ignore into bounded_market_context_fill_cache values(?,?)',
            (key, zlib.compress(canonical(payload).encode(), 6)))
    return payload, False


def _quote_sources(store, network, market, cutoff, start, end, feed, limits):
    # Source event bounds come from the collector's min/max frame timestamps.
    # They exclude wholly post-fill lots. Unknown bounds are decoded explicitly;
    # a bounded scan refusal never masquerades as absent market observations.
    return _rows(store,
        "network=? and source='hyperliquid-websocket-v1' and entity_type='market' "
        'and entity_id=? and endpoint=? and observed_at<=? '
        'and (window_start_ms is null or window_start_ms<=?) '
        'and (window_end_ms is null or window_end_ms>=?)',
        (network, market, feed, _event_iso(cutoff), end, start),
        limits['max_quote_lots_per_feed'])


def _quotes(store, sources, market, cutoff, start, end, limits):
    values = []
    diagnostics = Counter()
    decoded = events = 0
    for meta in sources:
        payload, size = _decode_verified(_raw(store, meta),
            max_decoded_bytes=limits['max_decoded_bytes_per_lot'], with_size=True)
        decoded += size
        feed = 'bbo' if meta['endpoint'] == 'bbo' else 'l2book'
        rows, rejects, count, _ = _quote_values(feed, payload, market,
            lot_received_ms=_ms(meta['requested_at']), cutoff_ms=cutoff)
        events += count
        if (decoded > limits['max_quote_decoded_bytes_per_feed']
                or events > limits['max_quote_events_per_feed']):
            raise ContextBoundError('Quote decoding limit exceeded; no partial context was retained')
        diagnostics.update(rejects)
        for quote in rows:
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
            values.append({**quote, 'archived_ms': _ms(meta['observed_at']),
                'source_ref': 'raw_observations:' + str(meta['observation_id']),
                'source_sha256': meta['response_sha256']})
    unique = {}
    for quote in values:
        key = tuple(quote[k] for k in ('event_ms','bid','ask','bid_size','ask_size'))
        old = unique.get(key)
        rank = lambda q: (q['event_received_ms'],q['archived_ms'],q['source_ref'],q['event_index'])
        if old is None or rank(quote) < rank(old):
            unique[key] = quote
    diagnostics['identical_source_quote_duplicates'] += len(values)-len(unique)
    values = list(unique.values())
    values.sort(key=lambda q: (q['event_ms'], q['event_received_ms'], q['archived_ms'],
        q['source_ref'], q['event_index']))
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


def _join(fills, quotes, start, end, receipts):
    times = [q['event_ms'] for q in quotes]
    rows = []
    for fill in fills:
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
                'received_before_fill_event': previous['event_received_ms'] < fill['time'],
                'archived_before_fill_event': previous['archived_ms'] < fill['time']}
            before = bisect_left(times, previous['event_ms'] - 60_000 + 1)-1
            if before >= 0:
                earlier = quotes[before]
                earlier_mid = (Decimal(earlier['bid'])+Decimal(earlier['ask']))/2
                context['prior_60s_move_bps'] = str((midpoint/earlier_mid-1)*10_000)
                context['prior_move_anchor_age_ms'] = previous['event_ms']-earlier['event_ms']
                context['prior_move_anchor'] = earlier
            else:
                context['prior_60s_move_bps'] = None
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


def _groups(rows):
    grouped = defaultdict(list)
    for row in rows:
        day = _event_iso(row['fill_event_ms'])[:10]
        grouped[(day, row['role'], row['position_effect'], row['side'] or 'unknown')].append(row)
    result = []
    for (day, role, effect, side), values in sorted(grouped.items()):
        matches = [r['strict_prefill_quote'] for r in values if r['strict_prefill_quote']]
        result.append({'utc_day': day, 'role': role, 'position_effect': effect, 'fill_side':side,
            'fills': len(values), 'matched': len(matches),
            'spread_bps': _ranked([Decimal(q['spread_bps']) for q in matches]),
            'prior_60s_move_bps': _ranked([Decimal(q['prior_60s_move_bps']) for q in matches if q['prior_60s_move_bps'] is not None]),
            'fill_cost_vs_prior_midpoint_bps': _ranked([Decimal(q['fill_cost_vs_prior_midpoint_bps'])
                for q in matches if q['fill_cost_vs_prior_midpoint_bps'] is not None]),
            'event_age_ms': _ranked([q['event_age_ms'] for q in matches])})
    return result


def prepare_market_context(store, *, network, address, market, cutoff_ms, limits=None):
    """Persist a bounded descriptive proof; unchanged manifests skip decoding.

    Refusals raise ContextBoundError/ValueError with no partial result published.
    Root callers can mark that subject technical and continue their queue.
    """
    bounds = _limits(limits)
    address = address.lower()
    if type(cutoff_ms) is not int or cutoff_ms < 0 or not isinstance(market, str) or not market:
        raise ValueError('Explicit context scope and nonnegative cutoff required')
    if not authorized_account_history(store, network, address, cutoff_ms):
        raise PermissionError('Context includes an unreleased reserved account period')
    store.connection.executescript(SCHEMA)
    fill_sources = _fill_sources(store, network, address, cutoff_ms, bounds)
    fill_data, _ = _fills(store, network, address, market, cutoff_ms, bounds, fill_sources)
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
        end, feed, bounds) for feed in ('bbo', 'l2Book')}
    input_fp = fingerprint({'version': VERSION, 'network': network, 'address': address,
        'market': market, 'fill_sources': fill_sources, 'quote_sources': quote_sources, 'limits': bounds})
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
    for feed, sources in quote_sources.items():
        quotes, decoding = _quotes(store, sources, market, cutoff_ms, quote_start, end, bounds)
        rows, coverage = _join(fills, quotes, start, end, fill_data['receipts'])
        result['feeds'][feed] = {'rows': rows, 'coverage': coverage, 'decoding': decoding,
            'groups': _groups(rows)}
    result['limitations'] = [
        'Descriptive association only; no placement policy, causal explanation, counterfactual fill or profitability claim.',
        'Strict source-event predecessor excludes same-millisecond ordering; local receipt and archival clocks remain separate.',
        'REST fill availability is page receipt, not fill event time; this result creates no live follower signal.',
        'Only the declared final fill window and quote lookback are studied; all other historical statistics remain separate.',
        'Missing/stale quotes, source-clock offset and selective coverage remain unknown, never zero movement.',
        'Quotes describe executed-fill contexts only; orders without fills and decisions to abstain remain unobserved.',
        'Fills and overlapping market windows are dependent observations; no inferential significance is claimed.',
    ]
    # Economic identity excludes cutoff/serialization/provenance churn. It changes
    # for actual selected prefill facts, not for wholly post-fill market updates.
    semantic = fingerprint({'version': VERSION,
        'scope': {k:v for k,v in result['scope'].items() if k != 'other_market_fills'}, 'market': market,
        'feeds': {feed: {'rows': data['rows'], 'coverage': data['coverage'], 'groups': data['groups']}
            for feed, data in result['feeds'].items()}})
    result_fp = fingerprint(result)
    summary = {'version': VERSION, 'status': 'complete_bounded_descriptive', 'market': market,
        'scope': result['scope'], 'semantic_fingerprint': semantic,
        'evidence_ref': 'bounded_market_context_results:' + result_fp,
        'result_fingerprint': result_fp, 'evidence_cutoff_ms': cutoff_ms,
        'feeds': {feed: {'coverage': data['coverage'], 'groups': data['groups']}
            for feed, data in result['feeds'].items()}, 'limitations': result['limitations']}
    with store.connection:
        store.connection.execute('insert or ignore into bounded_market_context_results values(?,?,?,?,?)',
            (result_fp, input_fp, semantic, canonical(summary), zlib.compress(canonical(result).encode(), 6)))
    return {**summary, 'cache': 'created', 'recalculated': True}


def load_result(store, result_fingerprint):
    row = store.connection.execute('select payload from bounded_market_context_results where result_fingerprint=?',
        (result_fingerprint,)).fetchone()
    if row is None:
        raise ValueError('Known market-context proof required')
    result = json.loads(zlib.decompress(row[0]))
    if fingerprint(result) != result_fingerprint:
        raise ValueError('Market-context proof integrity mismatch')
    return result
