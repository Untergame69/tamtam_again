"""Use the isolated hypothesis runtime on a specifically authorized paper period."""
import json
from .paper_research import initialize,packet
from .population_runtime import execute_job
from .research import scheduler_lock
from .engine import canonical,fingerprint


def run(store,request_id):
    with scheduler_lock(store):return _run(store,request_id)


def _run(store,request_id):
    initialize(store);store.connection.commit()
    row=store.connection.execute('select network,address,status,policy_json,created_ms,adaptation_request_id,parent_request_id '
        'from paper_research_jobs where request_id=?',(request_id,)).fetchone()
    if not row or row['status']!='sealed':return {'status':'unchanged_no_inference','request_id':request_id}
    policy=json.loads(row['policy_json'])
    # packet authorizes from session/diagnostic metadata BEFORE reading the diagnosis.
    # Rebuild at the original seal time: no retrospective access grant is permitted.
    fresh=packet(store,row['adaptation_request_id'],clock_ms=row['created_ms'],max_chars=policy['max_packet_chars'],parent_request_id=row['parent_request_id'])
    if fresh['status']!='packet_ready':raise ValueError('Original paper research packet no longer eligible')
    saved=json.loads(store.connection.execute('select packet_json from paper_research_jobs where request_id=?',(request_id,)).fetchone()[0])
    expected=fresh['packet']
    if 'source_period_membership' not in saved:
        expected={k:v for k,v in expected.items() if k not in ('source_period_membership','fingerprint')}
        expected['fingerprint']=fingerprint(expected)
    if canonical(saved)!=canonical(expected):raise ValueError('Sealed paper research provenance changed')
    if row['network'] is not None and (row['network'],row['address'])!=(saved['network'],saved['address']):
        raise ValueError('Paper registry scope differs from authorized diagnosis')
    # Compatible old sealed rows get derived scope metadata, no invented receipt.
    store.connection.execute('update paper_research_jobs set network=?,address=? where request_id=? and network is null',
        (saved['network'],saved['address'],request_id));store.connection.commit()
    return execute_job(store,request_id,row,kind='paper',sealed_packet=saved)
