"""Bounded population hypothesis scheduling under the existing process lock."""
from .discovery import protected_addresses
from .population_research import initialize, seal, validate_policy
from .population_runtime import _run
from .research import scheduler_lock
from .validation import now_ms


def tick(store,network,policy,*,dispatch=True,max_jobs=1,plan_policies=None,experiment_policy=None,reserve_policy=None,paper_policy=None):
    validate_policy(policy)
    if paper_policy is not None:
        if experiment_policy is None:raise ValueError('External experiment allocation required for paper research')
        if paper_policy.get('version')!='paper-adaptation-research-v1' or not paper_policy.get('justification'):
            raise ValueError('Explicit paper diagnosis policy required')
        validate_policy({**paper_policy,'version':'population-research-v1'})
        if paper_policy['max_requests']!=policy['max_requests']:
            raise ValueError('Both research origins must share the same total request ceiling')
    if reserve_policy is not None:
        from .reserve_cycle import validate_policy as validate_reserve_policy
        validate_reserve_policy(reserve_policy)
    if experiment_policy is not None:
        from .experiment_allocation import validate_policy as validate_allocation
        validate_allocation(experiment_policy)
        if plan_policies is not None:raise ValueError('Choose one external experiment policy source')
    if plan_policies is not None and (not isinstance(plan_policies,dict) or any(not isinstance(k,str) or not isinstance(v,dict) for k,v in plan_policies.items())):
        raise ValueError('Explicit per-request prospective policies required')
    if type(max_jobs) is not int or max_jobs<1:raise ValueError('Positive dispatch budget required')
    with scheduler_lock(store):
        initialize(store);store.connection.commit()
        if experiment_policy is not None:
            from .experiment_allocation import bind_policy
            bind_policy(store,experiment_policy)
        # Every cooperating worker holds this kernel lock through its calls.
        # Acquiring it proves no such worker is still executing this DB's job.
        recovered=[r[0] for r in store.connection.execute("select request_id from population_research_jobs where status='running'")]
        store.connection.execute("update population_research_jobs set status='interrupted',actual_cost_usd=NULL,updated_ms=? where status='running'",(now_ms(),))
        store.connection.commit()
        reserves=None
        if reserve_policy is not None:
            from .reserve_cycle import tick as reserve_tick
            reserves=reserve_tick(store,reserve_policy)
        sealed=[];processed=[];blocked=protected_addresses(store)
        if store.connection.execute("select 1 from sqlite_master where name='population_accounts'").fetchone():
            addresses=[r[0] for r in store.connection.execute("select address from population_accounts where network=? and status!='retired' order by next_due_ms,address",(network,))]
        elif store.connection.execute("select 1 from sqlite_master where name='account_scope_reports'").fetchone():
            addresses=[r[0] for r in store.connection.execute('select distinct address from account_scope_reports where network=? order by address',(network,))]
        else:addresses=[]
        for address in addresses:
            if address in blocked:continue
            result=seal(store,network,address,policy)
            if result['status']=='sealed':sealed.append(result)
            if result['status']=='budget_exhausted' or len(sealed)>=max_jobs:break
        if dispatch:
            pending=store.connection.execute("select request_id,address from population_research_jobs where network=? and status='sealed' order by created_ms,request_id",(network,)).fetchall()
            for request in pending:
                if request['address'] in blocked:continue
                processed.append(_run(store,request['request_id']))
                if len(processed)>=max_jobs:break
        from .population_memory import remember
        memory=[]
        for request, in store.connection.execute("select request_id from population_research_jobs where status='hypothesis_recorded'").fetchall():
            try:memory.append({'request_id':request,**remember(store,request)})
            except ValueError as exc:memory.append({'request_id':request,'status':'waiting','reason':str(exc)})
        from .population_routing import route
        routes=[route(store,r[0]) for r in store.connection.execute("select request_id from population_research_jobs where network=? and status not in ('sealed','running') order by created_ms,request_id",(network,)).fetchall()]
        plans=[]
        if plan_policies or experiment_policy is not None:
            import json
            from .population_plans import _prepare_plan
            for candidate in routes:
                request_id=candidate['request_id']
                if candidate['state']!='prospective_plan_required':continue
                if experiment_policy is None and request_id not in plan_policies:continue
                if store.connection.execute("select 1 from sqlite_master where name='population_experiment_links'").fetchone():
                    if store.connection.execute('select 1 from population_experiment_links where request_id=?',(request_id,)).fetchone():continue
                job=store.connection.execute('select result_json from population_research_jobs where request_id=?',(request_id,)).fetchone()
                profile=json.loads(job[0])['proposal']['hypothesis'].get('experiment_profile')
                if not profile:
                    plans.append({'request_id':request_id,'status':'waiting','reason':'justified experiment profile required'})
                else:
                    try:
                        if experiment_policy is not None:
                            from .experiment_allocation import plan_policy
                            spec=json.loads(job[0])['proposal']['hypothesis']['executable_spec']
                            allocated=plan_policy(experiment_policy,profile,spec)
                        else:allocated=plan_policies[request_id]
                        plans.append({'request_id':request_id,**_prepare_plan(store,request_id,allocated,profile)})
                    except ValueError as exc:plans.append({'request_id':request_id,'status':'waiting','reason':str(exc)})
                if len(plans)>=max_jobs:break
        paper=None
        if paper_policy is not None:
            if experiment_policy is None:raise ValueError('External experiment allocation required for paper research')
            from .paper_scheduler import _tick as paper_tick
            paper=paper_tick(store,paper_policy,experiment_policy=experiment_policy,dispatch=dispatch and len(processed)<max_jobs,max_jobs=max_jobs)
        return {'paper_research':paper,'reserves':reserves,'plans':plans,'routes':routes,'sealed':sealed,'processed':processed,'interrupted_without_retry':recovered,'memory':memory,
                'promotion_authorized':False}
