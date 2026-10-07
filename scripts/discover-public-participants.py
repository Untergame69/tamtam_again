#!/usr/bin/env python3
"""Bounded live public discovery probe on explicitly chosen non-pilot markets."""
import argparse,json,time
from pathlib import Path
from uuid import uuid4
from websockets.sync.client import connect
from tamtam_again.storage import Store,utc_now
from tamtam_again.discovery import participants,protected_addresses
from tamtam_again.websocket import WEBSOCKET_URLS
p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--markets',nargs='+',required=True);p.add_argument('--seconds',type=int,default=45);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
if not 1<=a.seconds<=300 or not 1<=len(a.markets)<=10:raise SystemExit('Bounded discovery duration/market budget required')
network='hyperliquid-mainnet';session=uuid4().hex;started=time.time();events={m:[] for m in a.markets};acks=set();bytes_received=0;gaps=[]
with Store(a.db) as s:
 protected={r[0] for r in s.connection.execute('select distinct coin from validation_plans where synthetic=0')}
 if protected.intersection(a.markets):raise SystemExit('Refusing to consume pilot reserved market feeds in discovery probe')
 with connect(WEBSOCKET_URLS[network],ping_interval=None,open_timeout=15,close_timeout=5,max_size=8*1024*1024) as ws:
  for coin in a.markets:ws.send(json.dumps({'method':'subscribe','subscription':{'type':'trades','coin':coin}}))
  while time.time()-started<a.seconds:
   try:raw=ws.recv(timeout=1)
   except TimeoutError:continue
   if not isinstance(raw,str):continue
   bytes_received+=len(raw.encode());message=json.loads(raw)
   if message.get('channel')=='subscriptionResponse':
    sub=message.get('data',{}).get('subscription',{})
    if sub.get('type')=='trades':acks.add(sub.get('coin'))
   if message.get('channel')!='trades':continue
   data=message.get('data');coin=data[0].get('coin') if isinstance(data,list) and data else None
   if coin not in events:continue
   message['_stream']={'connection_id':session};receipt=utc_now();events[coin].append((receipt,message))
  ended=time.time()
 reports=[]
 for coin,batch in events.items():
  if not batch:continue
  s.save_observation(network=network,source='hyperliquid-discovery-probe-v1',entity_type='market',entity_id=coin,endpoint='trades',payload={'events':[{'received_at':r,'message':m} for r,m in batch]},requested_at=batch[0][0],request_payload={'session':session,'coverage':'bounded_probe_no_gap_proof','subscription_ack':coin in acks},record_count=len(batch))
  reports.extend(participants(s,network,coin,batch,limit=100,coverage='bounded_probe_no_gap_proof'))
 summary={'session':session,'started_at':started,'ended_at':ended,'markets':a.markets,'subscriptions_acknowledged':sorted(acks),'frames':{m:len(v) for m,v in events.items()},'bytes_received':bytes_received,'reports':reports,'new_candidates':sum(r['new_candidates'] for r in reports),'protected_pilot_accounts_excluded':True,'live_user_slots_used':0,'scope':'public participants discovered, no profitability claim; at most 100 unique addresses per market per observed batch minute','bias':'five explicitly chosen markets, 45-second activity window; infrequent traders less likely to appear'}
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(summary,indent=2)+'\n');print('Live participant discovery:',summary['new_candidates'],'new candidates; report',a.output)
