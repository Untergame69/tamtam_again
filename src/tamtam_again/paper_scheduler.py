"""Bounded diagnosis -> isolated proposal/review -> future experiment decisions."""
import json
from .paper_research import initialize,seal
from .population_research import validate_policy
from .paper_runtime import _run
from .research import scheduler_lock
from .validation import now_ms


def tick(store,policy,*,experiment_policy,dispatch=True,max_jobs=1):
    with scheduler_lock(store):return _tick(store,policy,experiment_policy=experiment_policy,dispatch=dispatch,max_jobs=max_jobs)


def _tick(store,policy,*,experiment_policy,dispatch=True,max_jobs=1):
    if policy.get('version')!='paper-adaptation-research-v1' or not policy.get('justification'):
        raise ValueError('Explicit paper research policy required')
    validate_policy({**policy,'version':'population-research-v1'})
    from .experiment_allocation import bind_policy,plan_policy
    bind_policy(store,experiment_policy)
    if type(max_jobs) is not int or max_jobs<1:raise ValueError('Positive paper worker budget required')
    inspected=policy.get('max_diagnoses_per_tick',8)
    if type(inspected) is not int or not 1<=inspected<=64:raise ValueError('Bounded diagnosis inspection budget required')
    initialize(store)
    from .paper_followup import recover_completed_reports
    followup_tasks=recover_completed_reports(store,clock_ms=now_ms(),max_tasks=min(inspected,8))
    local_resolutions=[]
    local_pending=store.connection.execute("select request_id,result_json from paper_research_jobs "
        "where status='needs_data' order by updated_ms,request_id limit ?",(inspected,)).fetchall()
    from .paper_local_resolution import prepare_from_local_archives
    for parent in local_pending:
        try:
            value=prepare_from_local_archives(store,parent['request_id'],clock_ms=now_ms())
            local_resolutions.append(value)
        except ValueError as exc:
            local_resolutions.append({'request_id':parent['request_id'],'status':'waiting',
                'reason':type(exc).__name__})
    store.connection.execute('create table if not exists paper_research_seal_attempts '
        '(adaptation_request_id text primary key,last_attempt_ms integer not null,attempts integer not null)')
    store.connection.commit()
    interrupted=[r[0] for r in store.connection.execute("select request_id from paper_research_jobs where status='running'")]
    store.connection.execute("update paper_research_jobs set status='interrupted',actual_cost_usd=NULL,updated_ms=? where status='running'",(now_ms(),))
    store.connection.commit()
    from .paper_research import finish_authorized_task
    for request_id in interrupted:
        finish_authorized_task(store,request_id,actual_cost_usd=None,result_status='interrupted')
    sealed=[];processed=[];plans=[];routes=[];memory=[];observation_plans=[]
    if store.connection.execute("select 1 from sqlite_master where name='paper_adaptation_requests'").fetchone():
        clock=now_ms()
        pending=store.connection.execute('select a.request_id from paper_adaptation_requests a '
            'left join paper_research_jobs j on j.adaptation_request_id=a.request_id '
            'left join paper_research_seal_attempts t on t.adaptation_request_id=a.request_id '
            'where a.created_ms<=? and j.request_id is null and (t.last_attempt_ms is null or t.last_attempt_ms<?) '
            'order by coalesce(t.attempts,0),a.created_ms,a.request_id limit ?',(clock,clock,inspected)).fetchall()
        for row in pending:
            store.connection.execute('insert into paper_research_seal_attempts values(?,?,1) '
                'on conflict(adaptation_request_id) do update set last_attempt_ms=excluded.last_attempt_ms,attempts=attempts+1',
                (row[0],clock));store.connection.commit()
            try:result=seal(store,row[0],policy)
            except ValueError as exc:result={'status':'blocked','adaptation_request_id':row[0],'error_type':type(exc).__name__}
            sealed.append(result)
            if result['status']=='budget_exhausted' or sum(r['status']=='sealed' for r in sealed)>=max_jobs:break
    # Only a proven wake for a reviewed paper parent admits a new, separately
    # counted job. The old diagnostic, result and route remain immutable.
    if store.connection.execute("select 1 from sqlite_master where name='research_observation_wakes'").fetchone():
        clock=now_ms()
        pending=store.connection.execute('select j.request_id,j.adaptation_request_id from paper_research_jobs j '
            'join research_observation_wakes w on w.request_id=j.request_id '
            'left join paper_research_jobs child on child.parent_request_id=j.request_id '
            "where j.status='hypothesis_recorded' and j.updated_ms<=? and w.available_ms<=? and child.request_id is null "
            'order by w.available_ms,j.request_id limit ?',(clock,clock,inspected)).fetchall()
        for parent in pending:
            if sum(r['status']=='sealed' for r in sealed)>=max_jobs:break
            try:result=seal(store,parent['adaptation_request_id'],policy,parent_request_id=parent['request_id'])
            except ValueError as exc:result={'status':'blocked','parent_request_id':parent['request_id'],'error_type':type(exc).__name__}
            sealed.append(result)
            if result['status']=='budget_exhausted':break
    if dispatch:
        for row in store.connection.execute("select request_id from paper_research_jobs where status='sealed' order by created_ms,request_id").fetchall():
            try:processed.append(_run(store,row[0]))
            except Exception as exc:
                store.connection.execute("update paper_research_jobs set status='suspended',updated_ms=?,result_json=? where request_id=? and status='sealed'",
                    (now_ms(),json.dumps({'error_type':type(exc).__name__,'promotion_authorized':False,'profitability_proven':False}),row[0]))
                store.connection.commit()
                finish_authorized_task(store,row[0],actual_cost_usd=None,result_status='suspended')
                processed.append({'request_id':row[0],'status':'suspended','error_type':type(exc).__name__})
            if len(processed)>=max_jobs:break
    from .population_routing import route
    from .population_plans import _prepare_plan
    from .paper_memory import remember
    for row in store.connection.execute("select request_id,status,result_json from paper_research_jobs where status not in ('sealed','running') order by created_ms,request_id").fetchall():
        if row['status']=='hypothesis_recorded':
            try:memory.append({'request_id':row['request_id'],**remember(store,row['request_id'])})
            except ValueError as exc:memory.append({'request_id':row['request_id'],'status':'waiting','reason':str(exc)})
        decision=route(store,row['request_id'],kind='paper');routes.append(decision)
        if row['status']=='hypothesis_recorded' and decision['state']=='needs_data':
            from .research_needs import register
            observation_plans.append(register(store,row['request_id'],kind='paper'))
        if decision['state']!='prospective_plan_required' or len(plans)>=max_jobs:continue
        if store.connection.execute("select 1 from sqlite_master where name='population_experiment_links'").fetchone() and store.connection.execute('select 1 from population_experiment_links where request_id=?',(row['request_id'],)).fetchone():continue
        hypothesis=json.loads(row['result_json'])['proposal']['hypothesis'];profile=hypothesis.get('experiment_profile')
        if not profile:
            plans.append({'request_id':row['request_id'],'status':'waiting','reason':'justified experiment profile required'});continue
        try:
            allocated=plan_policy(experiment_policy,profile,hypothesis['executable_spec'])
            plans.append({'request_id':row['request_id'],**_prepare_plan(store,row['request_id'],allocated,profile,kind='paper')})
        except ValueError as exc:plans.append({'request_id':row['request_id'],'status':'waiting','reason':str(exc)})
    # Prepared budget-required packets remain dormant. They are not repeatedly
    # polled or dispatched until an explicitly authorized activation is supplied.
    return {'sealed':sealed,'processed':processed,'plans':plans,'routes':routes,'memory':memory,
        'followup_tasks':followup_tasks,'local_resolutions':local_resolutions,
        'interrupted_without_retry':interrupted,'promotion_authorized':False,'observation_plans':observation_plans}
