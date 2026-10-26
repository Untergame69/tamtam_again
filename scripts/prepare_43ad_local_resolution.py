#!/usr/bin/env python3
"""Reproduce 43ad/BTC local execution strata and bounded-episode detail.

Reads the authorized population archive and sealed request packet through a
SQLite read-only, query-only transaction. No network, model, or service calls.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from tamtam_again.engine import canonical, fingerprint
from tamtam_again.descriptive_admission import validate_report_paths
from tamtam_again.hype_diagnostics import start_position_chain_summary
from tamtam_again.population_descriptive import (
    _d, _load_fills, _position_flows, prepare_candidate_market_detail,
    prepare_inventory_execution_association,
)


ADDRESS = '0xbb160cb61e694570f9d570f9fcde7c61dd2143ad'
MARKET = 'BTC'
CUTOFF_MS = 1793009400000
PERIOD_START_MS = 1790417400000
REQUEST_ID = '52a31dce1f171f51849b38c0a3760992e12d02991f07bc9276a7f1e79388ce32'


class ReadOnlyStore:
    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA query_only=ON')
        self.connection.execute('BEGIN')

    def close(self):
        self.connection.close()


def _crossed(fill):
    if fill.get('crossed') is False:
        return 'maker_crossed_false'
    if fill.get('crossed') is True:
        return 'taker_crossed_true'
    return 'crossed_unknown'


def _day(ms):
    return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).date().isoformat()


def _blank_stratum():
    return {
        'fill_count': 0, 'execution_quantity': Decimal(0),
        'execution_notional_quote_units': Decimal(0),
        'close_quantity': Decimal(0), 'open_quantity': Decimal(0),
        'reversal_count': 0, 'reversal_close_quantity': Decimal(0),
        'reversal_open_quantity': Decimal(0), 'fee_part_count': 0,
        'fee_missing_count': 0, 'signed_fees_by_token': defaultdict(Decimal),
    }


def _add(matrix, key, fill, pre, post):
    row = matrix[key]
    quantity = _d(fill['sz'])
    price = _d(fill['px'])
    delta = post - pre
    if pre == 0 or pre * delta >= 0:
        close = Decimal(0)
        opened = quantity
    else:
        close = min(abs(pre), abs(delta))
        opened = max(Decimal(0), quantity - close)
    row['fill_count'] += 1
    row['execution_quantity'] += quantity
    row['execution_notional_quote_units'] += quantity * price
    row['close_quantity'] += close
    row['open_quantity'] += opened
    if close and opened:
        row['reversal_count'] += 1
        row['reversal_close_quantity'] += close
        row['reversal_open_quantity'] += opened
    if fill.get('fee') is None:
        row['fee_missing_count'] += 1
    else:
        row['fee_part_count'] += 1
        row['signed_fees_by_token'][str(fill.get('feeToken') or 'unknown')] += _d(fill['fee'])


def _serialize_stratum(key, row):
    segment, day, side, bucket, crossed = key
    return {
        'segment': segment, 'utc_day': day, 'position_side': side,
        'inventory_bucket': bucket, 'crossed_group': crossed,
        'fill_count': row['fill_count'],
        'execution_quantity': str(row['execution_quantity']),
        'execution_notional_quote_units': str(row['execution_notional_quote_units']),
        'close_quantity': str(row['close_quantity']), 'open_quantity': str(row['open_quantity']),
        'reversal_count': row['reversal_count'],
        'reversal_close_quantity': str(row['reversal_close_quantity']),
        'reversal_open_quantity': str(row['reversal_open_quantity']),
        'fee_part_count': row['fee_part_count'], 'fee_missing_count': row['fee_missing_count'],
        'signed_fees_by_token': {k: str(v) for k, v in sorted(row['signed_fees_by_token'].items())},
    }


def _inventory_matrix(events, offsets, cuts):
    def bucket(pre):
        magnitude = abs(pre)
        if magnitude == 0:
            return 'flat'
        if magnitude <= cuts['q25']:
            return 'inventory_q1'
        if magnitude <= cuts['q50']:
            return 'inventory_q2'
        if magnitude <= cuts['q75']:
            return 'inventory_q3'
        return 'inventory_q4'

    segment_by_index = {}
    for offset in offsets:
        for i in range(offset['first_event'], offset['first_event'] + offset['event_count']):
            segment_by_index[i] = offset['segment']
    strata = defaultdict(_blank_stratum)
    segment_days = set()
    for i, event in enumerate(events):
        fill = event['fill']
        pre = _d(event['pre_position'])
        post = _d(event['post_position'])
        segment, day = str(segment_by_index[i]), _day(fill['time'])
        segment_days.add((segment, day))
        side = 'flat' if pre == 0 else 'long' if pre > 0 else 'short'
        key = (segment, day, side, bucket(pre), _crossed(fill))
        _add(strata, key, fill, pre, post)

    # Dense rows retain true zero cells for every side/bucket and crossed class.
    buckets = [('flat', 'flat')] + [(side, f'inventory_q{i}') for side in ('long', 'short') for i in range(1, 5)]
    crossed_groups = ('maker_crossed_false', 'taker_crossed_true', 'crossed_unknown')
    for segment, day in sorted(segment_days, key=lambda x: (int(x[0]), x[1])):
        for side, inv_bucket in buckets:
            for crossed in crossed_groups:
                strata.setdefault((segment, day, side, inv_bucket, crossed), _blank_stratum())
    rows = [_serialize_stratum(k, v) for k, v in sorted(strata.items(), key=lambda x: (
        int(x[0][0]), x[0][1], x[0][2], x[0][3], x[0][4]))]
    return rows, sorted(segment_days, key=lambda x: (int(x[0]), x[1]))


def _unclassified_activity(fills, invalid_groups):
    """Retain execution totals for same-time groups without a unique path."""
    invalid_times = {int(row['time_ms']) for row in invalid_groups}
    groups = defaultdict(lambda: {
        'fill_count': 0, 'size': Decimal(0), 'notional_quote_units': Decimal(0),
        'signed_fees_by_token': defaultdict(Decimal),
    })
    for fill in fills:
        if int(fill['time']) not in invalid_times:
            continue
        row = groups[(_day(fill['time']), _crossed(fill))]
        size = _d(fill['sz'])
        row['fill_count'] += 1
        row['size'] += size
        row['notional_quote_units'] += size * _d(fill['px'])
        if fill.get('fee') is not None:
            row['signed_fees_by_token'][str(fill.get('feeToken') or 'unknown')] += _d(fill['fee'])
    return [{
        'utc_day': day, 'crossed_group': crossed, 'fill_count': row['fill_count'],
        'size': str(row['size']), 'notional_quote_units': str(row['notional_quote_units']),
        'signed_fees_by_token': {k: str(v) for k, v in sorted(row['signed_fees_by_token'].items())},
    } for (day, crossed), row in sorted(groups.items())]


def _episode_table(segment_events):
    episodes = []
    expected_cash_fees = {'price_result_quote_units': Decimal(0), 'fees_by_token': defaultdict(Decimal)}
    for segment_no, events in segment_events:
        _, bounded, _ = _position_flows([event['fill'] for event in events])
        index_by_tid = {str(event['fill']['tid']): i for i, event in enumerate(events)}
        for ep in bounded:
            first = index_by_tid[ep['entry_tid']]
            last = index_by_tid[ep['exit_tid']]
            if last < first:
                raise AssertionError('bounded episode exit precedes entry')
            path = events[first:last + 1]
            buys = sells = buy_notional = sell_notional = maker_qty = taker_qty = unknown_qty = Decimal(0)
            maker_count = taker_count = unknown_count = missing_fee_parts = 0
            fee_parts = defaultdict(Decimal)
            part_count = 0
            peak = Decimal(0)
            local_position = Decimal(0)
            for j, event in enumerate(path):
                fill = event['fill']
                pre, post = _d(event['pre_position']), _d(event['post_position'])
                full_qty = _d(fill['sz'])
                qty = full_qty
                if j == 0 and str(fill['tid']) == ep['entry_tid'] and pre * post < 0:
                    qty = abs(post)  # reversal opening leg
                if j == len(path) - 1 and str(fill['tid']) == ep['exit_tid'] and pre * post < 0:
                    qty = abs(pre)  # reversal closing leg
                if qty < 0 or qty > full_qty:
                    raise AssertionError('invalid episode part quantity')
                px = _d(fill['px'])
                notion = px * qty
                if fill['side'] == 'B':
                    buys += qty
                    buy_notional += notion
                else:
                    sells += qty
                    sell_notional += notion
                if fill.get('crossed') is False:
                    maker_qty += qty
                    maker_count += 1
                elif fill.get('crossed') is True:
                    taker_qty += qty
                    taker_count += 1
                else:
                    unknown_qty += qty
                    unknown_count += 1
                if fill.get('fee') is None:
                    missing_fee_parts += 1
                else:
                    token = str(fill.get('feeToken') or 'unknown')
                    fee_parts[token] += _d(fill['fee']) * qty / full_qty if full_qty else Decimal(0)
                part_count += 1
                # A reversal also belongs to its neighbouring episode. Only the
                # allocated leg contributes to this episode's inventory peak.
                local_position += qty if fill['side']=='B' else -qty
                peak = max(peak, abs(local_position))

            cash = sell_notional - buy_notional
            if local_position != 0:
                raise AssertionError('allocated bounded episode does not return to zero')
            if cash != _d(ep['price_result_quote_units']):
                raise AssertionError(f"episode cash reconstruction mismatch: {ep['entry_tid']}..{ep['exit_tid']}")
            expected_fees = {str(k): _d(v) for k, v in ep['signed_fees_by_token'].items()}
            if dict(fee_parts) != expected_fees:
                raise AssertionError(f"episode fee reconstruction mismatch: {ep['entry_tid']}..{ep['exit_tid']}")
            if ep['close_type'] == 'returned_to_zero' and _d(path[-1]['post_position']) != 0:
                raise AssertionError('flat bounded episode does not end at zero')
            if ep['close_type'] == 'position_reversal':
                reversal = path[-1]
                pre = _d(reversal['pre_position'])
                delta = _d(reversal['post_position']) - pre
                closing_delta = abs(pre) if delta > 0 else -abs(pre)
                if pre * delta >= 0 or pre + closing_delta != 0:
                    raise AssertionError('reversal closing part does not return its local episode to zero')
            expected_cash_fees['price_result_quote_units'] += cash
            for token, value in fee_parts.items():
                expected_cash_fees['fees_by_token'][token] += value
            episodes.append({
                'segment': segment_no, 'start_ms': ep['start_ms'], 'end_ms': ep['end_ms'],
                'duration_ms': int(ep['end_ms']) - int(ep['start_ms']),
                'entry_tid': ep['entry_tid'], 'exit_tid': ep['exit_tid'],
                'close_type': ep['close_type'], 'fill_part_count': part_count,
                'buy_quantity': str(buys), 'sell_quantity': str(sells),
                'buy_notional_quote_units': str(buy_notional),
                'sell_notional_quote_units': str(sell_notional),
                'total_part_notional_quote_units': str(buy_notional + sell_notional),
                'price_result_quote_units': str(cash),
                'signed_fees_by_token': {k: str(v) for k, v in sorted(fee_parts.items())},
                'fee_part_missing_count': missing_fee_parts,
                'maker_part_count': maker_count, 'maker_quantity': str(maker_qty),
                'taker_part_count': taker_count, 'taker_quantity': str(taker_qty),
                'crossed_unknown_part_count': unknown_count, 'crossed_unknown_quantity': str(unknown_qty),
                'peak_abs_position': str(peak),
            })
    return episodes, expected_cash_fees


def _episode_concentration(episodes, axis):
    grouped = defaultdict(lambda: {
        'episode_count': 0, 'positive_count': 0, 'negative_count': 0, 'zero_count': 0,
        'positive_cash': Decimal(0), 'negative_cash': Decimal(0), 'net_cash': Decimal(0),
        'fees': defaultdict(Decimal),
    })
    for episode in episodes:
        key = _day(episode['end_ms']) if axis == 'exit_utc_day' else str(episode['segment'])
        row = grouped[key]
        cash = _d(episode['price_result_quote_units'])
        row['episode_count'] += 1
        row['net_cash'] += cash
        if cash > 0:
            row['positive_count'] += 1
            row['positive_cash'] += cash
        elif cash < 0:
            row['negative_count'] += 1
            row['negative_cash'] += cash
        else:
            row['zero_count'] += 1
        for token, fee in episode['signed_fees_by_token'].items():
            row['fees'][token] += _d(fee)
    ordered = sorted(grouped.items(), key=lambda item: int(item[0]) if axis == 'segment' else item[0])
    gross_positive = sum((row['positive_cash'] for row in grouped.values()), Decimal(0))
    result = {
        'axis': axis,
        'keys': [key for key, _ in ordered],
        'episodes': [row['episode_count'] for _, row in ordered],
        'positive_count': [row['positive_count'] for _, row in ordered],
        'negative_count': [row['negative_count'] for _, row in ordered],
        'zero_count': [row['zero_count'] for _, row in ordered],
        'positive_cash': [str(row['positive_cash']) for _, row in ordered],
        'negative_cash_signed': [str(row['negative_cash']) for _, row in ordered],
        'net_cash': [str(row['net_cash']) for _, row in ordered],
        'fees': [';'.join(f'{token}={value}' for token, value in sorted(row['fees'].items()))
            for _, row in ordered],
        'positive_cash_share_pct': [
            str(row['positive_cash'] * 100 / gross_positive) if gross_positive else None
            for _, row in ordered],
        'positive_share_basis': 'cell positive cash / sum of all positive episode cash; negative rows excluded; no net denominator',
    }
    if ordered:
        top_key, top_row = max(ordered, key=lambda item: item[1]['positive_cash'])
        result['largest_positive_contribution'] = {
            'key': top_key, 'cash': str(top_row['positive_cash']),
            'share_pct_of_gross_positive': str(top_row['positive_cash'] * 100 / gross_positive)
                if gross_positive else None,
        }
    else:
        result['largest_positive_contribution'] = {'key': None, 'cash': '0', 'share_pct_of_gross_positive': None}
    return result


def _sealed_fingerprint(store, request_id):
    row = store.connection.execute(
        'select j.packet_json,j.input_fingerprint,j.status,t.packet_fingerprint,t.address,t.candidate '
        'from population_research_jobs j join population_research_pilot_tasks t using(request_id) '
        'where j.request_id=?', (request_id,)).fetchone()
    if row is None or row['candidate'] != '43ad' or row['address'].lower() != ADDRESS:
        raise ValueError('sealed packet request is missing or has a different account scope')
    packet = json.loads(row['packet_json'])
    if packet.get('fingerprint') != row['packet_fingerprint']:
        raise ValueError('sealed packet/task fingerprint mismatch')
    detail = packet['observations']['market_execution_detail_v1'][MARKET]
    return {
        'sealed_packet_fingerprint': row['packet_fingerprint'],
        'sealed_input_fingerprint': row['input_fingerprint'],
        'sealed_source_detail_fingerprint': detail['source_detail_fingerprint'],
        'sealed_packet_cutoff_ms': detail['cutoff_ms'],
    }


def build(store, request_id=REQUEST_ID):
    sealed = _sealed_fingerprint(store, request_id)
    metadata=store.connection.execute(
        "select count(*) pages,coalesce(sum(record_count),0) records from raw_observations "
        "where network=? and entity_type='account' and entity_id=? "
        "and source='hyperliquid-population-rest-v1' and endpoint in ('userFills','userFillsByTime') "
        "and observed_at<=? and (window_end_ms is null or window_end_ms<=?)",
        ('hyperliquid-mainnet',ADDRESS,datetime.fromtimestamp(CUTOFF_MS/1000,timezone.utc).isoformat(timespec='milliseconds'),CUTOFF_MS)).fetchone()
    if metadata['pages']>500 or metadata['records']>250000:
        raise ValueError('approved local study exceeds 500-page / 250000-record processing cap')
    detail = prepare_candidate_market_detail(store, 'hyperliquid-mainnet', ADDRESS,
        cutoff_ms=CUTOFF_MS, market=MARKET)
    if detail['detail_fingerprint'] != sealed['sealed_source_detail_fingerprint']:
        raise AssertionError('recomputed source detail fingerprint differs from sealed packet')
    if sealed['sealed_packet_cutoff_ms'] != CUTOFF_MS:
        raise AssertionError('sealed packet cutoff mismatch')
    fills, coverage, refs = _load_fills(store, 'hyperliquid-mainnet', ADDRESS, CUTOFF_MS)
    fills = [f for f in fills if f.get('coin') == MARKET]
    if any(int(f['time']) < PERIOD_START_MS or int(f['time']) >= CUTOFF_MS for f in fills):
        raise AssertionError('fill escaped the authorized event-time interval')
    chain = start_position_chain_summary(fills, include_fill_events=True)
    events, offsets = chain['ordered_segment_fill_events'], chain['ordered_segment_event_offsets']
    cuts = {key: _d(value) for key, value in prepare_inventory_execution_association(
        store, 'hyperliquid-mainnet', ADDRESS, cutoff_ms=CUTOFF_MS,
        market=MARKET)['inventory_magnitude_quantile_cuts'].items()}
    matrix, segment_days = _inventory_matrix(events, offsets, cuts)
    unclassified = _unclassified_activity(fills, chain.get('invalid_timestamp_groups', []))
    segment_events = []
    cursor = 0
    for offset in offsets:
        segment_events.append((offset['segment'], events[cursor:cursor + offset['event_count']]))
        cursor += offset['event_count']
    episodes, reconstructed = _episode_table(segment_events)
    source_episodes = detail['position_path']['episodes']
    if len(episodes) != source_episodes['count']:
        raise AssertionError('bounded episode count differs from source detail')
    if sum((_d(ep['price_result_quote_units']) for ep in episodes), Decimal(0)) != _d(
            detail['position_path']['segments'] and sum((
                _d(s['bounded_episode_price_result_quote_units'])
                for s in detail['position_path']['segments'].values()), Decimal(0))):
        raise AssertionError('episode cashflow total differs from source detail segments')
    if episodes and any(ep['close_type'] not in ('returned_to_zero', 'position_reversal') for ep in episodes):
        raise AssertionError('unexpected unbounded episode in detail')
    aggregate = {
        'episode_count': len(episodes),
        'return_to_zero_count': sum(ep['close_type'] == 'returned_to_zero' for ep in episodes),
        'position_reversal_count': sum(ep['close_type'] == 'position_reversal' for ep in episodes),
        'price_result_quote_units': str(sum((_d(ep['price_result_quote_units']) for ep in episodes), Decimal(0))),
        'signed_fees_by_token': {k: str(v) for k, v in sorted(reconstructed['fees_by_token'].items())},
        'maker_quantity': str(sum((_d(ep['maker_quantity']) for ep in episodes), Decimal(0))),
        'taker_quantity': str(sum((_d(ep['taker_quantity']) for ep in episodes), Decimal(0))),
        'part_notional_quote_units': str(sum((_d(ep['total_part_notional_quote_units']) for ep in episodes), Decimal(0))),
    }
    positive_episodes = [ep for ep in episodes if _d(ep['price_result_quote_units']) > 0]
    negative_episodes = [ep for ep in episodes if _d(ep['price_result_quote_units']) < 0]
    zero_episode_count = len(episodes) - len(positive_episodes) - len(negative_episodes)
    positive_cash = sum((_d(ep['price_result_quote_units']) for ep in positive_episodes), Decimal(0))
    negative_cash = sum((_d(ep['price_result_quote_units']) for ep in negative_episodes), Decimal(0))
    episode_concentration = {
        'episode_count': len(episodes), 'positive_count': len(positive_episodes),
        'negative_count': len(negative_episodes), 'zero_count': zero_episode_count,
        'positive_cash_gross': str(positive_cash), 'negative_cash_signed': str(negative_cash),
        'net_price_cashflow': str(positive_cash + negative_cash),
        'signed_fees_by_token': {k: str(v) for k, v in sorted(reconstructed['fees_by_token'].items())},
        'positive_share_basis': 'positive day/segment amount divided by gross positive episode cash; negative results are excluded; net cash has no share denominator',
        'by_exit_utc_day': _episode_concentration(episodes, 'exit_utc_day'),
        'by_segment': _episode_concentration(episodes, 'segment'),
    }
    side_totals = defaultdict(_blank_stratum)
    day_totals = defaultdict(_blank_stratum)
    segment_totals = defaultdict(_blank_stratum)
    for row in matrix:
        # Aggregate only nonempty strata to avoid multiplying zeros.
        if not row['fill_count']:
            continue
        k = (row['position_side'], row['inventory_bucket'], row['crossed_group'])
        _accumulate_serialized(side_totals[k], row)
        _accumulate_serialized(day_totals[row['utc_day']], row)
        _accumulate_serialized(segment_totals[row['segment']], row)
    for side, inv_bucket in [('flat', 'flat')] + [
            (side, f'inventory_q{i}') for side in ('long', 'short') for i in range(1, 5)]:
        for crossed in ('maker_crossed_false', 'taker_crossed_true', 'crossed_unknown'):
            side_totals[(side, inv_bucket, crossed)]
    def compact_pooled(rows):
        ordered = sorted(rows.items())
        return {
            'keys': [f'{side}/{bucket}/{crossed}' for (side, bucket, crossed), _ in ordered],
            'fills': [value['fill_count'] for _, value in ordered],
            'qty': [str(value['execution_quantity']) for _, value in ordered],
            'notional': [str(value['execution_notional_quote_units']) for _, value in ordered],
            'close_qty': [str(value['close_quantity']) for _, value in ordered],
            'open_qty': [str(value['open_quantity']) for _, value in ordered],
            'reversals': [value['reversal_count'] for _, value in ordered],
            'fees': [';'.join(f'{t}={v}' for t, v in sorted(value['signed_fees_by_token'].items()))
                for _, value in ordered],
        }

    def compact_concentration(rows, name):
        ordered = sorted(rows.items())
        result = {
            'axis': name, 'keys': [key for key, _ in ordered],
            'fills': [], 'maker_fills': [], 'taker_fills': [], 'unknown_fills': [],
            'qty': [], 'maker_qty': [], 'taker_qty': [], 'unknown_qty': [],
            'notional': [], 'maker_fees': [], 'taker_fees': [], 'unknown_fees': [],
        }
        for key, value in ordered:
            result['fills'].append(value['fill_count'])
            result['qty'].append(str(value['execution_quantity']))
            result['notional'].append(str(value['execution_notional_quote_units']))
            for group, prefix in (('maker_crossed_false', 'maker'),
                                  ('taker_crossed_true', 'taker'),
                                  ('crossed_unknown', 'unknown')):
                group_rows = [r for r in matrix if r['crossed_group'] == group and
                    (r['utc_day'] if name == 'utc_day' else r['segment']) == key]
                result[f'{prefix}_fills'].append(sum(r['fill_count'] for r in group_rows))
                result[f'{prefix}_qty'].append(str(sum((_d(r['execution_quantity']) for r in group_rows), Decimal(0))))
                fees = defaultdict(Decimal)
                for row in group_rows:
                    for token, amount in row['signed_fees_by_token'].items():
                        fees[token] += _d(amount)
                result[f'{prefix}_fees'].append(';'.join(f'{t}={v}' for t, v in sorted(fees.items())))
        def peak_share(field):
            total = sum((_d(value) for value in result[field]), Decimal(0))
            if total == 0:
                return {'key': None, 'share_pct': None}
            idx = max(range(len(result[field])), key=lambda i: _d(result[field][i]))
            return {'key': result['keys'][idx], 'share_pct': str(_d(result[field][idx]) * 100 / total)}
        result['max_day_or_segment_share'] = {
            'fills': peak_share('fills'), 'quantity': peak_share('qty'), 'notional': peak_share('notional')}
        result['pooled_maker_fill_share_pct'] = str(
            Decimal(sum(result['maker_fills'])) * 100 / sum(result['fills'])) if sum(result['fills']) else None
        result['pooled_taker_fill_share_pct'] = str(
            Decimal(sum(result['taker_fills'])) * 100 / sum(result['fills'])) if sum(result['fills']) else None
        return result

    artifact = {
        'schema_version': '43ad-btc-local-resolution-v1',
        'scope': {'network': 'hyperliquid-mainnet', 'address': ADDRESS, 'market': MARKET,
            'period_start_ms': PERIOD_START_MS, 'cutoff_ms': CUTOFF_MS,
            'request_id': request_id, **sealed},
        'source_detail_fingerprint_match': True,
        'coverage': {
            'fill_archive': coverage, 'observed_market_fills': len(fills),
            'ordered_position_events': len(events), 'segment_count': len(offsets),
            'rupture_count': len(chain.get('position_chain_ruptures', [])),
            'ambiguous_timestamp_groups': chain.get('ambiguous_timestamp_groups', 0),
            'invalid_timestamp_groups': len(chain.get('invalid_timestamp_groups', [])),
            'inventory_quantile_cuts': {k: str(v) for k, v in cuts.items()},
            'matrix_segment_day_count': len(segment_days),
            'matrix_rows_dense': len(matrix),
            'continuity_proven': False,
        },
        'inventory_execution_by_segment_utc_day': matrix,
        'unclassified_ambiguous_activity_by_utc_day_and_crossed': unclassified,
        'bounded_episodes': episodes,
        'bounded_episode_aggregate': aggregate,
        'bounded_episode_price_fee_concentration': episode_concentration,
        'unclassified_ambiguous_activity_by_utc_day_and_crossed': unclassified,
        'evidence_refs': detail['evidence_refs'],
        'limits': [
            'Rows are local deterministic descriptions of archived fills; page coverage is not history completeness.',
            'Position segments are not bridged; ruptures, ambiguous timestamp groups, and censored endpoints remain.',
            'The 41 fills in ambiguous same-time groups remain in separate daily activity totals and are not assigned an inventory bucket or episode.',
            'Reversal fills are split at zero: the closing part belongs to the prior episode and the opening part to the next.',
            'Maker/taker quantities describe crossed flags on executed fill parts; they do not reveal placement, intent, or queue position.',
            'Episode cashflow and fees cover only locally bounded legs and are not account PnL.',
        ],
    }
    artifact['artifact_fingerprint'] = fingerprint(artifact)
    addendum = {
        'schema_version': '43ad-btc-local-resolution-addendum-v1',
        'scope': artifact['scope'],
        'source_detail_fingerprint_match': True,
        'source_detail_fingerprint': detail['detail_fingerprint'],
        'artifact_fingerprint': artifact['artifact_fingerprint'],
        'artifact_file': '43AD-BTC-LOCAL-RESOLUTION-20261026.json.gz',
        'evidence_fingerprint': detail['evidence_fingerprint'],
        'evidence_reference_count': len(detail['evidence_refs']),
        'coverage': artifact['coverage'],
        'bounded_episode_aggregate': aggregate,
        'bounded_episode_price_fee_concentration': episode_concentration,
        'pooled_inventory_cells': compact_pooled(side_totals),
        'execution_concentration_by_utc_day': compact_concentration(day_totals, 'utc_day'),
        'execution_concentration_by_segment': compact_concentration(segment_totals, 'segment'),
        'ambiguous_activity_by_utc_day_and_crossed': unclassified,
        'interpretation_limits': artifact['limits'],
        'retained_detail': {
            'segment_day_inventory_matrix_rows': len(matrix),
            'bounded_episode_rows': len(episodes),
            'note': 'Full strata matrix and all bounded episode rows are retained in the gzip artifact; this JSON aggregates across every eligible row.',
        },
    }
    addendum['addendum_fingerprint'] = fingerprint(addendum)
    return artifact, addendum


def _accumulate_serialized(dest, row):
    for name in ('fill_count', 'reversal_count', 'fee_part_count', 'fee_missing_count'):
        dest[name] += row[name]
    for name in ('execution_quantity', 'execution_notional_quote_units', 'close_quantity', 'open_quantity',
                 'reversal_close_quantity', 'reversal_open_quantity'):
        dest[name] += _d(row[name])
    for token, value in row['signed_fees_by_token'].items():
        dest['signed_fees_by_token'][token] += _d(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--request-id', default=REQUEST_ID)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--addendum', type=Path, required=True)
    args = parser.parse_args()
    validate_report_paths(args.db,args.artifact,args.addendum)
    store = ReadOnlyStore(args.db)
    try:
        artifact, addendum = build(store, args.request_id)
    finally:
        store.close()
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    args.artifact.write_bytes(gzip.compress((canonical(artifact)+'\n').encode('utf-8'),compresslevel=9,mtime=0))
    args.addendum.parent.mkdir(parents=True, exist_ok=True)
    args.addendum.write_text(canonical(addendum) + '\n', encoding='utf-8')
    print(json.dumps({
        'artifact': str(args.artifact), 'artifact_bytes': args.artifact.stat().st_size,
        'artifact_fingerprint': artifact['artifact_fingerprint'],
        'addendum': str(args.addendum), 'addendum_chars': len(args.addendum.read_text(encoding='utf-8')),
        'addendum_fingerprint': addendum['addendum_fingerprint'],
        'source_detail_fingerprint': artifact['scope']['sealed_source_detail_fingerprint'],
        'episode_count': len(artifact['bounded_episodes']),
        'matrix_rows_dense': len(artifact['inventory_execution_by_segment_utc_day']),
    }, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
