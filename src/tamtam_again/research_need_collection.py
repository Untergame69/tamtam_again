"""Bounded history acquisitions inside an existing population lease and quota."""
import json
from datetime import datetime
from .engine import canonical,fingerprint
from .research_needs import classify,validate_requests
from .research_memory import authorized_period
from .population_history import collect_history
from .account_coverage import pagination_coverage
from .validation import now_ms


def validate_policy(policy):
    if policy.get('version')!='research-need-collection-v1' or not policy.get('policy_id') or not policy.get('justification'):
        raise ValueError('Explicit observation acquisition policy required')
    for key,limit in [('max_needs_per_job',4),('max_pages_per_need',6),('max_attempts_per_need',16)]:
        if type(policy.get(key)) is not int or not 1<=policy[key]<=limit:raise ValueError('Bounded acquisition budget required: '+key)


def tick_for_job(store,client,job,policy,*,clock_ms=None):
    validate_policy(policy);clock=now_ms() if clock_ms is None else clock_ms
    if type(clock) is not int or clock<0:raise ValueError('Explicit collection availability required')
    store.connection.executescript('''create table if not exists research_need_collection_policies
      (policy_id text primary key,fingerprint text not null,policy_json text not null);
      create table if not exists research_need_collection_states
      (need_id text primary key,plan_id text not null,attempts integer not null,state text not null,updated_ms integer not null,evidence_json text not null,lease_token text not null);
      create table if not exists research_need_collection_attempts
      (need_id text not null,attempt_number integer not null,started_ms integer not null,lease_token text not null,status text not null,updated_ms integer not null,evidence_json text,primary key(need_id,attempt_number));
      create table if not exists research_observation_wakes
      (request_id text primary key,available_ms integer not null,evidence_fingerprint text not null,evidence_json text not null);''')
    digest=fingerprint(policy)
    old=store.connection.execute('select fingerprint from research_need_collection_policies where policy_id=?',(policy['policy_id'],)).fetchone()
    if old and old[0]!=digest:raise ValueError('Acquisition policy identity is immutable')
    store.connection.execute('insert or ignore into research_need_collection_policies values(?,?,?)',(policy['policy_id'],digest,canonical(policy)));store.connection.commit()
    if not store.connection.execute("select 1 from sqlite_master where name='research_observation_plans'").fetchone():return {'processed':[],'wakes':[],'waiting':[],'model_calls':0}
    plans=store.connection.execute('select plan_id,plan_json from research_observation_plans where created_ms<=? order by created_ms,plan_id',(clock,)).fetchall()
    processed=[];wakes=[];waiting=[];spent=0
    for row in plans:
        plan=json.loads(row['plan_json'])
        if plan['network']!=job['network'] or plan['address'].lower()!=job['address'].lower():continue
        if 'entries' not in plan:
            waiting.append({'request_id':plan['request_id'],'state':plan['state']});continue
        requests=[e['request'] for e in plan['entries']];missing=[e['missing_observation'] for e in sorted(plan['entries'],key=lambda e:e['request']['required_data_index'])]
        validate_requests(missing,requests);all_proven=True;proofs=[]
        for request in requests:
            identity=fingerprint({'plan_id':row['plan_id'],'request':request})
            period={'network':job['network'],'address':job['address'],'market':'*','start_ms':request['start_ms'],'end_ms':request['end_ms']}
            capability=classify(request)
            if capability['state']!='acquisition_required':
                waiting.append({'need_id':identity,**capability});all_proven=False;continue
            if request['end_ms']>clock:
                waiting.append({'need_id':identity,'state':'await_window_end','wake_ms':request['end_ms']});all_proven=False;continue
            if not authorized_period(store,period,clock,end_inclusive=True):
                waiting.append({'need_id':identity,'state':'reserved_period','wake':'authorized period release required'});all_proven=False;continue
            state=store.connection.execute('select * from research_need_collection_states where need_id=?',(identity,)).fetchone()
            if state and state['state']=='proof_observed':proofs.append(json.loads(state['evidence_json']));continue
            if state and state['state']=='saturated_timestamp_unresolvable':
                waiting.append({'need_id':identity,'state':state['state'],'wake':'verified boundary acquisition correction required'});all_proven=False;continue
            if spent>=policy['max_needs_per_job'] or state and state['attempts']>=policy['max_attempts_per_need']:
                waiting.append({'need_id':identity,'state':'collection_budget_exhausted' if state and state['attempts']>=policy['max_attempts_per_need'] else 'job_budget_exhausted'});all_proven=False;continue
            store.connection.execute('begin immediate')
            try:
                lease=store.connection.execute('select lease_token,lease_until_ms from population_accounts where network=? and address=?',(job['network'],job['address'])).fetchone()
                if not lease or lease[0]!=job['lease_token'] or lease[1]<=clock:raise ValueError('Current population lease required')
                current=store.connection.execute('select attempts,state,lease_token from research_need_collection_states where need_id=?',(identity,)).fetchone()
                if current and current['attempts']>=policy['max_attempts_per_need']:
                    store.connection.rollback();all_proven=False;continue
                if current and current['state']=='running' and current['lease_token']==job['lease_token']:
                    store.connection.rollback();all_proven=False;continue
                store.connection.execute("update research_need_collection_attempts set status='lease_revoked',updated_ms=? where need_id=? and status='running' and lease_token!=?",(clock,identity,job['lease_token']))
                store.connection.execute("insert into research_need_collection_states values(?,?,1,'running',?,'{}',?) on conflict(need_id) do update set attempts=attempts+1,state='running',updated_ms=excluded.updated_ms,lease_token=excluded.lease_token",(identity,row['plan_id'],clock,job['lease_token']))
                attempt_number=store.connection.execute('select attempts from research_need_collection_states where need_id=?',(identity,)).fetchone()[0]
                store.connection.execute("insert into research_need_collection_attempts values(?,?,?,?,'running',?,NULL)",(identity,attempt_number,clock,job['lease_token'],clock))
                store.connection.commit()
            except BaseException:store.connection.rollback();raise
            spent+=1
            bounded={**job,'policy':{**job['policy'],'history_max_pages_per_endpoint':min(policy['max_pages_per_need'],job['policy'].get('history_max_pages_per_endpoint',3))}}
            try:
                _,history=collect_history(store,client,bounded,request['endpoint'],request['end_ms'],cursor_scope=identity,requested_start_ms=request['start_ms'],as_of_ms=clock)
                cutoff=max(clock,now_ms());pages=[]
                # Authorize again before scanning any archived request metadata.
                if not authorized_period(store,period,cutoff,end_inclusive=True):raise ValueError('Observation period became reserved')
                for raw in store.connection.execute("select observation_id,observed_at,requested_at,request_json,window_start_ms,window_end_ms from raw_observations where network=? and entity_type='account' and entity_id=? and source='hyperliquid-population-rest-v1' and endpoint=?",(job['network'],job['address'],request['endpoint'])).fetchall():
                    query=json.loads(raw['request_json']);available=int(datetime.fromisoformat(raw['observed_at']).timestamp()*1000)
                    requested=int(datetime.fromisoformat(raw['requested_at']).timestamp()*1000)
                    if query.get('research_need_id')!=identity or not requested<=available<=cutoff:continue
                    if query.get('type')!=request['endpoint'] or query.get('user','').lower()!=job['address'].lower():continue
                    pages.append({'available_ms':available,'start_ms':raw['window_start_ms'],'end_ms':raw['window_end_ms'],
                        'pagination_status':query.get('pagination_status'),'covered_until_ms':query.get('covered_until_ms'),
                        'evidence_ref':'raw_observations:'+str(raw['observation_id'])})
                evidence=pagination_coverage(pages,start_ms=request['start_ms'],end_ms=request['end_ms'],as_of_ms=cutoff)
                evidence.update(need_id=identity,available_ms=cutoff,proof='pagination_coverage',decision_use=request['decision_use'],source_request=request)
                status='proof_observed' if evidence['pagination_status']=='covered' else 'saturated_timestamp_unresolvable' if history['pagination_status']=='saturated_timestamp_unresolvable' else 'needs_more_pages'
            except Exception as exc:
                cutoff=max(clock,now_ms());status='collection_failed';evidence={'error_type':type(exc).__name__,'need_id':identity,'available_ms':cutoff}
            changed=store.connection.execute('update research_need_collection_states set state=?,updated_ms=?,evidence_json=? where need_id=? and lease_token=? and exists(select 1 from population_accounts where network=? and address=? and lease_token=?)',(status,cutoff,canonical(evidence),identity,job['lease_token'],job['network'],job['address'],job['lease_token'])).rowcount
            store.connection.execute("update research_need_collection_attempts set status=?,updated_ms=?,evidence_json=? where need_id=? and attempt_number=? and status='running'",(status if changed else 'lease_revoked',cutoff,canonical(evidence),identity,attempt_number))
            store.connection.commit()
            active=store.connection.execute('select state,lease_token from research_need_collection_states where need_id=?',(identity,)).fetchone()
            if active['lease_token']!=job['lease_token'] or active['state']!=status:all_proven=False;continue
            processed.append({'need_id':identity,'state':status})
            if status=='proof_observed':proofs.append(evidence)
            else:all_proven=False
        if all_proven and requests:
            evidence={'proofs':proofs,'promotion_authorized':False,'economic_completeness_proven':False,
                'next_action':'reassess on these changed observations under the unchanged research budget'}
            available=max(p['available_ms'] for p in proofs)
            cursor=store.connection.execute('insert or ignore into research_observation_wakes values(?,?,?,?)',(plan['request_id'],available,fingerprint(evidence),canonical(evidence)));store.connection.commit()
            if cursor.rowcount:wakes.append(plan['request_id'])
    return {'processed':processed,'wakes':wakes,'model_calls':0,'waiting':waiting}


def export_wakes(store,network,address,*,as_of_ms):
    """Recheck authority and provenance before exporting the promised raw pages."""
    if not store.connection.execute("select 1 from sqlite_master where name='research_observation_wakes'").fetchone():return []
    from .storage import decode_observation_payload
    output=[]
    for row in store.connection.execute('select w.*,p.plan_id,p.plan_json from research_observation_wakes w join research_observation_plans p using(request_id) where w.available_ms<=? order by w.available_ms,w.request_id',(as_of_ms,)).fetchall():
        plan=json.loads(row['plan_json'])
        if plan['network']!=network or plan['address'].lower()!=address.lower():continue
        evidence=json.loads(row['evidence_json'])
        if fingerprint(evidence)!=row['evidence_fingerprint']:raise ValueError('Wake evidence identity changed')
        pages=[]
        for proof in evidence['proofs']:
            request=proof['source_request']
            if request not in [e['request'] for e in plan['entries']] or proof['need_id']!=fingerprint({'plan_id':row['plan_id'],'request':request}):raise ValueError('Wake request provenance mismatch')
            period={'network':network,'address':address,'market':'*','start_ms':request['start_ms'],'end_ms':request['end_ms']}
            if proof['available_ms']>row['available_ms'] or not authorized_period(store,period,as_of_ms,end_inclusive=True):raise ValueError('Wake period unavailable')
            for ref in proof['evidence_refs']:
                if not ref.startswith('raw_observations:'):raise ValueError('Archived wake page required')
                # Metadata only before authorization of this page identity.
                raw=store.connection.execute('select observation_id,network,source,entity_type,entity_id,endpoint,requested_at,observed_at,request_json from raw_observations where observation_id=?',(int(ref.split(':')[1]),)).fetchone()
                if not raw:raise ValueError('Wake page missing')
                query=json.loads(raw['request_json'])
                requested=int(datetime.fromisoformat(raw['requested_at']).timestamp()*1000);available=int(datetime.fromisoformat(raw['observed_at']).timestamp()*1000)
                if raw['network']!=network or raw['source']!='hyperliquid-population-rest-v1' or raw['entity_type']!='account' or raw['entity_id'].lower()!=address.lower() or raw['endpoint']!=request['endpoint'] or query.get('research_need_id')!=proof['need_id'] or not requested<=available<=proof['available_ms']:
                    raise ValueError('Wake page provenance or availability mismatch')
                payload=store.connection.execute('select response_json,response_encoding from raw_observations where observation_id=?',(raw['observation_id'],)).fetchone()
                values=decode_observation_payload(payload)
                if not isinstance(values,list) or any(not isinstance(v,dict) or type(v.get('time')) is not int or not request['start_ms']<=v['time']<=request['end_ms'] for v in values):raise ValueError('Wake page content outside requested interval')
                pages.append({'evidence_ref':ref,'available_ms':available,'endpoint':request['endpoint'],'values':values})
        output.append({'request_id':row['request_id'],'available_ms':row['available_ms'],'evidence_fingerprint':row['evidence_fingerprint'],'evidence':evidence,'pages':pages})
    return output
