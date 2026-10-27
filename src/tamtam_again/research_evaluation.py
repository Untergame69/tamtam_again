"""Deterministic reviewed-rule handoff and durable evaluation feedback.

This adapter never turns an association into a trading rule, reads reserved
market payloads, changes a gate, calls a model, or places an order. The existing
pipeline owns evaluation and paper starts; polling observes its durable results.
"""
import json
from datetime import datetime
from .engine import canonical, fingerprint, number
from .validation import now_ms

SCHEMA = '''
CREATE TABLE IF NOT EXISTS research_evaluation_events (
 event_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, research_origin TEXT NOT NULL,
 created_ms INTEGER NOT NULL, event_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_evaluation_memory (
 event_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, available_ms INTEGER NOT NULL,
 memory_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_evaluation_source_periods (
 event_id TEXT NOT NULL, period_json TEXT NOT NULL, PRIMARY KEY(event_id,period_json));
'''


def _exists(store, name):
    return bool(store.connection.execute("select 1 from sqlite_master where type='table' and name=?", (name,)).fetchone())


def _persist(store, request_id, kind, state, *, evidence=None, diagnostic=None, wake=None):
    store.connection.executescript(SCHEMA)
    terminal = state in {'descriptive', 'rejected', 'technical_required', 'paper_complete'}
    next_plan = {'iteration_class': 'reject' if state == 'rejected' else 'technical' if state == 'technical_required' else 'continue',
                 'kind': 'next_candidate' if terminal else 'continue_candidate',
                 'changed_evidence_required': True, 'rearm_budget': False,
                 'model_calls_authorized': 0, 'live_orders_authorized': False}
    event = {'version': 'research-evaluation-v1', 'request_id': request_id,
             'research_origin': kind, 'state': state, 'terminal': terminal,
             'diagnostic': diagnostic, 'evidence': evidence or {}, 'wake': wake or {},
             'next_plan': next_plan, 'promotion_authorized': False}
    event_id = fingerprint(event)
    previous = store.connection.execute('select event_json from research_evaluation_events where event_id=?', (event_id,)).fetchone()
    if previous:
        return json.loads(previous[0])
    event.update(event_id=event_id, created_ms=now_ms())
    memory = {'version': 'research-evaluation-memory-v1', 'request_id': request_id,
              'state': state, 'evidence': event['evidence'], 'next_plan': next_plan,
              'profitability_proven': False, 'evaluation_event_id': event_id}
    with store.connection:
        store.connection.execute('insert or ignore into research_evaluation_events values(?,?,?,?,?)',
            (event_id, request_id, kind, event['created_ms'], canonical(event)))
        for session in event['evidence'].get('sessions', []):
            store.connection.execute('insert or ignore into research_evaluation_source_periods values(?,?)',
                (event_id, canonical(session['source_period'])))
        store.connection.execute('insert or ignore into research_evaluation_memory values(?,?,?,?)',
            (event_id, request_id, event['created_ms'], canonical(memory)))
    return event


def _pollable_needs_data(result):
    """True only for a complete supported request contract, never for prose."""
    proposal=result.get('proposal');critique=result.get('critique')
    direct=(critique if isinstance(critique,dict) and critique.get('decision')=='needs_data'
        else proposal if isinstance(proposal,dict) and proposal.get('decision')=='needs_data' else None)
    hypothesis=proposal.get('hypothesis') if isinstance(proposal,dict) else None
    if isinstance(direct,dict):
        missing=direct.get('required_data');requests=direct.get('observation_requests')
    elif isinstance(hypothesis,dict):
        missing=hypothesis.get('required_data');requests=hypothesis.get('observation_requests')
    else:return False
    if not isinstance(missing,list) or not missing or not isinstance(requests,list):return False
    try:
        from .research_needs import validate_requests,classify
        validate_requests(missing,requests)
        return all(classify(request).get('state')=='acquisition_required' for request in requests)
    except (ValueError,KeyError,TypeError):
        return False


def handoff(store, request_id, *, kind='population', experiment_policy=None):
    """Persist a typed next plan; freeze only an explicitly reviewed executable rule.

    Allocation is externally supplied and immutable. Missing rule/profile remains
    descriptive or needs design; unsupported execution is a technical outcome.
    Replay recovers the same preregistered plan rather than moving its windows.
    """
    from .research import scheduler_lock
    with scheduler_lock(store):
        return _handoff(store, request_id, kind=kind, experiment_policy=experiment_policy)


def handoff_locked(store, request_id, *, kind='population', experiment_policy=None):
    """Handoff for a caller already holding this database's scheduler_lock."""
    return _handoff(store, request_id, kind=kind, experiment_policy=experiment_policy)


def _handoff(store, request_id, *, kind, experiment_policy):
    from .research_jobs import table
    from .population_routing import route
    registry = table(kind)
    job = store.connection.execute(f'select status,result_json,packet_json from {registry} where request_id=?', (request_id,)).fetchone()
    if not job:
        raise ValueError('Known reviewed research request required')
    result = json.loads(job['result_json'] or '{}')
    hypothesis = result.get('proposal', {}).get('hypothesis', {})
    # Do not interpret prose from local analyses, diagnostic strings or required
    # observations as a reviewed executable mechanism.
    routed = route(store, request_id, kind=kind)
    evidence = {'route_fingerprint': fingerprint(routed), 'source_status': job['status']}
    if _exists(store, 'population_experiment_links'):
        link = store.connection.execute('select plan_id,family_id from population_experiment_links where request_id=?', (request_id,)).fetchone()
        if link:
            return _observe(store, request_id, kind, dict(link))
    if routed['state']=='needs_data' and _exists(store,'research_work_queue'):
        # The generic resolver closes needs_data decisions that have no complete
        # typed request. Keep the provider status unchanged, but expose the
        # terminal descriptive disposition here instead of a phantom wait.
        pending=store.connection.execute("select payload_json,outcome_json from research_work_queue "
            "where source_kind='population_resolution' and source_id=? order by updated_ms desc,work_id desc limit 1",
            (request_id,)).fetchone()
        payload=json.loads(pending['payload_json']) if pending else {}
        outcome=json.loads(pending['outcome_json'] or '{}') if pending else {}
        resolution=payload.get('resolution',{})
        assessment=resolution.get('assessment',{})
        if (assessment.get('disposition')=='needs_data_contract_required'
                or assessment.get('state')=='technical' or outcome.get('state')=='technical'):
            evidence['resolution_disposition']='technical_required'
            evidence['source_decision_preserved']=True
            diagnostic=(assessment.get('reason') or
                'The needs_data result lacks a complete typed acquisition contract; manual technical correction is required.')
            return _persist(store,request_id,kind,'technical_required',evidence=evidence,
                diagnostic=diagnostic,wake={'kind':'structured_observation_contract_required',
                    'automatic_collection_retry':False,'model_calls_authorized':0})
        if (assessment.get('disposition')=='insufficient_data_unstructured'
                or outcome.get('state')=='insufficient_data'):
            diagnostic=(assessment.get('reason') or
                'The typed observations remained unavailable after bounded collection; retain descriptive insufficiency and continue.')
            evidence['resolution_disposition']=assessment.get('disposition') or outcome.get('state')
            evidence['source_decision_preserved']=True
            return _persist(store,request_id,kind,'descriptive',evidence=evidence,diagnostic=diagnostic,
                wake={'kind':'changed_authorized_evidence_only','new_input_fingerprint_required':True,
                    'automatic_collection_retry':False})
        if outcome.get('state')=='technical':
            evidence['resolution_disposition']='technical_required'
            return _persist(store,request_id,kind,'technical_required',evidence=evidence,
                diagnostic='Typed acquisition or evidence verification needs a technical correction.',
                wake={'kind':'verified_adapter_or_provenance_correction','automatic_collection_retry':False})
    if routed['state']=='needs_data' and not _pollable_needs_data(result):
        evidence['resolution_disposition']='needs_data_contract_required'
        evidence['source_decision_preserved']=True
        return _persist(store,request_id,kind,'technical_required',evidence=evidence,
            diagnostic='The needs_data result lacks a complete supported typed observation contract; preserve the source decision and correct the contract.',
            wake={'kind':'structured_observation_contract_required','automatic_collection_retry':False,
                'model_calls_authorized':0})
    if routed['state'] != 'prospective_plan_required':
        state = ('descriptive' if routed['state'] in {'specification_required', 'completed', 'local_archive_analysis_complete', 'non_identifiable'}
                 else 'needs_data' if routed['state'] in {'needs_data', 'local_archive_data_required'}
                 else 'rejected' if routed['state'] == 'reject' else 'technical_required')
        return _persist(store, request_id, kind, state, evidence=evidence,
            diagnostic=routed.get('next_action'), wake=routed.get('wake'))
    profile = hypothesis.get('experiment_profile')
    if not isinstance(profile, dict):
        return _persist(store, request_id, kind, 'descriptive', evidence=evidence,
            diagnostic='Explicit justified experiment profile required; no parameters inferred from prose')
    if experiment_policy is None:
        return _persist(store, request_id, kind, 'allocation_required', evidence=evidence,
            diagnostic='External immutable prospective allocation required')
    from .experiment_allocation import bind_policy, plan_policy
    from .population_plans import _prepare_plan
    from .population_compilation import validate_packet_compilation
    try:
        validate_packet_compilation(hypothesis, profile, json.loads(job['packet_json']), request_id)
        allocated = plan_policy(experiment_policy, profile, hypothesis['executable_spec'])
        bind_policy(store, experiment_policy)
        if kind == 'population':
            from .continuous_plan_allocation import scoped_policy
            allocated = scoped_policy(store, request_id, experiment_policy, allocated)
        prepared = _prepare_plan(store, request_id, allocated, profile, kind=kind)
    except ValueError as exc:
        return _persist(store, request_id, kind, 'technical_required', evidence=evidence, diagnostic=str(exc))
    if prepared['status'] == 'budget_exhausted':
        return _persist(store, request_id, kind, 'allocation_required', evidence=evidence,
                        diagnostic='Allocated plan budget exhausted; no automatic increase')
    return _observe(store, request_id, kind, prepared)


def _archive_blocker(store, variant_id, stage):
    if not _exists(store, 'pipeline_decisions'):
        return None
    row = store.connection.execute(
        'select decision_id,diagnostic,wake_json from pipeline_decisions where evidence_json=? '
        'order by decision_id desc limit 1',
        (canonical({'variant_id': variant_id, 'stage': stage}),)).fetchone()
    if row and json.loads(row['wake_json']).get('archive_or_plan_correction_required') is True:
        return {'decision_id': row['decision_id'], 'diagnostic': row['diagnostic'],
                'variant_id': variant_id, 'stage': stage}
    return None


def _observe(store, request_id, kind, link):
    family = link['family_id']; plan_id = link['plan_id']
    evidence = {'family_id': family, 'plan_id': plan_id}
    plan = json.loads(store.connection.execute('select plan_json from validation_plans where plan_id=?', (plan_id,)).fetchone()[0])
    attempts = [dict(r) for r in store.connection.execute('select variant_id,status,diagnostic from experiment_attempts where family_id=? order by attempt_index', (family,))]
    evidence['attempts'] = attempts
    variants = [r['variant_id'] for r in attempts if r['variant_id']]
    if not variants:
        return _persist(store, request_id, kind, 'technical_required', evidence=evidence,
                        diagnostic='No executable family variants; failed specifications retained')
    evaluations = [dict(r) for r in store.connection.execute('select evaluation_id,variant_id,stage,status from validation_evaluations where plan_id=? order by stage,variant_id,evaluation_id', (plan_id,))]
    for evaluation in evaluations:
        row = store.connection.execute('select result_json from validation_evaluations where evaluation_id=?',
            (evaluation['evaluation_id'],)).fetchone()
        result = json.loads(row[0] or '{}')
        # Preserve the actual gate diagnostic for later released feedback, not
        # merely a label that makes the next candidate repeat the same mistake.
        evaluation['outcome'] = {key: result[key] for key in (
            'failures', 'error_type', 'criteria_fingerprint', 'synthetic', 'promotable') if key in result}
    evidence['evaluations'] = evaluations
    selection = store.connection.execute('select variant_id,status from experiment_selections where family_id=?', (family,)).fetchone()
    if not selection:
        blockers = [blocker for variant in variants
                    if not any(r['variant_id'] == variant and r['stage'] == 'comparison' for r in evaluations)
                    if (blocker := _archive_blocker(store, variant, 'comparison'))]
        if blockers:
            evidence['archive_blockers'] = blockers
        failed = {r['variant_id'] for r in evaluations if r['stage'] == 'comparison' and r['status'] not in {'running', 'passed'}}
        blocked = {r['variant_id'] for r in blockers}
        if len(failed | blocked) == len(variants):
            state = 'technical_required' if blockers or any(r['status'] == 'error' for r in evaluations) else 'rejected'
            return _persist(store, request_id, kind, state, evidence=evidence,
                            diagnostic='All comparisons failed; no final or paper authorization')
        if not plan.get('synthetic', False) and now_ms() >= plan['final']['start_ms']:
            return _persist(store, request_id, kind, 'technical_required', evidence=evidence,
                diagnostic='Selection window missed; preserve original reserve and allocate a new prospective candidate')
        return _persist(store, request_id, kind, 'awaiting_comparison', evidence=evidence,
                        wake={'not_before_ms': plan['comparison']['end_ms'], 'owner': 'pipeline'})
    evidence['selection'] = dict(selection)
    if selection['status'] == 'no_candidate':
        return _persist(store, request_id, kind, 'rejected', evidence=evidence, diagnostic='No comparison winner')
    final = [r for r in evaluations if r['stage'] == 'final' and r['variant_id'] == selection['variant_id']]
    if not final or any(r['status'] == 'running' for r in final):
        blocker = _archive_blocker(store, selection['variant_id'], 'final') if not final else None
        if blocker:
            evidence['archive_blockers'] = [blocker]
            return _persist(store, request_id, kind, 'technical_required', evidence=evidence,
                diagnostic='Completed final archive requires correction or a new prospective reserve; no economic rejection')
        return _persist(store, request_id, kind, 'awaiting_final', evidence=evidence,
                        wake={'not_before_ms': plan['final']['end_ms'], 'owner': 'pipeline'})
    if not any(r['status'] == 'passed' for r in final):
        state = 'technical_required' if any(r['status'] == 'error' for r in final) else 'rejected'
        return _persist(store, request_id, kind, state, evidence=evidence, diagnostic='Final did not pass; new candidate requires new future reserve')
    sessions = []
    for row in store.connection.execute('select session_id,status,state_json,started_ms,updated_at from paper_sessions where variant_id=? order by started_ms,session_id', (selection['variant_id'],)):
        body = json.loads(row['state_json'])
        try:
            position = number(body.get('position'))
            complete = position == 0 and isinstance(body.get('pending'), list) and not body['pending']
        except (ValueError, TypeError):
            complete = False
        try:
            updated_ms = int(datetime.fromisoformat(row['updated_at']).timestamp()*1000)
            period_start, period_end = row['started_ms'], max(row['started_ms']+1, updated_ms+1)
        except (ValueError, TypeError):
            period_start, period_end = 0, 0  # Invalid provenance prevents memory export.
        session = {'session_id': row['session_id'], 'status': row['status'],
            'position': body.get('position'), 'pending': bool(body.get('pending')),
            'pending_count': len(body['pending']) if isinstance(body.get('pending'), list) else None,
            'complete_flat_state': complete, 'diagnostics': body.get('diagnostics', [])[:32],
            'source_period': {'network': plan['network'], 'address': plan['address'], 'market': plan['coin'],
                              'start_ms': period_start, 'end_ms': period_end}}
        for key in ('net_pnl', 'realized_pnl', 'fees', 'funding', 'cash'):
            if key in body:
                session[key] = body[key]
        sessions.append(session)
    evidence['sessions'] = sessions
    state = ('paper_active' if any(r['status'] == 'active' for r in sessions)
             else 'technical_required' if any(not r['complete_flat_state'] for r in sessions)
             else 'paper_complete' if sessions else 'paper_gate_required')
    if state == 'technical_required':
        evidence['incomplete_paper'] = True

    return _persist(store, request_id, kind, state, evidence=evidence,
                    diagnostic=('Inactive paper retains exposure, pending orders or unknown flatness; preserve incomplete ledger'
                        if state == 'technical_required' else
                        'Existing pipeline and explicit paper support own paper admission; paper status does not prove profitability'))


def poll(store, *, limit=8):
    """Observe at most limit linked candidates; caller runs the existing pipeline.

    The durable next_candidate directive is consumed by the separately bounded
    research scheduler; it never resets a request, budget or held-out reserve.
    """
    if type(limit) is not int or not 1 <= limit <= 64:
        raise ValueError('Explicit bounded poll limit between one and 64 required')
    if not _exists(store, 'population_experiment_links'):
        return {'decisions': [], 'model_calls': 0, 'live_orders_enabled': False}
    # Fair rotation makes terminal/unchanged early candidates unable to starve
    # newly linked work. This cursor is operational, never economic selection.
    store.connection.execute('create table if not exists research_evaluation_cursor (id integer primary key, last_request_id text not null)')
    cursor = store.connection.execute('select last_request_id from research_evaluation_cursor where id=1').fetchone()
    last = cursor[0] if cursor else ''
    rows = store.connection.execute('select * from population_experiment_links order by (request_id<=?),request_id limit ?', (last, limit)).fetchall()
    decisions = []
    for row in rows:
        plan = json.loads(store.connection.execute('select plan_json from validation_plans where plan_id=?', (row['plan_id'],)).fetchone()[0])
        kind = plan.get('population_origin', {}).get('research_origin', 'population')
        decisions.append(_observe(store, row['request_id'], kind, dict(row)))
    if rows:
        store.connection.execute('insert or replace into research_evaluation_cursor values(1,?)', (rows[-1]['request_id'],))
        store.connection.commit()
    return {'decisions': decisions, 'model_calls': 0, 'live_orders_enabled': False}


def memory(store, *, as_of_ms, request_id=None, limit=8):
    """Return bounded feedback that existed at the decision cutoff.

    Only lifecycle metadata and evaluation identifiers are exposed; this is not
    permission to export market payloads from held-out validation periods.
    """
    if type(as_of_ms) is not int or as_of_ms < 0 or type(limit) is not int or not 1 <= limit <= 64:
        raise ValueError('Explicit nonnegative cutoff and bounded memory limit required')
    if not _exists(store, 'research_evaluation_memory'):
        return []
    query = 'select memory_json from research_evaluation_memory where available_ms<=?'
    args = [as_of_ms]
    if request_id is not None:
        query += ' and request_id=?'
        args.append(request_id)
    query += ' order by available_ms desc,event_id limit ?'
    args.append(limit)
    return [json.loads(row[0]) for row in store.connection.execute(query, args)]


def export_memory(store, network, address, as_of_ms, *, limit=8):
    """Export causal, scoped lifecycle feedback after all source reserve checks.

    Full source unions are retained, including inherited accounts. A release at
    today's cutoff never grants an earlier decision access to these outcomes.
    """
    from .research_memory import authorized_account_history, authorized_period
    from .research_jobs import table
    if type(as_of_ms) is not int or as_of_ms < 0 or type(limit) is not int or not 1 <= limit <= 64:
        raise ValueError('Explicit cutoff and bounded export limit required')
    if not _exists(store, 'research_evaluation_memory'):
        return []
    if not authorized_account_history(store, network, address, as_of_ms):
        return []
    records = []
    for kind in ('population', 'paper'):
        registry = table(kind)
        if not _exists(store, registry):
            continue
        # Availability and account scope precede reading any outcome payload.
        rows = store.connection.execute(
            f'select m.event_id,m.request_id,m.available_ms from research_evaluation_memory m '
            f'join {registry} j using(request_id) where j.network=? and j.address=? and m.available_ms<=? '
            'order by m.available_ms desc,m.event_id limit ?', (network, address, as_of_ms, limit)).fetchall()
        for row in rows:
            source = store.connection.execute(f'select packet_json from {registry} where request_id=?', (row['request_id'],)).fetchone()
            packet = json.loads(source[0])
            periods = [{'network': network, 'address': address, 'market': '*',
                        'start_ms': 0, 'end_ms': packet['available_ms'] + 1}]
            for inherited in packet.get('research_memory', []):
                for period in inherited['item']['periods']:
                    if period not in periods:
                        periods.append(period)
            # Feedback itself can refer to earlier lifecycle feedback; retain
            # those source unions rather than reducing to the current address.
            for inherited in packet.get('research_evaluation_memory', []):
                for period in inherited['periods']:
                    if period not in periods:
                        periods.append(period)
            if _exists(store, 'population_experiment_links'):
                plan_row = store.connection.execute('select p.plan_id,p.plan_json,p.coin from population_experiment_links l '
                    'join validation_plans p using(plan_id) where l.request_id=?', (row['request_id'],)).fetchone()
                if plan_row:
                    plan = json.loads(plan_row['plan_json'])
                    stages = {r[0] for r in store.connection.execute('select stage from validation_evaluations where plan_id=?', (plan_row['plan_id'],))}
                    for stage in stages:
                        periods.append({'network': network, 'address': address, 'market': plan_row['coin'], **plan[stage]})
            if _exists(store, 'research_evaluation_source_periods'):
                for source_row in store.connection.execute('select period_json from research_evaluation_source_periods where event_id=?', (row['event_id'],)):
                    period=json.loads(source_row[0])
                    if period not in periods:
                        periods.append(period)
            if not all(authorized_period(store, p, as_of_ms) for p in periods):
                continue
            body = store.connection.execute('select memory_json from research_evaluation_memory where event_id=?', (row['event_id'],)).fetchone()
            records.append({'event_id': row['event_id'], 'available_ms': row['available_ms'],
                'periods': periods, 'item': json.loads(body[0]),
                'evidence_refs': [{'kind': 'research_evaluation', 'id': row['event_id']}]})
    return sorted(records, key=lambda r: (-r['available_ms'], r['event_id']))[:limit]


def validate_feedback_reference(store, event_id, periods, as_of_ms):
    """Resolve one typed proof through the same causal export authorization."""
    from .research_jobs import table
    if not _exists(store, 'research_evaluation_events'):
        raise ValueError('Registered evaluation feedback proof required')
    metadata = store.connection.execute('select request_id,research_origin,created_ms from research_evaluation_events where event_id=?', (event_id,)).fetchone()
    if not metadata or metadata['created_ms'] > as_of_ms:
        raise ValueError('Available evaluation feedback proof required')
    registry = table(metadata['research_origin'])
    source = store.connection.execute(f'select network,address from {registry} where request_id=?', (metadata['request_id'],)).fetchone()
    if not source:
        raise ValueError('Evaluation feedback source required')
    found = next((entry for entry in export_memory(store, source['network'], source['address'], as_of_ms, limit=64)
                  if entry['event_id'] == event_id), None)
    if not found or any(period not in periods for period in found['periods']):
        raise ValueError('Evaluation feedback requires its complete authorized source-period union')
    return found
