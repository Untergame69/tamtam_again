"""Targeted public order observations, with no retrospective lifecycle completeness claim."""
import time
import hashlib
import json
from collections import Counter
from .discovery import protected_addresses, fingerprint
from .engine import canonical
from .providers.hyperliquid import ADDRESS_RE
from .storage import utc_now


def collect_orders(store,client,network,address,*,dexes):
    address=address.lower()
    if not ADDRESS_RE.fullmatch(address):raise ValueError('Public account address required')
    if address in protected_addresses(store):raise ValueError('Reserved account excluded before order request')
    if not isinstance(dexes,list) or not 1<=len(dexes)<=3 or any(not isinstance(d,str) for d in dexes) or len(set(dexes))!=len(dexes):
        raise ValueError('Explicit one to three distinct DEX scopes required')
    if client.network!=network:raise ValueError('Client network differs from provenance')
    store.connection.execute('create table if not exists population_order_reports '
        '(report_id text primary key,network text not null,address text not null,available_ms integer not null,payload_json text not null)')
    store.connection.commit()
    refs=[];responses={};started_ms=int(time.time()*1000)
    queries=[{'type':'historicalOrders','user':address}]+[
        {'type':'frontendOpenOrders','user':address,'dex':dex} for dex in dexes]
    for query in queries:
        requested=utc_now();rows=client.post_info(query)
        if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):raise ValueError('Expected public order list')
        envelope={'response':rows,'dex_scope':query.get('dex'),'received_ms':int(time.time()*1000)}
        digest=hashlib.sha256(json.dumps(envelope,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        store.save_observation(network=network,source='hyperliquid-population-orders-rest-v1',
            entity_type='account',entity_id=address,endpoint=query['type'],payload=envelope,
            request_payload={**query,'transport':'rest','phase':'targeted_order_inventory'},
            requested_at=requested,record_count=len(rows),complete=False)
        raw=store.connection.execute('select observation_id from raw_observations where network=? and source=? and entity_id=? and endpoint=? and response_sha256=? order by observation_id desc limit 1',
            (network,'hyperliquid-population-orders-rest-v1',address,query['type'],digest)).fetchone()
        refs.append('raw_observations:'+str(raw[0]))
        responses[query['type']+':'+query.get('dex','')]=rows
    historical=responses['historicalOrders:']
    statuses=Counter(str(r.get('status','unknown')) for r in historical)
    timestamps=[r['statusTimestamp'] for r in historical if type(r.get('statusTimestamp')) is int]
    descriptor={'dex_scopes':dexes,'historical_orders_returned':len(historical),
        'historical_status_counts':dict(statuses),'historical_status_time_bounds':
            {'start_ms':min(timestamps),'end_ms':max(timestamps)} if timestamps else None,
        'open_orders_by_dex':{d:len(responses['frontendOpenOrders:'+d]) for d in dexes},
        'content_fingerprint':fingerprint(responses),
        'historical_coverage':'bounded_recent_orders; complete prior history and intermediate amendments unknown',
        'saturated_history':len(historical)>=2000,
        'live_follower_signal':False,'queue_priority':'unknown','private_target':'unknown',
        'order_lifecycle_complete':False}
    available_ms=int(time.time()*1000)
    report={'network':network,'address':address,'started_ms':started_ms,'available_ms':available_ms,
        'descriptor':descriptor,'evidence_refs':refs,'responses':responses,
        'limits':['REST snapshot is not a stream of all submissions, amendments and cancellations',
            'multiple DEX snapshots are sequential, not simultaneous',
            'status timestamps are event times; observations become available only after receipt',
            'an empty response does not establish absence of earlier activity']}
    identity=fingerprint(report)
    store.connection.execute('insert or ignore into population_order_reports values(?,?,?,?,?)',
        (identity,network,address,available_ms,canonical(report)));store.connection.commit()
    return {'report_id':identity,**report}
