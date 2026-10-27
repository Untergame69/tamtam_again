#!/usr/bin/env python3
"""Capture a bounded, read-only production checkpoint; never start inference."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
from types import SimpleNamespace
from tamtam_again.engine import fingerprint
from tamtam_again.research_jobs import request_count
from tamtam_again.population_runtime import _run

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--db',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
if a.output.resolve()==a.db.resolve():raise ValueError('Evidence cannot overwrite the database')
c=sqlite3.connect(a.db.resolve().as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
store=SimpleNamespace(connection=c,path=a.db)
root=Path(__file__).resolve().parents[1]
policy=json.loads((root/'config/continuous-research-policy.json').read_text())
bound=c.execute('select policy_fingerprint from continuous_research_allowances where policy_id=?',(policy['policy_id'],)).fetchone()
assert bound and bound[0]==fingerprint(policy),'Running allowance differs from versioned policy'
tasks=[]
calls_before=c.execute('select count(*) from continuous_research_calls').fetchone()[0]
for row in c.execute('select t.request_id,t.candidate,t.state,j.status,j.packet_json from continuous_research_tasks t '
        'join population_research_jobs j using(request_id) order by t.authorized_ms limit 16').fetchall():
    assert row['status'] not in {'sealed','running'},'Checkpoint requires completed observed provider work'
    packet=json.loads(row['packet_json'])
    assert packet['fingerprint']==fingerprint({k:v for k,v in packet.items() if k!='fingerprint'})
    # The database is read-only: any unexpected dispatch path fails before a
    # provider could be reached. Terminal replay returns without any mutation.
    replay=_run(store,row['request_id'])
    assert replay['status']=='unchanged_no_inference'
    event=c.execute('select event_json from research_evaluation_events where request_id=? '
        'order by created_ms desc,event_id desc limit 1',(row['request_id'],)).fetchone()
    event=json.loads(event[0]) if event else {}
    tasks.append({'request_id':row['request_id'],'candidate':row['candidate'],
        'provider_state':row['status'],'operational_state':event.get('state'),
        'next_plan':event.get('next_plan'),'packet_fingerprint_valid':True,'replay':replay['status']})
assert calls_before==c.execute('select count(*) from continuous_research_calls').fetchone()[0]
units={}
for name in ('tamtam-again-population-research.timer','tamtam-again-population-research.service',
             'tamtam-again-population.timer','tamtam-again-paper.timer'):
    raw=subprocess.check_output(['systemctl','--user','show',name,'-p','ActiveState','-p','SubState',
        '-p','Result','-p','ExecMainStatus','-p','UnitFileState','-p','NextElapseUSecRealtime'],text=True)
    units[name]=dict(line.split('=',1) for line in raw.splitlines() if '=' in line)
installed=Path('/home/Untergame/.config/systemd/user/tamtam-again-population-research.service')
assert installed.read_bytes()==(root/'systemd/user/tamtam-again-population-research.service').read_bytes()
assert units['tamtam-again-population-research.timer']['ActiveState']=='active'
assert units['tamtam-again-population-research.service'].get('Result')=='success'
proof={'version':'continuous-research-production-proof-v1','code_commit':subprocess.check_output(
    ['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'policy_fingerprint':fingerprint(policy),
    'tasks':tasks,'calls':[dict(r) for r in c.execute('select request_id,call_index,state,'
        'actual_input_tokens,actual_output_tokens,actual_duration_ms from continuous_research_calls order by reserved_ms')],
    'shared_historical_request_count':request_count(store),'shared_historical_ceiling':8,
    'paper_sessions':[dict(r) for r in c.execute('select status,count(*) as count from paper_sessions group by status')],
    'units':units,'installed_unit_matches_git':True,'replay_call_count_unchanged':True,
    'file_sha256':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in (
        'config/continuous-research-policy.json','config/continuous-experiment-policy.json',
        'systemd/user/tamtam-again-population-research.service')},
    'real_final_evaluations_passed':c.execute("select count(*) from validation_evaluations e join validation_plans p using(plan_id) where p.synthetic=0 and e.stage='final' and e.status='passed'").fetchone()[0],
    'real_orders_enabled':False}
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(proof,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
print(json.dumps({'tasks_verified':len(tasks),'calls':calls_before,'shared_count':proof['shared_historical_request_count'],
    'service_result':units['tamtam-again-population-research.service'].get('Result'),'output':str(a.output)}))
