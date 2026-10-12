"""Bounded population hypothesis scheduling under the existing process lock."""
import json
from datetime import datetime, timezone

from .discovery import protected_addresses
from .population_research import initialize, seal, validate_policy
from .population_runtime import _run
from .research import scheduler_lock
from .validation import now_ms


def historical_research_gate(store,network,address,*,as_of_ms,max_requests,request_id=None):
    """Gate new population model work on reviewed history, changed data and budget.

    This check never reserves a request or calls a model. ``seal`` remains the
    authority for content identity, cooldown and the shared request ceiling.
    """
    if network=='synthetic':
        from .research_jobs import request_count
        current_requests=request_count(store)
        within_budget=current_requests<=max_requests if request_id else current_requests<max_requests
        return {'allowed':within_budget,'qualification':True,'new_data':True,'budget':within_budget,
                'reason':'synthetic acceptance fixture; no real dispatch unless explicitly mocked'}
    table=store.connection.execute("select 1 from sqlite_master where type='table' and name='population_historical_decisions'").fetchone()
    if not table:return {'allowed':False,'qualification':False,'new_data':False,'budget':False,'reason':'historical screen not yet available'}
    sealed_job=None
    if request_id:
        sealed_job=store.connection.execute('select request_id,network,address,input_fingerprint,packet_json,created_ms,status '
            'from population_research_jobs where request_id=?',(request_id,)).fetchone()
        if not sealed_job or sealed_job['status']!='sealed':
            return {'allowed':False,'qualification':False,'new_data':False,'budget':False,
                    'reason':'request is not an existing sealed reservation'}
        try:
            packet=json.loads(sealed_job['packet_json'])
            from .engine import fingerprint
            packet_body={k:v for k,v in packet.items() if k!='fingerprint'}
            immutable_packet=(packet.get('fingerprint')==fingerprint(packet_body) and
                packet.get('research_input_fingerprint')==sealed_job['input_fingerprint'] and
                packet.get('address','').lower()==address.lower() and packet.get('network')==network and
                type(packet.get('available_ms')) is int and packet['available_ms']<=sealed_job['created_ms'])
        except (TypeError,ValueError,KeyError):
            immutable_packet=False
        if not immutable_packet:
            return {'allowed':False,'qualification':False,'new_data':False,'budget':False,
                    'reason':'sealed request packet does not match its immutable reservation'}
        decision_cutoff=min(as_of_ms,sealed_job['created_ms'])
    else:
        decision_cutoff=as_of_ms
    row=store.connection.execute('select decision_id,status,as_of_ms,decision_json from population_historical_decisions '
        'where network=? and address=? and as_of_ms<=? order by as_of_ms desc,decision_id desc limit 1',
        (network,address.lower(),decision_cutoff)).fetchone()
    if not row:return {'allowed':False,'qualification':False,'new_data':False,'budget':False,'reason':'no reviewed historical decision'}
    try:decision=json.loads(row['decision_json'])
    except (TypeError,ValueError):decision={}
    economic=decision.get('economic_research_readiness',{})
    economic_ok=(decision.get('economic_validation') is True and
                 economic.get('status')=='approved_for_re' and
                 economic.get('eligible_for_ai_research') is True and
                 bool(economic.get('evidence_refs')))
    qualified=row['status']=='credible_deep_dive_candidate' and economic_ok
    if request_id:
        last=store.connection.execute('select max(created_ms) from population_research_jobs where network=? and address=? and created_ms<?',
            (network,address.lower(),sealed_job['created_ms'])).fetchone()
        last_request=last[0] if last else None
        new_data=(immutable_packet and row['as_of_ms']<=sealed_job['created_ms'] and
                  (last_request is None or (row['as_of_ms']>last_request and packet['available_ms']>last_request)))
    else:
        last=store.connection.execute('select max(created_ms) from population_research_jobs where network=? and address=?',
            (network,address.lower())).fetchone()
        last_request=last[0] if last else None
        if last_request is None:
            new_data=True
        else:
            rows=store.connection.execute("select observed_at from raw_observations where network=? and source='hyperliquid-population-rest-v1' "
                "and entity_type='account' and entity_id=? and endpoint in ('portfolio','userFillsByTime','userFunding','userNonFundingLedgerUpdates')",
                (network,address.lower())).fetchall()
            decision_cutoff_ms=row['as_of_ms']
            included_new_observation=False
            for source_row in rows:
                observed_at=datetime.fromisoformat(source_row['observed_at'])
                if observed_at.tzinfo is None:observed_at=observed_at.replace(tzinfo=timezone.utc)
                observed_ms=int(observed_at.timestamp()*1000)
                if last_request<observed_ms<=decision_cutoff_ms:
                    included_new_observation=True
                    break
            # Do not let a later observation beyond this screen invalidate data
            # that the screen actually included. It will be considered next time.
            new_data=decision_cutoff_ms>last_request and included_new_observation
    from .research_jobs import request_count
    current_requests=request_count(store)
    # A sealed job already occupies one of the shared reservations; it may
    # dispatch at the ceiling, while a new seal may not exceed it.
    within_budget=current_requests<=max_requests if request_id else current_requests<max_requests
    allowed=qualified and new_data and within_budget
    if row['status']=='credible_deep_dive_candidate' and not economic_ok:
        reason='curve/activity screening has not passed the separate economic review required for research RE'
    elif not qualified:reason='historical qualification is not sufficient for deeper AI research'
    elif not new_data:reason='no population observations arrived after the prior research request'
    elif not within_budget:reason='the existing shared population research request ceiling is exhausted'
    else:reason='historical qualification, new observations and existing request budget all pass'
    return {'allowed':allowed,'qualification':qualified,'new_data':new_data,'budget':within_budget,
            'reason':reason,'historical_decision_ref':'population_historical_decisions:'+row['decision_id']}


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
        sealed=[];processed=[];blocked=protected_addresses(store);historical_gates=[];newly_sealed=set()
        if store.connection.execute("select 1 from sqlite_master where name='population_accounts'").fetchone():
            addresses=[r[0] for r in store.connection.execute("select address from population_accounts where network=? and status!='retired' order by next_due_ms,address",(network,))]
        elif store.connection.execute("select 1 from sqlite_master where name='account_scope_reports'").fetchone():
            addresses=[r[0] for r in store.connection.execute('select distinct address from account_scope_reports where network=? order by address',(network,))]
        else:addresses=[]
        from .research_memory import authorized_account_history
        for address in addresses:
            if address in blocked:continue
            if not authorized_account_history(store,network,address,now_ms()):continue
            gate=historical_research_gate(store,network,address,as_of_ms=now_ms(),max_requests=policy['max_requests'])
            historical_gates.append({'address':address,**gate})
            if not gate['allowed']:continue
            result=seal(store,network,address,policy)
            if result['status']=='sealed':sealed.append(result);newly_sealed.add(result['request_id'])
            if result['status']=='budget_exhausted' or len(sealed)>=max_jobs:break
        if dispatch:
            pending=store.connection.execute("select request_id,address from population_research_jobs where network=? and status='sealed' order by created_ms,request_id",(network,)).fetchall()
            for request in pending:
                if request['address'] in blocked:continue
                gate=historical_research_gate(store,network,request['address'],as_of_ms=now_ms(),
                                              max_requests=policy['max_requests'],request_id=request['request_id'])
                if request['request_id'] not in newly_sealed and not gate['allowed']:
                    historical_gates.append({'address':request['address'],'request_id':request['request_id'],**gate})
                    continue
                processed.append(_run(store,request['request_id']))
                if len(processed)>=max_jobs:break
        from .population_memory import remember
        memory=[]
        for request, in store.connection.execute("select request_id from population_research_jobs where status='hypothesis_recorded'").fetchall():
            try:memory.append({'request_id':request,**remember(store,request)})
            except ValueError as exc:memory.append({'request_id':request,'status':'waiting','reason':str(exc)})
        from .population_routing import route
        routes=[route(store,r[0]) for r in store.connection.execute("select request_id from population_research_jobs where network=? and status not in ('sealed','running') order by created_ms,request_id",(network,)).fetchall()]
        from .research_needs import register as register_needs
        observation_plans=[register_needs(store,r['request_id']) for r in routes if r['source_status']=='hypothesis_recorded' and r['state']=='needs_data']
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
        return {'paper_research':paper,'reserves':reserves,'plans':plans,'routes':routes,'sealed':sealed,'processed':processed,'historical_ai_gates':historical_gates,'interrupted_without_retry':recovered,'memory':memory,
                'promotion_authorized':False,'observation_plans':observation_plans}
