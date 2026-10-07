#!/usr/bin/env python3
"""Bind prospective sessions explicitly, or resolve only their paper observations."""
import argparse,json
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.procedure_registry import bind_session,bound_outcomes
p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True)
p.add_argument('--procedure-id',required=True);p.add_argument('--period-index',type=int,required=True)
p.add_argument('--role');p.add_argument('--session-id');p.add_argument('--as-of-ms',type=int)
p.add_argument('--output',type=Path)
a=p.parse_args()
if (a.role is None)!=(a.session_id is None):p.error('role and session-id required together')
if a.role is None and (a.as_of_ms is None or a.output is None):p.error('outcomes require as-of-ms and output')
with Store(a.db) as s:
 r=bind_session(s,a.procedure_id,a.period_index,a.role,a.session_id) if a.role else bound_outcomes(s,a.procedure_id,a.period_index,as_of_ms=a.as_of_ms)
if a.output:
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps(r) if a.role else r['status'])
