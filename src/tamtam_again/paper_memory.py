"""Typed memory of post-diagnosis hypotheses, preserving the paper source interval."""
import json
from .research_memory import save_knowledge
from .validation import now_ms


def remember(store,request_id):
    store.connection.execute('create table if not exists paper_research_memory '
        '(request_id text primary key,knowledge_id text not null,created_ms integer not null)')
    store.connection.commit()
    previous=store.connection.execute('select knowledge_id from paper_research_memory where request_id=?',(request_id,)).fetchone()
    if previous:return {'status':'already_recorded','knowledge_id':previous[0]}
    row=store.connection.execute('select status,packet_json,result_json from paper_research_jobs where request_id=?',(request_id,)).fetchone()
    if not row or row['status']!='hypothesis_recorded':raise ValueError('Reviewed paper hypothesis required')
    packet=json.loads(row['packet_json']);result=json.loads(row['result_json']);h=result['proposal']['hypothesis']
    questions=h['required_data']
    item={'schema_version':1,'mechanism':h['mechanism'],'origin_accounts':[packet['address']],
        'origin_markets':sorted(set(h['markets'])|{'*'}),'periods':packet['source_periods'],
        'evidence_refs':[{'kind':'paper_research','id':request_id}],
        'experiments':[],'success_conditions':['unproven; new prospective evaluation required'],
        'failure_conditions':[h['rejection_criteria']],
        'execution_limits':[h['execution_constraints'],h['risk'],
            'paper diagnosis describes our simulated executions, not leader profitability'],
        'open_questions':questions if isinstance(questions,list) else [questions],
        'related_hypotheses':[packet['variant_id']],'status':'hypothesis'}
    saved=save_knowledge(store,item)
    store.connection.execute('insert or ignore into paper_research_memory values(?,?,?)',(request_id,saved['knowledge_id'],now_ms()))
    store.connection.commit();return {'status':'recorded',**saved}
