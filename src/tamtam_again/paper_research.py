"""Seal bounded paper diagnosis research without reading reserved observations."""
import json
from .engine import canonical,fingerprint
from .population_research import validate_policy
from .research_memory import authorized_period
from .validation import now_ms


def initialize(store):
    store.connection.execute('create table if not exists paper_research_jobs '
        '(request_id text primary key,adaptation_request_id text not null unique,'
        'session_id text not null,created_ms integer not null,packet_json text not null,'
        'policy_json text not null,status text not null)')


def packet(store,adaptation_request_id,*,clock_ms,max_chars):
    if type(clock_ms) is not int or clock_ms<0 or type(max_chars) is not int or max_chars<1:
        raise ValueError('Explicit availability and packet budget required')
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
    if not authorized_period(store,period,clock_ms):
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
    output={'schema_version':'paper-diagnostic-research-v1','network':period['network'],
        'address':period['address'],'session_id':row['session_id'],'variant_id':session['variant_id'],
        'available_ms':row['created_ms'],'source_periods':[period],
        'observations':{'markets':markets,'frozen_rule':spec,'paper_diagnostic':diagnostic},
        'evidence_refs':['paper_adaptation_requests:'+adaptation_request_id,*diagnostic.get('evidence_refs',[])],
        'research_contract':{'profitability_claim_authorized':False,'strategy_promotion_authorized':False,
            'existing_rule_mutation_authorized':False,'new_prospective_comparison_required':True},
        'limits':['risk-limit crossing does not prove economic degradation',
                  'paper outcomes are own simulated executions, not public leader decisions',
                  'packet contains no reserved observations or final evaluation results',
                  'no old session resumption, position transfer or research budget rearm']}
    output['fingerprint']=fingerprint(output)
    if len(canonical(output))>max_chars:return {'status':'needs_data','reason':'complete paper diagnostic exceeds packet budget'}
    return {'status':'packet_ready','packet':output}


def seal(store,adaptation_request_id,policy,*,clock_ms=None):
    if policy.get('version')!='paper-adaptation-research-v1' or not isinstance(policy.get('justification'),str) or not policy['justification'].strip():
        raise ValueError('Explicit justified paper research policy required')
    # Same isolated model/call/timeout/output budgets as the existing runtime.
    validate_policy({**policy,'version':'population-research-v1'})
    clock=now_ms() if clock_ms is None else clock_ms
    if type(clock) is not int or clock<0:raise ValueError('Explicit research clock required')
    initialize(store);store.connection.commit()
    previous=store.connection.execute('select request_id from paper_research_jobs where adaptation_request_id=? and created_ms<=?',(adaptation_request_id,clock)).fetchone()
    if previous:return {'status':'unchanged_no_inference','request_id':previous[0]}
    result=packet(store,adaptation_request_id,clock_ms=clock,max_chars=policy['max_packet_chars'])
    if result['status']!='packet_ready':return result
    store.connection.execute('begin immediate')
    try:
        previous=store.connection.execute('select request_id from paper_research_jobs where adaptation_request_id=? and created_ms<=?',(adaptation_request_id,clock)).fetchone()
        if previous:
            store.connection.commit();return {'status':'unchanged_no_inference','request_id':previous[0]}
        # A new policy version does not reset counts or rearm failed jobs.
        if store.connection.execute('select count(*) from paper_research_jobs').fetchone()[0]>=policy['max_requests']:
            store.connection.commit();return {'status':'budget_exhausted'}
        recent=store.connection.execute('select max(created_ms) from paper_research_jobs where session_id=?',(result['packet']['session_id'],)).fetchone()[0]
        if recent is not None and clock-recent<policy['minimum_interval_ms']:
            store.connection.commit();return {'status':'waiting','wake_ms':recent+policy['minimum_interval_ms']}
        identity=fingerprint({'adaptation_request_id':adaptation_request_id,'packet':result['packet']['fingerprint']})
        store.connection.execute('insert into paper_research_jobs values(?,?,?,?,?,?,?)',
            (identity,adaptation_request_id,result['packet']['session_id'],clock,
             canonical(result['packet']),canonical(policy),'sealed'))
        store.connection.commit();return {'status':'sealed','request_id':identity,'model_calls':0}
    except BaseException:store.connection.rollback();raise
