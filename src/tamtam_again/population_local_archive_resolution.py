"""Reusable local resolver for the sealed fill/market-context contract."""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

from .engine import canonical, fingerprint
from .eth_existing_window_resolution import (_build_artifact, _validate_fill_join)
from .eth_prospective_observation import _fills, _quotes
from .eth_report_projection import semantic_fingerprint
from .population_local_analysis_contract import validate_contract
from .validation import now_ms

VERSION = 'population-local-archive-resolution-v1'
TABLE = 'population_local_archive_resolutions'
SHA256_RE = re.compile(r'^[0-9a-f]{64}$')


def _table(store):
    store.connection.execute(f'''create table if not exists {TABLE} (
        request_id text not null, analysis_version text not null, contract_fingerprint text not null,
        report_input_fingerprint text not null, source_fingerprint text not null,
        artifact_fingerprint text not null, artifact_json text not null, created_ms integer not null,
        primary key(request_id,analysis_version,contract_fingerprint,report_input_fingerprint))''')


def _fallback_raw(row, market):
    """Use the sealed report row when a raw fill page is absent; retain unknown OID/time."""
    return {'coin': market, 'tid': str(row.get('tid')), 'oid': None,
        'time': row.get('event_ms'), 'side': row.get('side'), 'crossed': row.get('crossed'),
        'startPosition': row.get('start_position'), 'sz': row.get('size'), 'px': row.get('price'),
        'fee': row.get('fee'), 'feeToken': row.get('fee_token'),
        'fill_page_observation_id': row.get('fill_page_observation_id'),
        'fill_page_sha256': row.get('fill_page_sha256'), 'fill_page_requested_at': None,
        'fill_page_received_at': row.get('fill_page_received_at'),
        'fill_page_archived_at': row.get('fill_page_archived_at'), 'poll_id': None}


def _merge_report_and_raw(report_rows, raw_fills, market):
    report_by_tid = {str(row.get('tid')): row for row in report_rows if row.get('tid') is not None}
    raw_by_tid = {str(row.get('tid')): row for row in raw_fills if row.get('tid') is not None}
    if len(report_by_tid) != len([row for row in report_rows if row.get('tid') is not None]):
        raise ValueError('duplicate report fill identity in sealed source')
    if len(raw_by_tid) != len(raw_fills):
        raise ValueError('duplicate raw fill identity after deterministic archive read')
    pairs = {}
    mismatches = {}
    analysis_fills = []
    for tid, row in sorted(report_by_tid.items()):
        raw = raw_by_tid.get(tid)
        if raw is not None:
            try:
                pairs.update(_validate_fill_join([row], [raw]))
                analysis_fills.append(raw)
                continue
            except ValueError as exc:
                mismatches[tid] = str(exc)[:240]
        analysis_fills.append(_fallback_raw(row, market))
    return analysis_fills, pairs, {'report_only_tid_count': len(report_by_tid.keys() - raw_by_tid.keys()),
        'raw_only_tid_count': len(raw_by_tid.keys() - report_by_tid.keys()),
        'field_mismatch_fill_count': len(mismatches),
        'mismatch_examples': dict(list(sorted(mismatches.items()))[:10])}


def _source_rows(store, contract):
    source = contract['source']
    runs_table = store.connection.execute("select 1 from sqlite_master where type='table' and name='eth_observation_runs'").fetchone()
    reports_table = store.connection.execute("select 1 from sqlite_master where type='table' and name='eth_observation_reports'").fetchone()
    if not runs_table or not reports_table:
        return None, {'stage': 'local_archive_source', 'code': 'source_registry_absent',
            'field': 'eth_observation_runs/eth_observation_reports', 'observed': None,
            'limit': 'persisted, authorized source report and frozen protocol are required'}
    run = store.connection.execute('select status,protocol_fingerprint,protocol_json,finalised_ms from eth_observation_runs where protocol_id=?',
        (source['protocol_id'],)).fetchone()
    report_row = store.connection.execute('select input_fingerprint,report_json from eth_observation_reports where protocol_id=? and stage=?',
        (source['protocol_id'], source['stage'])).fetchone()
    if not run or not report_row:
        return None, {'stage': 'local_archive_source', 'code': 'source_report_unavailable',
            'field': 'source.report_ref', 'observed': {'run_present': bool(run), 'report_present': bool(report_row)},
            'limit': 'the exact report and run named by the sealed contract must already exist'}
    if run['status'] != 'finalised' or type(run['finalised_ms']) is not int:
        return None, {'stage': 'local_archive_source', 'code': 'source_not_finalised',
            'field': 'eth_observation_runs.finalised_ms', 'observed': run['finalised_ms'],
            'limit': 'use only a finalized archive cutoff; no collection is started'}
    try:
        protocol = json.loads(run['protocol_json'])
        report = json.loads(report_row['report_json'])
    except (TypeError, ValueError) as exc:
        return None, {'stage': 'local_archive_source', 'code': 'source_json_invalid',
            'field': 'protocol_json/report_json', 'observed': type(exc).__name__,
            'limit': 'valid persisted protocol and report JSON'}
    if report_row['input_fingerprint'] != source['input_fingerprint'] or report.get('input_fingerprint') != source['input_fingerprint']:
        return None, {'stage': 'local_archive_source', 'code': 'source_input_fingerprint_mismatch',
            'field': 'source.input_fingerprint', 'observed': report_row['input_fingerprint'],
            'limit': source['input_fingerprint']}
    if semantic_fingerprint(report) != source['semantic_fingerprint']:
        return None, {'stage': 'local_archive_source', 'code': 'source_semantic_fingerprint_mismatch',
            'field': 'source.semantic_fingerprint', 'observed': semantic_fingerprint(report),
            'limit': source['semantic_fingerprint']}
    scope = contract['scope']
    actual = {'network': protocol.get('network'), 'address': str(protocol.get('address', '')).lower(),
        'market': protocol.get('market'), 'start_ms': protocol.get('start_ms'), 'end_ms': protocol.get('end_ms')}
    expected = {key: scope[key] for key in ('network', 'address', 'market', 'start_ms', 'end_ms')}
    if actual != expected:
        return None, {'stage': 'local_archive_source', 'code': 'source_scope_mismatch',
            'field': 'eth_observation_runs.protocol_json', 'observed': actual, 'limit': expected}
    report_window = report.get('window')
    if not isinstance(report_window, dict):
        report_window = {'start_ms': report.get('observation_start_ms'),
            'end_ms': report.get('observation_end_ms')}
    if (report.get('protocol_id') != source['protocol_id'] or report.get('stage') != source['stage']
            or report.get('protocol_fingerprint') != run['protocol_fingerprint']
            or not isinstance(report.get('fills'), list) or not isinstance(report.get('coverage'), dict)):
        return None, {'stage': 'local_archive_source', 'code': 'source_report_schema_unsupported',
            'field': 'report', 'observed': {'protocol_id': report.get('protocol_id'), 'stage': report.get('stage'),
                'protocol_fingerprint_matches': report.get('protocol_fingerprint') == run['protocol_fingerprint'],
                'fills_is_list': isinstance(report.get('fills'), list)},
            'limit': 'finalized observation report with matching protocol fingerprint, per-fill rows and coverage inventory'}
    expected_window = {'start_ms': scope['start_ms'], 'end_ms': scope['end_ms']}
    if not isinstance(report_window, dict) or any(report_window.get(key) != value
            for key, value in expected_window.items()):
        return None, {'stage': 'local_archive_source', 'code': 'source_report_window_unverifiable',
            'field': 'report.window', 'observed': report_window, 'limit': expected_window}
    if run['finalised_ms'] < scope['end_ms']:
        return None, {'stage': 'local_archive_source', 'code': 'source_cutoff_before_scope_end',
            'field': 'eth_observation_runs.finalised_ms', 'observed': run['finalised_ms'],
            'limit': f">={scope['end_ms']} for frozen half-open window"}
    invalid_rows = []
    seen_tids = set()
    for index, row in enumerate(report['fills']):
        if (not isinstance(row, dict) or not isinstance(row.get('tid'), (str, int))
                or type(row.get('event_ms')) is not int
                or not scope['start_ms'] <= row['event_ms'] < scope['end_ms']):
            invalid_rows.append(index)
        elif str(row['tid']) in seen_tids:
            invalid_rows.append(index)
        else:
            seen_tids.add(str(row['tid']))
    if invalid_rows:
        return None, {'stage': 'local_archive_source', 'code': 'source_report_fill_scope_invalid',
            'field': 'report.fills', 'observed': {'rows': len(report['fills']), 'invalid_examples': invalid_rows[:10]},
            'limit': 'unique fill tids with integer event_ms inside the sealed half-open window'}

    fill_coverage = report.get('coverage', {}).get('fills')
    market_coverage = report.get('coverage', {}).get('market')
    fill_inventory = fill_coverage.get('pages') if isinstance(fill_coverage, dict) else None
    quote_inventory = market_coverage.get('source_refs') if isinstance(market_coverage, dict) else None
    for name, inventory, expected_fingerprint in (
            ('fills.pages', fill_inventory, source['fill_reference_fingerprint']),
            ('market.source_refs', quote_inventory, source['quote_reference_fingerprint'])):
        if not isinstance(inventory, list):
            return None, {'stage': 'local_archive_source', 'code': 'source_reference_inventory_unavailable',
                'field': 'report.coverage.' + name, 'observed': type(inventory).__name__,
                'limit': 'explicit list of source references; absence from the AI packet is not source absence'}
        identities = []
        malformed = []
        for index, ref in enumerate(inventory):
            if (not isinstance(ref, dict) or type(ref.get('observation_id')) is not int
                    or ref['observation_id'] < 1 or not isinstance(ref.get('sha256'), str)
                    or not SHA256_RE.fullmatch(ref['sha256'])):
                malformed.append(index)
            elif name == 'market.source_refs' and ref.get('endpoint') not in {'bbo', 'l2Book'}:
                malformed.append(index)
            else:
                identities.append(ref['observation_id'])
        if malformed:
            return None, {'stage': 'local_archive_source', 'code': 'source_reference_inventory_invalid',
                'field': 'report.coverage.' + name, 'observed': {'count': len(inventory), 'invalid_rows': malformed[:10]},
                'limit': 'each source reference has a positive observation_id and lowercase SHA-256; quote refs name bbo/l2Book'}
        if len(set(identities)) != len(identities):
            return None, {'stage': 'local_archive_source', 'code': 'source_reference_inventory_duplicate',
                'field': 'report.coverage.' + name, 'observed': len(identities)-len(set(identities)),
                'limit': 'one reference per archived observation lot'}
        observed_fingerprint = fingerprint(inventory)
        if observed_fingerprint != expected_fingerprint:
            return None, {'stage': 'local_archive_source', 'code': 'source_reference_fingerprint_mismatch',
                'field': 'source.' + ('fill_reference_fingerprint' if name == 'fills.pages' else 'quote_reference_fingerprint'),
                'observed': observed_fingerprint, 'limit': expected_fingerprint}
    # Preserve the registered report unchanged in storage; this transient field is
    # metadata ignored by semantic_fingerprint and used only as an archive cutoff.
    report['finalised_ms'] = run['finalised_ms']
    report['semantic_fingerprint'] = source['semantic_fingerprint']
    return {'run': run, 'protocol': protocol, 'report_row': report_row, 'report': report,
        'report_window': report_window, 'fill_source_refs': fill_inventory,
        'quote_source_refs': quote_inventory}, None


def _link_result(store, job, contract_fp, report_input_fp, artifact, artifact_fp, artifact_path):
    result = json.loads(job['result_json'] or '{}')
    resolutions = result.setdefault('local_archive_resolutions_v1', {})
    previous = resolutions.get(contract_fp)
    reference = {'version': VERSION, 'state': artifact['resolution']['state'],
        'contract_fingerprint': contract_fp, 'artifact_fingerprint': artifact_fp,
        'report_input_fingerprint': report_input_fp, 'artifact_path': artifact_path,
        'coverage': artifact['resolution']['coverage'], 'next_action': artifact['resolution']['next_action'],
        'model_calls': 0, 'collection_started': False}
    changed = previous != reference
    if changed:
        resolutions[contract_fp] = reference
        store.connection.execute("update population_research_jobs set result_json=?,updated_ms=? where request_id=? and status in ('hypothesis_recorded','needs_data')",
            (canonical(result), now_ms(), job['request_id']))
        store.connection.commit()
    return reference


def _write_artifact(path, artifact):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(gzip.compress(canonical(artifact).encode('utf-8'), mtime=0))


def execute(store, request_id: str, *, repo_root=None):
    """Resolve a sealed supported contract; do no model call and no acquisition."""
    from .population_routing import route

    job = store.connection.execute('select * from population_research_jobs where request_id=?',
        (request_id,)).fetchone()
    if not job or job['status'] not in ('hypothesis_recorded', 'needs_data'):
        raise ValueError('terminal reviewed hypothesis task required for local archive resolution')
    packet = json.loads(job['packet_json'])
    body = {key: value for key, value in packet.items() if key != 'fingerprint'}
    if packet.get('fingerprint') != fingerprint(body):
        raise ValueError('sealed task packet fingerprint mismatch')
    if packet.get('research_input_fingerprint') != job['input_fingerprint']:
        raise ValueError('sealed task input fingerprint mismatch')
    contract = packet.get('local_analysis_contract_v1')
    validation = validate_contract(packet, contract)
    contract_fp = validation['contract_fingerprint']
    result = json.loads(job['result_json'] or '{}')
    proposal, critique = result.get('proposal', {}), result.get('critique', {})
    required_data = proposal.get('hypothesis', {}).get('required_data')
    if (proposal.get('decision') != 'hypothesis' or critique.get('decision') != 'consistent'
            or result.get('promotion_authorized') is not False or not isinstance(required_data, list) or not required_data):
        raise ValueError('reviewed needs-data hypothesis is required; contract does not authorize a strategy')
    auth_table = store.connection.execute("select 1 from sqlite_master where type='table' and name='population_research_pilot_tasks'").fetchone()
    pilot_scope = packet.get('pilot_research')
    auth = (store.connection.execute('select state,packet_fingerprint from population_research_pilot_tasks where request_id=?',
        (request_id,)).fetchone() if auth_table else None)
    if pilot_scope is not None and (not auth_table or not auth):
        raise PermissionError('dedicated pilot authorization is missing for a pilot-scoped local analysis')
    if auth and (auth['packet_fingerprint'] != packet['fingerprint'] or auth['state'] != job['status']):
        raise PermissionError('dedicated pilot authorization does not match the sealed task state and fingerprint')

    _table(store)
    source_result, diagnostic = _source_rows(store, contract)
    if diagnostic:
        waiting_codes = {'source_registry_absent', 'source_report_unavailable', 'source_not_finalised'}
        status = 'waiting_data' if diagnostic['code'] in waiting_codes else 'technical_required'
        return {'request_id': request_id, 'status': status, 'diagnostic': diagnostic,
            'contract_fingerprint': contract_fp, 'model_calls': 0, 'collection_started': False,
            'recalculated': False}
    report = source_result['report']
    report_row = source_result['report_row']
    protocol = source_result['protocol']
    scope = contract['scope']
    source = contract['source']
    cutoff = source_result['run']['finalised_ms']
    cached = store.connection.execute(f'select source_fingerprint,artifact_fingerprint,artifact_json from {TABLE} '
        'where request_id=? and analysis_version=? and contract_fingerprint=? and report_input_fingerprint=?',
        (request_id, VERSION, contract_fp, source['input_fingerprint'])).fetchone()
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    relpath = f'docs/continuous-research/POPULATION-LOCAL-ARCHIVE-{VERSION}-{request_id[:12]}-{contract_fp[:10]}.json.gz'
    filepath = root / relpath
    if cached:
        artifact = json.loads(cached['artifact_json'])
        check = dict(artifact); check.pop('analysis_fingerprint', None)
        if fingerprint(check) != cached['artifact_fingerprint'] or artifact.get('source_fingerprint') != cached['source_fingerprint']:
            raise ValueError('persisted local-analysis artifact fingerprint mismatch')
        _write_artifact(filepath, artifact)
        reference = _link_result(store, job, contract_fp, source['input_fingerprint'], artifact,
            cached['artifact_fingerprint'], relpath)
        routed = route(store, request_id)
        return {'request_id': request_id, 'status': 'unchanged', 'resolver_version': VERSION,
            'contract_fingerprint': contract_fp, 'artifact_fingerprint': cached['artifact_fingerprint'],
            'artifact_path': relpath, 'resolution': reference, 'route': routed, 'model_calls': 0,
            'collection_started': False, 'recalculated': False}

    reader_protocol = {**protocol, 'market': scope['market'],
        'fill_source': source['fill_source'], 'quote_source': source['quote_source']}
    fill_refs = source_result['fill_source_refs']
    quote_refs = source_result['quote_source_refs']
    raw_fills, fill_coverage = _fills(store, reader_protocol, cutoff, allowed_source_refs=fill_refs)
    quote_events, quote_coverage = _quotes(store, reader_protocol, cutoff, allowed_source_refs=quote_refs)
    report_rows = report['fills']
    analysis_fills, exact_pairs, fill_diagnostics = _merge_report_and_raw(report_rows, raw_fills, scope['market'])
    expected_quotes = report.get('coverage', {}).get('market', {}).get('quotes', {})
    expected_by_channel = {channel: expected_quotes.get(channel, {}).get('event_count') for channel in ('bbo', 'l2Book')}
    actual_by_channel = {channel: quote_coverage.get('quotes', {}).get(channel, {}).get('event_count', 0)
        for channel in ('bbo', 'l2Book')}
    fill_ref_coverage = fill_coverage.get('reference_coverage') or {}
    fill_references_match = (fill_ref_coverage.get('expected_ref_count') == len(fill_refs)
        and fill_ref_coverage.get('matched_ref_count') == len(fill_refs)
        and fill_ref_coverage.get('missing_ref_count') == 0
        and fill_ref_coverage.get('sha256_mismatch_count') == 0)
    fill_source_state = ('available_and_joined' if len(exact_pairs) == len(report_rows)
        and not fill_diagnostics['raw_only_tid_count'] and not fill_diagnostics['field_mismatch_fill_count']
        and fill_references_match and fill_coverage.get('incomplete_page_count') == 0
        and not fill_coverage.get('conflicting_fill_ids')
        else 'partially_covered_exploitable' if raw_fills or report_rows else 'absent')
    quote_has_source = bool(quote_coverage.get('source_refs'))
    quote_ref_coverage = quote_coverage.get('reference_coverage') or {}
    quote_references_match = (quote_ref_coverage.get('expected_ref_count') == len(quote_refs)
        and quote_ref_coverage.get('matched_ref_count') == len(quote_refs)
        and quote_ref_coverage.get('missing_ref_count') == 0
        and quote_ref_coverage.get('sha256_mismatch_count') == 0
        and quote_ref_coverage.get('unreferenced_archive_lot_count') == 0)
    quote_counts_known_and_match = all(type(expected_by_channel[ch]) is int
        and expected_by_channel[ch] == actual_by_channel[ch] for ch in ('bbo', 'l2Book'))
    report_embedded_quote_count = sum(isinstance(row.get('prefill_quote'), dict)
        or isinstance(row.get('future_quote'), dict) for row in report_rows)
    quote_evidence_exists = (quote_has_source or bool(quote_events)
        or quote_ref_coverage.get('unreferenced_archive_lot_count', 0) > 0
        or report_embedded_quote_count > 0)
    quote_source_state = ('available_and_joined' if quote_counts_known_and_match
        and quote_references_match and quote_has_source
        and not quote_coverage.get('rejected_events')
        else 'partially_covered_exploitable' if quote_evidence_exists
        else 'absent')
    coverage_state = 'complete' if fill_source_state == 'available_and_joined' and quote_source_state == 'available_and_joined' else 'partial'
    packet_projection = packet.get('observations', {}).get('prospective_eth_observation_v1', {})
    example_count = packet_projection.get('examples', {}).get('selected_count', 0)
    source_coverage = {'classification': coverage_state,
        'fills': {'classification': fill_source_state, 'report_rows': len(report_rows),
            'raw_unique_rows': len(raw_fills), 'exact_join_rows': len(exact_pairs),
            'report_only_tid_count': fill_diagnostics['report_only_tid_count'],
            'raw_only_tid_count': fill_diagnostics['raw_only_tid_count'],
            'field_mismatch_fill_count': fill_diagnostics['field_mismatch_fill_count'],
            'mismatch_examples': fill_diagnostics['mismatch_examples'],
            'pages': fill_coverage.get('page_count'), 'complete_pages': fill_coverage.get('complete_page_count'),
            'incomplete_pages': fill_coverage.get('incomplete_page_count'),
            'duplicate_instances': fill_coverage.get('duplicate_fill_instances'),
            'conflicts': len(fill_coverage.get('conflicting_fill_ids', [])),
            'reference_inventory_fingerprint': source['fill_reference_fingerprint'],
            'reference_coverage': fill_ref_coverage,
            'source_fingerprint': fill_coverage.get('source_fingerprint')},
        'quotes': {'classification': quote_source_state, 'expected_events_by_channel': expected_by_channel,
            'archived_events_by_channel': actual_by_channel, 'lot_count': len(quote_coverage.get('source_refs', [])),
            'report_embedded_quote_fill_count': report_embedded_quote_count,
            'reference_inventory_fingerprint': source['quote_reference_fingerprint'],
            'reference_coverage': quote_ref_coverage,
            'rejects': quote_coverage.get('rejected_events', {}),
            'source_fingerprint': quote_coverage.get('source_fingerprint')},
        'cutoff_ms': cutoff, 'packet_example_count_excluded_from_statistics': example_count}
    artifact_scope = {'protocol_id': source['protocol_id'], 'network': scope['network'],
        'address': scope['address'], 'market': scope['market'], 'start_ms': scope['start_ms'],
        'end_ms': scope['end_ms'], 'finalised_ms': cutoff, 'generic_contract': True,
        'source_coverage': source_coverage, 'contract': contract, 'packet_example_count': example_count}
    artifact = _build_artifact(request_id, report, report_row['input_fingerprint'], report_rows,
        raw_fills, fill_coverage, quote_events, quote_coverage, len(report_row['report_json']),
        scope=artifact_scope, analysis_fills=analysis_fills, validated_pairs=exact_pairs,
        field_mismatches=fill_diagnostics)
    next_action = ('No additional historical collection is justified by this local resolution; preserve partial gaps. '
        'A new analysis requires changed authorized evidence.')
    artifact['resolution'] = {'state': coverage_state, 'coverage': source_coverage,
        'next_action': next_action, 'model_calls': 0, 'collection_started': False}
    artifact.pop('analysis_fingerprint', None)
    artifact['analysis_fingerprint'] = fingerprint(artifact)
    artifact_fp = artifact['analysis_fingerprint']
    source_fp = artifact['source_fingerprint']
    store.connection.execute(f'insert into {TABLE} values(?,?,?,?,?,?,?,?)',
        (request_id, VERSION, contract_fp, source['input_fingerprint'], source_fp, artifact_fp,
            canonical(artifact), now_ms()))
    store.connection.commit()
    _write_artifact(filepath, artifact)
    reference = _link_result(store, job, contract_fp, source['input_fingerprint'], artifact, artifact_fp, relpath)
    routed = route(store, request_id)
    return {'request_id': request_id, 'status': 'prepared', 'resolver_version': VERSION,
        'contract_fingerprint': contract_fp, 'source_fingerprint': source_fp,
        'artifact_fingerprint': artifact_fp, 'artifact_path': relpath,
        'resolution': reference, 'route': routed, 'model_calls': 0,
        'collection_started': False, 'recalculated': True}
