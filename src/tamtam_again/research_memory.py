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

def authorized_period(store:Store,period:dict[str,Any],as_of_ms:int) -> bool:
    if not 0<=period['start_ms']<period['end_ms']<=as_of_ms:return False
    for row in store.connection.execute('select plan_id,plan_json from validation_plans where network=? and address=? and (?=\'*\' or coin=?)',(period['network'],period['address'],period['market'],period['market'])):
        plan=json.loads(row['plan_json'])
        for stage in ('comparison','final'):
            window=plan[stage]
            if period['start_ms']>=window['end_ms'] or period['end_ms']<=window['start_ms']:continue
            released=store.connection.execute('select 1 from research_period_releases r join validation_evaluations e using(evaluation_id) where e.plan_id=? and e.stage=? and r.released_ms<=?',(row['plan_id'],stage,as_of_ms)).fetchone()
            if not released:return False
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
            # Conservative union: descriptors can refer to older inventory/history.
            # Never narrow the declared period to just a favorable episode.
            if not any(p['network']==row['network'] and p['address']==row['address'] and
                       p['market']=='*' and p['start_ms']==0 and
                       p['end_ms']>=packet['available_ms']+1 for p in item['periods']):
                raise ValueError('Whole population packet source period must remain explicit')
        elif proof['kind']=='knowledge':
            row=store.connection.execute('select item_json from research_knowledge where knowledge_id=?',(proof['id'],)).fetchone()
            if not row:raise ValueError('Unknown related knowledge')
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
    for row in store.connection.execute('select * from research_knowledge where created_ms<=? order by created_ms,knowledge_id',(as_of_ms,)):
        item=json.loads(row['item_json'])
        if address not in item['origin_accounts'] or market not in item['origin_markets'] and '*' not in item['origin_markets']:continue
        if not all(authorized_period(store,p,as_of_ms) for p in item['periods']):continue
        if not any(p['network']==network for p in item['periods']):continue
        entry={'knowledge_id':row['knowledge_id'],'created_ms':row['created_ms'],'item':item,
               'period_status':'development knowledge; evaluated source periods never become virgin again'}
        if len(canonical(output+[entry]))>max_chars:break
        output.append(entry)
    return output
