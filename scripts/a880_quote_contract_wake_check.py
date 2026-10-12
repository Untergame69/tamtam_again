#!/usr/bin/env python3
"""One bounded, read-only follow-up for the stopped v3 launch and v4 proposal."""
from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/tamtam.sqlite3'
REPORT=ROOT/'docs/continuous-research/PAPER-FRESHNESS-GATE-20261012-A880-HYPE.json'
OUT=ROOT/'docs/continuous-research/PAPER-V4-REVIEW-WAKE-20261012.json'

def main()->int:
    now=datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
    report=json.loads(REPORT.read_text())
    con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
    hypothesis='a880-hype-live-delta-follow-v3-independent-600ms'
    rows=con.execute("select p.session_id,p.status from paper_sessions p join paper_experimental_sessions e using(session_id) where e.hypothesis_id=?",(hypothesis,)).fetchall()
    con.close()
    timer=subprocess.run(['systemctl','--user','is-active','tamtam-again-v3-gate-recheck.timer'],
        capture_output=True,text=True)
    result={'artifact_type':'bounded_quote_contract_review_wake_check','checked_at_utc':now,
        'scheduled_for_local':'2026-10-12T16:43:02+02:00','automatic_v3_timer_active':timer.stdout.strip()=='active',
        'v3_session_count':len(rows),'v3_sessions':[dict(x) for x in rows],
        'latest_gate_id':report['observation_windows'][-1]['gate_id'],
        'latest_gate_passed':report['observation_windows'][-1]['passed'],
        'proposal_ref':'docs/continuous-research/PROPOSED-QUOTE-VALIDITY-V4-A880-HYPE.json',
        'action':'No collection or launch is performed. Keep v3 blocked unless an independently versioned contract is explicitly approved and separately gated.'}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))
    return 0

if __name__=='__main__':raise SystemExit(main())
