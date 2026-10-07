"""Preserve reviewed population mechanisms as hypotheses, never economic results."""
import json
from .research_memory import save_knowledge
from .validation import now_ms


def remember(store,request_id):
    store.connection.execute('create table if not exists population_research_memory '
        '(request_id text primary key,knowledge_id text not null,created_ms integer not null)')
    store.connection.commit()
    previous=store.connection.execute('select knowledge_id from population_research_memory where request_id=?',(request_id,)).fetchone()
    if previous:return {'status':'already_recorded','knowledge_id':previous[0]}
    row=store.connection.execute('select * from population_research_jobs where request_id=?',(request_id,)).fetchone()
    if not row or row['status']!='hypothesis_recorded':raise ValueError('Reviewed hypothesis required before memory import')
    packet=json.loads(row['packet_json']);result=json.loads(row['result_json'])
    if result.get('promotion_authorized') is not False or result.get('profitability_proven') is not False:
        raise ValueError('Population memory may not inherit economic certification')
    hypothesis=result['proposal']['hypothesis']
    if result['critique']['decision']!='consistent':raise ValueError('Consistency review evidence required')
    questions=hypothesis['required_data']
    item={'schema_version':1,'mechanism':hypothesis['mechanism'],'origin_accounts':[row['address']],
        'origin_markets':sorted(set(hypothesis['markets'])|{'*'}),
        'periods':[{'network':row['network'],'address':row['address'],'market':'*',
                    'start_ms':0,'end_ms':packet['available_ms']+1}],
        'evidence_refs':[{'kind':'population_research','id':request_id}],
        'experiments':[], 'success_conditions':['unproven; prospective executable evaluation required'],
        'failure_conditions':[hypothesis['rejection_criteria']],
        'execution_limits':[hypothesis['execution_constraints'],hypothesis['risk']],
        'open_questions':questions if isinstance(questions,list) else [questions],
        'related_hypotheses':[],'status':'hypothesis'}
    # Inherited knowledge can concern other accounts or markets. Keep its entire
    # declared source union instead of laundering it into this account's period.
    for entry in packet.get('research_memory',[]):
        inherited=entry['item']
        for period in inherited['periods']:
            if period not in item['periods']:item['periods'].append(period)
        item['origin_accounts']=sorted(set(item['origin_accounts'])|set(inherited['origin_accounts']))
        item['origin_markets']=sorted(set(item['origin_markets'])|set(inherited['origin_markets']))
        item['evidence_refs'].append({'kind':'knowledge','id':entry['knowledge_id']})
    saved=save_knowledge(store,item)
    store.connection.execute('insert or ignore into population_research_memory values(?,?,?)',
        (request_id,saved['knowledge_id'],now_ms()));store.connection.commit()
    return {'status':'recorded',**saved}
