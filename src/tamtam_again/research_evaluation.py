"""Deterministic reviewed-rule handoff and durable evaluation feedback.

This adapter never turns an association into a trading rule, reads reserved
market payloads, changes a gate, calls a model, or places an order. The existing
pipeline owns evaluation and paper starts; polling observes its durable results.
"""
import json
from .engine import canonical, fingerprint
from .validation import now_ms

SCHEMA = '''
CREATE TABLE IF NOT EXISTS research_evaluation_events (
 event_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, research_origin TEXT NOT NULL,
 created_ms INTEGER NOT NULL, event_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_evaluation_memory (
 event_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, available_ms INTEGER NOT NULL,
 memory_json TEXT NOT NULL);
'''


def _exists(store, name):
    return bool(store.connection.execute("select 1 from sqlite_master where type='table' and name=?", (name,)).fetchone())


def _persist(store, request_id, kind, state, *, evidence=None, diagnostic=None, wake=None):
    store.connection.executescript(SCHEMA)
    terminal = state in {'descriptive', 'rejected', 'technical_required', 'paper_complete'}
    next_plan = {'kind': 'next_candidate' if terminal else 'continue_candidate',
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
        store.connection.execute('insert or ignore into research_evaluation_memory values(?,?,?,?)',
            (event_id, request_id, event['created_ms'], canonical(memory)))
    return event


def handoff(store, request_id, *, kind='population', experiment_policy=None):
    """Persist a typed next plan; freeze only an explicitly reviewed executable rule.

    Allocation is externally supplied and immutable. Missing rule/profile remains
    descriptive or needs design; unsupported execution is a technical outcome.
    Replay recovers the same preregistered plan rather than moving its windows.
    """
    from .research import scheduler_lock
    with scheduler_lock(store):
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
    if routed['state'] != 'prospective_plan_required':
        state = ('descriptive' if routed['state'] in {'specification_required', 'completed', 'local_archive_analysis_complete'}
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
        prepared = _prepare_plan(store, request_id, allocated, profile, kind=kind)
    except ValueError as exc:
        return _persist(store, request_id, kind, 'technical_required', evidence=evidence, diagnostic=str(exc))
    if prepared['status'] == 'budget_exhausted':
        return _persist(store, request_id, kind, 'allocation_required', evidence=evidence,
                        diagnostic='Allocated plan budget exhausted; no automatic increase')
    return _observe(store, request_id, kind, prepared)


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
    evidence['evaluations'] = evaluations
    selection = store.connection.execute('select variant_id,status from experiment_selections where family_id=?', (family,)).fetchone()
    if not selection:
        failed = {r['variant_id'] for r in evaluations if r['stage'] == 'comparison' and r['status'] not in {'running', 'passed'}}
        if len(failed) == len(variants):
            state = 'technical_required' if any(r['status'] == 'error' for r in evaluations) else 'rejected'
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
        return _persist(store, request_id, kind, 'awaiting_final', evidence=evidence,
                        wake={'not_before_ms': plan['final']['end_ms'], 'owner': 'pipeline'})
    if not any(r['status'] == 'passed' for r in final):
        state = 'technical_required' if any(r['status'] == 'error' for r in final) else 'rejected'
        return _persist(store, request_id, kind, state, evidence=evidence, diagnostic='Final did not pass; new candidate requires new future reserve')
    sessions = [dict(r) for r in store.connection.execute('select session_id,status from paper_sessions where variant_id=? order by started_ms,session_id', (selection['variant_id'],))]
    evidence['sessions'] = sessions
    state = ('paper_active' if any(r['status'] == 'active' for r in sessions)
             else 'paper_complete' if sessions else 'paper_gate_required')
    return _persist(store, request_id, kind, state, evidence=evidence,
                    diagnostic='Existing pipeline and explicit paper support own paper admission; final pass alone does not start a session')


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
