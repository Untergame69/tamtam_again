#!/usr/bin/env python3
"""Profile population source only; reserved accounts refused before raw reads."""
import argparse,json,time
from pathlib import Path
from tamtam_again.storage import Store,decode_observation_payload
from tamtam_again.account_adapter import millis
from tamtam_again.behavior import profile_behavior
from tamtam_again.discovery import protected_addresses
p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--start-ms',type=int,required=True);p.add_argument('--end-ms',type=int,required=True);p.add_argument('--grouping-ms',type=int,default=1000);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
asof=int(time.time()*1000);reports=[]
with Store(a.db) as store:
 blocked=protected_addresses(store)
 for address, in store.connection.execute('select distinct address from account_scope_reports order by address'):
  if address.lower() in blocked:raise ValueError('Reserved pilot account excluded from behavior research')
  observations=[]
  for row in store.connection.execute("select * from raw_observations where network='hyperliquid-mainnet' and source='hyperliquid-population-rest-v1' and entity_type='account' and entity_id=? and endpoint='userFillsByTime' order by observation_id",(address,)):
   available=millis(row['observed_at'])
   if available>asof:continue
   payload=decode_observation_payload(row)
   if isinstance(payload,list):observations.extend({'fill':f,'available_ms':available,'evidence_ref':'raw_observations:'+str(row['observation_id'])} for f in payload)
  profile=profile_behavior(observations,start_ms=a.start_ms,end_ms=a.end_ms,as_of_ms=asof,grouping_ms=a.grouping_ms)
  reports.append({'address':address,'profile':profile})
result={'synthetic':False,'economic_validation':False,'as_of_ms':asof,'accounts':reports}
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n')
print('Behavior profiles:',len(reports),'observed fills:',sum(r['profile']['fills_observed'] for r in reports))
