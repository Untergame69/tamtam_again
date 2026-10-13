"""Seal bounded paper diagnosis research without reading reserved observations."""
import json,re
from .engine import canonical,fingerprint,number
from .population_research import validate_policy
from .research_memory import authorized_period,period_release_evidence
from .validation import now_ms


def initialize(store):
    store.connection.execute('create table if not exists paper_research_jobs '
        '(request_id text primary key,adaptation_request_id text not null,'
        'session_id text not null,created_ms integer not null,packet_json text not null,'
        'policy_json text not null,status text not null)')
    columns={r[1] for r in store.connection.execute('pragma table_info(paper_research_jobs)')}
    for name,kind in {'network':'text','address':'text','updated_ms':'integer',
            'reserved_cost_usd':'text','actual_cost_usd':'text','result_json':'text','usage_json':'text',
            'parent_request_id':'text','activated_ms':'integer','data_available_ms':'integer',
            'local_resolution_id':'text'}.items():
        if name not in columns:store.connection.execute('alter table paper_research_jobs add column '+name+' '+kind)

    # Earlier schemas allowed exactly one job per diagnostic. Keep one initial
    # job, but allow a separately counted child on proven new observations.
    sql=store.connection.execute("select sql from sqlite_master where name='paper_research_jobs'").fetchone()[0]
    revised=re.sub(r'(?i)(adaptation_request_id\s+text\s+not\s+null)\s+unique',r'\1',sql)
    if revised!=sql:
        # Never let a DROP cascade into an unknown external registry.
        tables=store.connection.execute("select name from sqlite_master where type='table'").fetchall()
        for table in tables:
            name=table[0].replace('"','""')
            if any(fk[2]=='paper_research_jobs' for fk in store.connection.execute('pragma foreign_key_list("'+name+'")')):
                raise ValueError('Paper followup migration requires explicit handling of referencing foreign keys')
        objects=store.connection.execute("select sql from sqlite_master where tbl_name='paper_research_jobs' and type in ('index','trigger') and sql is not null").fetchall()
        store.connection.execute('savepoint paper_followup_migration')
        try:
            store.connection.execute('create table paper_followup_migration as select * from paper_research_jobs')
            store.connection.execute('drop table paper_research_jobs')
            store.connection.execute(revised)
            store.connection.execute('insert into paper_research_jobs select * from paper_followup_migration')
            store.connection.execute('drop table paper_followup_migration')
            for obj in objects:store.connection.execute(obj[0])
            store.connection.execute('release paper_followup_migration')
        except BaseException:
            store.connection.execute('rollback to paper_followup_migration')
            store.connection.execute('release paper_followup_migration');raise
    # More than one immutable packet can descend from the same diagnostic; the
    # deterministic request id prevents duplicate presentation of each packet.
    store.connection.execute('drop index if exists paper_research_initial_diagnostic')
    store.connection.execute('create unique index if not exists paper_research_initial_packet on paper_research_jobs(adaptation_request_id,request_id) where parent_request_id is null')
    store.connection.execute('drop index if exists paper_research_followup_parent')
    store.connection.execute('create index if not exists paper_research_followup_parent on paper_research_jobs(parent_request_id) where parent_request_id is not null')
    store.connection.execute('create unique index if not exists paper_research_local_resolution on paper_research_jobs(local_resolution_id) where local_resolution_id is not null')
    store.connection.execute('create table if not exists paper_outcome_packets '
        '(adaptation_request_id text primary key,session_id text not null,report_id text not null,'
        'created_ms integer not null,source_fingerprint text not null,packet_json text not null,'
        'route_json text not null,task_id text not null unique)')
    store.connection.execute('create table if not exists paper_research_packet_adaptations '
        '(request_id text primary key,adapter_version text not null,source_fingerprint text not null,'
        'adapted_fingerprint text not null,prepared_ms integer not null,activated_ms integer not null,'
        'data_available_ms integer not null,data_age_ms integer not null,packet_json text not null)')
    store.connection.execute('create table if not exists paper_research_task_authorizations '
        '(request_id text primary key,authorization_ref text not null unique,packet_fingerprint text not null,'
        'authorized_ms integer not null,max_calls integer not null,max_reserved_cost_usd text,'
        'state text not null,calls_started integer not null default 0,reserved_cost_usd text,'
        'actual_cost_usd text,result_status text,activated_ms integer,updated_ms integer not null)')
    auth_columns={r[1] for r in store.connection.execute('pragma table_info(paper_research_task_authorizations)')}
    for name,kind in {'usage_mode':'text','max_input_tokens_per_call':'integer',
            'max_total_input_tokens':'integer','max_total_output_tokens':'integer',
            'max_total_duration_ms':'integer'}.items():
        if name not in auth_columns:store.connection.execute('alter table paper_research_task_authorizations add column '+name+' '+kind)
    store.connection.execute('create table if not exists paper_local_evidence_resolutions '
        '(resolution_id text primary key,parent_request_id text not null,source_result_fingerprint text not null,'
        'source_packet_fingerprint text not null,evidence_fingerprint text not null,prepared_ms integer not null,'
        'data_available_ms integer not null,child_request_id text not null unique,resolution_json text not null,'
        'packet_json text not null)')


def authorize_task(store,request_id,*,authorization_ref,authorized_ms,packet_fingerprint_value,
        max_calls=2,max_reserved_cost_usd='2',usage_mode='pay_as_you_go',
        max_input_tokens_per_call=None,max_total_input_tokens=None,
        max_total_output_tokens=None,max_total_duration_ms=None):
    """Persist a one-task approval without changing the shared trial ceiling."""
    initialize(store)
    row=store.connection.execute('select packet_json,status,activated_ms from paper_research_jobs where request_id=?',
        (request_id,)).fetchone()
    if not row or row['status']!='budget_required' or row['activated_ms'] is not None:
        raise ValueError('Only the exact dormant paper task can be authorized')
    source=json.loads(row['packet_json'])
    if source.get('fingerprint')!=packet_fingerprint_value:
        raise ValueError('Authorization packet fingerprint mismatch')
    if type(authorized_ms) is not int or type(max_calls) is not int or not 1<=max_calls<=2:
        raise ValueError('One task and at most two calls are allowed')
    if usage_mode=='subscription':
        caps=(max_input_tokens_per_call,max_total_input_tokens,max_total_output_tokens,max_total_duration_ms)
        if any(type(value) is not int or value<1 for value in caps):
            raise ValueError('Subscription authorization requires explicit token and duration ceilings')
        reserve=None
    elif usage_mode=='pay_as_you_go':
        reserve=number(max_reserved_cost_usd)
        if not reserve.is_finite() or reserve<=0 or reserve>number('2'):
            raise ValueError('Dedicated reservation must be positive and at most 2 USD')
        max_input_tokens_per_call=max_total_input_tokens=max_total_output_tokens=max_total_duration_ms=None
    else:
        raise ValueError('Explicit supported authorization usage mode required')
    prior=store.connection.execute('select * from paper_research_task_authorizations where request_id=?',(request_id,)).fetchone()
    if prior:
        if (prior['authorization_ref']==authorization_ref and prior['packet_fingerprint']==packet_fingerprint_value
                and prior['max_calls']==max_calls and prior['usage_mode']==usage_mode
                and (prior['max_reserved_cost_usd'] is None if reserve is None else number(prior['max_reserved_cost_usd'])==reserve)
                and prior['state']=='authorized'):
            return {'status':'already_authorized','request_id':request_id}
        raise ValueError('Task already has a different or consumed authorization')
    store.connection.execute('insert into paper_research_task_authorizations '
        '(request_id,authorization_ref,packet_fingerprint,authorized_ms,max_calls,max_reserved_cost_usd,state,updated_ms,'
        'usage_mode,max_input_tokens_per_call,max_total_input_tokens,max_total_output_tokens,max_total_duration_ms) '
        'values(?,?,?,?,?,?,?,?,?,?,?,?,?)',(request_id,authorization_ref,packet_fingerprint_value,authorized_ms,
        max_calls,str(reserve) if reserve is not None else '0','authorized',authorized_ms,usage_mode,
        max_input_tokens_per_call,max_total_input_tokens,max_total_output_tokens,max_total_duration_ms))
    store.connection.commit()
    return {'status':'authorized','request_id':request_id,'max_calls':max_calls,
        'usage_mode':usage_mode,'max_reserved_cost_usd':str(reserve) if reserve is not None else None}


def claim_authorized_call(store,request_id):
    """Consume one persisted call slot before contacting the model provider."""
    authorization=store.connection.execute('select state from paper_research_task_authorizations where request_id=?',(request_id,)).fetchone()
    if not authorization:return
    store.connection.execute('update paper_research_task_authorizations set calls_started=calls_started+1,updated_ms=? '
        'where request_id=? and state=\'activated\' and calls_started<max_calls',(now_ms(),request_id))
    if store.connection.execute('select changes()').fetchone()[0]!=1:
        raise ValueError('No unused call in the dedicated task authorization')
    store.connection.commit()


def finish_authorized_task(store,request_id,*,actual_cost_usd,result_status):
    store.connection.execute('update paper_research_task_authorizations set state=\'completed\',actual_cost_usd=?,'
        'result_status=?,updated_ms=? where request_id=? and state=\'activated\'',
        (actual_cost_usd,result_status,now_ms(),request_id))
    store.connection.commit()


def _authorization_covers_policy(authorization,policy):
    mode=policy.get('usage_mode','pay_as_you_go')
    if authorization['max_calls']<policy.get('max_model_calls',2):return False
    # Null mode means a preserved pre-versioned authorization. It can cover
    # only the historical pay-as-you-go contract, never a subscription task.
    auth_mode=authorization['usage_mode'] or 'pay_as_you_go'
    if auth_mode!=mode:return False
    if mode=='subscription':
        return all(authorization[key] is not None and authorization[key]>=policy[policy_key]
            for key,policy_key in (
                ('max_input_tokens_per_call','max_input_tokens_per_call'),
                ('max_total_input_tokens','max_total_input_tokens'),
                ('max_total_output_tokens','max_total_output_tokens'),
                ('max_total_duration_ms','max_total_duration_ms')))
    return (authorization['max_reserved_cost_usd'] is not None
        and number(policy['call_reservation_usd'])*authorization['max_calls']
        <=number(authorization['max_reserved_cost_usd']))


def adapt_outcome_packet(source,*,prepared_ms,activated_ms):
    """Version the terminal outcome into the runtime/validator packet contract."""
    if source.get('schema_version')!='paper-outcome-research-v1':
        raise ValueError('Supported immutable paper outcome packet required')
    periods=source.get('source_periods') or []
    if not periods or any(not {'network','address','market','start_ms','end_ms'}<=p.keys() for p in periods):
        raise ValueError('Explicit source periods required for paper runtime adaptation')
    networks={p['network'] for p in periods};addresses={p['address'] for p in periods}
    if len(networks)!=1 or len(addresses)!=1:
        raise ValueError('Paper runtime adaptation requires one attributed account scope')
    available=source.get('available_ms')
    if type(available) is not int or type(prepared_ms) is not int or type(activated_ms) is not int or not available<=prepared_ms<=activated_ms:
        raise ValueError('Ordered source, preparation and activation times required')
    market=source.get('simulated_parameters',{}).get('spec',{}).get('market')
    markets=[market] if isinstance(market,str) and market else sorted({p['market'] for p in periods})
    result={'schema_version':'paper-diagnostic-research-v2','adapter':{
            'name':'paper-outcome-to-runtime-v2','source_schema':'paper-outcome-research-v1',
            'source_fingerprint':source.get('fingerprint'),'adapter_created_ms':activated_ms},
        'network':next(iter(networks)),'address':next(iter(addresses)),
        'session_id':source['session_id'],'variant_id':source['variant_id'],
        'prepared_ms':prepared_ms,'activated_ms':activated_ms,'data_available_ms':available,
        'data_age_ms_at_activation':activated_ms-available,'available_ms':available,
        'source_periods':periods,'observations':{'markets':markets,
            'frozen_rule':source.get('simulated_parameters',{}).get('spec'),
            'paper_outcome':source},'evidence_refs':source.get('evidence_refs',[]),
        'research_contract':source.get('research_contract',{})}
    result['fingerprint']=fingerprint(result)
    return result


def packet(store,adaptation_request_id,*,clock_ms,max_chars,parent_request_id=None,_ancestry=(),local_resolution_id=None):
    if type(clock_ms) is not int or clock_ms<0 or type(max_chars) is not int or max_chars<1:
        raise ValueError('Explicit availability and packet budget required')
    if local_resolution_id is not None:
        from .paper_local_resolution import packet_for_resolution
        return packet_for_resolution(store,local_resolution_id,clock_ms=clock_ms,max_chars=max_chars)
    row=store.connection.execute('select session_id,created_ms from paper_adaptation_requests where request_id=?',
                                 (adaptation_request_id,)).fetchone()
    if not row or row['created_ms']>clock_ms:raise ValueError('Available adaptation request required')
    # Lookup only metadata before authorizing the paper period. No packet/state,
    # raw observations or reserved evaluation results are queried here.
    session=store.connection.execute('select variant_id,started_ms from paper_sessions where session_id=?',(row['session_id'],)).fetchone()
    variant=store.connection.execute('select network,address,coin from validation_plans p join strategy_variants v using(plan_id) where v.variant_id=?',
                                    (session['variant_id'],)).fetchone() if session else None
    if not session or not variant:raise ValueError('Attributed immutable paper version required')
    period={'network':variant['network'],'address':variant['address'],'market':'*',
            'start_ms':session['started_ms'],'end_ms':row['created_ms']}
    if not authorized_period(store,period,clock_ms,end_inclusive=True):
        raise ValueError('Paper research period intersects an unreleased reserve')
    diagnostic=json.loads(store.connection.execute('select diagnostic_json from paper_adaptation_requests where request_id=?',
        (adaptation_request_id,)).fetchone()[0])
    if diagnostic.get('request_id')!=adaptation_request_id or diagnostic.get('session_id')!=row['session_id'] or diagnostic.get('created_ms')!=row['created_ms']:
        raise ValueError('Adaptation provenance mismatch')
    if diagnostic.get('state')!='research_budget_required':
        return {'status':'not_researchable','reason':'resolve non-performance diagnosis through its declared action'}
    snapshot=diagnostic.get('paper_snapshot_available_ms')
    if type(snapshot) is not int or not period['start_ms']<=snapshot<=row['created_ms']:
        raise ValueError('Snapshot chronology inconsistent')
    # Frozen specification is a rule, not a reserved outcome. Do not query state_json.
    spec_row=store.connection.execute('select spec_json,frozen_ms from strategy_variants where variant_id=?',(session['variant_id'],)).fetchone()
    if not spec_row or spec_row['frozen_ms']>period['start_ms']:
        raise ValueError('Rule unavailable before paper session')
    spec=json.loads(spec_row['spec_json'])
    markets=[leg['market'] for leg in spec.get('legs',[])] if spec.get('engine')=='portfolio_reference_v1' else [variant['coin']]
    prepared_row=store.connection.execute('select session_id,report_id,source_fingerprint,packet_json,task_id '
        'from paper_outcome_packets where adaptation_request_id=?',(adaptation_request_id,)).fetchone() \
        if store.connection.execute("select 1 from sqlite_master where name='paper_outcome_packets'").fetchone() else None
    prepared=json.loads(prepared_row['packet_json']) if prepared_row else diagnostic.get('prepared_packet')
    if prepared is not None:
        # Outcome tasks are built once from the terminal report. Reuse that
        # immutable packet; the report-to-task handoff is not a model call.
        if not isinstance(prepared,dict):
            raise ValueError('Prepared terminal report packet provenance mismatch')
        if prepared.get('session_id')!=row['session_id'] or prepared.get('variant_id')!=session['variant_id']:
            raise ValueError('Prepared terminal report attribution mismatch')
        if prepared.get('available_ms',clock_ms+1)>clock_ms:
            raise ValueError('Prepared terminal report is not yet available')
        if prepared.get('simulated_parameters',{}).get('spec')!=spec:
            raise ValueError('Prepared terminal report rule fingerprint mismatch')
        if prepared.get('fingerprint')!=fingerprint({k:v for k,v in prepared.items() if k!='fingerprint'}):
            raise ValueError('Prepared terminal report packet fingerprint mismatch')
        if prepared_row and (prepared_row['session_id']!=row['session_id']
                or prepared_row['source_fingerprint']!=prepared['fingerprint']):
            raise ValueError('Prepared outcome registry attribution mismatch')
        for source_period in prepared.get('source_periods',[]):
            if not authorized_period(store,source_period,clock_ms,end_inclusive=True):
                raise ValueError('Prepared paper outcome period is no longer authorized')
        if len(canonical(prepared))>max_chars:
            return {'status':'needs_data','reason':'complete prepared outcome packet exceeds packet budget'}
        return {'status':'packet_ready','packet':prepared}
    output={'schema_version':'paper-diagnostic-research-v1','network':period['network'],
        'address':period['address'],'session_id':row['session_id'],'variant_id':session['variant_id'],
        'available_ms':row['created_ms'],'source_periods':[period],
        'source_period_membership':'closed interval of paper availability',
        'observations':{'markets':markets,'frozen_rule':spec,'paper_diagnostic':diagnostic},
        'evidence_refs':['paper_adaptation_requests:'+adaptation_request_id,*diagnostic.get('evidence_refs',[])],
        'research_contract':{'profitability_claim_authorized':False,'strategy_promotion_authorized':False,
            'existing_rule_mutation_authorized':False,'new_prospective_comparison_required':True},
        'limits':['risk-limit crossing does not prove economic degradation',
                  'paper outcomes are own simulated executions, not public leader decisions',
                  'packet contains no reserved observations or final evaluation results',
                  'no old session resumption, position transfer or research budget rearm']}
    access=period_release_evidence(store,period,clock_ms,end_inclusive=True)
    if access:
        output['access_provenance']=access
        output['available_ms']=max(output['available_ms'],max(p['available_ms'] for p in access))
        output['evidence_refs'].extend(p['evidence_ref'] for p in access)
    if parent_request_id is not None:
        from .research_need_collection import export_wakes
        if parent_request_id in _ancestry or len(_ancestry)>=64:raise ValueError('Bounded acyclic paper ancestry required')
        parent=store.connection.execute('select adaptation_request_id,session_id,network,address,status,updated_ms,created_ms,parent_request_id from paper_research_jobs where request_id=?',(parent_request_id,)).fetchone()
        if (not parent or parent['adaptation_request_id']!=adaptation_request_id
                or parent['session_id']!=row['session_id']
                or (parent['network'],parent['address'])!=(period['network'],period['address'])
                or parent['status']!='hypothesis_recorded' or parent['updated_ms']>clock_ms
                or not parent['created_ms']<clock_ms):
            raise ValueError('Available attributed paper parent required')
        rebuilt=packet(store,adaptation_request_id,clock_ms=parent['created_ms'],max_chars=max_chars,
            parent_request_id=parent['parent_request_id'],_ancestry=(*_ancestry,parent_request_id))
        if rebuilt['status']!='packet_ready':raise ValueError('Original parent packet no longer authorized')
        wakes=export_wakes(store,period['network'],period['address'],as_of_ms=clock_ms,
            request_ids={parent_request_id},research_origin='paper')
        if len(wakes)!=1:return {'status':'waiting','reason':'complete new observations required for paper reassessment'}
        wake=wakes[0]
        prior=json.loads(store.connection.execute('select packet_json from paper_research_jobs where request_id=?',(parent_request_id,)).fetchone()['packet_json'])
        expected=rebuilt['packet']
        if 'source_period_membership' not in prior:
            expected={k:v for k,v in expected.items() if k not in ('source_period_membership','fingerprint')}
            expected['fingerprint']=fingerprint(expected)
        if canonical(prior)!=canonical(expected):raise ValueError('Original paper parent provenance changed')
        result=json.loads(store.connection.execute('select result_json from paper_research_jobs where request_id=?',(parent_request_id,)).fetchone()[0])
        if (result.get('critique',{}).get('decision')!='consistent'
                or result.get('promotion_authorized') is not False
                or result.get('profitability_proven') is not False
                or not result['proposal']['hypothesis']['required_data']):
            raise ValueError('Reviewed missing-observation parent required')
        requested=result['proposal']['hypothesis'].get('observation_requests')
        if (not isinstance(requested,list) or sorted(canonical(r) for r in requested)
                !=sorted(canonical(p['source_request']) for p in wake['evidence']['proofs'])):
            raise ValueError('Wake differs from reviewed paper observation contracts')
        if prior.get('parent_research',{}).get('observation_fingerprint')==wake['evidence_fingerprint']:
            return {'status':'unchanged_no_inference','request_id':parent_request_id}
        # Inherit every period supplied to the parent, never just its paper period.
        for inherited in prior['source_periods']:
            if not authorized_period(store,inherited,clock_ms,end_inclusive=True):
                raise ValueError('Inherited paper research period intersects an unreleased reserve')
            if inherited not in output['source_periods']:output['source_periods'].append(inherited)
        for proof in wake['evidence']['proofs']:
            request=proof['source_request']
            source={**period,'start_ms':request['start_ms'],'end_ms':request['end_ms']}
            if source not in output['source_periods']:output['source_periods'].append(source)
            access=period_release_evidence(store,source,clock_ms,end_inclusive=True)
            if access:
                output.setdefault('access_provenance',[]).extend(access)
                output['evidence_refs'].extend(p['evidence_ref'] for p in access)
        output['parent_research']={'request_id':parent_request_id,'observation_fingerprint':wake['evidence_fingerprint'],
            'hypothesis':result['proposal']['hypothesis']}
        output['observations']['completed_observation_requests']=[*prior['observations'].get('completed_observation_requests',[]),wake]
        output['evidence_refs'].extend(ref for ref in prior['evidence_refs'] if ref not in output['evidence_refs'])
        output['available_ms']=max(output['available_ms'],parent['updated_ms'],wake['available_ms'],prior['available_ms'])
        output['evidence_refs'].extend(['paper_research:'+parent_request_id,'research_observation_wakes:'+parent_request_id])
        output['evidence_refs'].extend(p['evidence_ref'] for p in wake['pages'])
    if output.get('access_provenance'):
        output['available_ms']=max(output['available_ms'],max(p['available_ms'] for p in output['access_provenance']))
    output['fingerprint']=fingerprint(output)
    if len(canonical(output))>max_chars:return {'status':'needs_data','reason':'complete paper diagnostic exceeds packet budget'}
    return {'status':'packet_ready','packet':output}


def seal(store,adaptation_request_id,policy,*,clock_ms=None,parent_request_id=None,local_resolution_id=None):
    if policy.get('version')!='paper-adaptation-research-v1' or not isinstance(policy.get('justification'),str) or not policy['justification'].strip():
        raise ValueError('Explicit justified paper research policy required')
    # Same isolated model/call/timeout/output budgets as the existing runtime.
    validate_policy({**policy,'version':'population-research-v1'})
    clock=now_ms() if clock_ms is None else clock_ms
    if type(clock) is not int or clock<0:raise ValueError('Explicit research clock required')
    initialize(store);store.connection.commit()
    result=packet(store,adaptation_request_id,clock_ms=clock,max_chars=policy['max_packet_chars'],
        parent_request_id=parent_request_id,local_resolution_id=local_resolution_id)
    if result['status']!='packet_ready':return result
    identity=fingerprint({'adaptation_request_id':adaptation_request_id,'packet':result['packet']['fingerprint']})
    previous=store.connection.execute('select request_id,status,packet_json,created_ms,local_resolution_id from paper_research_jobs where request_id=? and parent_request_id is ? and created_ms<=?',(identity,parent_request_id,clock)).fetchone()
    prepared_handoff=store.connection.execute('select 1 from paper_outcome_packets where adaptation_request_id=?',(adaptation_request_id,)).fetchone()
    if not previous and not prepared_handoff:
        legacy=store.connection.execute('select request_id,status from paper_research_jobs where adaptation_request_id=? and parent_request_id is ? and created_ms<=? order by created_ms,request_id limit 1',(adaptation_request_id,parent_request_id,clock)).fetchone()
        if legacy and legacy['status']!='budget_required':return {'status':'unchanged_no_inference','request_id':legacy['request_id']}
    if previous and previous['status']!='budget_required':return {'status':'unchanged_no_inference','request_id':previous['request_id']}
    from .research_jobs import request_count
    authorization=store.connection.execute('select * from paper_research_task_authorizations where request_id=?',(identity,)).fetchone()
    dedicated=bool(authorization and authorization['state']=='authorized'
        and authorization['packet_fingerprint']==result['packet']['fingerprint'])
    if authorization and not dedicated:return {'status':'authorization_unavailable','request_id':identity}
    if dedicated and (not previous or not _authorization_covers_policy(authorization,policy)):
        return {'status':'authorization_limits_do_not_cover_policy','request_id':identity}
    if not dedicated and request_count(store)>=policy['max_requests']:return {'status':'budget_exhausted'}
    store.connection.execute('begin immediate')
    try:
        previous=store.connection.execute('select request_id,status,packet_json,created_ms,local_resolution_id from paper_research_jobs where request_id=? and parent_request_id is ? and created_ms<=?',(identity,parent_request_id,clock)).fetchone()
        if previous and previous['status']!='budget_required':
            store.connection.commit();return {'status':'unchanged_no_inference','request_id':previous['request_id']}
        # A new policy version does not reset counts or rearm failed jobs.
        from .research_jobs import request_count
        authorization=store.connection.execute('select * from paper_research_task_authorizations where request_id=?',(identity,)).fetchone()
        dedicated=bool(authorization and authorization['state']=='authorized'
            and authorization['packet_fingerprint']==result['packet']['fingerprint'])
        if authorization and not dedicated:
            store.connection.commit();return {'status':'authorization_unavailable','request_id':identity}
        if dedicated and (not previous or not _authorization_covers_policy(authorization,policy)):
            store.connection.commit();return {'status':'authorization_limits_do_not_cover_policy','request_id':identity}
        if not dedicated and request_count(store)>=policy['max_requests']:
            store.connection.commit();return {'status':'budget_exhausted'}
        recent=store.connection.execute('select max(created_ms) from paper_research_jobs where session_id=? and status!=\'budget_required\'',(result['packet']['session_id'],)).fetchone()[0]
        if not previous and recent is not None and clock-recent<policy['minimum_interval_ms']:
            store.connection.commit();return {'status':'waiting','wake_ms':recent+policy['minimum_interval_ms']}
        data_available_ms=int(result['packet']['available_ms'])
        if result['packet'].get('schema_version')=='paper-outcome-research-v1':
            adapted=adapt_outcome_packet(result['packet'],prepared_ms=(previous['created_ms'] if previous else clock),activated_ms=clock)
            if len(canonical(adapted))>policy['max_packet_chars']:
                store.connection.commit();return {'status':'needs_data','reason':'adapted runtime packet exceeds configured packet budget'}
            prior_adapter=store.connection.execute('select * from paper_research_packet_adaptations where request_id=?',(identity,)).fetchone()
            if prior_adapter and (prior_adapter['source_fingerprint']!=result['packet']['fingerprint']
                    or prior_adapter['packet_json']!=canonical(adapted)):
                raise ValueError('Previously activated packet adaptation is immutable')
            if not prior_adapter:
                store.connection.execute('insert into paper_research_packet_adaptations '
                    '(request_id,adapter_version,source_fingerprint,adapted_fingerprint,prepared_ms,activated_ms,data_available_ms,data_age_ms,packet_json) '
                    'values(?,?,?,?,?,?,?,?,?)',(identity,'paper-outcome-to-runtime-v2',result['packet']['fingerprint'],
                    adapted['fingerprint'],adapted['prepared_ms'],clock,data_available_ms,clock-data_available_ms,canonical(adapted)))
        if previous:
            if previous['request_id']!=identity or previous['packet_json']!=canonical(result['packet']):
                raise ValueError('Budget-required task packet changed before activation')
            if previous['local_resolution_id']!=local_resolution_id:
                raise ValueError('Prepared local evidence resolution identity changed')
            store.connection.execute('update paper_research_jobs set policy_json=?,status=\'sealed\',reserved_cost_usd=?,activated_ms=?,data_available_ms=?,updated_ms=? where request_id=? and status=\'budget_required\'',
                (canonical(policy),str(policy['call_reservation_usd']) if policy.get('usage_mode','pay_as_you_go')=='pay_as_you_go' else None,
                 clock,data_available_ms,clock,identity))
            if dedicated:
                reserved=(str(number(policy['call_reservation_usd'])*authorization['max_calls'])
                    if policy.get('usage_mode','pay_as_you_go')=='pay_as_you_go' else None)
                changed=store.connection.execute('update paper_research_task_authorizations set state=\'activated\',reserved_cost_usd=?,activated_ms=?,updated_ms=? where request_id=? and state=\'authorized\' and packet_fingerprint=?',
                    (reserved,clock,clock,identity,result['packet']['fingerprint'])).rowcount
                if changed!=1:raise ValueError('Dedicated authorization was concurrently consumed')
            store.connection.commit();return {'status':'sealed','request_id':identity,'model_calls':0,'activated_existing_task':True,'activated_ms':clock,'data_available_ms':data_available_ms}
        store.connection.execute('insert into paper_research_jobs '
            '(request_id,adaptation_request_id,session_id,created_ms,packet_json,policy_json,status,network,address,updated_ms,parent_request_id,activated_ms,data_available_ms,local_resolution_id) '
            'values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (identity,adaptation_request_id,result['packet']['session_id'],clock,
             canonical(result['packet']),canonical(policy),'sealed',result['packet']['network'],result['packet']['address'],clock,parent_request_id,clock,data_available_ms,local_resolution_id))
        store.connection.commit();return {'status':'sealed','request_id':identity,'model_calls':0,'activated_ms':clock,'data_available_ms':data_available_ms}
    except BaseException:store.connection.rollback();raise
