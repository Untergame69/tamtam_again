"""Preserve reviewed population mechanisms as hypotheses, never economic results."""
import json
from .research_memory import save_knowledge
from .validation import now_ms
from .engine import fingerprint


def remember(store,request_id):
    store.connection.execute('create table if not exists population_research_memory '
        '(request_id text primary key,knowledge_id text not null,created_ms integer not null)')
    store.connection.commit()
    previous=store.connection.execute('select knowledge_id from population_research_memory where request_id=?',(request_id,)).fetchone()
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
    # Keep the original import link immutable; later evidence is a new item.
    resolution=resolution_snapshot(store,request_id,result)
    if resolution and not previous:
        original=save_knowledge(store,item)
        store.connection.execute('insert or ignore into population_research_memory values(?,?,?)',
            (request_id,original['knowledge_id'],now_ms()));store.connection.commit()
        previous=(original['knowledge_id'],)
    if resolution:
        item['resolution_synthesis_v1']=resolution['synthesis']
        item['periods'] += [p for p in resolution['periods'] if p not in item['periods']]
        item['origin_markets']=sorted(set(item['origin_markets'])|{p['market'] for p in item['periods']})
        item['evidence_refs'].append({'kind':'population_resolution','id':request_id+':'+resolution['fingerprint']})
        item['open_questions']=resolution['synthesis']['unknowns']
        item['status']='observed_descriptor'
        item['memory_revision_v1']={'request_id':request_id,'supersedes':previous[0] if previous else None}
    elif previous:
        return {'status':'already_recorded','knowledge_id':previous[0]}
    saved=save_knowledge(store,item)
    store.connection.execute('create table if not exists population_research_memory_revisions '
        '(request_id text not null,resolution_fingerprint text not null,knowledge_id text not null,created_ms integer not null,'
        'primary key(request_id,resolution_fingerprint))')
    if resolution:
        prior=store.connection.execute('select knowledge_id from population_research_memory_revisions where request_id=? and resolution_fingerprint=?',
            (request_id,resolution['fingerprint'])).fetchone()
        if prior:return {'status':'already_recorded','knowledge_id':prior[0]}
        store.connection.execute('insert into population_research_memory_revisions values(?,?,?,?)',
            (request_id,resolution['fingerprint'],saved['knowledge_id'],now_ms()))
    store.connection.execute('insert or ignore into population_research_memory values(?,?,?)',
        (request_id,saved['knowledge_id'],now_ms()));store.connection.commit()
    return {'status':'recorded',**saved}


def resolution_snapshot(store,request_id,result):
    """Verify registered local artifacts; timestamps never define semantic identity."""
    refs=list(result.get('local_archive_resolutions_v1',{}).values())
    if result.get('local_eth_existing_window_resolution'):
        refs.append(result['local_eth_existing_window_resolution'])
    refs=[r for r in refs if r.get('state') in {'completed','complete','partial'}]
    if not refs:return None
    artifacts=[];periods=[]
    for ref in refs:
        found=None
        for table in ('population_local_archive_resolutions','population_eth_existing_window_resolutions'):
            if not store.connection.execute("select 1 from sqlite_master where name=?",(table,)).fetchone():continue
            row=store.connection.execute(f'select artifact_json,created_ms from {table} where request_id=? and artifact_fingerprint=?',
                (request_id,ref['artifact_fingerprint'])).fetchone()
            if row:
                artifact=json.loads(row['artifact_json'])
                checked=dict(artifact); checked.pop('analysis_fingerprint',None)
                if fingerprint(checked)!=ref['artifact_fingerprint']:raise ValueError('Local resolution artifact fingerprint mismatch')
                if row['created_ms']>now_ms():raise ValueError('Local resolution is not yet available')
                found=artifact;break
        if found is None:raise ValueError('Registered local resolution artifact required')
        w=found['window']
        periods.append({'network':found['network'],'address':found['address'],'market':found['market'],
            'start_ms':w['start_ms'],'end_ms':max(w['end_ms'],w.get('archive_receipt_cutoff_ms',w['end_ms']))+1})
        artifacts.append({'artifact_fingerprint':ref['artifact_fingerprint'],
            'report_input_fingerprint':ref['report_input_fingerprint'], 'next_action':found['next_action']})
    assessment=result.get('resolution_assessment_v1')
    if assessment:
        required={'version','question','new_evidence','conclusion','unknowns','next_action','disposition','artifact_fingerprints'}
        if not required<=assessment.keys() or assessment['version']!=1 or assessment['disposition']!='completed':
            raise ValueError('Explicit bounded resolution assessment required')
        if sorted(assessment['artifact_fingerprints'])!=sorted(a['artifact_fingerprint'] for a in artifacts):
            raise ValueError('Assessment must reference the current local artifacts')
        if not isinstance(assessment['unknowns'],list):raise ValueError('Explicit unknowns required')
        synthesis=assessment
    else:
        synthesis={'version':1,'question':result['proposal']['hypothesis']['required_data'],
            'new_evidence':artifacts,'conclusion':'Local archive calculation persisted; no economic validation.',
            'unknowns':[a['next_action'].get('remaining_question') for a in artifacts],
            'next_action':[a['next_action'] for a in artifacts]}
    semantic={'artifacts':artifacts,'synthesis':synthesis,'periods':periods}
    return {**semantic,'fingerprint':fingerprint(semantic)}
