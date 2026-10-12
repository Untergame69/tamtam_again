#!/usr/bin/env python3
"""Idempotently register and start the one frozen HYPE v4 paper session."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tamtam_again.cli import _paper_collection_runtime_state
from tamtam_again.engine import fingerprint
from tamtam_again.experimental_paper import initialize, start as start_experimental
from tamtam_again.storage import Store
from tamtam_again.validation import create_plan, now_ms, register_variant

DB=ROOT/'data/tamtam.sqlite3'
SPEC_PATH=ROOT/'config/experiments/a880-hype-live-delta-v4.json'
HYP_PATH=ROOT/'config/experiments/a880-hype-live-delta-hypothesis-v4.json'
PLAN_PATH=ROOT/'config/experiments/a880-hype-live-delta-plan-v4.json'
EVIDENCE=ROOT/'docs/continuous-research/PAPER-V4-START-20261012-A880-HYPE.json'
HYP_ID='a880-hype-live-delta-follow-v4-causal-bbo-l2-1s'

def main()->int:
    store=Store(DB);initialize(store)
    spec=json.loads(SPEC_PATH.read_text());hyp=json.loads(HYP_PATH.read_text());template=json.loads(PLAN_PATH.read_text())
    if hyp['hypothesis_id']!=HYP_ID or hyp['max_duration_ms']!=1_800_000 or hyp['review_interval_ms']!=300_000:
        raise RuntimeError('Frozen v4 id, 30-minute duration, or five-minute first review changed')
    runtime=_paper_collection_runtime_state(store)
    store.connection.execute('''CREATE TABLE IF NOT EXISTS paper_version_launches (
        hypothesis_id TEXT PRIMARY KEY, spec_fingerprint TEXT NOT NULL, plan_id TEXT,
        variant_id TEXT, session_id TEXT, status TEXT NOT NULL, created_ms INTEGER NOT NULL)''')
    existing=store.connection.execute('SELECT * FROM paper_version_launches WHERE hypothesis_id=?',(HYP_ID,)).fetchone()
    if existing:
        if existing['spec_fingerprint']!=fingerprint(spec):raise RuntimeError('Existing v4 launch has a different frozen spec')
        found=existing['session_id']
        if not found and existing['variant_id']:
            row=store.connection.execute('SELECT p.session_id FROM paper_sessions p JOIN paper_experimental_sessions e USING(session_id) WHERE p.variant_id=? ORDER BY p.started_ms DESC LIMIT 1',(existing['variant_id'],)).fetchone()
            if row:
                found=row['session_id'];store.connection.execute("UPDATE paper_version_launches SET session_id=?,status='started' WHERE hypothesis_id=?",(found,HYP_ID));store.connection.commit()
        if found:
            result={'status':'already_started','session_id':found,'variant_id':existing['variant_id'],'plan_id':existing['plan_id'],'duplicate_start':'refused'}
            print(json.dumps(result));return 0
        raise RuntimeError('A v4 start reservation exists without a recoverable session; refusing a second start')
    store.connection.execute('INSERT INTO paper_version_launches VALUES(?,?,?,?,?,?,?)',
        (HYP_ID,fingerprint(spec),None,None,None,'reserved',now_ms()));store.connection.commit()
    base=now_ms()+60_000;width=hyp['max_duration_ms'];gap=int(template['embargo_ms'])
    template['exploration']={'start_ms':base,'end_ms':base+width}
    template['comparison']={'start_ms':base+width+gap,'end_ms':base+2*width+gap}
    template['final']={'start_ms':base+2*width+2*gap,'end_ms':base+3*width+2*gap}
    template['budget']['max_duration_ms']=width;template['budget']['max_runs']=1
    created_plan=create_plan(store,template)
    store.connection.execute('UPDATE paper_version_launches SET plan_id=?,status=? WHERE hypothesis_id=?',
        (created_plan['plan_id'],'plan_registered',HYP_ID));store.connection.commit()
    variant=register_variant(store,created_plan['plan_id'],spec)
    store.connection.execute('UPDATE paper_version_launches SET variant_id=?,status=? WHERE hypothesis_id=?',
        (variant['variant_id'],'starting',HYP_ID));store.connection.commit()
    started=start_experimental(store,variant['variant_id'],hyp,
        restart_reason='Independent v4 after incomplete v2; no residual position, cash, fill, or result transferred.',
        independent_after_incomplete=True,runtime_state=runtime)
    session_id=started['session_id']
    store.connection.execute('UPDATE paper_version_launches SET session_id=?,status=? WHERE hypothesis_id=?',
        (session_id,'started',HYP_ID));store.connection.commit()
    exp=store.connection.execute('SELECT created_ms,next_review_ms,review_interval_ms,max_duration_ms FROM paper_experimental_sessions WHERE session_id=?',(session_id,)).fetchone()
    paper=store.connection.execute('SELECT started_ms,last_observation_id,status FROM paper_sessions WHERE session_id=?',(session_id,)).fetchone()
    result={'artifact_type':'a880_hype_v4_independent_paper_start','status':'started',
        'hypothesis_id':HYP_ID,'session_id':session_id,'plan_id':created_plan['plan_id'],
        'variant_id':variant['variant_id'],'spec_fingerprint':fingerprint(spec),
        'hypothesis_fingerprint':fingerprint(hyp),'independent_after_incomplete':True,
        'predecessor_disposition':'v2 residual preserved; no balance or result transferred',
        'paper_status':paper['status'],'started_ms':paper['started_ms'],'initial_observation_cursor':paper['last_observation_id'],
        'first_automatic_review_ms':exp['next_review_ms'],'review_interval_ms':exp['review_interval_ms'],
        'max_duration_ms':exp['max_duration_ms'],'planned_stop_conditions':hyp['decision_rules'],
        'runtime_at_start':runtime,'global_95_percent_gate':'descriptive_only_not_a_launch_precondition'}
    EVIDENCE.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False));store.close();return 0

if __name__=='__main__':raise SystemExit(main())
