#!/usr/bin/env python3
"""Measure reserved collection budget; scenario values remain assumptions."""
import argparse,json,time,sqlite3
from pathlib import Path
from tamtam_again.telemetry import Telemetry
p=argparse.ArgumentParser();p.add_argument('--telemetry',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--minutes',type=int,default=30);a=p.parse_args()
now=time.time();t=Telemetry(a.telemetry)
with t.connect() as c:
 first=c.execute('select min(started_at) from collection_attempts').fetchone()[0]
 if first is None:raise SystemExit('No measured attempts yet')
 since=max(first,now-a.minutes*60)
 report=t.report(since,now=now)
 c.row_factory=sqlite3.Row
 buckets=[dict(r) for r in c.execute('select cast(started_at/60 as int) minute,sum(reserved_weight) weight,count(*) attempts from collection_attempts where started_at>=? group by minute',(since,))]
 ws=[{'recorded_at':r['recorded_at'],**json.loads(r['metrics_json'])} for r in c.execute("select recorded_at,metrics_json from collector_measurements where collector='websocket' and recorded_at>=?",(since,))]
 duration=sum(x['window_seconds'] for x in ws)
 ws_report={'windows':len(ws),'observed_window_seconds':duration,'frames_per_second':sum(x['frames'] for x in ws)/duration if duration else None,'bytes_per_second':sum(x['bytes'] for x in ws)/duration if duration else None,'max_flush_lag_seconds':max((x['max_flush_lag_seconds'] for x in ws),default=None),'queue_peak_messages':max((x['queue_peak_messages'] for x in ws),default=None),'latest_counts':{k:ws[-1][k] for k in ('connections','user_addresses','subscriptions_sent','acknowledged_bbo')} if ws else None}
 rate=report['reserved_weight_per_minute'];headroom=max(0,900-rate)
 scenarios=[]
 # Only incremental fill requests, not whole-account qualification/backfill.
 for minutes in (5,15,60,360):
  scenarios.append({'fill_poll_minutes':minutes,'reserved_weight_per_poll':120,'marginal_accounts_upper_bound':int(headroom*minutes/120),'scope':'fill polls only; account snapshots, scopes, funding, backfill and compute costs excluded; not a sustainable population claim'})
 report.update({'sampling_warning':'Startup and backfill are mixed with incremental tasks; observe complete cadence cycles and classify workload before deployment decisions','official_ip_budget_per_minute':1200,'local_budget_per_minute':900,'margin_to_official':300,'completed_minute_buckets':buckets,'websocket':ws_report,'scenario_assumptions':scenarios,'measured_local_headroom':headroom,'confidence':'initial measurement only' if now-first<1800 else 'window observation; workload completeness must be reviewed'})
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+'\n');print('Capacity report:',a.output,'minutes',round(report['window_minutes'],2),'reserved_weight/min',round(rate,1))
