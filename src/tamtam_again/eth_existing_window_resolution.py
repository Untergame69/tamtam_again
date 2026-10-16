"""Resolve the 67f7/ETH final-window request from its sealed local archive."""
from __future__ import annotations

import bisect
import gzip
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .engine import canonical, fingerprint
from .hype_diagnostics import start_position_chain_summary
from .validation import now_ms

VERSION = 'population-eth-existing-window-resolution-v1'
REQUEST_ID = '501c352cd53c5a65ce3f035fe393ccdf15d640f418976b1a279b2d4bd248aece'
PROTOCOL_ID = '67f7-eth-public-observation-24h-20261014-v1'
NETWORK = 'hyperliquid-mainnet'
ADDRESS = '0x67f7aa8fb95c47e6ea9c517b623e0701cbf9d9ba'
MARKET = 'ETH'
START_MS = 1_791_990_000_000
END_MS = 1_792_076_400_000
OUTCOME_HORIZON_MS = 60_000
MOVEMENT_HORIZONS_MS = (5_000, 30_000, 60_000)
FRESHNESS_MS = (100, 1_000, 5_000, 30_000, 60_000, 300_000)
TIME_BLOCK_MS = 300_000
ARTIFACT_PATH = 'docs/continuous-research/POPULATION-67F7-ETH-EXISTING-WINDOW-RESOLUTION-20261016-v1.json.gz'


def _d(value):
    try:
        out = Decimal(str(value))
        return out if out.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _iso_ms(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    delta = dt - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000


def _utc_day(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat()


def _classify(fill):
    pre, size = _d(fill.get('startPosition')), _d(fill.get('sz'))
    side = fill.get('side')
    if pre is None or size is None or size <= 0 or side not in ('A', 'B'):
        return 'unknown', None, None, None
    signed = size if side == 'B' else -size
    post = pre + signed
    if pre == 0 or pre * signed > 0:
        return 'opens', Decimal(0), size, post
    close = min(abs(pre), size)
    opened = size - close
    return ('inverts' if opened > 0 else 'reduces'), close, opened, post


def _quote_ref(q):
    return {'observation_id': q['observation_id'], 'event_index': q['event_index'],
        'sha256': q['sha256']}


def _mid(q):
    bid, ask = _d(q['bid']), _d(q['ask'])
    return None if bid is None or ask is None else (bid + ask) / 2


def _quote_context(q, fill):
    if q is None:
        return None
    requested_ms = _iso_ms(fill['fill_page_requested_at']) if fill.get('fill_page_requested_at') else None
    received_ms = q.get('received_ms', q.get('event_received_ms'))
    archived_ms = q.get('archived_ms')
    mid = _mid(q)
    spread = _d(q['ask']) - _d(q['bid']) if q.get('ask') is not None and q.get('bid') is not None else None
    return {'event_ms': q['event_ms'], 'event_received_ms': received_ms,
        'event_received_source': q.get('event_received_source'), 'archived_ms': archived_ms,
        'event_age_ms': int(fill['time']) - q['event_ms'],
        'received_before_fill_page_request': None if requested_ms is None or received_ms is None else received_ms <= requested_ms,
        'archived_before_fill_page_request': None if requested_ms is None or archived_ms is None else archived_ms <= requested_ms,
        'connection_id': q.get('connection_id'), 'bid': q['bid'], 'bid_size': q['bid_size'],
        'ask': q['ask'], 'ask_size': q['ask_size'], 'mid': None if mid is None else str(mid),
        'spread': None if spread is None else str(spread),
        'spread_bps': None if not mid else str(spread / mid * Decimal(10_000)),
        'reference': _quote_ref(q)}


def _nearest_rank(values, percentile):
    if not values:
        return None
    values = sorted(values)
    return values[max(0, (percentile * len(values) + 99) // 100 - 1)]


def _tertile(value, cuts):
    if value is None:
        return 'unknown'
    if cuts[0] is None and cuts[1] is None:
        return 'unknown'
    numeric = _d(value)
    if cuts[0] is not None and numeric <= cuts[0]:
        return 'low'
    if cuts[1] is not None and numeric <= cuts[1]:
        return 'mid'
    return 'high'


def _execution_type(row):
    return 'taker' if row['crossed'] is True else 'maker' if row['crossed'] is False else 'unknown'


def _numeric_summary(values):
    values = [float(x) for x in values if x is not None]
    if not values:
        return {'count': 0, 'median': None, 'mean': None, 'p10': None, 'p90': None}
    return {'count': len(values), 'median': statistics.median(values),
        'mean': statistics.fmean(values), 'p10': _nearest_rank(values, 10), 'p90': _nearest_rank(values, 90)}


def _group_summary(rows):
    event = [r.get('event_time_markout_60s_bps') for r in rows]
    receipt = [r.get('post_receipt_markout_60s_bps') for r in rows]
    orders = {r.get('order_id') for r in rows if r.get('order_id') is not None}
    qty = sum((_d(r.get('size')) or Decimal(0) for r in rows), Decimal(0))
    close = sum((_d(r.get('close_quantity')) or Decimal(0) for r in rows), Decimal(0))
    opened = sum((_d(r.get('open_quantity')) or Decimal(0) for r in rows), Decimal(0))
    fees = defaultdict(Decimal)
    missing_fee = 0
    for row in rows:
        if row.get('fee') is None:
            missing_fee += 1
        else:
            try:
                fees[str(row.get('fee_token') or 'unknown')] += _d(row['fee']) or Decimal(0)
            except (InvalidOperation, TypeError, ValueError):
                missing_fee += 1
    return {'fills': len(rows), 'orders': len(orders), 'outcome_60s_count': sum(v is not None for v in event),
        'outcome_60s_coverage_pct': round(100 * sum(v is not None for v in event) / len(rows), 4) if rows else None,
        'event_time_directional_markout_60s_bps': _numeric_summary(event),
        'post_fill_page_receipt_markout_60s_bps': _numeric_summary(receipt),
        'quantity': str(qty), 'position_reduction_quantity': str(close), 'position_open_quantity': str(opened),
        'signed_observed_fees_by_token': {k: str(v) for k, v in sorted(fees.items())},
        'fills_missing_fee': missing_fee}


def _summaries(rows, dimensions):
    groups = defaultdict(list)
    for row in rows:
        key = tuple(row.get(name) for name in dimensions)
        groups[key].append(row)
    return [{**dict(zip(dimensions, key)), **_group_summary(group)}
        for key, group in sorted(groups.items(), key=lambda item: tuple(str(v) for v in item[0]))]


def _validate_fill_join(report_rows, raw_fills):
    report_by_tid = {str(row.get('tid')): row for row in report_rows}
    raw_by_tid = {str(row.get('tid')): row for row in raw_fills}
    if len(report_by_tid) != len(report_rows) or len(raw_by_tid) != len(raw_fills):
        raise ValueError('Duplicate fill identity remains after deterministic archive read')
    if report_by_tid.keys() != raw_by_tid.keys():
        raise ValueError(f'Final report/raw fill identity mismatch: report_only={len(report_by_tid.keys()-raw_by_tid.keys())}, raw_only={len(raw_by_tid.keys()-report_by_tid.keys())}')
    mismatches = Counter()
    pairs = {}
    for tid, report in report_by_tid.items():
        raw = raw_by_tid[tid]
        checks = (('event_ms', 'time'), ('side', 'side'), ('crossed', 'crossed'),
            ('start_position', 'startPosition'), ('size', 'sz'), ('price', 'px'),
            ('fee', 'fee'), ('fee_token', 'feeToken'),
            ('fill_page_observation_id', 'fill_page_observation_id'),
            ('fill_page_sha256', 'fill_page_sha256'),
            ('fill_page_received_at', 'fill_page_received_at'), ('fill_page_archived_at', 'fill_page_archived_at'))
        for report_key, raw_key in checks:
            left, right = report.get(report_key), raw.get(raw_key)
            if report_key in ('start_position', 'size', 'price', 'fee') and left is not None and right is not None:
                equal = _d(left) == _d(right)
            else:
                equal = left == right
            if not equal:
                mismatches[report_key] += 1
        action, close, opened, _ = _classify(raw)
        if report.get('action') != action:
            mismatches['action'] += 1
        if close is not None and abs((_d(report.get('close_quantity')) or Decimal(0)) - close) > Decimal('1e-12'):
            mismatches['close_quantity'] += 1
        if opened is not None and abs((_d(report.get('open_quantity')) or Decimal(0)) - opened) > Decimal('1e-12'):
            mismatches['open_quantity'] += 1
        pairs[tid] = (raw, report)
    if mismatches:
        raise ValueError('Report fields differ from their archived fill source: ' + canonical(dict(mismatches)))
    return pairs


def _join_contexts(report_rows, raw_fills, quote_events):
    from .population_local_join import _segment_map
    _, segment_by_tid, _ = _segment_map(raw_fills)
    raw_by_tid = {str(f['tid']): f for f in raw_fills}
    by_channel = {}
    event_times = {}
    ties = {}
    unique_event_times = {}
    receipt_order = {}
    receipt_times = {}
    for channel in ('bbo', 'l2Book'):
        selected = [q for q in quote_events if q.get('channel') == channel]
        selected.sort(key=lambda q: (q['event_ms'], q.get('received_ms', q.get('event_received_ms', 0)),
            q['observation_id'], q['event_index']))
        by_channel[channel] = selected
        event_times[channel] = [q['event_ms'] for q in selected]
        tie_counts = Counter(q['event_ms'] for q in selected)
        ties[channel] = tie_counts
        unique_event_times[channel] = sorted(tie_counts)
        received = sorted(selected, key=lambda q: (q.get('received_ms', q.get('event_received_ms', 0)),
            q['archived_ms'], q['event_ms'], q['observation_id'], q['event_index']))
        receipt_order[channel] = received
        receipt_times[channel] = [q.get('received_ms', q.get('event_received_ms', 0)) for q in received]

    rows = []
    for report in report_rows:
        tid = str(report['tid'])
        raw = raw_by_tid[tid]
        t = int(raw['time'])
        action, close, opened, post = _classify(raw)
        requested_ms = _iso_ms(raw['fill_page_requested_at']) if raw.get('fill_page_requested_at') else None
        received_ms = _iso_ms(raw['fill_page_received_at']) if raw.get('fill_page_received_at') else None
        row = {'fill_id': tid, 'order_id': str(raw['oid']) if raw.get('oid') is not None else None,
            'event_ms': t, 'utc_day': _utc_day(t), 'segment': segment_by_tid.get(tid),
            'side': raw.get('side'), 'execution_type': _execution_type({'crossed': raw.get('crossed')}),
            'crossed': raw.get('crossed'), 'start_position': raw.get('startPosition'),
            'post_fill_position': None if post is None else str(post), 'action': action,
            'size': raw.get('sz'), 'price': raw.get('px'), 'close_quantity': None if close is None else str(close),
            'open_quantity': None if opened is None else str(opened),
            'fee': raw.get('fee'), 'fee_token': raw.get('feeToken'),
            'fill_page': {'observation_id': raw.get('fill_page_observation_id'), 'sha256': raw.get('fill_page_sha256'),
                'poll_id': raw.get('poll_id'), 'requested_at': raw.get('fill_page_requested_at'),
                'received_at': raw.get('fill_page_received_at'), 'archived_at': raw.get('fill_page_archived_at'),
                'request_to_receive_ms': None if requested_ms is None or received_ms is None else received_ms - requested_ms,
                'event_to_page_receipt_ms_cross_clock_unaligned': report.get('event_to_fill_page_receipt_ms')},
            'event_time_markout_60s_bps': report.get('event_time_markout_60s_bps'),
            'post_receipt_markout_60s_bps': report.get('post_receipt_markout_60s_bps'),
            'report_prefill_quote': report.get('prefill_quote'), 'report_future_quote': report.get('future_quote'),
            'receipt_baseline_quote': report.get('receipt_baseline_quote'),
            'receipt_future_quote': report.get('receipt_future_quote'),
            'receipt_baseline_quote_ref': report.get('receipt_baseline_quote_ref'),
            'receipt_future_quote_ref': report.get('receipt_future_quote_ref'), 'market_context': {}}
        for channel in ('bbo', 'l2Book'):
            quotes = by_channel[channel]
            times = event_times[channel]
            # bisect_left excludes all quotes with the fill timestamp.
            index = bisect.bisect_left(times, t) - 1
            prior = quotes[index] if index >= 0 else None
            same = [q for q in quotes[bisect.bisect_left(times, t):bisect.bisect_right(times, t)]]
            context = _quote_context(prior, raw)
            if context is not None:
                context['same_event_time_predecessor_tie_count'] = ties[channel].get(prior['event_ms'], 0)
                context['same_event_time_predecessor_reference_sample'] = [
                    _quote_ref(q) for q in quotes[bisect.bisect_left(times, prior['event_ms']):
                        bisect.bisect_right(times, prior['event_ms'])][:8]]
                unique_times = unique_event_times[channel]
                pidx = bisect.bisect_left(unique_times, prior['event_ms'])
                context['gap_before_predecessor_event_ms'] = prior['event_ms'] - unique_times[pidx-1] if pidx > 0 else None
                context['local_receipt_gap_before_predecessor_ms'] = None
                ridx = bisect.bisect_left(receipt_times[channel], prior.get('received_ms', prior.get('event_received_ms', 0)))
                if ridx > 0:
                    earlier_same_clock = receipt_order[channel][ridx-1]
                    context['local_receipt_gap_before_predecessor_ms'] = (
                        prior.get('received_ms', prior.get('event_received_ms', 0)) -
                        earlier_same_clock.get('received_ms', earlier_same_clock.get('event_received_ms', 0)))
            row['market_context'][channel] = {'strict_event_time_predecessor': context,
                'fill_timestamp_quote_count_relative_order_unknown': len(same),
                'fill_timestamp_quote_refs_sample': [_quote_ref(q) for q in same[:8]],
                'predecessor_available_by_rest_request_local_clock': None if context is None else context['received_before_fill_page_request'],
                'predecessor_archived_by_rest_request_local_clock': None if context is None else context['archived_before_fill_page_request']}

        bbo = row['market_context']['bbo']['strict_event_time_predecessor']
        l2 = row['market_context']['l2Book']['strict_event_time_predecessor']
        if bbo and bbo['mid'] is not None:
            mid = _d(bbo['mid'])
            for horizon in MOVEMENT_HORIZONS_MS:
                baseline_i = bisect.bisect_right(event_times['bbo'], t - horizon) - 1
                baseline = by_channel['bbo'][baseline_i] if baseline_i >= 0 else None
                if baseline is None or _mid(baseline) in (None, Decimal(0)):
                    movement = None
                else:
                    base_mid = _mid(baseline)
                    movement = {'horizon_ms': horizon, 'measured_lookback_ms': t - baseline['event_ms'],
                        'return_bps': str((mid / base_mid - 1) * Decimal(10_000)),
                        'baseline_event_ms': baseline['event_ms'], 'baseline_received_ms': baseline.get('received_ms'),
                        'baseline_archived_ms': baseline.get('archived_ms'), 'baseline_ref': _quote_ref(baseline),
                        'current_ref': bbo['reference']}
                row['market_context'].setdefault('bbo_preceding_mid_moves', {})[str(horizon)] = movement
        if l2:
            bid_size, ask_size = _d(l2['bid_size']), _d(l2['ask_size'])
            total = bid_size + ask_size if bid_size is not None and ask_size is not None else None
            pre = _d(raw.get('startPosition'))
            reducing_depth = (bid_size if pre is not None and pre > 0 else
                ask_size if pre is not None and pre < 0 else None)
            row['market_context']['l2Book']['best_level_depth'] = {
                'bid_size': str(bid_size) if bid_size is not None else None,
                'ask_size': str(ask_size) if ask_size is not None else None,
                'total_best_level_size': str(total) if total is not None else None,
                'inventory_reducing_side_best_level_size': str(reducing_depth) if reducing_depth is not None else None,
                'bid_ask_size_imbalance': (str((bid_size - ask_size) / total) if total else None)}
        else:
            row['market_context']['l2Book']['best_level_depth'] = None
        row['market_context']['bbo_preceding_mid_moves'] = row['market_context'].get('bbo_preceding_mid_moves',
            {str(h): None for h in MOVEMENT_HORIZONS_MS})
        row['market_context']['event_time_context_usable_by_age_ms'] = {
            str(age): bool(bbo and l2 and bbo['event_age_ms'] <= age and l2['event_age_ms'] <= age)
            for age in FRESHNESS_MS}
        row['market_context']['context_available_at_execution'] = 'unknown: no decision timestamp or calibrated event-to-local clock offset'
        rows.append(row)
    return rows


def _add_condition_bins(rows):
    usable = [r for r in rows if all(r['market_context'][channel]['strict_event_time_predecessor'] is not None
        for channel in ('bbo', 'l2Book')) and r['market_context']['event_time_context_usable_by_age_ms']['30000']
        and r['market_context']['bbo_preceding_mid_moves'].get(str(30_000)) is not None
        and r['market_context']['bbo_preceding_mid_moves'][str(30_000)]['measured_lookback_ms'] <= 60_000]
    spread_values = [_d(r['market_context']['bbo']['strict_event_time_predecessor']['spread_bps'])
        for r in usable if r['market_context']['bbo']['strict_event_time_predecessor'].get('spread_bps') is not None]
    depth_values = [_d(r['market_context']['l2Book']['best_level_depth']['inventory_reducing_side_best_level_size'])
        for r in usable if r['market_context']['l2Book']['best_level_depth'] and
            r['market_context']['l2Book']['best_level_depth']['inventory_reducing_side_best_level_size'] is not None]
    spread_cuts = [_nearest_rank(spread_values, 33), _nearest_rank(spread_values, 67)]
    depth_cuts = [_nearest_rank(depth_values, 33), _nearest_rank(depth_values, 67)]
    for row in rows:
        ctx = row['market_context']
        bbo = ctx['bbo']['strict_event_time_predecessor']
        l2depth = ctx['l2Book'].get('best_level_depth')
        move = ctx['bbo_preceding_mid_moves'].get(str(30_000))
        row['market_context']['movement_30s_direction'] = ('unknown' if move is None else
            'down' if _d(move['return_bps']) < -1 else 'up' if _d(move['return_bps']) > 1 else 'flat_within_1bp')
        row['market_context']['bbo_spread_tertile'] = _tertile(bbo.get('spread_bps') if bbo else None, spread_cuts)
        row['market_context']['inventory_reducing_depth_tertile'] = _tertile(
            l2depth.get('inventory_reducing_side_best_level_size') if l2depth else None, depth_cuts)
    return usable, {'bbo_spread_tertiles_bps': [str(x) if x is not None else None for x in spread_cuts],
        'inventory_reducing_side_best_level_size_tertiles': [str(x) if x is not None else None for x in depth_cuts],
        'movement_direction_thresholds_bps': {'down_below': -1, 'up_above': 1,
            'flat_inclusive': [-1, 1]},
        'cuts_are_descriptive_only': True}


def _order_groups(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get('order_id') or 'unknown:' + row['fill_id']].append(row)
    details = []
    order_medians = defaultdict(list)
    for order_id, values in sorted(grouped.items()):
        values.sort(key=lambda r: (r['event_ms'], r['fill_id']))
        actions = Counter(r['action'] for r in values)
        execution_types = Counter(r['execution_type'] for r in values)
        sides = Counter(str(r['side']) for r in values)
        markouts = [r['event_time_markout_60s_bps'] for r in values if r['event_time_markout_60s_bps'] is not None]
        item = {'order_id': order_id, 'fill_count': len(values), 'first_event_ms': values[0]['event_ms'],
            'last_event_ms': values[-1]['event_ms'], 'span_ms': values[-1]['event_ms'] - values[0]['event_ms'],
            'side_counts': dict(sorted(sides.items())), 'execution_type_counts': dict(sorted(execution_types.items())),
            'position_effect_counts': dict(sorted(actions.items())), 'fill_ids': [r['fill_id'] for r in values],
            'event_time_markout_60s_bps': _numeric_summary(markouts)}
        details.append(item)
        for row in values:
            order_medians[(row['execution_type'], row['action'])].append((order_id, row))
    clustered = []
    for key, values in sorted(order_medians.items()):
        per_order = defaultdict(list)
        for order_id, row in values:
            if row['event_time_markout_60s_bps'] is not None:
                per_order[order_id].append(row['event_time_markout_60s_bps'])
        medians = [statistics.median(v) for v in per_order.values() if v]
        clustered.append({'execution_type': key[0], 'action': key[1], 'orders_with_outcomes': len(medians),
            'fills_with_outcomes': sum(len(v) for v in per_order.values()),
            'median_of_order_medians_bps': statistics.median(medians) if medians else None,
            'interpretation': 'descriptive order-cluster summary; orders are not independent strategy trials'})
    return details, {'distinct_order_count': len(grouped),
        'multi_fill_order_count': sum(len(v) > 1 for v in grouped.values()),
        'fills_in_multi_fill_orders': sum(len(v) for v in grouped.values() if len(v) > 1),
        'max_fills_per_order': max((len(v) for v in grouped.values()), default=0),
        'median_fills_per_order': statistics.median([len(v) for v in grouped.values()]) if grouped else None,
        'outcome_cluster_summaries': clustered}


def _time_groups(rows):
    grouped = defaultdict(list)
    for row in rows:
        start = (row['event_ms'] // TIME_BLOCK_MS) * TIME_BLOCK_MS
        grouped[start].append(row)
    details = []
    for start, values in sorted(grouped.items()):
        effects = Counter(r['action'] for r in values)
        details.append({'utc_day': _utc_day(start), 'block_start_ms': start,
            'block_end_ms': start + TIME_BLOCK_MS, 'fill_count': len(values),
            'orders': len({r['order_id'] for r in values if r.get('order_id') is not None}),
            'position_effect_counts': dict(sorted(effects.items())),
            'by_execution_and_effect': _summaries(values, ('execution_type', 'action'))})
    clustered = defaultdict(list)
    for block in details:
        for group in block['by_execution_and_effect']:
            clustered[(group['execution_type'], group['action'])].append(group['event_time_directional_markout_60s_bps']['median'])
    cluster_summaries = [{'execution_type': key[0], 'action': key[1],
        'time_blocks_with_outcomes': sum(x is not None for x in values),
        'median_of_5min_block_medians_bps': statistics.median([x for x in values if x is not None]) if any(x is not None for x in values) else None}
        for key, values in sorted(clustered.items())]
    return details, cluster_summaries


def _overlap_summary(rows):
    times = sorted(row['event_ms'] for row in rows)
    pair_count = 0
    affected = 0
    max_concurrent = 0
    for index, stamp in enumerate(times):
        left = bisect.bisect_left(times, stamp - OUTCOME_HORIZON_MS, 0, index)
        overlap = index - left
        pair_count += overlap
        if overlap:
            affected += 1
        max_concurrent = max(max_concurrent, overlap + 1)
    return {'outcome_horizon_ms': OUTCOME_HORIZON_MS,
        'fills_with_at_least_one_prior_overlapping_outcome': affected,
        'overlapping_fill_pairs': pair_count, 'max_concurrent_outcome_windows': max_concurrent,
        'method': 'event-time fills within 60 seconds overlap in their forward 60-second outcome windows; inclusive endpoint is counted',
        'independent_fill_inference_authorized': False}


def _market_condition_summaries(rows):
    features = ('movement_30s_direction', 'bbo_spread_tertile', 'inventory_reducing_depth_tertile')
    all_groups = []
    for feature in features:
        usable = [r for r in rows if r['market_context']['event_time_context_usable_by_age_ms']['30000']
            and r['market_context'].get(feature) != 'unknown']
        groups = defaultdict(list)
        for row in usable:
            groups[(row['execution_type'], row['action'], row['side'], row['market_context'][feature])].append(row)
        for key, values in sorted(groups.items(), key=lambda item: tuple(str(v) for v in item[0])):
            all_groups.append({'condition': feature, 'execution_type': key[0], 'action': key[1],
                'side': key[2], 'market_state': key[3], **_group_summary(values)})
    return all_groups


def _freshness(rows):
    result = []
    for age in FRESHNESS_MS:
        selected = [r for r in rows if r['market_context']['event_time_context_usable_by_age_ms'][str(age)]]
        result.append({'both_bbo_and_l2book_strict_predecessors_max_age_ms': age,
            'eligible_fill_count': len(selected), 'coverage_pct': round(100 * len(selected) / len(rows), 4) if rows else None,
            'by_execution_and_position_effect': _summaries(selected, ('execution_type', 'action'))})
    all_counts = _summaries(rows, ('execution_type', 'action'))
    covered_30s = [r for r in rows if r['market_context']['event_time_context_usable_by_age_ms']['30000']]
    return {'all_fills_baseline_by_execution_and_effect': all_counts,
        'covered_subset_at_30s_by_execution_and_effect': _summaries(covered_30s, ('execution_type', 'action')),
        'sensitivity': result}


def _data_inventory(report, report_rows, raw_fills, fill_coverage, quote_events, quote_coverage):
    market = report.get('coverage', {}).get('market', {})
    fills = report.get('coverage', {}).get('fills', {})
    return [
        {'request': 'Fill/order identity, side, crossed, start position, signed size and position effect for the fixed window',
            'classification': 'available_and_joined', 'source': 'final_24h report plus archived prospective REST pages',
            'period_ms': [START_MS, END_MS], 'report_fills': len(report_rows), 'raw_unique_fills': len(raw_fills),
            'pages': fill_coverage.get('page_count'), 'complete_pages': fill_coverage.get('complete_page_count'),
            'duplicate_instances': fill_coverage.get('duplicate_fill_instances'),
            'conflicts': len(fill_coverage.get('conflicting_fill_ids', [])),
            'fields_used': ['tid','oid','time','side','crossed','startPosition','sz','px','fee','feeToken'],
            'usage': 'all unique fills joined by tid; oid added from raw pages; effects recalculated from startPosition and signed size'},
        {'request': 'Strict-prior quotes, outcomes, local REST/page receipt and reference joins',
            'classification': 'available_and_joined', 'source': 'final_24h report plus archived BBO/l2Book event lots',
            'period_ms': [START_MS, END_MS], 'event_count': len(quote_events),
            'bbo_events': quote_coverage.get('quotes', {}).get('bbo', {}).get('event_count'),
            'l2book_events': quote_coverage.get('quotes', {}).get('l2Book', {}).get('event_count'),
            'market_lots': len(quote_coverage.get('source_refs', [])),
            'source_fingerprint': quote_coverage.get('source_fingerprint'),
            'report_source_fingerprint': market.get('source_fingerprint'),
            'usage': 'all decoded event lots searched for per-fill context; strict predecessors, local receipt and archive time kept separate'},
        {'request': 'Matched pre-event spread, displayed depth, recent price changes, connection and gap context',
            'classification': 'available_but_calculation_was_missing', 'source': 'BBO and l2Book raw event snapshots',
            'period_ms': [START_MS, END_MS],
            'depth_scope': 'best displayed bid and ask level only; deeper L2 levels are not inferred from top-level projection',
            'usage': 'strict event-time predecessors and preceding BBO returns; equal timestamps excluded and counted as ambiguous'},
        {'request': 'A local market quote known at the actual execution-decision instant',
            'classification': 'partially_covered_unavailable_retroactively',
            'available': 'quote frame received_at and archived_at; fill REST requested_at/received_at; connection IDs',
            'missing': 'decision timestamp and calibrated venue-to-local clock offset',
            'usage': 'compare quote receipt/archive to local REST request as a diagnostic only; do not claim execution-time availability'},
        {'request': 'Trader order placement, unfilled orders, queue position, and why the trader chose each action',
            'classification': 'absent_or_unobservable_from_fills',
            'usage': 'not inferred; observed fills are not treated as placement decisions'},
        {'request': 'Independent prospective confirmation of the conditional association',
            'classification': 'not_in_this_archive_and_not_authorized_for_collection_here',
            'usage': 'remains the single next research stage; no request or collection initiated'},
    ]


def _build_artifact(request_id, report, report_input_fp, report_rows, raw_fills, fill_coverage,
        quote_events, quote_coverage, report_row_chars):
    pairs = _validate_fill_join(report_rows, raw_fills)
    raw_by_tid = {tid: pair[0] for tid, pair in pairs.items()}
    chain = start_position_chain_summary(raw_fills)
    rows = _join_contexts(report_rows, raw_fills, quote_events)
    usable, cuts = _add_condition_bins(rows)
    by_behavior_action = _summaries(rows, ('execution_type', 'action'))
    by_day_side_behavior_action = _summaries(rows, ('utc_day', 'side', 'execution_type', 'action'))
    by_segment_behavior_action = _summaries(rows, ('segment', 'execution_type', 'action'))
    order_details, order_summary = _order_groups(rows)
    time_details, time_cluster_summaries = _time_groups(rows)
    event_times = [r['event_ms'] for r in rows]
    event_outcomes = [r['event_time_markout_60s_bps'] for r in rows if r['event_time_markout_60s_bps'] is not None]
    receipt_outcomes = [r['post_receipt_markout_60s_bps'] for r in rows if r['post_receipt_markout_60s_bps'] is not None]
    overlap = _overlap_summary(rows)
    quote_latency = report.get('quote_latency_ms', {})
    stream_health = report.get('stream_health', [])
    disconnected = sum(item.get('connected') is False for item in stream_health if isinstance(item, dict))
    unique_connections = set(q.get('connection_id') for q in quote_events if q.get('connection_id') is not None)
    archive_delays = [q['archived_ms'] - q.get('received_ms', q.get('event_received_ms')) for q in quote_events
        if q.get('archived_ms') is not None and q.get('received_ms', q.get('event_received_ms')) is not None]
    negative_archive_delays = sum(x < 0 for x in archive_delays)
    archive_delays = [x for x in archive_delays if x >= 0]
    source_fingerprint = fingerprint({'report_input_fingerprint': report_input_fp,
        'fill_source_fingerprint': fill_coverage['source_fingerprint'],
        'quote_source_fingerprint': quote_coverage['source_fingerprint'],
        'protocol_id': PROTOCOL_ID, 'window_ms': [START_MS, END_MS]})
    markout_comparison = []
    for label, selected in (
        ('taker_reductions', [r for r in rows if r['execution_type'] == 'taker' and r['action'] == 'reduces']),
        ('taker_openings', [r for r in rows if r['execution_type'] == 'taker' and r['action'] == 'opens']),
        ('taker_inversions', [r for r in rows if r['execution_type'] == 'taker' and r['action'] == 'inverts']),
        ('taker_openings_or_inversions_combined', [r for r in rows if r['execution_type'] == 'taker' and r['action'] in ('opens','inverts')]),
        ('maker_reductions', [r for r in rows if r['execution_type'] == 'maker' and r['action'] == 'reduces']),
        ('maker_openings_or_inversions_combined', [r for r in rows if r['execution_type'] == 'maker' and r['action'] in ('opens','inverts')])):
        markout_comparison.append({'comparison': label, **_group_summary(selected)})
    # Quote references are event-level and recoverable; the complete source-lot list remains in raw_observations.
    quote_refs = quote_coverage.get('source_refs', [])
    quote_manifest = {'lot_count': len(quote_refs), 'event_count': len(quote_events),
        'source_fingerprint': quote_coverage['source_fingerprint'],
        'source_reference_fingerprint': fingerprint(quote_refs),
        'reference_examples': quote_refs[:2] + quote_refs[-2:] if len(quote_refs) > 4 else quote_refs,
        'by_channel': quote_coverage.get('quotes', {}),
        'rejects': quote_coverage.get('rejected_events', {})}
    artifact = {'schema_version': VERSION, 'request_id': request_id,
        'source_fingerprint': source_fingerprint,
        'protocol_id': PROTOCOL_ID, 'network': NETWORK, 'address': ADDRESS, 'market': MARKET,
        'window': {'start_ms': START_MS, 'end_ms': END_MS, 'event_interval': '[start_ms, end_ms)',
            'archive_receipt_cutoff_ms': report.get('finalised_ms'),
            'archive_receipt_cutoff_note': 'The last REST page was received after the event window ended; include receipts through run finalised_ms while still excluding fill/quote event times outside the frozen window.'},
        'evidence': {'report_input_fingerprint': report_input_fp,
            'report_semantic_fingerprint': report.get('semantic_fingerprint'),
            'report_ref': f'eth_observation_reports:{PROTOCOL_ID}:final_24h#sha256:{report.get("semantic_fingerprint")}',
            'report_archived_json_chars': report_row_chars,
            'fill_source_fingerprint': fill_coverage['source_fingerprint'],
            'fill_pages': {'count': fill_coverage['page_count'], 'complete': fill_coverage['complete_page_count'],
                'incomplete': fill_coverage['incomplete_page_count'], 'unique_fills': fill_coverage['unique_eth_fills'],
                'duplicate_instances': fill_coverage['duplicate_fill_instances'],
                'conflicts': len(fill_coverage['conflicting_fill_ids']),
                'page_reference_fingerprint': fill_coverage['source_fingerprint']},
            'quotes': quote_manifest,
            'connection_count': len(unique_connections), 'stream_disconnection_count': disconnected,
            'quote_event_to_receipt_latency_from_report': quote_latency,
            'local_frame_receipt_to_lot_archive_ms': _numeric_summary(archive_delays),
            'negative_local_frame_receipt_to_lot_archive_count': negative_archive_delays,
            'report_markouts': {'event_time_60s_count': len(event_outcomes),
                'rest_page_receipt_60s_count': len(receipt_outcomes),
                'event_time_60s_missing': len(rows)-len(event_outcomes),
                'rest_page_receipt_60s_missing': len(rows)-len(receipt_outcomes)}},
        'inventory_matrix': _data_inventory(report, report_rows, raw_fills, fill_coverage, quote_events, quote_coverage),
        'reconciliation': {'report_fill_count': len(report_rows), 'raw_fill_count': len(raw_fills),
            'exact_tid_join_count': len(pairs), 'field_mismatches': {}, 'statistics_include_all_fills': True,
            'statistics_exclude_packet_examples': True, 'packet_example_count': 24,
            'fills_used_for_calculations': len(rows), 'source_quote_events_searched': len(quote_events),
            'outcome_60s_event_time_count': len(event_outcomes),
            'outcome_60s_rest_page_receipt_count': len(receipt_outcomes)},
        'definitions': {'position_effect': 'Recomputed from startPosition and signed fill size; inversions split arithmetically into close_quantity=min(abs(pre),size) and open_quantity=size-close_quantity. The observed fee remains attached to the whole fill; it is not split.',
            'event_time_context': 'For BBO and l2Book independently, use only the latest event_ms strictly less than fill event_ms. Same-millisecond quotes are excluded from context and counted with references.',
            'local_receipt_context': 'Frame received_at, REST page requested_at/received_at and raw lot archived_at remain separate local timestamps. Receipt comparisons use the local clock and refer only to page request/receipt, not an execution decision.',
            'clock_limits': 'Venue event_ms versus local receive/archive times are not calibrated; numeric cross-clock deltas are recorded only as diagnostics and are not called latency or proof of availability at execution.',
            'outcomes': 'The archived final report event-time 60s markout and REST-page-receipt 60s markout are separate outcome fields. Future quotes are never used for pre-event context.',
            'displayed_depth': 'Only the visible best bid and best ask level sizes are compared; deeper book depth is not inferred.'},
        'position_chain': {'unique_fills_with_start_position': chain.get('unique_fills_with_start_position'),
            'timestamp_groups': chain.get('timestamp_groups'),
            'multi_fill_timestamp_groups': chain.get('multi_fill_timestamp_groups'),
            'ambiguous_timestamp_groups': chain.get('ambiguous_timestamp_groups'),
            'invalid_timestamp_groups': chain.get('invalid_timestamp_groups'),
            'segments': chain.get('position_chain_segments'), 'ruptures': chain.get('position_chain_ruptures'),
            'coverage_warning': chain.get('coverage_warning')},
        'comparison': {'all_fills_by_execution_and_position_effect': by_behavior_action,
            'by_utc_day_side_execution_and_effect': by_day_side_behavior_action,
            'by_local_position_segment_and_execution_effect': by_segment_behavior_action,
            'primary_taker_vs_combined_comparator': markout_comparison,
            'market_condition_strata_at_max_30s_context_age': _market_condition_summaries(usable),
            'market_condition_usable_fill_count': len(usable),
            'context_cut_definitions': cuts,
            'freshness_sensitivity_and_covered_vs_all_bias': _freshness(rows),
            'by_5min_utc_block': time_details,
            'time_block_cluster_summaries': time_cluster_summaries,
            'order_cluster_summary': order_summary,
            'overlapping_outcome_windows': overlap},
        'fills': rows, 'orders': order_details,
        'next_action': {'state': 'local_analysis_complete',
            'decision': 'The two IA data requests are answered to the extent the fixed archive allows; no further historical collection or inference is justified.',
            'remaining_question': 'A separate prospectively specified evaluation is needed to test conditional repeatability; current fills cannot establish placement decisions, real-time quote availability at execution, or causal trader policy.',
            'automatic_action': 'Persist this exploratory result and its route; stop this existing-window task without collection or another IA call.',
            'model_calls_authorized_or_used_by_resolution': 0, 'collection_started': False, 'paper_or_order_authorized': False},
        'limits': ['This is an exploratory description of executed fills, not the trader’s decision policy or unfilled opportunities.',
            'The 24 packet examples were not used in any calculation; all 9,874 joined fills inform population summaries.',
            'Event-time association does not prove local quote availability or causality because decision timestamps and clock calibration are absent.',
            'Fills within the same order, 5-minute block and overlapping 60-second outcome windows are dependent; cluster summaries are descriptive and no iid confidence claims are made.',
            'Market-context coverage is selected by quote availability; covered-subset summaries are shown beside all-fill baselines.',
            'The fixed 30-second context age is a descriptive analysis cut, accompanied by sensitivity at 100 ms, 1 s, 5 s, 60 s and 5 min; it is not the paper engine’s admission rule.',
            'No prospective window, new collection, IA call, paper run or order was initiated.']}
    return artifact


def _artifact_summary(artifact):
    return {'fill_count': artifact['reconciliation']['fills_used_for_calculations'],
        'exact_tid_join_count': artifact['reconciliation']['exact_tid_join_count'],
        'bbo_event_count': artifact['evidence']['quotes']['by_channel'].get('bbo', {}).get('event_count'),
        'l2book_event_count': artifact['evidence']['quotes']['by_channel'].get('l2Book', {}).get('event_count'),
        'order_count': artifact['comparison']['order_cluster_summary']['distinct_order_count'],
        'primary_context_usable_count': sum(r['eligible_fill_count'] for r in artifact['comparison']['freshness_sensitivity_and_covered_vs_all_bias']['sensitivity']
            if r['both_bbo_and_l2book_strict_predecessors_max_age_ms'] == 30_000),
        'market_condition_usable_fill_count': artifact['comparison']['market_condition_usable_fill_count'],
        'event_time_markout_count': artifact['reconciliation']['outcome_60s_event_time_count'],
        'receipt_markout_count': artifact['reconciliation']['outcome_60s_rest_page_receipt_count'],
        'overlapping_outcome_pairs': artifact['comparison']['overlapping_outcome_windows']['overlapping_fill_pairs']}


def _link_result(store, job, report_row, artifact, artifact_fingerprint, *, reused):
    result = json.loads(job['result_json'] or '{}')
    prior = result.get('local_eth_existing_window_resolution')
    reference = {'version': VERSION, 'state': 'completed', 'artifact_fingerprint': artifact_fingerprint,
        'report_input_fingerprint': report_row['input_fingerprint'], 'artifact_path': ARTIFACT_PATH,
        'summary': _artifact_summary(artifact), 'model_calls': 0, 'collection_started': False}
    followup = {'kind': 'eth_existing_window_analysis', 'state': 'completed',
        'version': VERSION, 'artifact_fingerprint': artifact_fingerprint,
        'request_inventory': artifact['inventory_matrix'],
        'next_action': artifact['next_action']}
    local_resolution = {'kind': 'eth_existing_window_analysis', 'state': 'completed',
        'version': VERSION, 'followup_task': followup, 'result': reference}
    changed = prior != reference or result.get('local_resolution') != local_resolution
    if changed:
        result['local_eth_existing_window_resolution'] = reference
        result['local_resolution'] = local_resolution
        store.connection.execute("update population_research_jobs set result_json=?,updated_ms=? where request_id=? and status in ('hypothesis_recorded','needs_data')",
            (canonical(result), now_ms(), job['request_id']))
        store.connection.commit()
    return reference


def _write_artifact_file(artifact, repo_root):
    path = Path(repo_root) / ARTIFACT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical(artifact).encode('utf-8')
    path.write_bytes(gzip.compress(encoded, mtime=0))
    return path


def execute(store, request_id=REQUEST_ID, *, repo_root=None):
    """Resolve the exact final ETH request from already archived observations."""
    from .eth_prospective_observation import _fills, _quotes
    from .eth_report_projection import semantic_fingerprint
    from .population_routing import route

    job = store.connection.execute('select * from population_research_jobs where request_id=?', (request_id,)).fetchone()
    if request_id != REQUEST_ID or not job or job['status'] not in ('hypothesis_recorded', 'needs_data'):
        raise ValueError('Exact persisted 67f7/ETH hypothesis_recorded needs-data task required')
    packet = json.loads(job['packet_json'])
    body = {k: v for k, v in packet.items() if k != 'fingerprint'}
    if packet.get('fingerprint') != fingerprint(body):
        raise ValueError('Sealed task packet fingerprint mismatch')
    pilot = packet.get('pilot_research', {})
    projection = packet.get('observations', {}).get('prospective_eth_observation_v1', {})
    if (job['network'] != NETWORK or job['address'].lower() != ADDRESS or packet.get('network') != NETWORK
            or packet.get('address', '').lower() != ADDRESS or pilot.get('candidate') != '67f7'
            or projection.get('source', {}).get('protocol_id') != PROTOCOL_ID
            or projection.get('source', {}).get('stage') != 'final_24h'):
        raise ValueError('Sealed packet identity or prospective evidence scope differs from 67f7/ETH final window')
    result = json.loads(job['result_json'] or '{}')
    proposal, critique = result.get('proposal', {}), result.get('critique', {})
    required = proposal.get('hypothesis', {}).get('required_data', [])
    if (proposal.get('decision') != 'hypothesis' or critique.get('decision') != 'consistent'
            or result.get('promotion_authorized') is not False or len(required) < 2
            or not any(str(START_MS) in str(item) and str(END_MS) in str(item) for item in required)):
        raise ValueError('Persisted reviewed proposal does not request the exact existing final window')

    protocol = store.connection.execute('select status,protocol_json,finalised_ms from eth_observation_runs where protocol_id=?',
        (PROTOCOL_ID,)).fetchone()
    report_row = store.connection.execute("select input_fingerprint,report_json from eth_observation_reports where protocol_id=? and stage='final_24h'",
        (PROTOCOL_ID,)).fetchone()
    if not protocol or protocol['status'] != 'finalised' or not protocol['finalised_ms'] or not report_row:
        raise ValueError('Finalized observation and persisted final report are required; no new collection will be started')
    protocol_body = json.loads(protocol['protocol_json'])
    if (protocol_body.get('network') != NETWORK or protocol_body.get('address', '').lower() != ADDRESS
            or protocol_body.get('market') != MARKET or protocol_body.get('start_ms') != START_MS
            or protocol_body.get('end_ms') != END_MS):
        raise ValueError('Frozen observation protocol does not match the requested ETH interval')
    report = json.loads(report_row['report_json'])
    report['finalised_ms'] = protocol['finalised_ms']
    if (report.get('protocol_id') != PROTOCOL_ID or report.get('stage') != 'final_24h'
            or report_row['input_fingerprint'] != report.get('input_fingerprint')
            or projection.get('source', {}).get('input_fingerprint') != report_row['input_fingerprint']
            or projection.get('source', {}).get('semantic_fingerprint') != semantic_fingerprint(report)):
        raise ValueError('Final report no longer matches its sealed packet fingerprint')
    report['semantic_fingerprint'] = semantic_fingerprint(report)

    store.connection.execute('''create table if not exists population_eth_existing_window_resolutions (
        request_id text not null, analysis_version text not null, report_input_fingerprint text not null,
        source_fingerprint text not null, artifact_fingerprint text not null, artifact_json text not null,
        created_ms integer not null, primary key(request_id,analysis_version,report_input_fingerprint))''')
    cached = store.connection.execute('select source_fingerprint,artifact_fingerprint,artifact_json from population_eth_existing_window_resolutions where request_id=? and analysis_version=? and report_input_fingerprint=?',
        (request_id, VERSION, report_row['input_fingerprint'])).fetchone()
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    if cached:
        artifact = json.loads(cached['artifact_json'])
        check = dict(artifact); check.pop('analysis_fingerprint', None)
        if fingerprint(check) != cached['artifact_fingerprint'] or artifact.get('source_fingerprint') != cached['source_fingerprint']:
            raise ValueError('Persisted local-resolution artifact fingerprint mismatch')
        _write_artifact_file(artifact, root)
        reference = _link_result(store, job, report_row, artifact, cached['artifact_fingerprint'], reused=True)
        route_value = route(store, request_id)
        return {'request_id': request_id, 'status': 'unchanged', 'resolver_version': VERSION,
            'source_fingerprint': cached['source_fingerprint'], 'artifact_fingerprint': cached['artifact_fingerprint'],
            'artifact_path': ARTIFACT_PATH, 'summary': reference['summary'], 'route': route_value,
            'model_calls': 0, 'collection_started': False, 'recalculated': False}

    # The archive receipt cutoff is the finalisation time, while event records
    # remain restricted to the protocol's frozen [start,end) window.
    cutoff = int(protocol['finalised_ms'])
    raw_fills, fill_coverage = _fills(store, protocol_body, cutoff)
    quote_events, quote_coverage = _quotes(store, protocol_body, cutoff)
    if len(raw_fills) != len(report.get('fills', [])):
        raise ValueError(f'Final report/raw fill count mismatch: report={len(report.get("fills", []))}, archive={len(raw_fills)}')
    expected_quote_counts = report.get('coverage', {}).get('market', {}).get('quotes', {})
    for channel in ('bbo', 'l2Book'):
        expected = expected_quote_counts.get(channel, {}).get('event_count')
        observed = quote_coverage.get('quotes', {}).get(channel, {}).get('event_count')
        if expected is not None and expected != observed:
            raise ValueError(f'{channel} quote archive count differs from finalized report: {observed} != {expected}')
    # Verify the report's event-level fields against every raw archive fill before analysis.
    _validate_fill_join(report['fills'], raw_fills)
    artifact = _build_artifact(request_id, report, report_row['input_fingerprint'], report['fills'],
        raw_fills, fill_coverage, quote_events, quote_coverage, len(report_row['report_json']))
    artifact.pop('analysis_fingerprint', None)
    artifact['analysis_fingerprint'] = fingerprint(artifact)
    artifact_fingerprint = artifact['analysis_fingerprint']
    source_fp = artifact['source_fingerprint']
    store.connection.execute('insert into population_eth_existing_window_resolutions values(?,?,?,?,?,?,?)',
        (request_id, VERSION, report_row['input_fingerprint'], source_fp, artifact_fingerprint,
            canonical(artifact), now_ms()))
    store.connection.commit()
    _write_artifact_file(artifact, root)
    reference = _link_result(store, job, report_row, artifact, artifact_fingerprint, reused=False)
    route_value = route(store, request_id)
    return {'request_id': request_id, 'status': 'prepared', 'resolver_version': VERSION,
        'source_fingerprint': source_fp, 'artifact_fingerprint': artifact_fingerprint,
        'artifact_path': ARTIFACT_PATH, 'summary': reference['summary'], 'route': route_value,
        'model_calls': 0, 'collection_started': False, 'recalculated': True}
