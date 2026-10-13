"""Use the isolated hypothesis runtime on a specifically authorized paper period."""
import json
from .paper_research import initialize,packet
from .population_runtime import execute_job
from .research import scheduler_lock
from .engine import canonical,fingerprint


def run(store,request_id):
    with scheduler_lock(store):
        try:return _run(store,request_id)
        except Exception as exc:
            authorized=store.connection.execute('select 1 from paper_research_task_authorizations where request_id=?',(request_id,)).fetchone()
            if not authorized:raise
            from .paper_research import finish_authorized_task
            from .validation import now_ms
            from .engine import canonical
            store.connection.execute("update paper_research_jobs set status='suspended',actual_cost_usd=NULL,usage_json='[]',result_json=?,updated_ms=? where request_id=? and status='sealed'",
                (canonical({'error_type':type(exc).__name__,'diagnostic':'Activated runtime failed before completion; no automatic retry'}),now_ms(),request_id))
            store.connection.commit()
            finish_authorized_task(store,request_id,actual_cost_usd=None,result_status='suspended')
            return {'status':'suspended','request_id':request_id,'error_type':type(exc).__name__}


def _run(store,request_id):
    initialize(store);store.connection.commit()
    row=store.connection.execute('select network,address,status,policy_json,created_ms,activated_ms,data_available_ms,adaptation_request_id,parent_request_id '
        'from paper_research_jobs where request_id=?',(request_id,)).fetchone()
    if not row or row['status']!='sealed':return {'status':'unchanged_no_inference','request_id':request_id}
    if row['activated_ms'] is None:raise ValueError('Explicit authorized activation timestamp required')
    policy=json.loads(row['policy_json'])
    # Revalidate access at activation without changing the evidence cutoff.
    # The preparation and source-data timestamps remain immutable.
    fresh=packet(store,row['adaptation_request_id'],clock_ms=row['activated_ms'],max_chars=policy['max_packet_chars'],parent_request_id=row['parent_request_id'])
    if fresh['status']!='packet_ready':raise ValueError('Original paper research packet no longer eligible')
    saved=json.loads(store.connection.execute('select packet_json from paper_research_jobs where request_id=?',(request_id,)).fetchone()[0])
    expected=fresh['packet']
    if 'source_period_membership' not in saved:
        expected={k:v for k,v in expected.items() if k not in ('source_period_membership','fingerprint')}
        expected['fingerprint']=fingerprint(expected)
    if canonical(saved)!=canonical(expected):raise ValueError('Sealed paper research provenance changed')
    source_period=(saved.get('source_periods') or [{}])[0]
    scope=(saved.get('network',source_period.get('network')),saved.get('address',source_period.get('address')))
    if row['network'] is not None and (row['network'],row['address'])!=scope:
        raise ValueError('Paper registry scope differs from authorized diagnosis')
    if saved.get('schema_version')=='paper-outcome-research-v1':
        adaptation=store.connection.execute('select * from paper_research_packet_adaptations where request_id=?',(request_id,)).fetchone()
        if not adaptation or adaptation['source_fingerprint']!=saved.get('fingerprint'):
            raise ValueError('Versioned runtime packet adaptation required')
        adapted=json.loads(adaptation['packet_json'])
        if (adaptation['activated_ms']!=row['activated_ms']
                or adaptation['data_available_ms']!=row['data_available_ms']
                or adapted.get('fingerprint')!=adaptation['adapted_fingerprint']
                or adapted.get('fingerprint')!=fingerprint({k:v for k,v in adapted.items() if k!='fingerprint'})):
            raise ValueError('Runtime packet adaptation provenance changed')
        if not {'network','address','observations','evidence_refs','available_ms'}<=adapted.keys():
            raise ValueError('Adapted runtime packet contract incomplete')
        if adapted['observations'].get('markets')!=[saved['simulated_parameters']['spec']['market']]:
            raise ValueError('Adapted runtime markets differ from frozen paper rule')
        if adapted['data_available_ms']!=saved['available_ms']:
            raise ValueError('Data age metadata differs from preserved packet')
        sealed_packet=adapted
    else:
        if not {'network','address','observations','evidence_refs','available_ms'}<=saved.keys():
            raise ValueError('Sealed paper packet does not satisfy runtime research contract')
        sealed_packet=saved
    # Compatible old sealed rows get derived scope metadata, no invented receipt.
    store.connection.execute('update paper_research_jobs set network=?,address=? where request_id=? and network is null',
        (scope[0],scope[1],request_id));store.connection.commit()
    return execute_job(store,request_id,row,kind='paper',sealed_packet=sealed_packet)
