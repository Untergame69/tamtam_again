"""Typed observation requests; model text never becomes an implicit acquisition."""
import json
from .engine import canonical,fingerprint
from .population_history import ENDPOINTS
from .research_memory import authorized_period
from .validation import now_ms

FIELDS={'required_data_index','source','endpoint','start_ms','end_ms','proof','decision_use'}


def validate_requests(required_data,requests):
    if not isinstance(required_data,list) or any(not isinstance(v,str) or not v.strip() for v in required_data):
        raise ValueError('Explicit list of missing observations required')
    if not isinstance(requests,list):raise ValueError('Structured observation request list required')
    indices=[]
    for request in requests:
        if not isinstance(request,dict) or set(request)!=FIELDS:raise ValueError('Exact observation contract fields required; budgets belong to external policy')
        index=request['required_data_index']
        if type(index) is not int or not 0<=index<len(required_data):raise ValueError('Request must refer to a declared missing observation')
        indices.append(index)
        for key in ('source','endpoint','proof','decision_use'):
            if not isinstance(request[key],str) or not request[key].strip():raise ValueError('Explicit observation source, proof and decision use required')
        if any(type(request[k]) is not int for k in ('start_ms','end_ms')) or not 0<=request['start_ms']<request['end_ms']:
            raise ValueError('Explicit observation interval required')
    if sorted(indices)!=list(range(len(required_data))):
        raise ValueError('Each missing observation needs exactly one contract; partial fulfillment cannot wake the hypothesis')


def classify(request):
    if request['source']!='public_rest_history' or request['endpoint'] not in ENDPOINTS:
        return {'state':'unsupported_acquisition','reason':'no verified local acquisition adapter for this source/endpoint; not economic rejection'}
    if request['proof']!='pagination_coverage':
        return {'state':'unsupported_proof','reason':'pagination adapter cannot certify inventory continuity, retention or economic completeness'}
    return {'state':'acquisition_required','adapter':'population_history',
        'limits':['REST availability remains receipt availability, never a live follower signal',
                  'pagination coverage alone proves neither retained history nor economic completeness']}


def register(store,request_id,*,kind='population',clock_ms=None):
    """Immutable acquisition plans, separate from immutable hypothesis routes."""
    from .research_jobs import table
    clock=now_ms() if clock_ms is None else clock_ms
    if type(clock) is not int or clock<0:raise ValueError('Explicit request availability required')
    row=store.connection.execute(f'select network,address,status,updated_ms,result_json from {table(kind)} where request_id=?',(request_id,)).fetchone()
    if not row or row['status'] not in {'hypothesis_recorded','needs_data'} or row['updated_ms']>clock:
        raise ValueError('Available typed research result required')
    result=json.loads(row['result_json'])
    if result.get('promotion_authorized') is not False or result.get('profitability_proven') is not False:
        raise ValueError('Non-promotional research result required')
    if row['status']=='hypothesis_recorded':
        if result.get('critique',{}).get('decision')!='consistent':
            raise ValueError('Reviewed hypothesis consistency required')
        hypothesis=result['proposal']['hypothesis'];missing=hypothesis['required_data'];requests=hypothesis.get('observation_requests')
    else:
        # Provider-level and critique-level needs_data can be collected only
        # when they carry the same exact typed contract as an accepted
        # hypothesis. No required-data prose is translated or guessed.
        decision=(result.get('critique') if result.get('critique',{}).get('decision')=='needs_data'
            else result.get('proposal') if result.get('proposal',{}).get('decision')=='needs_data' else None)
        if not isinstance(decision,dict):raise ValueError('Typed needs_data decision required')
        missing=decision.get('required_data');requests=decision.get('observation_requests')
        if not isinstance(missing,list) or not missing or not isinstance(requests,list):
            raise ValueError('Explicit typed observation contract required for needs_data collection')
    # Legacy prose stays intact; it is neither guessed nor relabeled impossible.
    if requests is None:
        plan={'state':'structured_request_required' if missing else 'no_missing_observations',
            'required_data':missing,'next_action':'supply explicit source, interval, proof and decision use before scheduling collection' if missing else 'continue executable-contract route'}
    else:
        validate_requests(missing,requests)
        entries=[]
        for request in requests:
            period={'network':row['network'],'address':row['address'],'market':'*','start_ms':request['start_ms'],'end_ms':request['end_ms']}
            decision=classify(request)
            if decision['state']=='acquisition_required':
                if request['end_ms']>clock:decision={'state':'await_window_end','wake_ms':request['end_ms']}
                elif not authorized_period(store,period,clock,end_inclusive=True):
                    decision={'state':'reserved_period','next_action':'await authorized release; do not read payloads'}
            entries.append({'request':request,'missing_observation':missing[request['required_data_index']],**decision})
        plan={'state':'observation_contracts_recorded','entries':entries,
            'wake':{'all_contracts_must_be_proven':True,'new_input_fingerprint_required':True},
            'dispatch_authorized':False,'next_action':'apply an external acquisition budget and verify adapters before dispatch'}
    plan.update(request_id=request_id,research_origin=kind,created_ms=clock,promotion_authorized=False,
        economic_rejection=False,network=row['network'],address=row['address'])
    identity=fingerprint({'request_id':request_id,'research_origin':kind})
    store.connection.execute('create table if not exists research_observation_plans '
        '(plan_id text primary key,request_id text not null,research_origin text not null,created_ms integer not null,plan_json text not null)')
    old=store.connection.execute('select plan_json from research_observation_plans where plan_id=?',(identity,)).fetchone()
    if old:return json.loads(old[0])
    store.connection.execute('insert into research_observation_plans values(?,?,?,?,?)',(identity,request_id,kind,clock,canonical(plan)))
    store.connection.commit()
    return plan
