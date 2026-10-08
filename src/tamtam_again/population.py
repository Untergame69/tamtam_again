"""Independent REST population scheduling, preserving direct slots and pilots."""
from __future__ import annotations
import hashlib
import json
import time
from uuid import uuid4
from typing import Any
from .storage import Store,utc_now
from .discovery import protected_addresses, fingerprint
from .providers.hyperliquid import HyperliquidInfo
from .population_history import collect_history, ENDPOINTS
from .behavior import profile_behavior
from .market_rules import mechanism_profile

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
    pages=policy.get('history_max_pages_per_endpoint',3)
    if type(pages) is not int or not 1<=pages<=6:raise ValueError('Invalid history page budget')
    age=policy.get('metadata_refresh_seconds',3600)
    if type(age) is not int or age<60:raise ValueError('Invalid metadata refresh cadence')
def enroll(store: Store,network: str,policy: dict[str,Any], *,now_ms: int | None=None):
    policy_validate(policy);migrate(store);now_ms=now_ms if now_ms is not None else int(time.time()*1000)
    if 'allocation' in policy:
        from .allocation import allocate_population
        return allocate_population(store,network,policy,now_ms=now_ms)
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
            allocation=None
            if p.get('allocation'):
                cohort=store.connection.execute('select cohort_id,snapshot_json from population_cohorts where network=? and epoch=? and policy_json=?',(network,now_ms//p['allocation']['epoch_ms'],json.dumps(p['allocation'],sort_keys=True,separators=(',',':')))).fetchone()
                if cohort:
                    group=next((g for g,members in json.loads(cohort['snapshot_json'])['groups'].items() if r['address'] in members),None)
                    allocation={'cohort_id':cohort['cohort_id'],'group':group}
            store.connection.commit();return {**dict(r),'lease_token':token,'attempt_id':attempt,'policy':p,'allocation':allocation}
        store.connection.commit();return None
    except BaseException:store.connection.rollback();raise

def cadence(policy:dict[str,Any],fills: list[dict[str,Any]],start_ms:int,end_ms:int):
    unique={(f.get('coin'),f.get('time'),f.get('tid',f.get('hash'))) for f in fills if isinstance(f,dict) and start_ms<=int(f.get('time',-1))<=end_ms}
    # Preserve content changes (including corrections), ignoring page order and repeats.
    content=sorted({json.dumps(f,sort_keys=True,separators=(',',':')) for f in fills
                    if isinstance(f,dict) and start_ms<=int(f.get('time',-1))<=end_ms})
    seconds=max((end_ms-start_ms)/1000,1)
    rate=len(unique)/seconds
    interval=policy['default_poll_seconds'] if not rate else int(policy['retention_fills']*policy['retention_fraction']/rate)
    interval=max(policy['min_poll_seconds'],min(policy['default_poll_seconds'],policy['max_poll_seconds'],interval))
    return interval,{'observed_unique_fills':len(unique),'observed_fill_content_fingerprint':fingerprint(content),'window_seconds':seconds,'fills_per_second':rate,'risk':'unknown retention/history completeness; rate may be underestimated if API response saturated','needs_faster_than_minimum':bool(rate and policy['retention_fills']*policy['retention_fraction']/rate<policy['min_poll_seconds'])}

def collect_overview(store: Store,client: HyperliquidInfo,job:dict[str,Any], *,now_ms:int|None=None):
    fixed_clock=now_ms is not None
    address=job['address'];network=job['network'];policy=job['policy'];now_ms=now_ms if now_ms is not None else int(time.time()*1000)
    if address in protected_addresses(store):raise ValueError('Reserved pilot account excluded from population research')
    responses={};proof=[]
    queries=[{'type':'userAbstraction','user':address},{'type':'userRole','user':address},{'type':'subAccounts','user':address},{'type':'spotClearinghouseState','user':address},{'type':'portfolio','user':address},{'type':'perpDexs'}]
    for query in queries:
        receipt=utc_now();value=client.post_info(query);key=query['type'];responses[key]=value
        store.save_observation(network=network,source='hyperliquid-population-rest-v1',entity_type='account' if key!='perpDexs' else 'market',entity_id=address if key!='perpDexs' else 'perpetuals:all',endpoint=key,payload=value,request_payload={**query,'transport':'rest','phase':'scope_inventory','acquisition_id':job['attempt_id']},requested_at=receipt)
        proof.append({'endpoint':key,'request':query,'available_after_request':True})
    dexes=responses['perpDexs']
    if not isinstance(dexes,list):raise ValueError('Invalid public dex inventory')
    inventory_request={'type':'perpDexs','transport':'rest','phase':'scope_inventory',
                       'acquisition_id':job['attempt_id']}
    inventory_row=store.connection.execute('select observation_id from raw_observations '
        "where network=? and source=? and entity_type='market' and entity_id='perpetuals:all' and endpoint=? and request_json=? order by observation_id desc limit 1",
        (network,'hyperliquid-population-rest-v1','perpDexs',json.dumps(inventory_request,ensure_ascii=False,sort_keys=True,separators=(',',':')))).fetchone()
    inventory_ref='raw_observations:'+str(inventory_row[0]) if inventory_row else None
    expected_dexes=[(dex.get('name') or '') if isinstance(dex,dict) else '' for dex in dexes]
    if len(set(expected_dexes))!=len(expected_dexes):raise ValueError('Duplicate dex inventory')
    if any(d is not None and (not isinstance(d,dict) or not isinstance(d.get('name'),str)) for d in dexes):raise ValueError('Malformed dex inventory')
    states={}
    for dex in dexes:
        name=dex.get('name') if isinstance(dex,dict) else ''
        if name is None:name=''
        query={'type':'clearinghouseState','user':address}
        if name:query['dex']=name
        receipt=utc_now();state=client.post_info(query);states[name]=state
        store.save_observation(network=network,source='hyperliquid-population-rest-v1',entity_type='account',entity_id=address,endpoint='clearinghouseState',payload=state,request_payload={**query,'transport':'rest','phase':'scope_inventory','acquisition_id':job['attempt_id'],'expected_dexes':expected_dexes,'inventory_evidence_ref':inventory_ref},requested_at=receipt)
    # Inventory calls may wait behind the shared quota. Bound history after
    # their completion, so a completed page can include those valuations.
    # Using job-start time leaves a systematic unqueried tail at every pass.
    history_end_ms=now_ms if fixed_clock else int(time.time()*1000)
    histories={};fills=[]
    for endpoint in ENDPOINTS:
        rows,history=collect_history(store,client,job,endpoint,history_end_ms)
        histories[endpoint]=history
        if endpoint=='userFillsByTime':fills=rows
    fill_history=histories['userFillsByTime']
    start=fill_history['start_ms']
    interval,activity=cadence(policy,fills,start,fill_history['end_ms'])
    if any(h['pagination_status']!='pagination_exhausted' for h in histories.values()):
        interval=min(interval,policy['retry_seconds'])
    mode=responses['userAbstraction'];markets=set();positions=[]
    for dex,state in states.items():
        if not isinstance(state,dict):continue
        for item in state.get('assetPositions',[]):
            pos=item.get('position',{});coin=pos.get('coin')
            if coin:markets.add(coin);positions.append({'dex':dex,'position':pos})
    markets.update(str(f.get('coin')) for f in fills if isinstance(f,dict) and f.get('coin'))
    available=int(time.time()*1000)
    behavior=profile_behavior([{'fill':f,'available_ms':available,'evidence_ref':'population_attempts:'+job['attempt_id']} for f in fills],start_ms=start,end_ms=fill_history['end_ms'],as_of_ms=available) if start<fill_history['end_ms'] else None
    mechanisms=[]
    if store.connection.execute("select 1 from sqlite_master where name='collateral_catalogs' and type='table'").fetchone():
        catalog=store.connection.execute('select payload_json from collateral_catalogs where network=? and available_ms<=? order by available_ms desc limit 1',(network,available)).fetchone()
        if catalog:mechanisms=[mechanism_profile(json.loads(catalog[0]),coin) for coin in sorted(markets)]
    from .spot_inventory import inventory as spot_inventory
    spot_components=spot_inventory(responses['spotClearinghouseState'])
    report={'address':address,'mode':mode,'role':responses['userRole'],'subaccounts':responses['subAccounts'],'perp_dexes_observed':list(states),'spot_observed':isinstance(responses['spotClearinghouseState'],dict),'spot_inventory':spot_components,'markets':sorted(markets),'simultaneous_position_snapshot':positions,'activity':activity,'poll_interval_seconds':interval,'fills_requested_start_ms':start,'fills_requested_end_ms':fill_history['end_ms'],'histories':histories,'current_pass_behavior_profile':behavior,'market_mechanisms':mechanisms,'fill_coverage':'unknown: bounded pagination, API retention cap, no continuity proof','capital_aggregation':'unknown: do not sum dex equities; account mode and shared collateral need reconciliation','external_hedges':'unknown','performance_status':'not_qualified','reproducibility_status':'unproven','proof_endpoints':proof,'scope':'public inventory only; REST availability is archive insertion, never a live follower signal'}
    report['allocation']=job.get('allocation')
    report['acquisition_id']=job['attempt_id']
    report['dex_inventory_evidence_ref']=inventory_ref
    finish(store,job,report,interval,now_ms=available)
    return report

def finish(store:Store,job:dict[str,Any],result:dict[str,Any],interval:int, *,now_ms:int|None=None,status:str='complete'):
    now_ms=now_ms if now_ms is not None else int(time.time()*1000)
    from .adaptation import initialize as initialize_adaptation, observe_population
    initialize_adaptation(store)
    store.connection.commit()
    store.connection.execute('begin immediate')
    try:
        row=store.connection.execute('select lease_token from population_accounts where network=? and address=?',(job['network'],job['address'])).fetchone()
        if not row or row['lease_token']!=job['lease_token']:raise ValueError('Stale population lease')
        if status=='complete':
            store.connection.execute('insert into account_scope_reports values (?,?,?,?,?)',(uuid4().hex,job['network'],job['address'],now_ms,json.dumps(result,sort_keys=True)))
            observe_population(store,job,result,now_ms)
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
