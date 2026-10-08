#!/usr/bin/env python3
"""Read-only prolonged REST/WS and scheduler control, without account payloads."""
import argparse,json,sqlite3,time
from pathlib import Path
from tamtam_again.capacity_windows import summarize_windows
p=argparse.ArgumentParser()
p.add_argument('--telemetry',type=Path,required=True)
p.add_argument('--db',type=Path,required=True)
p.add_argument('--hours',type=int,default=24)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
if not 1<=a.hours<=168:raise SystemExit('Hours must be 1..168')
now=time.time()
def connect(path):
 c=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
 c.row_factory=sqlite3.Row;c.execute('pragma query_only=on');return c
with connect(a.telemetry) as c:
 first=c.execute('select min(started_at) from collection_attempts').fetchone()[0]
 if first is None:raise SystemExit('No instrumented REST requests')
 since=max(first,now-a.hours*3600)
 rows=[dict(r) for r in c.execute('select started_at,task,reserved_weight,http_status,wait_seconds,response_bytes from collection_attempts where started_at>=? and started_at<?',(since,now))]
 windows=summarize_windows(rows,since=since,until=now)
 ws=[json.loads(r[0]) for r in c.execute("select metrics_json from collector_measurements where collector='websocket' and recorded_at>=? and recorded_at<?",(since,now))]
 resources=[json.loads(r[0]) for r in c.execute("select metrics_json from collector_measurements where collector='resources' and recorded_at>=? and recorded_at<? order by recorded_at",(since,now))]
with connect(a.db) as c:
 # This query reads job metadata only, including failures. No report_json/raw data.
 jobs=[dict(r) for r in c.execute('select status,started_ms,completed_ms from population_attempts where started_ms>=? and started_ms<?',(int(since*1000),int(now*1000)))]
 due=[dict(r) for r in c.execute("select status,interval_seconds,next_due_ms,last_success_ms from population_accounts where status!='retired'")]
 statuses={s:sum(j['status']==s for j in jobs) for s in sorted({j['status'] for j in jobs})}
 durations=sorted((j['completed_ms']-j['started_ms'])/1000 for j in jobs if j['completed_ms'] is not None)
 lateness=[max(0,(now*1000-r['next_due_ms'])/1000) for r in due if r['status']!='running']
 from tamtam_again.resources import resource_change
 resource_delta=resource_change(resources[0],resources[-1]) if len(resources)>1 else None
out={'version':'sustained-capacity-control-v1','since':since,'until':now,
 'observed_hours':(now-since)/3600,'requested_hours':a.hours,'rest_windows':windows,
 'population_jobs':{'attempts':len(jobs),'statuses':statuses,
  'maximum_completed_job_seconds':max(durations) if durations else None,
  'active_slots':len(due),'running_slots':sum(r['status']=='running' for r in due),
  'overdue_nonrunning_slots':sum(x>0 for x in lateness),
  'maximum_nonrunning_due_lateness_seconds':max(lateness) if lateness else None,
  'poll_intervals_seconds':sorted({r['interval_seconds'] for r in due})},
 'websocket':{'measurement_windows':len(ws),
  'observed_seconds':sum(r['window_seconds'] for r in ws),
  'max_flush_lag_seconds':max((r['max_flush_lag_seconds'] for r in ws),default=None),
  'queue_peak_messages':max((r['queue_peak_messages'] for r in ws),default=None)},
 'resource_measurements':len(resources),'resource_change':resource_delta,
 'provider_calls':0,'archive_payloads_read':False,'services_changed':False,
 'limits':['job duration includes queue waits and processing; not isolated CPU cost',
  'scheduler lateness is a current snapshot, not historical SLA',
  'resource samples may omit child processes; no IA CPU allocation inferred',
  'window may not cover a full allocation epoch or incident recovery',
  'no claim that unknown history coverage or economic qualification became valid']}
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({k:out[k] for k in ('observed_hours','population_jobs','resource_measurements')}))
