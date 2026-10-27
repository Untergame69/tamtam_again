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
    # Preserve every reviewed, non-economic hypothesis before acting on its
    # next route. Packet construction can then select it even when this result
    # still needs data or an executable contract.
    memory = None
    if source_kind == 'population' and row['status'] == 'hypothesis_recorded':
        from .population_memory import remember
        memory = remember(store, source_id)
    from .population_routing import route
    routed = route(store, source_id, kind=source_kind)
    assessment = _assessment(result, routed)
    local_run = None
    if assessment['state'] == 'local_calculation' and assessment['action'] == 'run_sealed_local_calculation':
        task = routed.get('followup_task', {})
        if task.get('kind') == 'population_local_archive_analysis':
            if run_local:
                from .population_local_archive_resolution import execute
                try:
                    local_run = execute(store, source_id, repo_root=repo_root)
                except Exception as exc:
                    local_run = {'status': 'technical_required', 'diagnostic_code': type(exc).__name__,
                        'model_calls': 0, 'collection_started': False}
                    assessment = {'state': 'technical', 'action': 'create_technical_task',
                        'reason': 'The sealed local resolver failed; inspect its deterministic diagnostic.',
                        'wake': {'kind': 'local_resolver_error', 'diagnostic_code': type(exc).__name__,
                            'automatic_retry': False}}
                else:
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
                try:
                    local_run = execute(store, source_id, repo_root=repo_root)
                except Exception as exc:
                    local_run = {'status': 'technical_required', 'diagnostic_code': type(exc).__name__,
                        'model_calls': 0, 'collection_started': False}
                    assessment = {'state': 'technical', 'action': 'create_technical_task',
                        'reason': 'The sealed local resolver failed; inspect its deterministic diagnostic.',
                        'wake': {'kind': 'local_resolver_error', 'diagnostic_code': type(exc).__name__,
                            'automatic_retry': False}}
                else:
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

    if assessment['state'] == 'resolved' and memory is None:
        status = row['status']
        if source_kind == 'population' and status == 'needs_data':
            from .population_memory import remember_verified_local_resolution
            memory = remember_verified_local_resolution(store, source_id)
        elif result.get('resolution_assessment_v1'):
            from .population_memory import remember_resolution_descriptor
            memory = remember_resolution_descriptor(store, source_id)
    elif assessment['state'] == 'resolved' and source_kind == 'population' and row['status'] == 'hypothesis_recorded':
        # A local resolver may have added a verified artifact after the early
        # hypothesis import above. Re-read it so the descriptor revision also
        # reaches the next packet; this is idempotent when no artifact changed.
        from .population_memory import remember
        memory = remember(store, source_id)

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


def poll_waits(store, *, clock_ms=None, limit=8, client=None, collection_job=None,
               collection_policy=None):
    """Poll typed population data waits and publish changed-evidence work.

    An optional collection call is permitted only with an already-held
    population lease, a client and the immutable existing needs policy. This
    function never claims a lease or invents collection authority. Durable
    wakes are verified before a follow-up becomes ready; bounded failed or
    saturated collection ends as insufficient data.
    """
    from .research_work_queue import set_status
    clock = now_ms() if clock_ms is None else clock_ms
    if type(clock) is not int or clock < 0 or type(limit) is not int or not 1 <= limit <= 64:
        raise ValueError('Explicit clock and bounded wait limit required')
    collection = None
    if (client is None) != (collection_job is None) or ((client is not None or collection_job is not None) and collection_policy is None):
        raise ValueError('An existing collector requires client, active job lease and immutable policy together')
    if collection_policy is not None:
        from .research_need_collection import tick_for_job, validate_policy
        validate_policy(collection_policy)
        if client is not None:
            collection = tick_for_job(store, client, collection_job, collection_policy, clock_ms=clock)

    store.connection.execute('create table if not exists continuous_research_wait_poll_cursor '
        '(cursor_id integer primary key check(cursor_id=1),last_work_id text not null,updated_ms integer not null)')
    cursor = store.connection.execute('select last_work_id from continuous_research_wait_poll_cursor where cursor_id=1').fetchone()
    last_id = cursor['last_work_id'] if cursor else ''
    rows = store.connection.execute(
        "select * from research_work_queue where source_kind='population_resolution' "
        "and status in ('waiting_data','waiting_deadline') and work_id>? order by work_id limit ?",
        (last_id, limit)).fetchall()
    if len(rows) < limit:
        remainder = limit - len(rows)
        wrapped = store.connection.execute(
            "select * from research_work_queue where source_kind='population_resolution' "
            "and status in ('waiting_data','waiting_deadline') and work_id<=? order by work_id limit ?",
            (last_id, remainder)).fetchall()
        rows = list(rows) + list(wrapped)
    advanced = []
    for work in rows:
        request_id = work['source_id']
        plan_row = store.connection.execute(
            'select plan_id,plan_json from research_observation_plans where request_id=? order by created_ms desc limit 1',
            (request_id,)).fetchone() if store.connection.execute(
                "select 1 from sqlite_master where type='table' and name='research_observation_plans'").fetchone() else None
        if not plan_row:
            continue
        plan = json.loads(plan_row['plan_json'])
        entries = plan.get('entries')
        if not isinstance(entries, list) or not entries:
            set_status(store, work['work_id'], 'technical_required',
                'Legacy or incomplete observation request needs an explicit structured contract.',
                outcome={'state': 'technical', 'kind': 'structured_request_required'}, clock_ms=clock)
            advanced.append({'request_id': request_id, 'state': 'technical_required'})
            continue

        # Complete a wake from already persisted per-need proofs without a
        # network call. This is the deterministic reducer formerly reached
        # only when another collector tick revisited the account.
        requests_for_wake = [entry.get('request', {}) for entry in entries]
        if store.connection.execute(
                "select 1 from sqlite_master where name='research_need_collection_states'").fetchone():
            proofs = []
            all_proofs = bool(requests_for_wake)
            from .research_memory import authorized_period
            for request in requests_for_wake:
                need_id = fingerprint({'plan_id': plan_row['plan_id'], 'request': request})
                state = store.connection.execute(
                    'select state,evidence_json from research_need_collection_states where need_id=?',
                    (need_id,)).fetchone()
                if not state or state['state'] != 'proof_observed':
                    all_proofs = False
                    break
                proof = json.loads(state['evidence_json'] or '{}')
                period = {'network': plan['network'], 'address': plan['address'], 'market': '*',
                    'start_ms': request['start_ms'], 'end_ms': request['end_ms']}
                if (proof.get('need_id') != need_id or proof.get('source_request') != request
                        or proof.get('available_ms', clock + 1) > clock
                        or not authorized_period(store, period, clock, end_inclusive=True)):
                    all_proofs = False
                    break
                proofs.append(proof)
            if all_proofs and len(proofs) == len(requests_for_wake):
                wake_evidence = {'proofs': proofs, 'promotion_authorized': False,
                    'economic_completeness_proven': False,
                    'next_action': 'reassess on these changed observations under the unchanged research budget'}
                available = max(p['available_ms'] for p in proofs)
                store.connection.execute('insert or ignore into research_observation_wakes '
                    '(request_id,available_ms,evidence_fingerprint,evidence_json) values(?,?,?,?)',
                    (request_id, available, fingerprint(wake_evidence), canonical(wake_evidence)))
                store.connection.commit()

        wake_row = store.connection.execute(
            'select available_ms,evidence_fingerprint,evidence_json from research_observation_wakes where request_id=?',
            (request_id,)).fetchone() if store.connection.execute(
                "select 1 from sqlite_master where type='table' and name='research_observation_wakes'").fetchone() else None
        if wake_row and wake_row['available_ms'] <= clock:
            wake_fingerprint = wake_row['evidence_fingerprint']
            payload = {'parent_request_id': request_id,
                'evidence_fingerprint': wake_fingerprint, 'available_ms': wake_row['available_ms'],
                'network': plan['network'], 'address': plan['address'],
                'next_packet_required': True, 'new_analysis_budget_authorized': False,
                'promotion_authorized': False, 'orders_authorized': False}
            prior = store.connection.execute(
                "select work_id from research_work_queue where source_kind='population_wake' "
                'and source_id=? and input_fingerprint=?',
                (request_id, fingerprint(payload))).fetchone()
            if prior:
                advanced.append({'request_id': request_id, 'state': 'wake_already_queued',
                    'work_id': prior['work_id'], 'evidence_fingerprint': wake_fingerprint,
                    'absence': 'all_required_proofs_present', 'export': 'verified_previously',
                    'calculation': 'not_run'})
                continue
            try:
                from .research_need_collection import export_wakes
                exported = export_wakes(store, plan['network'], plan['address'],
                    as_of_ms=clock, request_ids=[request_id], research_origin='population')
            except (ValueError, KeyError, TypeError) as exc:
                set_status(store, work['work_id'], 'technical_required',
                    'Persisted wake failed provenance validation.',
                    outcome={'state': 'technical', 'diagnostic_code': type(exc).__name__}, clock_ms=clock)
                advanced.append({'request_id': request_id, 'state': 'technical_required',
                    'absence': 'unresolved', 'export': 'rejected', 'calculation': 'not_run'})
                continue
            if not exported or exported[0]['evidence_fingerprint'] != wake_fingerprint:
                set_status(store, work['work_id'], 'technical_required',
                    'Verified wake is absent or has a different evidence identity.',
                    outcome={'state': 'technical', 'kind': 'wake_identity_mismatch'}, clock_ms=clock)
                advanced.append({'request_id': request_id, 'state': 'technical_required',
                    'absence': 'unresolved', 'export': 'identity_mismatch', 'calculation': 'not_run'})
                continue
            from .research_work_queue import enqueue
            queued, created = enqueue(store, 'population_wake', request_id, payload,
                status='ready', reason='all typed observations verified; prepare a changed evidence packet',
                clock_ms=clock)
            set_status(store, work['work_id'], 'completed', 'superseded by verified observation wake',
                outcome={'wake_work_id': queued['work_id'], 'evidence_fingerprint': wake_fingerprint},
                clock_ms=clock)
            advanced.append({'request_id': request_id, 'state': 'evidence_changed',
                'work_id': queued['work_id'], 'created': created,
                'evidence_fingerprint': wake_fingerprint,
                'next_packet_required': True, 'new_analysis_budget_authorized': False,
                'absence': 'all_required_proofs_present', 'export': 'verified',
                'calculation': 'not_run'})
            continue

        requests = [entry.get('request', {}) for entry in entries]
        statuses = []
        deadlines = []
        unsupported = []
        terminal_failures = []
        for request in requests:
            capability = _classify_request(request)
            if capability in {'unsupported_acquisition', 'unsupported_proof'}:
                unsupported.append(capability)
                continue
            deadline = request.get('end_ms')
            if type(deadline) is int:
                deadlines.append(deadline)
                if deadline > clock:
                    statuses.append('waiting_deadline')
                    continue
            identity = fingerprint({'plan_id': plan_row['plan_id'], 'request': request})
            state = store.connection.execute(
                'select attempts,state from research_need_collection_states where need_id=?', (identity,)).fetchone() \
                if store.connection.execute("select 1 from sqlite_master where name='research_need_collection_states'").fetchone() else None
            if not state:
                statuses.append('waiting_data')
            elif state['state'] == 'proof_observed':
                statuses.append('waiting_data')  # aggregate wake is persisted by the collector
            elif state['state'] == 'saturated_timestamp_unresolvable':
                terminal_failures.append('saturated_timestamp_unresolvable')
            elif state['state'] in {'collection_failed', 'needs_more_pages'} and collection_policy and state['attempts'] >= collection_policy['max_attempts_per_need']:
                terminal_failures.append('bounded_collection_attempts_exhausted')
            else:
                statuses.append('waiting_data')

        if unsupported:
            set_status(store, work['work_id'], 'technical_required',
                'No verified acquisition adapter or proof supports this typed request.',
                outcome={'state': 'technical', 'unsupported': sorted(set(unsupported))}, clock_ms=clock)
            advanced.append({'request_id': request_id, 'state': 'technical_required',
                'unsupported': sorted(set(unsupported)), 'absence': 'unresolved',
                'export': 'unsupported', 'calculation': 'unsupported'})
        elif terminal_failures:
            set_status(store, work['work_id'], 'completed', 'required observation remained insufficient after bounded collection.',
                outcome={'state': 'insufficient_data', 'terminal': True,
                    'failures': sorted(set(terminal_failures)), 'collection_started': bool(collection)}, clock_ms=clock)
            advanced.append({'request_id': request_id, 'state': 'insufficient_data_terminal',
                'failures': sorted(set(terminal_failures)), 'next_candidate': True,
                'absence': 'confirmed_after_bounded_attempts', 'export': 'not_possible',
                'calculation': 'not_run'})
        elif statuses and all(s == 'waiting_deadline' for s in statuses):
            deadline = max(deadlines) if deadlines else None
            set_status(store, work['work_id'], 'waiting_deadline', 'typed observation window has not ended',
                wake_at_ms=deadline, clock_ms=clock)
            advanced.append({'request_id': request_id, 'state': 'waiting_deadline', 'deadline_ms': deadline,
                'absence': 'not_due', 'export': 'not_attempted', 'calculation': 'not_run'})
        else:
            set_status(store, work['work_id'], 'waiting_data', 'polling the existing bounded collection state',
                clock_ms=clock)
            advanced.append({'request_id': request_id, 'state': 'waiting_data',
                'absence': 'incomplete_or_unobserved', 'export': 'not_attempted',
                'calculation': 'not_run'})
    if rows:
        store.connection.execute('insert into continuous_research_wait_poll_cursor values(1,?,?) '
            'on conflict(cursor_id) do update set last_work_id=excluded.last_work_id,updated_ms=excluded.updated_ms',
            (rows[-1]['work_id'], clock))
        store.connection.commit()
    return {'advanced': advanced, 'collection': collection, 'candidate_followups': [x for x in advanced if x['state']=='evidence_changed'],
        'model_calls': 0, 'orders_authorized': False}


def _classify_request(request):
    from .research_needs import classify
    try:
        return classify(request)['state']
    except (KeyError, TypeError, ValueError):
        return 'unsupported_acquisition'
