"""Immutable next actions from reviewed hypotheses; never infer executable rules from prose."""
import json
from .engine import canonical,fingerprint
from .harness_extensions import capability
from .validation import now_ms


def route(store,request_id,*,kind='population'):
    from .research_jobs import table
    registry=table(kind)
    store.connection.execute('create table if not exists population_hypothesis_routes '
        '(request_id text primary key,created_ms integer not null,route_json text not null)')
    store.connection.execute('create table if not exists population_hypothesis_route_history '
        '(request_id text not null,result_fingerprint text not null,sequence integer not null,'
        'created_ms integer not null,route_json text not null,primary key(request_id,result_fingerprint))')
    store.connection.commit()
    previous=store.connection.execute('select route_json from population_hypothesis_routes where request_id=?',(request_id,)).fetchone()
    row=store.connection.execute(f'select status,result_json from {registry} where request_id=?',(request_id,)).fetchone()
    if not row or row['status'] in ('sealed','running'):raise ValueError('Terminal population decision required')
    result=json.loads(row['result_json'] or '{}')
    saved=json.loads(previous[0]) if previous else None
    if saved and saved.get('research_origin','population')!=kind:raise ValueError('Immutable route origin mismatch')
    packet_row=store.connection.execute(f'select packet_json from {registry} where request_id=?',(request_id,)).fetchone()
    packet_body=json.loads(packet_row[0]) if packet_row else {}
    pilot_scope=packet_body.get('pilot_research')
    local_contract=packet_body.get('local_analysis_contract_v1')
    eth_window_projection=packet_body.get('observations',{}).get('prospective_eth_observation_v1',{})
    is_existing_eth_window=(kind=='population' and isinstance(pilot_scope,dict)
        and pilot_scope.get('candidate')=='67f7'
        and eth_window_projection.get('source',{}).get('protocol_id')=='67f7-eth-public-observation-24h-20261014-v1'
        and eth_window_projection.get('source',{}).get('stage')=='final_24h')
    route_version=('population-local-analysis-routing-v1' if isinstance(local_contract,dict)
        else 'population-eth-existing-window-routing-v1' if is_existing_eth_window
        else 'prospective-execution-routing-v7' if isinstance(pilot_scope,dict) else 'population-routing-v1')
    if result.get('resolution_assessment_v1'):route_version+='-assessment-v1'
    result_fp=fingerprint({'status':row['status'],'result':result,'route_version':route_version})
    history=store.connection.execute('select route_json from population_hypothesis_route_history where request_id=? and result_fingerprint=?',(request_id,result_fp)).fetchone()
    if history:return json.loads(history[0])
    if saved and saved.get('source_result_fingerprint')==result_fp:
        return saved
    if saved and row['status']==saved.get('source_status') and result.get('route') and not (result.get('critique') or result.get('proposal')):
        # Same deterministic preparation result: keep returning its immutable route.
        return saved
    if kind=='paper' and result.get('route') and not (result.get('critique') or result.get('proposal')):
        # Carry deterministic report dispositions through the existing route
        # registry. This prepares work without calling the model or arming v6.
        output={'request_id':request_id,'research_origin':kind,'source_status':row['status'],
            'promotion_authorized':False,'economic_rejection':False,
            'evidence_refs':['paper_research:'+request_id,result.get('source_report_id','')],
            'diagnostic':result.get('reason','terminal report awaits shared research budget'),
            'wake':result.get('wake',{}),'created_ms':now_ms(),
            'state':result.get('state',row['status']),'route':result['route'],
            'next_action':('wait for explicit shared budget availability; no model call made'
                if result.get('state')=='budget_required' else result.get('reason','follow the recorded deterministic disposition'))}
    else:
        decision=result.get('critique') or result.get('proposal') or {}
        validation_diagnostic=result.get('validation_diagnostic')
        output={'request_id':request_id,'research_origin':kind,'source_status':row['status'],'promotion_authorized':False,
            'economic_rejection':False,'evidence_refs':[('population_research:' if kind=='population' else 'paper_research:')+request_id],
            'diagnostic':decision.get('diagnostic',
                (validation_diagnostic.get('code') if isinstance(validation_diagnostic,dict) else None)
                or result.get('error_type','terminal request without hypothesis')),
            'wake':decision.get('wake',{}),'created_ms':now_ms()}
        if isinstance(validation_diagnostic,dict):
            output['validation_diagnostic']=validation_diagnostic
        if row['status']=='hypothesis_recorded':
            if (result.get('promotion_authorized') is not False or result.get('profitability_proven') is not False
                    or decision.get('decision')!='consistent'):
                raise ValueError('Reviewed non-economic hypothesis required')
            hypothesis=result['proposal']['hypothesis'];missing=hypothesis['required_data']
            if missing:
                output.update(state='needs_data',required_data=missing,
                    next_action='collect specified observations, then reassess on changed evidence',
                    wake={'kind':'required_observations_available','observations':missing,
                          'new_input_fingerprint_required':True})
            elif 'executable_spec' not in hypothesis:
                output.update(state='specification_required',next_action='compile an explicit executable contract and preregister a new prospective experiment',
                    wake={'kind':'executable_contract_supplied','new_input_fingerprint_required':True})
            else:
                spec=hypothesis['executable_spec']
                markets=([leg.get('market') for leg in spec.get('legs',[])]
                         if spec.get('engine')=='portfolio_reference_v1' else [spec.get('market')])
                if set(markets)!=set(hypothesis['markets']) or (spec.get('type') is not None and spec['type']!=hypothesis['type']):
                    raise ValueError('Executable contract must preserve hypothesis markets and type')
                supported=capability(spec)
                output['capability']=supported
                output.update(state=supported['state'],next_action='resolve capability diagnostic')
                if supported['state'] in ('executable','executable_experimental'):
                    integrated=supported['contract']['real_validation_adapter']
                    output.update(state='prospective_plan_required' if integrated else 'unsupported_validation_adapter',
                        next_action='preregister future windows, criteria and experiment budget' if integrated else 'implement and verify the prospective validation adapter',
                        wake={'kind':'prospective_plan_registered' if integrated else 'validation_adapter_verified'})
        else:
            output.update(state=row['status'],next_action={
                'needs_data':'collect observations specified by decision',
                'unsupported_mechanism':'implement and verify missing mechanism',
                'non_identifiable':'archive until a new source makes mechanism observable',
                'reject':'archive economic or hypothesis rejection with its original diagnostic',
            }.get(row['status'],'resolve interruption or contract failure before any explicitly budgeted new attempt'))
            if row['status']=='suspended' and isinstance(validation_diagnostic,dict):
                if validation_diagnostic.get('stage') == 'provider_execution':
                    output['next_action']='Inspect the isolated provider/runtime failure; this reserved attempt remains consumed and is not retried automatically.'
                    output['wake']={'kind':'manual_runtime_diagnosis','automatic_retry':False,
                        'attempt_consumed':True}
                else:
                    output['next_action']='Correct the recorded response contract before any separately authorized work; this rejected response is not promoted.'
                    output['wake']={'kind':'manual_contract_correction','automatic_retry':False}
        if is_existing_eth_window and row['status']=='hypothesis_recorded' and output.get('state')=='needs_data':
            requested=result.get('proposal',{}).get('hypothesis',{}).get('required_data',[])
            exact_window=bool(requested) and any(
                '1791990000000' in str(item) and '1792076400000' in str(item) for item in requested)
            report_source=eth_window_projection.get('source',{})
            report_available=store.connection.execute("select input_fingerprint from eth_observation_reports where protocol_id=? and stage='final_24h'",
                (report_source.get('protocol_id'),)).fetchone()
            run=store.connection.execute('select status,protocol_json,finalised_ms from eth_observation_runs where protocol_id=?',
                (report_source.get('protocol_id'),)).fetchone() if store.connection.execute(
                    "select 1 from sqlite_master where type='table' and name='eth_observation_runs'").fetchone() else None
            protocol_body=json.loads(run['protocol_json']) if run else {}
            authorized_report=bool(report_available and run and run['status']=='finalised'
                and run['finalised_ms'] is not None
                and report_available['input_fingerprint']==report_source.get('input_fingerprint')
                and protocol_body.get('network')=='hyperliquid-mainnet'
                and protocol_body.get('address','').lower()=='0x67f7aa8fb95c47e6ea9c517b623e0701cbf9d9ba'
                and protocol_body.get('market')=='ETH'
                and protocol_body.get('start_ms')==1791990000000
                and protocol_body.get('end_ms')==1792076400000)
            if exact_window and authorized_report:
                local=result.get('local_eth_existing_window_resolution',{})
                followup={'kind':'eth_existing_window_analysis','version':'population-eth-existing-window-resolution-v1',
                    'title':'Join every final-window fill to archived ETH pre-event context and persist order/time-aware comparisons',
                    'protocol_id':report_source['protocol_id'],'stage':'final_24h',
                    'report_input_fingerprint':report_source['input_fingerprint'],
                    'report_semantic_fingerprint':report_source.get('semantic_fingerprint'),
                    'window_ms':[1791990000000,1792076400000],
                    'requested_data_count':len(requested),'model_calls_authorized':0,'collection_authorized':False}
                if local.get('state')=='completed' and local.get('version')==followup['version']:
                    output.update(state='local_archive_analysis_complete',local_resolution=result.get('local_resolution'),
                        local_eth_existing_window_resolution=local,followup_task=followup,
                        next_action='No additional historical collection is needed. Keep the result exploratory; any repeatability test requires a separately authorized prospective evaluation.',
                        wake={'kind':'new_prospectively_authorized_evidence_only','new_input_fingerprint_required':True,
                            'model_calls_authorized':0,'collection_authorized':False,'paper_authorized':False})
                else:
                    output.update(state='local_archive_analysis_required',followup_task=followup,
                        next_action=followup['title'],
                        wake={'kind':'local_existing_window_analysis_ready','new_input_fingerprint_required':False,
                            'model_calls_authorized':0,'collection_authorized':False,'paper_authorized':False})
        if (isinstance(local_contract,dict) and kind=='population'
                and row['status'] in {'hypothesis_recorded','needs_data'} and output.get('state')=='needs_data'):
            from .population_local_analysis_contract import LocalAnalysisContractError, validate_contract
            try:
                validated=validate_contract(packet_body,local_contract)
            except LocalAnalysisContractError as exc:
                output.update(state='technical_required',validation_diagnostic=exc.diagnostic,
                    next_action='Correct the unsupported or unsealed local-analysis contract; do not translate required-data prose.')
            else:
                contract_fp=validated['contract_fingerprint'];source=local_contract['source'];scope=local_contract['scope']
                from .population_local_archive_resolution import _source_rows
                _,diagnostic=_source_rows(store,local_contract)
                if diagnostic:
                    waiting_codes={'source_registry_absent','source_report_unavailable','source_not_finalised'}
                    waiting=diagnostic['code'] in waiting_codes
                    output.update(state='local_archive_data_required' if waiting else 'technical_required',
                        validation_diagnostic=diagnostic,
                        next_action=('Wait for the exact named source report to become available; no collection is scheduled.'
                            if waiting else 'Resolve the sealed source, scope or reference mismatch; do not infer a different dataset.'))
                else:
                    followup={'kind':'population_local_archive_analysis','version':'population-local-archive-resolution-v1',
                        'contract_fingerprint':contract_fp,'source':source,'scope':scope,
                        'model_calls_authorized':0,'collection_authorized':False}
                    saved_resolution=result.get('local_archive_resolutions_v1',{}).get(contract_fp,{})
                    if saved_resolution.get('state') in {'complete','partial'}:
                        output.update(state='local_archive_analysis_complete',
                            local_archive_resolution=saved_resolution,followup_task={**followup,'state':'completed'},
                            next_action=saved_resolution.get('next_action','Local archive calculation is persisted; no automatic collection or inference.'),
                            wake={'kind':'changed_authorized_evidence_only','new_input_fingerprint_required':True,
                                'model_calls_authorized':0,'collection_authorized':False})
                    else:
                        output.update(state='local_archive_analysis_required',followup_task=followup,
                            next_action='Run the sealed local fill/market-context calculation profile.',
                            wake={'kind':'local_contract_ready','new_input_fingerprint_required':False,
                                'model_calls_authorized':0,'collection_authorized':False,'paper_authorized':False})
        local_resolution=result.get('local_resolution')
        followup=(local_resolution.get('followup_task')
            if isinstance(local_resolution,dict) else None)
        if (kind=='population' and isinstance(pilot_scope,dict) and row['status']=='needs_data'
                and isinstance(followup,dict) and followup.get('kind')=='offline_archive_join'):
            joined=result.get('local_archive_join')
            if isinstance(joined,dict) and joined.get('state')=='completed':
                output.update(state='local_archive_analysis_complete',
                    local_resolution=local_resolution,followup_task=followup,
                    local_archive_join=joined,
                    local_inventory_market_context=result.get('local_inventory_market_context'),
                    local_eth_execution_contribution=result.get('local_eth_execution_contribution'),
                    next_action='Review the recorded historical comparisons; no new collection or inference is scheduled.',
                    wake={'kind':'changed_authorized_evidence_only','new_input_fingerprint_required':True,
                        'model_calls_authorized':0,'collection_authorized':False,'paper_authorized':False})
            else:
                output.update(state='local_archive_analysis_required',
                    local_resolution=local_resolution,followup_task=followup,
                    next_action=followup['title'],
                    wake={'kind':'offline_archive_join_completed',
                        'new_input_fingerprint_required':True,'model_calls_authorized':0,
                        'collection_authorized':False,'paper_authorized':False})
        if (kind=='population' and isinstance(pilot_scope,dict) and row['status']=='needs_data'
                and isinstance(result.get('critique'),dict)
                and result['critique'].get('decision')=='needs_data'):
            diagnostic=result['critique'].get('diagnostic',{})
            wake=result['critique'].get('wake',{})
            if isinstance(diagnostic,dict) and wake.get('kind')=='prospective_observation_and_technical_task':
                missing=diagnostic.get('required_missing_observations')
                limits=diagnostic.get('limitations')
                if not isinstance(missing,list) or not missing or not isinstance(limits,list):
                    raise ValueError('Pilot technical route requires the validated critique evidence fields')
                output.update(state='technical_task_required',
                    local_resolution=result.get('local_resolution'),
                    technical_task={'route_version':'prospective-execution-instrumentation-v1',
                        'title':'Mesurer les ordres, rétrocessions et l’exécution passive HYPE',
                        'evidence_question':diagnostic.get('testability'),
                        'required_observations':missing,
                        'engine_constraint':(next((item for item in limits if 'IOC engine' in item),None)
                            or next((item for item in limits if 'passive' in item.lower()),None)),
                        'historical_backfill_requested':False,
                        'condition_for_reanalysis':'new authorized prospective evidence with a changed input fingerprint',
                        'paper_or_orders_authorized':False},
                    next_action='Traiter la tâche technique d’instrumentation et d’adaptation passive; relancer l’analyse seulement sur des preuves autorisées réellement nouvelles.',
                    wake={'kind':'changed_authorized_prospective_evidence','historical_backfill_requested':False,
                        'new_input_fingerprint_required':True,'execution_or_promotion_authorized':False})
    if result.get('resolution_assessment_v1'):
        from .population_memory import resolution_snapshot
        snapshot=resolution_snapshot(store,request_id,result)
        if not snapshot:raise ValueError('Resolution assessment requires registered local evidence')
        assessment=snapshot['synthesis']
        if output.get('required_data'):output['resolved_data']=output.pop('required_data')
        output.update(state='completed',resolution_assessment_v1=assessment,
            resolution_fingerprint=snapshot['fingerprint'],next_action=assessment['next_action'],
            wake={'kind':'changed_authorized_evidence_only','new_input_fingerprint_required':True,
                'model_calls_authorized':0,'collection_authorized':False,'paper_authorized':False})
    output['source_result_fingerprint']=result_fp
    output['supersedes_route_fingerprint']=fingerprint(saved) if saved else None
    if not saved:
        store.connection.execute('insert or ignore into population_hypothesis_routes values(?,?,?)',
            (request_id,output['created_ms'],canonical(output)))
        chosen=store.connection.execute('select route_json from population_hypothesis_routes where request_id=?',(request_id,)).fetchone()[0]
    else:
        seq=store.connection.execute('select coalesce(max(sequence),0)+1 from population_hypothesis_route_history where request_id=?',(request_id,)).fetchone()[0]
        store.connection.execute('insert or ignore into population_hypothesis_route_history values(?,?,?,?,?)',
            (request_id,result_fp,seq,output['created_ms'],canonical(output)))
        chosen=store.connection.execute('select route_json from population_hypothesis_route_history where request_id=? and result_fingerprint=?',(request_id,result_fp)).fetchone()[0]
    store.connection.commit()
    return json.loads(chosen)
