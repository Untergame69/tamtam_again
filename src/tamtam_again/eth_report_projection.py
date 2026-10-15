"""Compact, deterministic model-facing projection of persisted ETH reports."""
from __future__ import annotations

import hashlib
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .engine import canonical, fingerprint

VERSION = 'eth-report-evidence-projection-v1'
MAX_EXAMPLES_PER_STRATUM = 2
BEHAVIORS = (('taker', True), ('maker', False), ('unknown', None))
ACTIONS = ('opens', 'reduces', 'inverts', 'unknown')


def semantic_fingerprint(report):
    return fingerprint({k: report.get(k) for k in ('protocol_id','protocol_fingerprint','stage','input_fingerprint',
        'decision','coverage','summary','fills','quote_latency_ms','limits')})


def work_payload(protocol_id, stage, report):
    return {'protocol_id': protocol_id, 'stage': stage,
        'semantic_fingerprint': semantic_fingerprint(report)}


def _day(fill):
    value = fill.get('event_ms')
    if type(value) is not int:
        return 'unknown'
    return datetime.fromtimestamp(value / 1000, timezone.utc).date().isoformat()


def _decimal_sum(rows, field):
    total = Decimal(0); found = False; missing = 0
    for row in rows:
        try:
            value = Decimal(str(row.get(field)))
            if not value.is_finite():
                raise InvalidOperation
            total += value; found = True
        except (InvalidOperation, TypeError, ValueError):
            missing += 1
    return {'sum': str(total) if found else None, 'missing': missing}


def _fee_sums(rows):
    sums = defaultdict(Decimal); missing = 0
    for row in rows:
        if row.get('fee') is None:
            missing += 1; continue
        try:
            value = Decimal(str(row['fee']))
            if not value.is_finite():
                raise InvalidOperation
            sums[str(row.get('fee_token') or 'unknown')] += value
        except (InvalidOperation, TypeError, ValueError):
            missing += 1
    return {'signed_amounts': {k: str(v) for k, v in sorted(sums.items())}, 'missing': missing}


def _stats(rows):
    def group_stat(group):
        def median(field, predicate=lambda row: True):
            values = []
            for row in group:
                value = row.get(field)
                if predicate(row) and isinstance(value, (int, float)):
                    values.append(value)
            return statistics.median(values) if values else None

        sensitivity = {}
        quote_coverage = {}
        for age in (100, 1000, 5000, 30000):
            usable = [row for row in group if isinstance(row.get('prefill_quote'), dict)
                and type(row['prefill_quote'].get('age_ms')) is int
                and row['prefill_quote']['age_ms'] <= age
                and isinstance(row.get('event_time_markout_60s_bps'), (int, float))]
            sensitivity[str(age)] = {'count': len(usable),
                'coverage_pct': round(100 * len(usable) / len(group), 2) if group else None,
                'median_bps': statistics.median([row['event_time_markout_60s_bps'] for row in usable]) if usable else None}
            quote_coverage[str(age)] = sum(1 for row in group if isinstance(row.get('prefill_quote'), dict)
                and type(row['prefill_quote'].get('age_ms')) is int and row['prefill_quote']['age_ms'] <= age)
        strict = sensitivity['1000']
        receipt = [row['post_receipt_markout_60s_bps'] for row in group
            if isinstance(row.get('post_receipt_markout_60s_bps'), (int, float))]
        return {'fills': len(group), 'markout_60s_count': strict['count'],
            'markout_60s_coverage_pct': strict['coverage_pct'],
            'directional_markout_60s_median_bps': strict['median_bps'],
            'freshness_sensitivity': sensitivity, 'prefill_quote_coverage_by_max_age': quote_coverage,
            'post_page_receipt_markout_60s_count': len(receipt),
            'post_page_receipt_markout_60s_median_bps': statistics.median(receipt) if receipt else None,
            'observed_fees_by_token': _fee_sums(group),
            'size_sum': _decimal_sum(group, 'size'), 'close_quantity_sum': _decimal_sum(group, 'close_quantity'),
            'open_quantity_sum': _decimal_sum(group, 'open_quantity')}

    result = {}
    for behavior, crossed in BEHAVIORS:
        result[behavior] = {}
        for action in ACTIONS:
            group = [row for row in rows if row.get('crossed') is crossed and row.get('action') == action]
            result[behavior][action] = group_stat(group)
    return result


def _stable_fill_key(fill):
    tid = fill.get('tid')
    if tid is not None:
        return str(tid)
    return canonical({key: fill.get(key) for key in ('event_ms','side','size','price','crossed',
        'fill_page_observation_id','fill_page_sha256')})


def _quote_sample(quote):
    if not isinstance(quote, dict):
        return None
    return {key: quote.get(key) for key in ('event_ms','age_ms','bid','bid_size','ask','ask_size',
        'channel','received_at','archived_at','archived_before_fill_page_request','connection_id','ref')
        if key in quote}


def _example(fill, day):
    obs_id = fill.get('fill_page_observation_id')
    sha = fill.get('fill_page_sha256')
    return {'day_utc': day, 'fill_id': fill.get('tid'), 'event_ms': fill.get('event_ms'),
        'action': fill.get('action'), 'crossed': fill.get('crossed'), 'side': fill.get('side'),
        'start_position': fill.get('start_position'), 'size': fill.get('size'), 'price': fill.get('price'),
        'close_quantity': fill.get('close_quantity'), 'open_quantity': fill.get('open_quantity'),
        'fee': fill.get('fee'), 'fee_token': fill.get('fee_token'),
        'event_to_fill_page_receipt_ms': fill.get('event_to_fill_page_receipt_ms'),
        'fill_page_received_at': fill.get('fill_page_received_at'),
        'fill_page_archived_at': fill.get('fill_page_archived_at'),
        'prefill_quote': _quote_sample(fill.get('prefill_quote')),
        'future_quote': _quote_sample(fill.get('future_quote')),
        'event_time_markout_60s_bps': fill.get('event_time_markout_60s_bps'),
        'post_receipt_markout_60s_bps': fill.get('post_receipt_markout_60s_bps'),
        'fill_page_ref': (f'raw_observations:{obs_id}#sha256:{sha}' if obs_id is not None and sha else None),
        'prefill_quote_ref': (fill.get('prefill_quote') or {}).get('ref') if isinstance(fill.get('prefill_quote'), dict) else None,
        'future_quote_ref': (fill.get('future_quote') or {}).get('ref') if isinstance(fill.get('future_quote'), dict) else None}


def _selected_examples(rows):
    groups = defaultdict(list)
    for fill in rows:
        day = _day(fill)
        crossed = fill.get('crossed')
        behavior = 'taker' if crossed is True else 'maker' if crossed is False else 'unknown'
        action = fill.get('action') if fill.get('action') in ACTIONS else 'unknown'
        identity = _stable_fill_key(fill)
        # Selection uses only stable identity and stratum, never prices, fees or outcomes.
        rank = hashlib.sha256((day + '\0' + behavior + '\0' + action + '\0' + identity).encode()).hexdigest()
        groups[(day, behavior, action)].append((rank, identity, fill))
    selected = []
    for (day, behavior, action), values in sorted(groups.items()):
        for rank, identity, fill in sorted(values, key=lambda row: (row[0], row[1]))[:MAX_EXAMPLES_PER_STRATUM]:
            sample = _example(fill, day)
            sample['stratum'] = {'behavior': behavior, 'action': action}
            sample['selection_sha256'] = rank
            selected.append(sample)
    return selected


def _coverage_projection(report):
    coverage = report.get('coverage') if isinstance(report.get('coverage'), dict) else {}
    fills = coverage.get('fills') if isinstance(coverage.get('fills'), dict) else {}
    pages = fills.get('pages') if isinstance(fills.get('pages'), list) else []
    market = coverage.get('market') if isinstance(coverage.get('market'), dict) else {}
    source_refs = market.get('source_refs') if isinstance(market.get('source_refs'), list) else []
    rejected = market.get('rejected_events') if isinstance(market.get('rejected_events'), dict) else {}
    quote_groups = market.get('quotes') if isinstance(market.get('quotes'), dict) else {}
    page_refs = [{key: page.get(key) for key in ('poll_id','observation_id','sha256','record_count','complete',
        'requested_at','response_received_at','archived_at','response_to_archive_ms') if key in page}
        for page in pages if isinstance(page, dict)]
    reject_counts = {str(k): v for k, v in rejected.items() if isinstance(v, (int, float, str, bool, type(None)))}
    return {'fills': {'page_count': fills.get('page_count', len(pages)),
            'complete_page_count': fills.get('complete_page_count'),
            'incomplete_page_count': fills.get('incomplete_page_count'),
            'empty_page_count': sum(1 for page in pages if page.get('record_count') == 0),
            'duplicate_fill_instances': fills.get('duplicate_fill_instances'),
            'conflicting_fill_count': len(fills.get('conflicting_fill_ids', [])) if isinstance(fills.get('conflicting_fill_ids'), list) else None,
            'unique_eth_fills': fills.get('unique_eth_fills'),
            'source_fingerprint': fills.get('source_fingerprint'),
            'page_proof_count': len(page_refs), 'page_proof_fingerprint': fingerprint(page_refs),
            'page_proof_examples': page_refs[:2] + page_refs[-2:] if len(page_refs) > 4 else page_refs},
        'market': {'quotes': quote_groups,
            'source_fingerprint': market.get('source_fingerprint'),
            'rejected_event_count_by_reason': reject_counts,
            'rejected_event_detail_count': len(rejected),
            'rejected_event_fingerprint': fingerprint(rejected),
            'source_reference_count': len(source_refs),
            'source_reference_fingerprint': fingerprint(source_refs),
            'source_reference_examples': sorted(source_refs, key=lambda ref: fingerprint(ref))[:4]},
        'polls': _poll_coverage(report.get('polls', [])),
        'stream_health': _health_coverage(report.get('stream_health', [])),
        'collector_telemetry': _telemetry_coverage(report.get('collector_telemetry', []))}


def _poll_coverage(rows):
    counts = Counter(); errors = Counter(); complete = 0; refs = []; intervals = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict): continue
        counts[str(row.get('status') or 'unknown')] += 1
        complete += bool(row.get('complete'))
        if row.get('error_code'): errors[str(row['error_code'])] += 1
        if type(row.get('start_ms')) is int and type(row.get('end_ms')) is int:
            intervals.append((row['start_ms'], row['end_ms']))
        refs.append({key: row.get(key) for key in ('poll_id','observation_id','start_ms','end_ms','status',
            'record_count','complete','error_code')})
    intervals.sort(); gaps = [max(0, intervals[i][0] - intervals[i-1][1]) for i in range(1, len(intervals))]
    return {'count': sum(counts.values()), 'by_status': dict(sorted(counts.items())),
        'complete_count': complete, 'error_count_by_code': dict(sorted(errors.items())),
        'covered_start_ms': intervals[0][0] if intervals else None,
        'covered_end_ms': max((end for _, end in intervals), default=None),
        'positive_gap_count': sum(gap > 0 for gap in gaps), 'max_gap_ms': max(gaps, default=0),
        'records_fingerprint': fingerprint(refs)}


def _health_coverage(rows):
    kinds = Counter(); disconnected = 0; sessions = set(); refs = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict): continue
        kinds[str(row.get('kind') or 'unknown')] += 1
        disconnected += row.get('connected') is False
        if row.get('session'): sessions.add(row['session'])
        refs.append({'observation_id': row.get('observation_id'), 'sha256': row.get('sha256'),
            'observed_at': row.get('observed_at'), 'kind': row.get('kind'), 'connected': row.get('connected')})
    return {'count': sum(kinds.values()), 'by_kind': dict(sorted(kinds.items())),
        'disconnected_count': disconnected, 'session_count': len(sessions), 'records_fingerprint': fingerprint(refs)}


def _telemetry_coverage(rows):
    collectors = Counter(); errors = Counter(); sessions = set(); frames = 0; reconnects = 0; lags = []
    refs = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict): continue
        collectors[str(row.get('collector') or 'unknown')] += 1
        if row.get('error_type'): errors[str(row['error_type'])] += 1
        if row.get('session'): sessions.add(row['session'])
        if isinstance(row.get('frames'), (int, float)): frames += row['frames']
        if isinstance(row.get('reconnections'), (int, float)): reconnects += row['reconnections']
        if isinstance(row.get('max_flush_lag_seconds'), (int, float)): lags.append(row['max_flush_lag_seconds'])
        refs.append({key: row.get(key) for key in ('ref','recorded_at','collector','session','frames',
            'reconnections','error_type','max_flush_lag_seconds')})
    return {'count': sum(collectors.values()), 'by_collector': dict(sorted(collectors.items())),
        'by_error_type': dict(sorted(errors.items())), 'session_count': len(sessions),
        'frame_count_sum': frames, 'reconnection_sum': reconnects,
        'max_flush_lag_seconds': max(lags) if lags else None,
        'records_fingerprint': fingerprint(refs)}


def project(report):
    """Retain complete comparison statistics, compress proof inventories, and bound examples."""
    rows = report.get('fills') if isinstance(report.get('fills'), list) else []
    by_day = defaultdict(list)
    for row in rows:
        if isinstance(row, dict): by_day[_day(row)].append(row)
    days = [{'day_utc': day, 'fill_count': len(group), 'statistics_by_execution_and_position_effect': _stats(group)}
        for day, group in sorted(by_day.items())]
    semantic = semantic_fingerprint(report)
    protocol = report.get('protocol_id', 'unknown')
    stage = report.get('stage', 'unknown')
    report_ref = f'eth_observation_reports:{protocol}:{stage}#sha256:{semantic}'
    projection = {'schema_version': VERSION,
        'source': {'protocol_id': protocol, 'stage': stage,
            'input_fingerprint': report.get('input_fingerprint'), 'semantic_fingerprint': semantic,
            'full_report_ref': report_ref},
        'decision': report.get('decision'),
        'population_statistics': {'fill_count': len(rows),
            'by_execution_and_position_effect': _stats(rows),
            'source_report_summary_fingerprint': fingerprint(report.get('summary', {})),
            'by_utc_day': days,
            'statistics_note': 'Overall and daily aggregates describe the full reported fill population; examples below are a separate identity-hash sample.'},
        'coverage_and_gaps': _coverage_projection(report),
        'quote_latency_ms': report.get('quote_latency_ms', {}),
        'limits': report.get('limits', []),
        'examples': {'selection_rule': 'At most two fills per UTC day × crossed classification × position-effect group; lowest SHA256 of stable fill identity within each stratum. Selection does not inspect prices, fees or markouts.',
            'population_count': len(rows), 'selected_count': 0, 'rows': []}}
    examples = _selected_examples(rows)
    projection['examples']['selected_count'] = len(examples)
    projection['examples']['rows'] = examples
    projection['projection_fingerprint'] = fingerprint(projection)
    return projection
