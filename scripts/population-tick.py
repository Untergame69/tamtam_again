#!/usr/bin/env python3
"""Bounded public REST population tick with a quota shared with collectors."""
import argparse,json,time
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.population import enroll,claim,collect_overview,finish
from tamtam_again.providers.hyperliquid import HyperliquidInfo
from tamtam_again.collateral import refresh_catalog
p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--policy',type=Path,required=True);p.add_argument('--output',type=Path);p.add_argument('--enroll-only',action='store_true');p.add_argument('--needs-policy',type=Path);a=p.parse_args()
needs_policy=json.loads(a.needs_policy.read_text()) if a.needs_policy else None
if needs_policy is not None:
 from tamtam_again.research_need_collection import validate_policy
 validate_policy(needs_policy)
policy=json.loads(a.policy.read_text());network='hyperliquid-mainnet';results=[]
HyperliquidInfo.telemetry_path=a.db.with_suffix('.telemetry.sqlite3')
with Store(a.db) as s:
 enrollment=enroll(s,network,policy)
 if not a.enroll_only:
  metadata_client=HyperliquidInfo(network)
  refresh_catalog(s,metadata_client,max_age_seconds=policy.get('metadata_refresh_seconds',3600))
  for _ in range(policy['max_jobs_per_tick']):
   job=claim(s,network)
   if not job:break
   client=HyperliquidInfo(network);client.task='population-rest-overview'
   try:
    need_report=None
    if needs_policy is not None:
     from tamtam_again.research_need_collection import tick_for_job
     need_report=tick_for_job(s,client,job,needs_policy)
    report=collect_overview(s,client,job);results.append({'address':job['address'],'status':'complete','observation_acquisitions':need_report,'mode':report['mode'],'perp_dexes_observed':report['perp_dexes_observed'],'markets':report['markets'],'poll_interval_seconds':report['poll_interval_seconds'],'performance_status':report['performance_status']})
   except Exception as exc:
    result={'error_type':type(exc).__name__,'condition':'public REST collection failed; retain observations and retry with new attempt'}
    finish(s,job,result,policy['retry_seconds'],status='failed');results.append({'address':job['address'],'status':'failed',**result})
 output={'at_ms':int(time.time()*1000),'enrollment':enrollment,'results':results,'live_user_slots_changed':False}
 if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(output,indent=2)+'\n')
 print(json.dumps(output))
