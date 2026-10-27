"""Renewable external evaluation allowance; never resets historical budgets."""
import json
from .engine import canonical, fingerprint

DAY_MS = 86400000


def validate(policy):
    if (not isinstance(policy, dict) or policy.get('version') != 'continuous-plan-allowance-v1'
            or policy.get('period_ms') != DAY_MS or not policy.get('justification')):
        raise ValueError('Explicit daily continuous plan allowance required')
    for key in ('max_plans_per_period', 'max_concurrent_plans'):
        if type(policy.get(key)) is not int or not 1 <= policy[key] <= 64:
            raise ValueError('Bounded continuous allocation required: ' + key)


def scoped_policy(store, request_id, external, allocated):
    """Only an existing authorized continuous task can opt into renewal."""
    allowance = external.get('continuous_plan_allowance')
    if allowance is None:
        return allocated
    validate(allowance)
    if not store.connection.execute("select 1 from sqlite_master where name='continuous_research_tasks'").fetchone():
        return allocated
    task = store.connection.execute('select policy_id,authorized_ms from continuous_research_tasks where request_id=?', (request_id,)).fetchone()
    if not task:
        return allocated
    return {**allocated, 'continuous_allocation_scope': {
        'version': 'continuous-plan-scope-v1', 'allocation_policy_id': external['policy_id'],
        'allocation_policy_fingerprint': fingerprint(external), 'task_policy_id': task['policy_id'],
        'request_id': request_id, 'authorized_ms': task['authorized_ms'], 'allowance': allowance}}


def reserve(store, request_id, policy, profile, clock):
    scope = policy['continuous_allocation_scope']; allowance = scope.get('allowance')
    validate(allowance)
    if scope.get('version') != 'continuous-plan-scope-v1' or scope.get('request_id') != request_id:
        raise ValueError('Immutable continuous task allocation scope required')
    task = store.connection.execute('select policy_id,authorized_ms from continuous_research_tasks where request_id=?', (request_id,)).fetchone()
    if not task or task['policy_id'] != scope.get('task_policy_id') or task['authorized_ms'] != scope.get('authorized_ms'):
        raise ValueError('Continuous plan scope differs from authorized task')
    bound = store.connection.execute('select fingerprint,policy_json from experiment_allocation_policies where policy_id=?', (scope.get('allocation_policy_id'),)).fetchone()
    if not bound or bound['fingerprint'] != scope.get('allocation_policy_fingerprint'):
        raise ValueError('Externally bound allocation scope required')
    external = json.loads(bound['policy_json'])
    if external.get('continuous_plan_allowance') != allowance:
        raise ValueError('Continuous allowance differs from immutable external policy')
    from .experiment_allocation import plan_policy
    expected = plan_policy(external, profile, json.loads(store.connection.execute(
        'select result_json from population_research_jobs where request_id=?', (request_id,)).fetchone()[0])['proposal']['hypothesis']['executable_spec'])
    if {k:v for k,v in policy.items() if k != 'continuous_allocation_scope'} != expected:
        raise ValueError('Continuous allocation cannot change external windows, criteria or budgets')
    store.connection.execute('create table if not exists continuous_plan_reservations '
        '(request_id text primary key,allocation_policy_id text not null,period_start_ms integer not null,'
        'reserved_ms integer not null,contract_fingerprint text not null,scope_json text not null)')
    contract = fingerprint({'policy': policy, 'profile': profile})
    period = task['authorized_ms'] // DAY_MS * DAY_MS
    if not task['authorized_ms'] <= clock < period + DAY_MS:
        raise ValueError('Continuous plan allocation expired; no transfer into a renewed day')
    previous = store.connection.execute('select contract_fingerprint from continuous_plan_reservations where request_id=?', (request_id,)).fetchone()
    if previous:
        if previous[0] != contract:
            raise ValueError('Continuous plan reservation is immutable')
        return
    used = store.connection.execute('select count(*) from continuous_plan_reservations where allocation_policy_id=? and period_start_ms=?',
        (scope['allocation_policy_id'], period)).fetchone()[0]
    if used >= allowance['max_plans_per_period']:
        raise ValueError('Continuous daily plan allowance exhausted')
    active = 0
    rows = store.connection.execute('select d.plan_json from continuous_plan_reservations r join population_plan_drafts d using(request_id) where r.allocation_policy_id=?', (scope['allocation_policy_id'],)).fetchall()
    for row in rows:
        plan_id = fingerprint(json.loads(row[0]))
        terminal = store.connection.execute("select 1 from validation_evaluations where plan_id=? and stage='final' and status in ('passed','failed','error')", (plan_id,)).fetchone()
        if not terminal and store.connection.execute("select 1 from sqlite_master where name='experiment_selections'").fetchone():
            terminal = store.connection.execute("select 1 from experiment_selections s join experiment_families f using(family_id) where f.plan_id=? and s.status='no_candidate'", (plan_id,)).fetchone()
        if not terminal and store.connection.execute("select 1 from sqlite_master where name='research_window_releases'").fetchone():
            terminal = store.connection.execute('select 1 from research_window_releases where plan_id=? group by plan_id having count(distinct stage)=2', (plan_id,)).fetchone()
        if not terminal:
            data=json.loads(row[0])
            if clock >= data['final']['end_ms'] and store.connection.execute("select 1 from sqlite_master where name='research_evaluation_events'").fetchone():
                request=data.get('population_origin',{}).get('request_id')
                for event_row in store.connection.execute('select event_json from research_evaluation_events where request_id=? and created_ms<=? order by created_ms desc limit 64', (request,clock)):
                    event=json.loads(event_row[0])
                    if event.get('state')=='technical_required' and event.get('evidence',{}).get('plan_id')==plan_id:
                        terminal=True
                        break
        if not terminal:
            active += 1
    if active >= allowance['max_concurrent_plans']:
        raise ValueError('Continuous concurrent plan allowance exhausted')
    # The reservation survives every subsequent error, including a malformed
    # candidate. A new day is a new allocation, never a refund or retry.
    store.connection.execute('insert into continuous_plan_reservations values(?,?,?,?,?,?)',
        (request_id, scope['allocation_policy_id'], period, clock, contract, canonical(scope)))
    store.connection.commit()
