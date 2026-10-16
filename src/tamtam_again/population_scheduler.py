"""Bounded population hypothesis scheduling under the existing process lock."""
import json
from datetime import datetime, timezone

from .discovery import protected_addresses
from .engine import fingerprint
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


def _execute_local_eth_contribution(store, request_id):
    """Run or retrieve the deterministic ETH economics step after its sealed join."""
    job=store.connection.execute('select result_json from population_research_jobs where request_id=?',(request_id,)).fetchone()
    if not job:
        return {'request_id':request_id,'status':'blocked','reason':'research request disappeared',
            'model_calls':0,'collection_started':False}
    join=json.loads(job['result_json'] or '{}').get('local_archive_join',{})
    table=store.connection.execute("select 1 from sqlite_master where type='table' and name='population_local_archive_joins'").fetchone()
    saved=(store.connection.execute('select 1 from population_local_archive_joins where request_id=? and artifact_fingerprint=?',
        (request_id,join.get('artifact_fingerprint'))).fetchone() if table and join.get('artifact_fingerprint') else None)
    if not saved:
        return {'request_id':request_id,'status':'blocked','reason':'referenced local archive join artifact is not persisted',
            'model_calls':0,'collection_started':False}
    from .population_eth_execution_contribution import execute
    try:
        result=execute(store,request_id=request_id)
    except (ValueError,PermissionError) as exc:
        return {'request_id':request_id,'status':'blocked','reason':str(exc),
            'model_calls':0,'collection_started':False}
    artifact=result['artifact']
    return {'request_id':request_id,'status':result['status'],
        'version':artifact['schema_version'],'analysis_fingerprint':result['analysis_fingerprint'],
        'base_join_fingerprint':artifact['base_join_fingerprint'],
        'artifact_path':'docs/continuous-research/POPULATION-67F7-ETH-EXECUTION-CONTRIBUTION-20261014-v1.json.gz',
        'model_calls':0,'collection_started':False}


def _reconcile_final_eth_report_queue(store, route_value):
    followup=route_value.get('followup_task',{})
    if followup.get('kind') not in {'eth_existing_window_analysis','population_local_archive_analysis'} or route_value.get('state') not in {
            'local_archive_analysis_required','local_archive_analysis_complete','completed'}:
        return None
    from .research_work_queue import eth_report_work_payload,set_status
    source=followup.get('source',{})
    protocol_id=followup.get('protocol_id') or source.get('protocol_id')
    stage=followup.get('stage') or source.get('stage')
    if not protocol_id or not stage:return None
    row=store.connection.execute("select report_json from eth_observation_reports where protocol_id=? and stage=?",
        (protocol_id,stage)).fetchone()
    if not row:return None
    report=json.loads(row['report_json']);payload=eth_report_work_payload(protocol_id,stage,report)
    work=store.connection.execute("select work_id from research_work_queue where source_kind='eth_observation_report' and source_id=? and input_fingerprint=?",
        (protocol_id,fingerprint(payload))).fetchone()
    if not work:return None
    complete=route_value['state'] in {'local_archive_analysis_complete','completed'}
    set_status(store,work['work_id'],'completed' if complete else 'resolution_ready',
        'final report local analysis completed' if complete else 'final report local archive analysis required',
        outcome={'request_id':route_value['request_id'],'report_semantic_fingerprint':payload['semantic_fingerprint'],
            'route':route_value,'model_calls':0,'collection_started':False},clock_ms=now_ms())
    return work['work_id']


def tick(store,network,policy,*,dispatch=True,max_jobs=1,plan_policies=None,experiment_policy=None,reserve_policy=None,paper_policy=None,pilot_policy=None,resume_local_resolution=None):
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
    if resume_local_resolution is not None and (not isinstance(resume_local_resolution,str) or dispatch):
        raise ValueError('Explicit local-resolution resume requires an id and model dispatch disabled')
    with scheduler_lock(store):
        initialize(store);store.connection.commit()
        if resume_local_resolution is not None:
            if any(value is not None for value in (plan_policies,experiment_policy,reserve_policy,paper_policy,pilot_policy)):
                raise ValueError('Explicit local-resolution resume cannot run unrelated scheduler work')
            from .population_routing import route
            from .population_local_join import execute_offline_archive_join
            before=route(store,resume_local_resolution)
            if before.get('research_origin')!='population' or before.get('state') not in {
                    'local_archive_analysis_required','local_archive_analysis_complete'}:
                raise ValueError('Explicit local-resolution resume requires its persisted local route')
            followup=before.get('followup_task',{})
            if followup.get('kind')=='eth_existing_window_analysis':
                from .eth_existing_window_resolution import execute as execute_eth_window
                outcome=execute_eth_window(store,resume_local_resolution)
            elif followup.get('kind')=='population_local_archive_analysis':
                from .population_local_archive_resolution import execute as execute_local_archive
                outcome=execute_local_archive(store,resume_local_resolution)
            else:
                outcome=execute_offline_archive_join(store,resume_local_resolution)
            after=route(store,resume_local_resolution)
            _reconcile_final_eth_report_queue(store,after)
            contribution=None
            if (after.get('state')=='local_archive_analysis_complete'
                    and after.get('followup_task',{}).get('kind') not in {
                        'eth_existing_window_analysis','population_local_archive_analysis'}):
                contribution=_execute_local_eth_contribution(store,resume_local_resolution)
                after=route(store,resume_local_resolution)
            outcome['execution_contribution']=contribution
            return {'local_resolutions':[outcome],'routes':[after],'processed':[],'sealed':[],
                'historical_ai_gates':[],'interrupted_without_retry':[],'plans':[],
                'observation_plans':[],'promotion_authorized':False,'model_calls':0,
                'collection_started':False}
        if experiment_policy is not None:
            from .experiment_allocation import bind_policy
            bind_policy(store,experiment_policy)
        # Every cooperating worker holds this kernel lock through its calls.
        # Acquiring it proves no such worker is still executing this DB's job.
        recovered=[r[0] for r in store.connection.execute("select request_id from population_research_jobs where status='running'")]
        store.connection.execute("update population_research_jobs set status='interrupted',actual_cost_usd=NULL,updated_ms=? where status='running'",(now_ms(),))
        if recovered and store.connection.execute("select 1 from sqlite_master where type='table' and name='population_research_pilot_tasks'").fetchone():
            store.connection.executemany("update population_research_pilot_tasks set state='interrupted' where request_id=? and state in ('authorized','needs_critique')",
                [(request_id,) for request_id in recovered])
        store.connection.commit()
        from .population_memory import remember
        for request, in store.connection.execute("select request_id from population_research_jobs where status='hypothesis_recorded'").fetchall():
            try:remember(store,request)
            except ValueError:pass  # Explicit waiting diagnostics are returned after local work below.
        pilot=None
        if pilot_policy is not None:
            from .population_pilot import tick_locked
            pilot=tick_locked(store,pilot_policy,dispatch=dispatch)
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
                if pilot and pilot.get('status') not in {'waiting','already_processed','no_admissible_candidate','unchanged_no_inference'}:
                    break
                gate=historical_research_gate(store,network,request['address'],as_of_ms=now_ms(),
                                              max_requests=policy['max_requests'],request_id=request['request_id'])
                if request['request_id'] not in newly_sealed and not gate['allowed']:
                    historical_gates.append({'address':request['address'],'request_id':request['request_id'],**gate})
                    continue
                processed.append(_run(store,request['request_id']))
                if len(processed)>=max_jobs:break
        from .population_routing import route
        routes=[route(store,r[0]) for r in store.connection.execute("select request_id from population_research_jobs where network=? and status not in ('sealed','running') order by created_ms,request_id",(network,)).fetchall()]
        # Resolve deterministic local archive work in the same locked scheduler
        # pass. This path has no model, collection, or budget dependency.
        local_resolutions=[]
        local_executions=0
        from .population_local_join import VERSION as local_resolver_version, execute_offline_archive_join
        from .population_inventory_market_context import VERSION as context_analysis_version
        from .eth_existing_window_resolution import execute as execute_eth_window
        resume_found=False
        for candidate in routes:
            if candidate.get('research_origin')!='population':
                continue
            if resume_local_resolution is not None and candidate.get('request_id')!=resume_local_resolution:
                continue
            complete=candidate.get('state')=='local_archive_analysis_complete'
            required=candidate.get('state')=='local_archive_analysis_required'
            if not (complete or required):
                continue
            resume_found=True
            joined=candidate.get('local_archive_join',{})
            context=candidate.get('local_inventory_market_context') or {}
            followup=candidate.get('followup_task') or {}
            if followup.get('kind')=='eth_existing_window_analysis':
                try:
                    outcome=execute_eth_window(store,candidate['request_id'])
                    local_resolutions.append(outcome)
                except (ValueError,PermissionError) as exc:
                    local_resolutions.append({'request_id':candidate['request_id'],'status':'blocked','reason':str(exc),
                        'model_calls':0,'collection_started':False})
                    continue
                if outcome.get('status')=='prepared':local_executions+=1
                if resume_local_resolution is not None or local_executions>=max_jobs:break
                continue
            if followup.get('kind')=='population_local_archive_analysis':
                from .population_local_archive_resolution import execute as execute_local_archive
                try:
                    outcome=execute_local_archive(store,candidate['request_id'])
                    local_resolutions.append(outcome)
                except (ValueError,PermissionError) as exc:
                    local_resolutions.append({'request_id':candidate['request_id'],'status':'blocked','reason':str(exc),
                        'diagnostic':getattr(exc,'diagnostic',None),'model_calls':0,'collection_started':False})
                    continue
                if outcome.get('status')=='prepared':local_executions+=1
                if resume_local_resolution is not None or local_executions>=max_jobs:break
                continue
            if (complete and joined.get('version')==local_resolver_version
                    and context.get('version')==context_analysis_version and context.get('state')=='completed'):
                # Report cached outcomes but do not use the bounded execution
                # slot that must remain available to pending local work.
                outcome={'request_id':candidate['request_id'],'status':'unchanged',
                    'resolver_version':joined.get('version'),'artifact_fingerprint':joined.get('artifact_fingerprint'),
                    'artifact_path':joined.get('artifact_path'),'model_calls':0,'collection_started':False,
                    'inventory_market_context':context}
                outcome['execution_contribution']=_execute_local_eth_contribution(store,candidate['request_id'])
                local_resolutions.append(outcome)
                continue
            try:
                outcome=execute_offline_archive_join(store,candidate['request_id'])
                if outcome.get('route',{}).get('state')=='local_archive_analysis_complete':
                    outcome['execution_contribution']=_execute_local_eth_contribution(store,candidate['request_id'])
                local_resolutions.append(outcome)
            except (ValueError,PermissionError) as exc:
                local_resolutions.append({'request_id':candidate['request_id'],'status':'blocked','reason':str(exc),
                    'model_calls':0,'collection_started':False})
                continue
            # A failed/technical route is recorded, but it does not consume the
            # bounded slot needed by another independently resolvable task.
            if outcome.get('status') in {'prepared','unchanged'}:local_executions+=1
            if resume_local_resolution is not None or local_executions>=max_jobs:break
        if resume_local_resolution is not None and not resume_found:
            raise ValueError('Explicit local-resolution resume did not match a required or completed local task')
        if local_executions or any(x.get('execution_contribution',{}).get('status')=='prepared'
                for x in local_resolutions):
            routes=[route(store,r[0]) for r in store.connection.execute("select request_id from population_research_jobs where network=? and status not in ('sealed','running') order by created_ms,request_id",(network,)).fetchall()]
        from .research_needs import register as register_needs
        observation_plans=[register_needs(store,r['request_id']) for r in routes if r['source_status']=='hypothesis_recorded' and r['state']=='needs_data']
        plans=[]
        if plan_policies or experiment_policy is not None:
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
        from .population_memory import remember
        memory=[]
        for request, in store.connection.execute("select request_id from population_research_jobs where status='hypothesis_recorded'").fetchall():
            try:memory.append({'request_id':request,**remember(store,request)})
            except ValueError as exc:memory.append({'request_id':request,'status':'waiting','reason':str(exc)})
        # Persist due research work without coupling it to an IA call. The
        # observation's dates and collection protocol remain owned by its runner.
        from .research_work_queue import (initialize as initialize_work_queue, enqueue as enqueue_work,
            tick as tick_work_queue, eth_report_work_payload)
        initialize_work_queue(store)
        queue_route_status={
            'needs_data':'waiting_data','local_archive_analysis_required':'ready',
            'local_archive_data_required':'waiting_data',
            'local_archive_analysis_complete':'completed','budget_required':'budget_exhausted',
            'technical_required':'technical_required','prospective_plan_required':'ready',
            'completed':'completed','abandoned':'completed','incomplete_observation':'completed',
        }
        for candidate in routes:
            state=candidate.get('state','technical_required')
            queue_status=queue_route_status.get(state,'completed' if state in {'hypothesis_recorded','needs_critique','not_promoted'} else 'technical_required')
            stable_route={k:v for k,v in candidate.items() if k!='created_ms'}
            enqueue_work(store,'population_route',candidate['request_id'],stable_route,
                status=queue_status,reason='persisted population route: '+state)
        if store.connection.execute("select 1 from sqlite_master where type='table' and name='eth_observation_runs'").fetchone():
            for run in store.connection.execute('select protocol_id,status,protocol_json from eth_observation_runs order by protocol_id').fetchall():
                protocol=json.loads(run['protocol_json'])
                if run['status']=='finalised':
                    report=store.connection.execute("select input_fingerprint,report_json from eth_observation_reports where protocol_id=? and stage='final_24h'",(run['protocol_id'],)).fetchone()
                    if report:
                        from .research_work_queue import set_status as set_work_status
                        old_work=store.connection.execute("select work_id,payload_json from research_work_queue where source_kind='eth_observation_report' and source_id=? and status in ('waiting_deadline','waiting_data')",(run['protocol_id'],)).fetchall()
                        for old_row in old_work:
                            if json.loads(old_row['payload_json']).get('stage')!='final_24h':
                                set_work_status(store,old_row['work_id'],'completed','superseded by final report',clock_ms=now_ms())
                        report_value=json.loads(report['report_json'])
                        payload=eth_report_work_payload(run['protocol_id'],'final_24h',report_value)
                        enqueue_work(store,'eth_observation_report',run['protocol_id'],payload,status='ready',reason='final report available')
                    else:
                        enqueue_work(store,'eth_observation_report',run['protocol_id'],{'protocol_id':run['protocol_id'],'stage':'final_24h'},status='waiting_data',reason='final report not persisted')
                else:
                    enqueue_work(store,'eth_observation_report',run['protocol_id'],{'protocol_id':run['protocol_id'],'stage':'final_24h'},status='waiting_deadline',reason='frozen observation is still running',wake_at_ms=protocol.get('end_ms'))
        work_queue=tick_work_queue(store,max_jobs=max_jobs,pilot_policy=pilot_policy)
        # Reconcile the final-report queue row to the actual local-resolution route.
        # Older versions incorrectly marked this row superseded when finalization
        # arrived, hiding its later analysis state.
        for candidate in routes:
            _reconcile_final_eth_report_queue(store,candidate)
        store.connection.commit()
        paper=None
        if paper_policy is not None:
            if experiment_policy is None:raise ValueError('External experiment allocation required for paper research')
            from .paper_scheduler import _tick as paper_tick
            paper=paper_tick(store,paper_policy,experiment_policy=experiment_policy,dispatch=dispatch and len(processed)<max_jobs,max_jobs=max_jobs)
        return {'paper_research':paper,'pilot_research':pilot,'reserves':reserves,'plans':plans,'routes':routes,'local_resolutions':local_resolutions,'work_queue':work_queue,'sealed':sealed,'processed':processed,'historical_ai_gates':historical_gates,'interrupted_without_retry':recovered,'memory':memory,
                'promotion_authorized':False,'observation_plans':observation_plans}
