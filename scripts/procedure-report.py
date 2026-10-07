#!/usr/bin/env python3
"""Resolve registered procedure evidence without archive replay or migrations."""
import argparse,json,sqlite3
from pathlib import Path
from types import SimpleNamespace
from tamtam_again.procedure_report import registered_report
p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True)
p.add_argument('--procedure-id',required=True);p.add_argument('--as-of-ms',type=int,required=True)
p.add_argument('--output',type=Path,required=True);a=p.parse_args()
c=sqlite3.connect(a.db.resolve().as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
try:r=registered_report(SimpleNamespace(connection=c),a.procedure_id,as_of_ms=a.as_of_ms)
finally:c.close()
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,indent=2)+'\n')
print(r['status'])
