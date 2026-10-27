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
        for table in ('population_local_archive_resolutions','population_eth_existing_window_resolutions',
                      'population_descriptive_study_resolutions'):
            if not store.connection.execute("select 1 from sqlite_master where name=?",(table,)).fetchone():continue
            row=store.connection.execute(f'select artifact_json,created_ms from {table} where request_id=? and artifact_fingerprint=?',
                (request_id,ref['artifact_fingerprint'])).fetchone()
            if row:
                artifact=json.loads(row['artifact_json'])
                checked=dict(artifact); checked.pop('analysis_fingerprint',None)
                if fingerprint(checked)!=ref['artifact_fingerprint']:raise ValueError('Local resolution artifact fingerprint mismatch')
                if row['created_ms']>now_ms():raise ValueError('Local resolution is not yet available')
                if table=='population_descriptive_study_resolutions':
                    job=store.connection.execute('select network,address,packet_json from population_research_jobs where request_id=?',
                        (request_id,)).fetchone()
                    packet=json.loads(job['packet_json']) if job else {}
                    window=artifact.get('window',{})
                    cutoff=packet.get('pilot_research',{}).get('admission_cutoff_ms',packet.get('available_ms'))
                    if (not job or artifact.get('request_id')!=request_id
                            or artifact.get('network')!=job['network'] or artifact.get('address')!=job['address']
                            or artifact.get('market') not in packet.get('observations',{}).get('markets',[])
                            or artifact.get('source_packet_fingerprint')!=packet.get('fingerprint')
                            or ref.get('report_input_fingerprint')!=packet.get('research_input_fingerprint')
                            or type(cutoff) is not int
                            or type(window.get('start_ms')) is not int or type(window.get('end_ms')) is not int
                            or not 0<=window['start_ms']<window['end_ms']<=cutoff
                            or window.get('archive_receipt_cutoff_ms',window['end_ms'])>cutoff):
                        raise ValueError('Descriptive resolution differs from its sealed source task')
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


def remember_resolution_descriptor(store,request_id):
    """Remember verified local observations without upgrading an IA needs_data result."""
    row=store.connection.execute('select network,address,status,result_json from population_research_jobs where request_id=?',
        (request_id,)).fetchone()
    if not row or row['status'] in ('sealed','running'):
        raise ValueError('Terminal research result required before remembering local observations')
    result=json.loads(row['result_json'])
    snapshot=resolution_snapshot(store,request_id,result)
    if not snapshot or not result.get('resolution_assessment_v1'):
        raise ValueError('Explicit assessment and registered local evidence required')
    synthesis=snapshot['synthesis'];periods=snapshot['periods']
    proof_id=request_id+':'+snapshot['fingerprint']
    previous=None
    if store.connection.execute("select 1 from sqlite_master where name='research_knowledge'").fetchone():
        for prior in store.connection.execute('select knowledge_id,item_json from research_knowledge '
                'where item_json like ? order by created_ms desc,rowid desc',('%'+request_id+'%',)):
            prior_item=json.loads(prior['item_json'])
            if (prior_item.get('status')=='observed_descriptor' and
                    {'kind':'population_resolution','id':proof_id} in prior_item.get('evidence_refs',[])):
                if '*' in prior_item.get('origin_markets',[]):
                    return {'status':'already_recorded_descriptor','knowledge_id':prior['knowledge_id'],
                        'economic_validation':False,'resolution_fingerprint':snapshot['fingerprint']}
                previous=prior['knowledge_id'];break
    item={'schema_version':1,'mechanism':synthesis['conclusion'],
        'origin_accounts':sorted({period['address'] for period in periods}),
        # The wildcard makes this descriptor selectable by the account-wide
        # packet builder. Source periods remain restricted to their actual markets.
        'origin_markets':sorted({period['market'] for period in periods}|{'*'}),'periods':periods,
        'evidence_refs':[{'kind':'population_resolution','id':proof_id}],
        'experiments':[],'success_conditions':['Descriptive calculations only; no strategy validation.'],
        'failure_conditions':[],'execution_limits':['No execution, collection or model call authorized by this memory.'],
        'open_questions':synthesis['unknowns'],'related_hypotheses':[],
        'status':'observed_descriptor','resolution_synthesis_v1':synthesis,
        'memory_revision_v1':{'request_id':request_id,'supersedes':previous}}
    saved=save_knowledge(store,item)
    return {'status':'recorded_descriptor',**saved,'resolution_fingerprint':snapshot['fingerprint']}


def remember_verified_local_resolution(store,request_id):
    """Import a deterministic local resolution even when the provider stayed needs_data.

    This preserves that original decision while making only the verified local
    descriptor available to a future packet. It does not require a new model
    assessment or convert the result into a hypothesis or economic outcome.
    """
    row=store.connection.execute('select network,address,status,result_json from population_research_jobs where request_id=?',
        (request_id,)).fetchone()
    if not row or row['status'] not in ('hypothesis_recorded','needs_data'):
        raise ValueError('Persisted research result required before local-resolution memory import')
    result=json.loads(row['result_json'] or '{}')
    snapshot=resolution_snapshot(store,request_id,result)
    if not snapshot:raise ValueError('Verified local artifact required before memory import')
    proof_id=request_id+':'+snapshot['fingerprint']
    from .research_memory import save_knowledge
    if store.connection.execute("select 1 from sqlite_master where name='research_knowledge'").fetchone():
        for prior in store.connection.execute('select knowledge_id,item_json from research_knowledge '
                'where item_json like ? order by created_ms desc,rowid desc',('%'+proof_id+'%',)):
            item=json.loads(prior['item_json'])
            if item.get('status')=='observed_descriptor' and {'kind':'population_resolution','id':proof_id} in item.get('evidence_refs',[]):
                return {'status':'already_recorded_descriptor','knowledge_id':prior['knowledge_id'],
                    'economic_validation':False,'resolution_fingerprint':snapshot['fingerprint']}
    periods=snapshot['periods']
    synthesis=snapshot['synthesis']
    item={'schema_version':1,'mechanism':synthesis['conclusion'],
        'origin_accounts':sorted({period['address'] for period in periods}),
        'origin_markets':sorted({period['market'] for period in periods}|{'*'}),
        'periods':periods,'evidence_refs':[{'kind':'population_resolution','id':proof_id}],
        'experiments':[],'success_conditions':['Descriptive local calculation only; no strategy validation.'],
        'failure_conditions':[],'execution_limits':['No collection, inference, paper run or orders authorized by this memory.'],
        'open_questions':synthesis['unknowns'],'related_hypotheses':[],
        'status':'observed_descriptor','resolution_synthesis_v1':synthesis,
        'memory_revision_v1':{'request_id':request_id,'supersedes':None}}
    saved=save_knowledge(store,item)
    return {'status':'recorded_descriptor',**saved,'economic_validation':False,
        'resolution_fingerprint':snapshot['fingerprint']}
