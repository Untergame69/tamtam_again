"""Deterministic handoff from a persisted research result to its next work item.

Model supplied strings are evidence to preserve. Only sealed local contracts,
typed observation requests, and verified persisted artifacts can schedule work.
"""
from __future__ import annotations

import json

from .engine import canonical, fingerprint
from .research_jobs import table
from .research_work_queue import enqueue
from .validation import now_ms


def _job(store, source_kind, source_id):
    name = table(source_kind)
    if source_kind != 'population':
        raise ValueError('Continuous resolution currently accepts population research jobs only')
    row = store.connection.execute(
        f'select request_id,status,result_json,packet_json,network,address,updated_ms from {name} where request_id=?',
        (source_id,)).fetchone()
    if not row or row['status'] in {'sealed', 'running'}:
        raise ValueError('Persisted terminal research result required')
    return row, json.loads(row['result_json'] or '{}'), json.loads(row['packet_json'] or '{}')


def _assessment(result, route):
    """Map validated contracts to a bounded action; never derive one from prose."""
    state = route.get('state')
    if state in {'local_archive_analysis_required', 'local_eth_existing_window_analysis'}:
        return {'state': 'local_calculation', 'action': 'run_sealed_local_calculation',
            'reason': route.get('next_action'), 'wake': route.get('wake', {})}
    if state == 'local_archive_analysis_complete':
        return {'state': 'resolved', 'action': 'remember_verified_resolution_and_refresh_packet',
            'reason': route.get('next_action'), 'wake': route.get('wake', {})}
    if state in {'local_archive_data_required', 'needs_data'}:
        return {'state': 'waiting', 'action': 'poll_for_named_evidence_or_deadline',
            'reason': route.get('next_action'), 'wake': route.get('wake', {})}
    if state in {'technical_required', 'technical_task_required', 'unsupported_mechanism',
                 'specification_required', 'unsupported_validation_adapter'}:
        return {'state': 'technical', 'action': 'create_technical_task',
            'reason': route.get('next_action'), 'wake': route.get('wake', {})}
    if state in {'non_identifiable', 'reject', 'suspended', 'interrupted', 'failed', 'error', 'timeout', 'expired'}:
        return {'state': 'terminal', 'action': 'archive_and_continue_to_next_candidate',
            'reason': route.get('next_action'), 'wake': route.get('wake', {})}
    if state in {'completed', 'local_archive_analysis_complete'}:
        return {'state': 'resolved', 'action': 'remember_verified_resolution_and_refresh_packet',
            'reason': route.get('next_action'), 'wake': route.get('wake', {})}
    # A hypothesis or deterministic disposition with no missing question must
    # not be converted into an inferred experiment.
    return {'state': 'no_new_question', 'action': 'retain_result_and_continue_queue',
        'reason': route.get('next_action') or 'No new typed question or authorized follow-up.',
        'wake': {'kind': 'changed_authorized_evidence_only', 'new_input_fingerprint_required': True}}


def _typed_wait(store, row, result, route, clock):
    """Add pollable evidence/deadline details for explicit structured requests."""
    if route.get('state') == 'local_archive_data_required':
        contract = json.loads(row['packet_json']).get('local_analysis_contract_v1', {})
        source, scope = contract.get('source', {}), contract.get('scope', {})
        diagnostic = route.get('validation_diagnostic', {})
        return {'kind': 'sealed_source_report', 'pollable': True,
            'evidence_fingerprint': fingerprint({'protocol_id': source.get('protocol_id'),
                'stage': source.get('stage'), 'input_fingerprint': source.get('input_fingerprint'),
                'scope': scope}),
            'deadline_ms': scope.get('end_ms') if diagnostic.get('code') == 'source_not_finalised' else None,
            'required_source': {key: source.get(key) for key in ('protocol_id', 'stage', 'input_fingerprint')},
            'new_input_fingerprint_required': True}
    proposal = result.get('proposal')
    hypothesis = proposal.get('hypothesis') if isinstance(proposal, dict) else None
    if not isinstance(hypothesis, dict) or not isinstance(hypothesis.get('required_data'), list):
        return {'kind': 'structured_request_required', 'pollable': False,
            'new_input_fingerprint_required': True}
    if not hypothesis['required_data']:
        return None
    if 'observation_requests' not in hypothesis:
        return {'kind': 'structured_contract_required', 'pollable': False,
            'required_data': hypothesis['required_data'], 'new_input_fingerprint_required': True}
    from .research_needs import register
    plan = register(store, row['request_id'], kind='population', clock_ms=clock)
    due = [entry['wake_ms'] for entry in plan.get('entries', [])
           if entry.get('state') == 'await_window_end' and type(entry.get('wake_ms')) is int]
    entries = plan.get('entries', [])
    expected = fingerprint({'request_id': row['request_id'], 'entries': entries,
        'source_result': fingerprint(result), 'packet': fingerprint(json.loads(row['packet_json']))})
    return {'kind': 'structured_observation_plan', 'pollable': True,
        'evidence_fingerprint': expected, 'deadline_ms': min(due) if due else None,
        'plan': plan, 'all_observations_required': True,
        'new_input_fingerprint_required': True}


def resolve_result(store, source_kind='population', source_id=None, *, clock_ms=None,
                   repo_root=None, run_local=True):
    """Classify one persisted result, execute only a sealed local resolver,
    import verified memory idempotently, and enqueue one independent handoff.

    `run_local=False` produces the same typed plan without invoking a resolver.
    No collection, inference, paper run, or order is initiated here.
    """
    if source_id is None:
        raise ValueError('source_id is required')
    clock = now_ms() if clock_ms is None else clock_ms
    if type(clock) is not int or clock < 0:
        raise ValueError('Explicit nonnegative clock required')
    row, result, packet = _job(store, source_kind, source_id)
    from .population_routing import route
    routed = route(store, source_id, kind=source_kind)
    assessment = _assessment(result, routed)
    local_run = None
    if assessment['state'] == 'local_calculation' and assessment['action'] == 'run_sealed_local_calculation':
        task = routed.get('followup_task', {})
        if task.get('kind') == 'population_local_archive_analysis':
            if run_local:
                from .population_local_archive_resolution import execute
                local_run = execute(store, source_id, repo_root=repo_root)
                # The resolver persists a fingerprinted result reference. Route
                # again to consume that exact artifact, never model narration.
                routed = route(store, source_id, kind=source_kind)
                assessment = _assessment(result, routed)
            else:
                local_run = {'status': 'prepared', 'model_calls': 0, 'collection_started': False}
        else:
            # Dedicated existing-window resolver has a distinct sealed contract.
            if run_local and task.get('kind') == 'eth_existing_window_analysis':
                from .eth_existing_window_resolution import execute
                local_run = execute(store, source_id, repo_root=repo_root)
                routed = route(store, source_id, kind=source_kind)
                assessment = _assessment(result, routed)

    if assessment['state'] == 'waiting':
        try:
            assessment['wake'] = _typed_wait(store, row, result, routed, clock) or assessment['wake']
        except (ValueError, KeyError):
            # Legacy unstructured requests remain inert; they never become a
            # guessed collection task.
            assessment['wake'] = {'kind': 'structured_contract_required', 'pollable': False,
                'new_input_fingerprint_required': True}

    memory = None
    if assessment['state'] == 'resolved':
        status = row['status']
        if source_kind == 'population' and status == 'hypothesis_recorded':
            from .population_memory import remember
            memory = remember(store, source_id)
        elif source_kind == 'population' and status == 'needs_data':
            from .population_memory import remember_verified_local_resolution
            memory = remember_verified_local_resolution(store, source_id)
        elif result.get('resolution_assessment_v1'):
            from .population_memory import remember_resolution_descriptor
            memory = remember_resolution_descriptor(store, source_id)

    semantic = {'source_kind': source_kind, 'source_id': source_id,
        'source_status': row['status'], 'source_result_fingerprint': fingerprint(result),
        'route_fingerprint': fingerprint(routed), 'assessment': assessment,
        'local_run': local_run, 'memory': memory}
    work_payload = {'resolution': semantic,
        'next_packet': {'memory_refresh_required': bool(memory),
            'input_fingerprint_must_change': True},
        'promotion_authorized': False, 'collection_authorized': False,
        'paper_authorized': False, 'orders_authorized': False}
    queue_status = {'local_calculation': 'resolution_ready', 'waiting': 'waiting_data',
        'technical': 'technical_required', 'terminal': 'completed',
        'resolved': 'completed', 'no_new_question': 'completed'}[assessment['state']]
    wake_at = assessment.get('wake', {}).get('deadline_ms') if isinstance(assessment.get('wake'), dict) else None
    if queue_status == 'waiting_data' and type(wake_at) is int and wake_at > clock:
        queue_status = 'waiting_deadline'
    work, created = enqueue(store, 'population_resolution', source_id, work_payload,
        status=queue_status, reason=assessment.get('reason') or assessment['state'],
        wake_at_ms=wake_at, clock_ms=clock)
    return {'source_id': source_id, 'state': assessment['state'], 'assessment': assessment,
        'route': routed, 'local_run': local_run, 'memory': memory,
        'next_packet': {'memory_refresh_required': bool(memory),
            'input_fingerprint_must_change': True},
        'work_id': work['work_id'], 'queue_status': work['status'], 'created': created,
        'next_candidate': assessment['state'] in {'terminal', 'resolved', 'no_new_question'},
        'model_calls': 0, 'collection_started': False, 'orders_authorized': False}
