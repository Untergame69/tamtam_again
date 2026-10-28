"""Structured knowledge with explicit releases of used validation periods."""
from __future__ import annotations
import json,time
from datetime import datetime
from typing import Any
from .engine import canonical,fingerprint
from .storage import Store
from .validation import initialize

SCHEMA='''
CREATE TABLE IF NOT EXISTS research_knowledge (
 knowledge_id TEXT PRIMARY KEY,created_ms INTEGER NOT NULL,item_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_period_releases (
 evaluation_id TEXT PRIMARY KEY,released_ms INTEGER NOT NULL,policy_json TEXT NOT NULL,
 network TEXT NOT NULL,address TEXT NOT NULL,market TEXT NOT NULL,
 start_ms INTEGER NOT NULL,end_ms INTEGER NOT NULL);'''

def clock():return int(time.time()*1000)
def migrate(store):initialize(store);store.connection.executescript(SCHEMA)

def release_period(store:Store,evaluation_id:str,policy:dict[str,Any]) -> dict[str,Any]:
    migrate(store)
    if not policy.get('version') or not policy.get('justification') or type(policy.get('grace_ms')) is not int or policy['grace_ms']<0:
        raise ValueError('Explicit versioned knowledge-release policy required')
    previous=store.connection.execute('select * from research_period_releases where evaluation_id=?',(evaluation_id,)).fetchone()
    if previous:return dict(previous)
    row=store.connection.execute('select e.stage,e.status,p.plan_json,p.network,p.address,p.coin from validation_evaluations e join validation_plans p using(plan_id) where e.evaluation_id=?',(evaluation_id,)).fetchone()
    if not row or row['stage'] not in ('comparison','final') or row['status'] not in ('passed','failed','error'):
        raise ValueError('Release requires a terminal evaluation of a reserved period')
    window=json.loads(row['plan_json'])[row['stage']];now=clock()
    if now<window['end_ms']+policy['grace_ms']:raise ValueError('Release grace or period not complete')
    if row['stage']=='final' and not store.connection.execute('select 1 from consumed_holdouts where evaluation_id=?',(evaluation_id,)).fetchone():
        raise ValueError('Final period must retain its consumed-holdout record')
    store.connection.execute('insert or ignore into research_period_releases values (?,?,?,?,?,?,?,?)',
        (evaluation_id,now,canonical(policy),row['network'],row['address'],row['coin'],window['start_ms'],window['end_ms']))
    store.connection.commit()
    return dict(store.connection.execute('select * from research_period_releases where evaluation_id=?',(evaluation_id,)).fetchone())

def window_released(store,plan_id,stage,as_of_ms):
    if store.connection.execute("select 1 from sqlite_master where name='research_period_releases'").fetchone():
        release=store.connection.execute('select 1 from research_period_releases r join validation_evaluations e using(evaluation_id) '
            'where e.plan_id=? and e.stage=? and r.released_ms<=?',(plan_id,stage,as_of_ms)).fetchone()
        if release:return True
    if store.connection.execute("select 1 from sqlite_master where name='research_window_releases'").fetchone():
        return bool(store.connection.execute('select 1 from research_window_releases '
            'where plan_id=? and stage=? and released_ms<=?',(plan_id,stage,as_of_ms)).fetchone())
    return False


def authorized_account_history(store,network,address,as_of_ms):
    """Whole-account archives are inclusive at cutoff; authorize before decoding.

    A current release cannot grant access at an earlier historical decision time.
    No payload, strategy or evaluation outcome is read by this check.
    """
    if type(as_of_ms) is not int or as_of_ms<0:return False
    if not store.connection.execute("select 1 from sqlite_master where name='validation_plans'").fetchone():return True
    columns={r[1] for r in store.connection.execute('pragma table_info(validation_plans)')}
    if not {'plan_id','plan_json','network'}<=columns:return False
    for row in store.connection.execute('select plan_id,plan_json from validation_plans where network=? and address=?',(network,address)):
        plan=json.loads(row['plan_json'])
        for stage in ('comparison','final'):
            if plan[stage]['start_ms']<=as_of_ms and not window_released(store,row['plan_id'],stage,as_of_ms):return False
    return True


def authorized_period(store:Store,period:dict[str,Any],as_of_ms:int,*,end_inclusive=False) -> bool:
    if not 0<=period['start_ms']<period['end_ms']<=as_of_ms:return False
    for row in store.connection.execute('select plan_id,plan_json from validation_plans where network=? and address=? and (?=\'*\' or coin=?)',(period['network'],period['address'],period['market'],period['market'])):
        plan=json.loads(row['plan_json'])
        for stage in ('comparison','final'):
            window=plan[stage]
            before=(period['end_ms']<window['start_ms'] if end_inclusive else period['end_ms']<=window['start_ms'])
            if period['start_ms']>=window['end_ms'] or before:continue
            if not window_released(store,row['plan_id'],stage,as_of_ms):return False
    return True

def save_knowledge(store:Store,item:dict[str,Any]) -> dict[str,Any]:
    migrate(store);now=clock()
    required={'schema_version','mechanism','origin_accounts','origin_markets','periods','evidence_refs',
              'experiments','success_conditions','failure_conditions','execution_limits','open_questions','related_hypotheses','status'}
    if not isinstance(item,dict) or not required<=item.keys() or item['schema_version']!=1:
        raise ValueError('Structured research-memory contract required')
    if item['status'] not in ('hypothesis','observed_descriptor','rejected_hypothesis','unsupported_mechanism') or not item['mechanism']:
        raise ValueError('Knowledge status does not grant economic validation')
    for key in required-{'schema_version','mechanism','status'}:
        if not isinstance(item[key],list):raise ValueError('Structured list required: '+key)
    if not item['periods'] or not item['evidence_refs']:raise ValueError('Evidence and periods required')
    for period in item['periods']:
        if not isinstance(period,dict) or not {'network','address','market','start_ms','end_ms'}<=period.keys():raise ValueError('Explicit source periods required')
        if not authorized_period(store,period,now):raise ValueError('Knowledge includes an unreleased reserved period')
        if period['address'] not in item['origin_accounts'] or period['market'] not in item['origin_markets']:
            raise ValueError('Source period differs from declared account/market origin')
    for proof in item['evidence_refs']:
        if not isinstance(proof,dict) or not {'kind','id'}<=proof.keys():raise ValueError('Typed evidence references required')
        if proof['kind']=='evaluation':
            row=store.connection.execute('select e.evaluation_id,e.status,p.network,p.address,p.coin,p.plan_json,e.stage from validation_evaluations e join validation_plans p using(plan_id) where evaluation_id=?',(proof['id'],)).fetchone()
            if not row or row['status'] not in ('passed','failed','error'):raise ValueError('Terminal evaluation evidence required')
            window=json.loads(row['plan_json'])[row['stage']]
            period={'network':row['network'],'address':row['address'],'market':row['coin'],**window}
            if period not in item['periods'] or not authorized_period(store,period,now):raise ValueError('Evaluation evidence is not an authorized declared period')
            if store.connection.execute("select 1 from sqlite_master where name='validation_evaluation_source_periods'").fetchone():
                for source in store.connection.execute('select period_json from validation_evaluation_source_periods where evaluation_id=?',(proof['id'],)):
                    inherited=json.loads(source[0])
                    if inherited not in item['periods'] or not authorized_period(store,inherited,now):
                        raise ValueError('Evaluation funding witness source periods must remain authorized and declared')
        elif proof['kind']=='research_evaluation':
            from .research_evaluation import validate_feedback_reference
            validate_feedback_reference(store,proof['id'],item['periods'],now)
        elif proof['kind']=='raw_observation':
            row=store.connection.execute('select network,source,entity_type,entity_id,endpoint,observed_at,window_start_ms,window_end_ms from raw_observations where observation_id=?',(proof['id'],)).fetchone()
            if not row or row['source']!='hyperliquid-population-rest-v1' or row['entity_type']!='account':
                raise ValueError('Only explicit population account observations admitted here')
            available=int(datetime.fromisoformat(row['observed_at']).timestamp()*1000)
            if available>now:raise ValueError('Evidence is not yet available')
            start=row['window_start_ms'] if row['window_start_ms'] is not None else available
            end=row['window_end_ms'] if row['window_end_ms'] is not None else available
            if not any(p['network']==row['network'] and p['address']==row['entity_id'] and p['market']=='*' and p['start_ms']<=start and end<=p['end_ms'] for p in item['periods']):
                raise ValueError('Raw source bounds must be contained in declared periods')
        elif proof['kind']=='population_research':
            row=store.connection.execute('select network,address,status,updated_ms,packet_json,result_json from population_research_jobs where request_id=?',(proof['id'],)).fetchone()
            if not row or row['status']!='hypothesis_recorded' or row['updated_ms']>now:
                raise ValueError('Available reviewed population hypothesis required')
            result=json.loads(row['result_json'])
            if (result.get('promotion_authorized') is not False or
                result.get('profitability_proven') is not False or
                result.get('critique',{}).get('decision')!='consistent'):
                raise ValueError('Population evidence must retain reviewed hypothesis status')
            packet=json.loads(row['packet_json'])
            for entry in packet.get('research_memory',[]):
                inherited=store.connection.execute('select item_json,created_ms from research_knowledge where knowledge_id=?',(entry['knowledge_id'],)).fetchone()
                if (not inherited or inherited['created_ms']>packet['available_ms'] or
                    json.loads(inherited['item_json'])['periods']!=entry['item']['periods'] or
                    {'kind':'knowledge','id':entry['knowledge_id']} not in item['evidence_refs']):
                    raise ValueError('Population inherited knowledge proof must remain available and explicit')
            for entry in packet.get('research_evaluation_memory',[]):
                from .research_evaluation import validate_feedback_reference
                registered=validate_feedback_reference(store,entry['event_id'],entry['periods'],packet['available_ms'])
                if (registered!=entry or any(p not in item['periods'] for p in registered['periods']) or
                    {'kind':'research_evaluation','id':entry['event_id']} not in item['evidence_refs']):
                    raise ValueError('Population evaluation feedback proof and complete periods must remain explicit')
            inherited_periods=[p for entry in packet.get('research_memory',[]) for p in entry['item']['periods']]
            inherited_periods+=packet.get('funding_witness_source_periods',[])
            if any(p not in item['periods'] for p in inherited_periods):
                raise ValueError('Population packet inherited periods must remain explicit')
            # Conservative union: descriptors can refer to older inventory/history.
            # Never narrow the declared period to just a favorable episode.
            if not any(p['network']==row['network'] and p['address']==row['address'] and
                       p['market']=='*' and p['start_ms']==0 and
                       p['end_ms']>=packet['available_ms']+1 for p in item['periods']):
                raise ValueError('Whole population packet source period must remain explicit')
        elif proof['kind']=='population_resolution':
            from .population_memory import resolution_snapshot
            request_id, digest=proof['id'].rsplit(':',1)
            row=store.connection.execute('select result_json from population_research_jobs where request_id=?',(request_id,)).fetchone()
            snapshot=resolution_snapshot(store,request_id,json.loads(row[0])) if row else None
            if (not snapshot or snapshot['fingerprint']!=digest or
                    item.get('resolution_synthesis_v1')!=snapshot['synthesis'] or
                    any(p not in item['periods'] for p in snapshot['periods'])):
                raise ValueError('Current verified resolution and explicit periods required')
        elif proof['kind']=='paper_research':
            row=store.connection.execute('select network,address,status,updated_ms,packet_json,result_json from paper_research_jobs where request_id=?',(proof['id'],)).fetchone()
            if not row or row['status']!='hypothesis_recorded' or row['updated_ms']>now:
                raise ValueError('Available reviewed paper hypothesis required')
            packet=json.loads(row['packet_json']);result=json.loads(row['result_json'])
            if result.get('promotion_authorized') is not False or result.get('profitability_proven') is not False or result.get('critique',{}).get('decision')!='consistent':
                raise ValueError('Paper research evidence cannot certify profitability')
            if not packet.get('source_periods') or any(p not in item['periods'] or not authorized_period(store,p,now,end_inclusive=True) for p in packet['source_periods']):
                raise ValueError('Paper source periods must remain explicit and authorized')
            if row['address'] not in item['origin_accounts'] or packet['address']!=row['address'] or packet['network']!=row['network']:
                raise ValueError('Paper source origin mismatch')
        elif proof['kind']=='knowledge':
            row=store.connection.execute('select item_json,created_ms from research_knowledge where knowledge_id=?',(proof['id'],)).fetchone()
            if not row or row['created_ms']>now:raise ValueError('Unknown or unavailable related knowledge')
            if any(p not in item['periods'] for p in json.loads(row[0])['periods']):raise ValueError('Inherited periods must remain explicit')
        else:raise ValueError('Unsupported evidence kind; arbitrary file paths cannot grant access')
    if len(canonical(item))>24000:raise ValueError('Research memory item exceeds bounded size')
    identity=fingerprint(item)
    store.connection.execute('insert or ignore into research_knowledge values (?,?,?)',(identity,now,canonical(item)));store.connection.commit()
    return {'knowledge_id':identity,'economic_validation':False,'created_ms':store.connection.execute('select created_ms from research_knowledge where knowledge_id=?',(identity,)).fetchone()[0]}

def export_knowledge(store:Store, *,as_of_ms:int,network:str,address:str,market:str,max_chars:int=12000) -> list[dict[str,Any]]:
    migrate(store)
    if type(as_of_ms) is not int or as_of_ms>clock() or type(max_chars) is not int or not 1<=max_chars<=24000:
        raise ValueError('Available cutoff and bounded export required')
    output=[]
    rows=store.connection.execute('select * from research_knowledge where created_ms<=? order by created_ms desc,rowid desc',(as_of_ms,)).fetchall()
    eligible_rows=[row for row in rows if all(authorized_period(store,p,as_of_ms) for p in json.loads(row['item_json'])['periods'])]
    superseded={json.loads(row['item_json']).get('memory_revision_v1',{}).get('supersedes') for row in eligible_rows}
    seen_revisions=set()
    for row in rows:
        if row['knowledge_id'] in superseded:continue
        item=json.loads(row['item_json'])
        if address not in item['origin_accounts'] or market not in item['origin_markets'] and '*' not in item['origin_markets']:continue
        if not all(authorized_period(store,p,as_of_ms) for p in item['periods']):continue
        if not any(p['network']==network for p in item['periods']):continue
        revision=item.get('memory_revision_v1',{}).get('request_id')
        if revision in seen_revisions:continue
        if revision:seen_revisions.add(revision)
        entry={'knowledge_id':row['knowledge_id'],'created_ms':row['created_ms'],'item':item,
               'period_status':'development knowledge; evaluated source periods never become virgin again'}
        if len(canonical(output+[entry]))>max_chars:continue
        output.append(entry)
    return output


def period_release_evidence(store,period,as_of_ms,*,end_inclusive=False):
    """Metadata of the earliest available access grant for each intersected window."""
    output=[]
    for row in store.connection.execute('select plan_id,plan_json from validation_plans where network=? and address=? and (?=\'*\' or coin=?)',
            (period['network'],period['address'],period['market'],period['market'])):
        plan=json.loads(row['plan_json'])
        for stage in ('comparison','final'):
            w=plan[stage]
            before=period['end_ms']<w['start_ms'] if end_inclusive else period['end_ms']<=w['start_ms']
            if period['start_ms']>=w['end_ms'] or before:continue
            candidates=[]
            if store.connection.execute("select 1 from sqlite_master where name='research_period_releases'").fetchone():
                candidates.extend((r[1],'research_period_releases:'+r[0]) for r in store.connection.execute(
                    'select r.evaluation_id,r.released_ms from research_period_releases r join validation_evaluations e using(evaluation_id) '
                    'where e.plan_id=? and e.stage=? and r.released_ms<=?',(row['plan_id'],stage,as_of_ms)))
            if store.connection.execute("select 1 from sqlite_master where name='research_window_releases'").fetchone():
                candidates.extend((r[0],'research_window_releases:'+row['plan_id']+':'+stage) for r in store.connection.execute(
                    'select released_ms from research_window_releases where plan_id=? and stage=? and released_ms<=?',(row['plan_id'],stage,as_of_ms)))
            if not candidates:raise ValueError('Source window has no available access grant')
            stamp,ref=min(candidates)
            output.append({'plan_id':row['plan_id'],'stage':stage,'available_ms':stamp,'evidence_ref':ref})
    return sorted(output,key=lambda x:(x['plan_id'],x['stage']))
