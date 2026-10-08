"""Discovery provenance and address-uniform sampling of public participants.

This registry does not qualify profitability or allocate direct user slots.
"""
from __future__ import annotations
from datetime import datetime
import hashlib
import json
from typing import Any
from .providers.hyperliquid import validate_address
from .storage import Store,utc_now

SCHEMA='''
CREATE TABLE IF NOT EXISTS discovery_windows (
 window_id TEXT PRIMARY KEY,network TEXT NOT NULL,source TEXT NOT NULL,
 market TEXT NOT NULL,start_ms INTEGER NOT NULL,end_ms INTEGER NOT NULL,
 available_ms INTEGER NOT NULL,sampling_version TEXT NOT NULL,
 coverage_json TEXT NOT NULL,selected_addresses INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS discovery_provenance (
 network TEXT NOT NULL,address TEXT NOT NULL,window_id TEXT NOT NULL,
 discovered_at TEXT NOT NULL,evidence_json TEXT NOT NULL,
 PRIMARY KEY(network,address,window_id),
 FOREIGN KEY(window_id) REFERENCES discovery_windows(window_id));
CREATE INDEX IF NOT EXISTS idx_discovery_address ON discovery_provenance(network,address);
'''
def migrate(store: Store):
    if not getattr(store,"_discovery_schema_ready",False):
        store.connection.executescript(SCHEMA)
        store._discovery_schema_ready=True
def protected_addresses(store: Store) -> set[str]:
    if not store.connection.execute("select 1 from sqlite_master where name='validation_plans'").fetchone():return set()
    # Compatibility: abbreviated fixture/legacy schemas retain the old guard.
    columns={r[1] for r in store.connection.execute('pragma table_info(validation_plans)')}
    if not {'plan_id','plan_json'}<=columns or not store.connection.execute(
            "select 1 from sqlite_master where name='research_window_releases'").fetchone():
        return {r[0].lower() for r in store.connection.execute('select distinct address from validation_plans where synthetic=0')}
    import time
    clock=int(time.time()*1000);blocked=set()
    for row in store.connection.execute('select plan_id,address,plan_json from validation_plans where synthetic=0'):
        plan=json.loads(row['plan_json'])
        # Legacy pilots remain protected even if another plan on their address closes.
        if not plan.get('population_origin'):
            blocked.add(row['address'].lower());continue
        stages={r[0] for r in store.connection.execute('select stage from research_window_releases '
            'where plan_id=? and released_ms<=?',(row['plan_id'],clock))}
        if stages!={'comparison','final'}:blocked.add(row['address'].lower())
    return blocked
def fingerprint(value: Any):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def record_window(store: Store, *, network: str,source: str,market: str,
                  start_ms: int,end_ms: int,available_ms: int,version: str,
                  coverage: dict[str,Any], evidence: dict[str,dict[str,Any]]) -> dict[str,Any]:
    if not 0<=start_ms<=end_ms<=available_ms:raise ValueError('Discovery window not causally available')
    migrate(store)
    payload={'network':network,'source':source,'market':market,'start_ms':start_ms,'end_ms':end_ms,'available_ms':available_ms,'version':version,'coverage':coverage,'evidence':evidence}
    identity=fingerprint(payload);stamp=utc_now()
    for address in evidence:validate_address(address)
    # An identical ranking/window already has immutable provenance. Avoid a
    # needless write lock on each tick, but repair incomplete provenance rows.
    existing=store.connection.execute('select selected_addresses from discovery_windows where window_id=?',(identity,)).fetchone()
    if existing and existing[0]==len(evidence):
        linked={r[0] for r in store.connection.execute('select address from discovery_provenance where window_id=?',(identity,))}
        if linked=={a.lower() for a in evidence}:
            return {'window_id':identity,'selected':len(evidence),'new_candidates':0,'coverage':coverage}
    store.connection.execute('insert or ignore into discovery_windows values (?,?,?,?,?,?,?,?,?,?)',(identity,network,source,market,start_ms,end_ms,available_ms,version,json.dumps(coverage,sort_keys=True),len(evidence)))
    new=0
    for address,proof in evidence.items():
        validate_address(address)
        cursor=store.connection.execute("insert or ignore into candidates(network,address,discovery_source,label,added_at,status) values (?,?,?,'',?,'candidate')",(network,address.lower(),source,stamp));new+=cursor.rowcount
        store.connection.execute('insert or ignore into discovery_provenance values (?,?,?,?,?)',(network,address.lower(),identity,stamp,json.dumps(proof,sort_keys=True)))
    store.connection.commit()
    return {'window_id':identity,'selected':len(evidence),'new_candidates':new,'coverage':coverage}
def participants(store: Store,network: str,market: str,events: list[tuple[str,dict[str,Any]]], *,limit: int=100,coverage: str='unknown',available_ms: int | None=None) -> list[dict[str,Any]]:
    if limit<1:raise ValueError('Positive discovery budget required')
    blocked=protected_addresses(store)
    buckets: dict[int,dict[str,dict[str,Any]]]={}; bounds:dict[int,list[int]]={};sessions:dict[int,set[str]]={}
    for receipt,message in events:
        available=int(datetime.fromisoformat(receipt).timestamp()*1000)
        bucket=available//60000
        for trade in message.get('data',[]) if isinstance(message.get('data'),list) else []:
            try:
                stamp=int(trade['time'])
                if stamp>available or stamp<0 or trade.get('coin')!=market:continue
            except (KeyError,ValueError,TypeError):continue
            users=trade.get('users')
            if not isinstance(users,list) or len(users)!=2:continue
            bounds.setdefault(bucket,[]).append(available)
            sessions.setdefault(bucket,set()).add(str(message.get('_stream',{}).get('connection_id','unknown')))
            for side,address in zip(('buyer','seller'),users):
                try:validate_address(address)
                except (ValueError,TypeError):continue
                address=address.lower()
                if address in blocked:continue
                candidates=buckets.setdefault(bucket,{})
                # One proof per address: no ranking by volume or fill count.
                candidates.setdefault(address,{'side':side,'event_ms':stamp,'received_ms':available,'trade_id':trade.get('tid')})
    reports=[]
    for bucket,evidence in buckets.items():
        seed=f'{network}:{market}:{bucket}:address-uniform-v1:'
        chosen=sorted(evidence,key=lambda a:hashlib.sha256((seed+a).encode()).hexdigest())[:limit]
        times=bounds[bucket]
        reports.append(record_window(store,network=network,source='hyperliquid-public-trades',market=market,start_ms=min(times),end_ms=max(times),available_ms=max(max(times),available_ms or 0),version='address-uniform-v1',coverage={'status':coverage,'sessions':sorted(sessions[bucket]),'window_bucket_ms':bucket*60000,'observed_unique_eligible':len(evidence),'cap_per_archived_batch':limit,'protected_pilot_accounts_excluded':True,'bias':'market activity and observed partial window; sampling unique addresses, not fills'},evidence={a:evidence[a] for a in chosen}))
    return reports


def leaderboard_provenance(store: Store, network: str, snapshot_id: str,
                           observed_at: str, rankings: list[dict[str,Any]],
                           limit_per_window: int) -> dict[str,Any]:
    """Ranking provenance only: no economic metrics or reserved observations."""
    blocked = protected_addresses(store)
    evidence: dict[str,dict[str,Any]] = {}
    for ranking in rankings:
        address = ranking['address'].lower()
        if address in blocked:
            continue
        proof = evidence.setdefault(address, {'snapshot_id': snapshot_id,
                                              'rankings': []})
        proof['rankings'].append({key: ranking[key]
                                  for key in ('window', 'metric', 'rank')})
    available = int(datetime.fromisoformat(observed_at).timestamp()*1000)
    return record_window(store, network=network,
        source='hyperliquid-official-web-stats:leaderboard', market='*',
        start_ms=available, end_ms=available, available_ms=available,
        version='positive-pnl-volume-ranking-v1',
        coverage={'status': 'ranking_snapshot_only',
                  'limit_per_window_metric': limit_per_window,
                  'protected_pilot_accounts_excluded': True,
                  'bias': 'positive reported PnL/volume and capital; top PnL/ROI; not independent economic qualification'},
        evidence=evidence)
