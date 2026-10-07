"""Independent REST population scheduling, preserving direct slots and pilots."""
from __future__ import annotations
import hashlib
import json
import time
from uuid import uuid4
from typing import Any
from .storage import Store,utc_now
from .discovery import protected_addresses
from .providers.hyperliquid import HyperliquidInfo

SCHEMA='''
CREATE TABLE IF NOT EXISTS population_accounts (
 network TEXT NOT NULL,address TEXT NOT NULL,policy_json TEXT NOT NULL,
 status TEXT NOT NULL,interval_seconds INTEGER NOT NULL,next_due_ms INTEGER NOT NULL,
 lease_token TEXT,lease_until_ms INTEGER,last_success_ms INTEGER,
 PRIMARY KEY(network,address));
CREATE TABLE IF NOT EXISTS population_attempts (
 attempt_id TEXT PRIMARY KEY,network TEXT NOT NULL,address TEXT NOT NULL,
 lease_token TEXT NOT NULL,started_ms INTEGER NOT NULL,completed_ms INTEGER,
 status TEXT NOT NULL,result_json TEXT);
CREATE TABLE IF NOT EXISTS population_state_corrections (
 correction_id INTEGER PRIMARY KEY,created_at TEXT NOT NULL,address TEXT NOT NULL,
 old_cursor_ms INTEGER,new_cursor_ms INTEGER,reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS account_scope_reports (
 report_id TEXT PRIMARY KEY,network TEXT NOT NULL,address TEXT NOT NULL,
 available_ms INTEGER NOT NULL,payload_json TEXT NOT NULL);
'''
def migrate(store: Store):store.connection.executescript(SCHEMA)
def policy_validate(policy: dict[str,Any]):
    for k in ('max_rest_accounts','max_jobs_per_tick','default_poll_seconds','min_poll_seconds','max_poll_seconds','lease_seconds','retry_seconds','initial_lookback_seconds','retention_fills'):
        if type(policy.get(k)) is not int or policy[k]<1:raise ValueError('Invalid population budget: '+k)
    if not policy['min_poll_seconds']<=policy['default_poll_seconds']<=policy['max_poll_seconds']:raise ValueError('Invalid population intervals')
    if not 0<policy.get('retention_fraction',0)<1:raise ValueError('Invalid retention headroom')
    if not policy.get('version') or not policy.get('sampling_seed'):raise ValueError('Policy identity required')
def enroll(store: Store,network: str,policy: dict[str,Any], *,now_ms: int | None=None):
    policy_validate(policy);migrate(store);now_ms=now_ms if now_ms is not None else int(time.time()*1000)
    blocked=protected_addresses(store)
    eligible=[r for r in store.candidates(network) if r['status']!='tracked' and r['address'].lower() not in blocked]
    ordered=sorted(eligible,key=lambda r:hashlib.sha256((policy['sampling_seed']+r['address']).encode()).hexdigest())
    count=store.connection.execute("select count(*) from population_accounts where network=? and status!='retired'",(network,)).fetchone()[0]
    added=[]
    for row in ordered:
        if count>=policy['max_rest_accounts']:break
        cursor=store.connection.execute('insert or ignore into population_accounts values (?,?,?,?,?,?,NULL,NULL,NULL)',(network,row['address'],json.dumps(policy,sort_keys=True),'scheduled',policy['default_poll_seconds'],now_ms))
        if cursor.rowcount:count+=1;added.append(row['address'])
    store.connection.commit();return {'enrolled':added,'rest_accounts':count,'direct_slots_changed':False}
def claim(store: Store,network: str, *,now_ms: int | None=None):
    migrate(store);now_ms=now_ms if now_ms is not None else int(time.time()*1000)
    blocked=protected_addresses(store)
    store.connection.execute('begin immediate')
    try:
        # An interrupted attempt remains an immutable failed attempt; next collection
        # gets a fresh lease and records a distinct retry, never a synthetic success.
        expired=store.connection.execute("select network,address,lease_token from population_accounts where status='running' and lease_until_ms<=?",(now_ms,)).fetchall()
        for r in expired:
            store.connection.execute("update population_attempts set status='interrupted',completed_ms=? where lease_token=? and status='running'",(now_ms,r['lease_token']))
            store.connection.execute("update population_accounts set status='scheduled',lease_token=NULL,lease_until_ms=NULL where network=? and address=?",(r['network'],r['address']))
        rows=store.connection.execute("select * from population_accounts where network=? and status='scheduled' and next_due_ms<=? order by next_due_ms,address",(network,now_ms)).fetchall()
        for r in rows:
            if r['address'] in blocked:continue
            p=json.loads(r['policy_json']);token=uuid4().hex;attempt=uuid4().hex
            store.connection.execute("update population_accounts set status='running',lease_token=?,lease_until_ms=? where network=? and address=?",(token,now_ms+p['lease_seconds']*1000,network,r['address']))
            store.connection.execute('insert into population_attempts values (?,?,?,?,?,NULL,?,NULL)',(attempt,network,r['address'],token,now_ms,'running'))
            store.connection.commit();return {**dict(r),'lease_token':token,'attempt_id':attempt,'policy':p}
        store.connection.commit();return None
    except BaseException:store.connection.rollback();raise

def cadence(policy:dict[str,Any],fills: list[dict[str,Any]],start_ms:int,end_ms:int):
    unique={(f.get('coin'),f.get('time'),f.get('tid',f.get('hash'))) for f in fills if isinstance(f,dict) and start_ms<=int(f.get('time',-1))<=end_ms}
    seconds=max((end_ms-start_ms)/1000,1)
    rate=len(unique)/seconds
    interval=policy['default_poll_seconds'] if not rate else int(policy['retention_fills']*policy['retention_fraction']/rate)
    interval=max(policy['min_poll_seconds'],min(policy['default_poll_seconds'],policy['max_poll_seconds'],interval))
    return interval,{'observed_unique_fills':len(unique),'window_seconds':seconds,'fills_per_second':rate,'risk':'unknown retention/history completeness; rate may be underestimated if API response saturated','needs_faster_than_minimum':bool(rate and policy['retention_fills']*policy['retention_fraction']/rate<policy['min_poll_seconds'])}

def collect_overview(store: Store,client: HyperliquidInfo,job:dict[str,Any], *,now_ms:int|None=None):
    address=job['address'];network=job['network'];policy=job['policy'];now_ms=now_ms if now_ms is not None else int(time.time()*1000)
    if address in protected_addresses(store):raise ValueError('Reserved pilot account excluded from population research')
    start=job['last_success_ms'] if job['last_success_ms'] is not None else max(0,now_ms-policy['initial_lookback_seconds']*1000)
    responses={};proof=[]
    queries=[{'type':'userAbstraction','user':address},{'type':'userRole','user':address},{'type':'subAccounts','user':address},{'type':'spotClearinghouseState','user':address},{'type':'portfolio','user':address},{'type':'perpDexs'}]
    for query in queries:
        receipt=utc_now();value=client.post_info(query);key=query['type'];responses[key]=value
        store.save_observation(network=network,source='hyperliquid-population-rest-v1',entity_type='account' if key!='perpDexs' else 'market',entity_id=address if key!='perpDexs' else 'perpetuals:all',endpoint=key,payload=value,request_payload={**query,'transport':'rest','phase':'scope_inventory'},requested_at=receipt)
        proof.append({'endpoint':key,'request':query,'available_after_request':True})
    dexes=responses['perpDexs']
    if not isinstance(dexes,list):raise ValueError('Invalid public dex inventory')
    states={}
    for dex in dexes:
        name=dex.get('name') if isinstance(dex,dict) else ''
        if name is None:name=''
        query={'type':'clearinghouseState','user':address}
        if name:query['dex']=name
        receipt=utc_now();state=client.post_info(query);states[name]=state
        store.save_observation(network=network,source='hyperliquid-population-rest-v1',entity_type='account',entity_id=address,endpoint='clearinghouseState',payload=state,request_payload={**query,'transport':'rest','phase':'scope_inventory'},requested_at=receipt)
    query={'type':'userFillsByTime','user':address,'startTime':start,'endTime':now_ms};receipt=utc_now();fills=client.post_info(query)
    if not isinstance(fills,list):raise ValueError('Invalid fill response')
    store.save_observation(network=network,source='hyperliquid-population-rest-v1',entity_type='account',entity_id=address,endpoint='userFillsByTime',payload=fills,request_payload={**query,'transport':'rest','coverage_status':'single_page_retention_unknown','phase':'incremental' if job['last_success_ms'] is not None else 'initial_probe'},requested_at=receipt,window_start_ms=start,window_end_ms=now_ms,record_count=len(fills),complete=False)
    interval,activity=cadence(policy,fills,start,now_ms)
    mode=responses['userAbstraction'];markets=set();positions=[]
    for dex,state in states.items():
        if not isinstance(state,dict):continue
        for item in state.get('assetPositions',[]):
            pos=item.get('position',{});coin=pos.get('coin')
            if coin:markets.add(coin);positions.append({'dex':dex,'position':pos})
    markets.update(str(f.get('coin')) for f in fills if isinstance(f,dict) and f.get('coin'))
    available=int(time.time()*1000)
    report={'address':address,'mode':mode,'role':responses['userRole'],'subaccounts':responses['subAccounts'],'perp_dexes_observed':list(states),'spot_observed':isinstance(responses['spotClearinghouseState'],dict),'markets':sorted(markets),'simultaneous_position_snapshot':positions,'activity':activity,'poll_interval_seconds':interval,'fills_requested_start_ms':start,'fills_requested_end_ms':now_ms,'fill_coverage':'unknown: single page, API retention cap, no continuity proof','capital_aggregation':'unknown: do not sum dex equities; account mode and shared collateral need reconciliation','external_hedges':'unknown','performance_status':'not_qualified','reproducibility_status':'unproven','proof_endpoints':proof,'scope':'public inventory only; REST availability is archive insertion, never a live follower signal'}
    finish(store,job,report,interval,now_ms=available)
    return report

def finish(store:Store,job:dict[str,Any],result:dict[str,Any],interval:int, *,now_ms:int|None=None,status:str='complete'):
    now_ms=now_ms if now_ms is not None else int(time.time()*1000)
    store.connection.execute('begin immediate')
    try:
        row=store.connection.execute('select lease_token from population_accounts where network=? and address=?',(job['network'],job['address'])).fetchone()
        if not row or row['lease_token']!=job['lease_token']:raise ValueError('Stale population lease')
        if status=='complete':
            store.connection.execute('insert into account_scope_reports values (?,?,?,?,?)',(uuid4().hex,job['network'],job['address'],now_ms,json.dumps(result,sort_keys=True)))
        store.connection.execute('update population_attempts set status=?,completed_ms=?,result_json=? where attempt_id=? and status=\'running\'',(status,now_ms,json.dumps(result,sort_keys=True),job['attempt_id']))
        store.connection.execute("update population_accounts set status='scheduled',interval_seconds=?,next_due_ms=?,lease_token=NULL,lease_until_ms=NULL,last_success_ms=case when ?='complete' then ? else last_success_ms end where network=? and address=?",(interval,now_ms+interval*1000,status,result.get('fills_requested_end_ms',now_ms),job['network'],job['address']))
        store.connection.commit()
    except BaseException:store.connection.rollback();raise


def inventory(store: Store,network: str) -> dict[str,Any]:
    migrate(store)
    tables={r[0] for r in store.connection.execute("select name from sqlite_master where type='table'")}
    direct=[r['address'] for r in store.candidates(network) if r['status']=='tracked']
    rest=[dict(r) for r in store.connection.execute('select address,status,interval_seconds,next_due_ms,last_success_ms from population_accounts where network=?',(network,))]
    analysis=[dict(r) for r in store.connection.execute('select plan_id,address,coin,synthetic from validation_plans where network=?',(network,))] if 'validation_plans' in tables else []
    paper=[dict(r) for r in store.connection.execute('select session_id,variant_id,address,coin,status from paper_sessions where network=?',(network,))] if 'paper_sessions' in tables else []
    return {'network':network,'discovered_accounts':len(store.candidates(network)),
            'rest_population':rest,'direct_subscription_candidates':direct,
            'direct_subscription_note':'desired cohort, actual subscriptions measured separately by websocket telemetry',
            'analysis_plans':analysis,'paper_sessions':paper,
            'qualification_note':'inventory completion is not an economic validation'}
