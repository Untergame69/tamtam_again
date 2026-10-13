#!/usr/bin/env python3
"""Consume one deterministic execution-correction request and start at most one v5 paper session."""
from __future__ import annotations
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from tamtam_again.cli import _paper_collection_runtime_state
from tamtam_again.engine import fingerprint
from tamtam_again.execution_correction import initialize as init_registry, register_request, route_request, record_admin_cancel, attach_session
from tamtam_again.experimental_paper import (initialize as init_exp,add_rectification,
    record_incomplete_disposition,start as start_experimental)
from tamtam_again.storage import Store
from tamtam_again.validation import create_plan,now_ms,register_variant

DB=ROOT/'data/tamtam.sqlite3';REQ=ROOT/'docs/continuous-research/PAPER-V4-CLOSEABLE-REDUCTION-REQUEST-20261013-V2.json'
SPEC=ROOT/'config/experiments/a880-hype-live-delta-v5.json';HYP=ROOT/'config/experiments/a880-hype-live-delta-hypothesis-v5.json';PLAN=ROOT/'config/experiments/a880-hype-live-delta-plan-v5.json'
EVIDENCE=ROOT/'docs/continuous-research/PAPER-V5-START-20261013-A880-HYPE.json'
HYP_ID='a880-hype-live-delta-follow-v5-closeable-order-selection';SOURCE='4303114ebedf4d238241a605a41c591c';REPORT='217019a2b7915f7e4b34baddccb23a8159edc08e8d6fea6bd671893980c4248c'

def main():
 s=Store(DB);init_registry(s);init_exp(s);request=json.loads(REQ.read_text());register_request(s,request);r=route_request(s,request['request_id'])
 launch_schema='''CREATE TABLE IF NOT EXISTS paper_version_launches (hypothesis_id TEXT PRIMARY KEY,spec_fingerprint TEXT NOT NULL,plan_id TEXT,variant_id TEXT,session_id TEXT,status TEXT NOT NULL,created_ms INTEGER NOT NULL)'''
 s.connection.execute(launch_schema);s.connection.commit();spec=json.loads(SPEC.read_text());hyp=json.loads(HYP.read_text());template=json.loads(PLAN.read_text())
 old=s.connection.execute('SELECT * FROM paper_version_launches WHERE hypothesis_id=?',(HYP_ID,)).fetchone()
 if old:
  if old['spec_fingerprint']!=fingerprint(spec):raise RuntimeError('Frozen v5 spec differs from reserved version')
  sid=old['session_id']
  if not sid and old['variant_id']:
   found=s.connection.execute('SELECT session_id FROM paper_experimental_sessions WHERE session_id IN (SELECT session_id FROM paper_sessions WHERE variant_id=?) ORDER BY created_ms DESC LIMIT 1',(old['variant_id'],)).fetchone()
   if found:sid=found['session_id'];s.connection.execute("UPDATE paper_version_launches SET session_id=?,status='started' WHERE hypothesis_id=?",(sid,HYP_ID));s.connection.commit()
  if sid:
   attach_session(s,request['request_id'],old['variant_id'],sid)
   print(json.dumps({'status':'already_started','session_id':sid,'duplicate_start':'refused'}));return 0
  if old['status']!='reserved':raise RuntimeError('v5 reservation has no recoverable session; refusing duplicate')
 else:
  s.connection.execute('INSERT INTO paper_version_launches VALUES(?,?,?,?,?,?,?)',(HYP_ID,fingerprint(spec),None,None,None,'reserved',now_ms()));s.connection.commit()
 # v4 operational queue cancellation is administrative only. Ledger and source report are untouched.
 action=record_admin_cancel(s,SOURCE,expected_position='0.05')
 disposition=record_incomplete_disposition(s,SOURCE,reason='v4 cycle 6 incomplete; expired virtual priority order administratively removed from the queue; +0.05 HYPE remains and no closing fill exists.',administrative_action_id=action['action_id'])
 rect=add_rectification(s,REPORT,{'code':'execution_policy_preselection_and_v4_incomplete_disposition','admin_action_id':action['action_id'],'disposition_id':disposition['disposition_id'],'residual_position':'+0.05 HYPE','closing_fill':None,'final_round_trip_result':'unknown','correction_request':request['request_id']})
 launch=s.connection.execute('SELECT * FROM paper_version_launches WHERE hypothesis_id=?',(HYP_ID,)).fetchone()
 plan_id=launch['plan_id']
 if not plan_id:
  width=hyp['max_duration_ms'];gap=template['embargo_ms'];base=now_ms()+60_000
  template['exploration']={'start_ms':base,'end_ms':base+width};template['comparison']={'start_ms':base+width+gap,'end_ms':base+2*width+gap};template['final']={'start_ms':base+2*width+2*gap,'end_ms':base+3*width+2*gap}
  template['budget']['max_runs']=1;template['budget']['max_duration_ms']=width;template['budget']['max_cost_usd']='0'
  plan=create_plan(s,template);plan_id=plan['plan_id'];s.connection.execute('UPDATE paper_version_launches SET plan_id=?,status=? WHERE hypothesis_id=?',(plan_id,'plan_registered',HYP_ID));s.connection.commit()
 variant_id=launch['variant_id']
 if not variant_id:
  variant=register_variant(s,plan_id,spec);variant_id=variant['variant_id'];s.connection.execute('UPDATE paper_version_launches SET variant_id=?,status=? WHERE hypothesis_id=?',(variant_id,'starting',HYP_ID));s.connection.commit()
 # Recover if a process stopped after session creation but before persisting the launch row.
 found=s.connection.execute('SELECT session_id FROM paper_sessions WHERE variant_id=? ORDER BY started_ms DESC LIMIT 1',(variant_id,)).fetchone()
 if found:sid=found['session_id']
 else:
  runtime=_paper_collection_runtime_state(s)
  started=start_experimental(s,variant_id,hyp,restart_reason='Independent v5 after administratively incomplete v4. The v4 +0.05 HYPE remains in its original session; no position, balance, fills, or result are transferred.',independent_after_incomplete=True,runtime_state=runtime);sid=started['session_id']
 attach_session(s,request['request_id'],variant_id,sid)
 s.connection.execute("UPDATE paper_version_launches SET session_id=?,status='started' WHERE hypothesis_id=?",(sid,HYP_ID));s.connection.commit()
 exp=s.connection.execute('SELECT created_ms,next_review_ms,review_interval_ms,max_duration_ms FROM paper_experimental_sessions WHERE session_id=?',(sid,)).fetchone();paper=s.connection.execute('SELECT started_ms,last_observation_id,status FROM paper_sessions WHERE session_id=?',(sid,)).fetchone()
 result={'artifact_type':'a880_hype_v5_execution_correction_start','status':'started','request_id':request['request_id'],'route':r['route'],'hypothesis_id':HYP_ID,'session_id':sid,'plan_id':plan_id,'variant_id':variant_id,'spec_fingerprint':fingerprint(spec),'hypothesis_fingerprint':fingerprint(hyp),'source_v4_session_id':SOURCE,'source_v4_report_id':REPORT,'source_v4_disposition_id':disposition['disposition_id'],'v4_admin_action_id':action['action_id'],'v4_rectification_id':rect['rectification_id'],'v4_residual_preserved':'+0.05 HYPE','v4_final_round_trip_result':'unknown','position_transferred':False,'paper_status':paper['status'],'started_ms':paper['started_ms'],'initial_observation_cursor':paper['last_observation_id'],'first_automatic_review_ms':exp['next_review_ms'],'review_interval_ms':exp['review_interval_ms'],'max_duration_ms':exp['max_duration_ms'],'no_live_orders':True,'max_cost_usd':'0','runtime_at_start':runtime,'duplicate_start_guard':'paper_version_launches primary key and session recovery by variant_id'}
 EVIDENCE.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False));s.close();return 0
if __name__=='__main__':raise SystemExit(main())
