#!/usr/bin/env python3
"""Explicitly register prospective matched witnesses; no trading or provider calls."""
import argparse,json,sqlite3
from pathlib import Path
from types import SimpleNamespace
from tamtam_again.cohort_matching import register
p=argparse.ArgumentParser()
p.add_argument('--db',type=Path,required=True)
p.add_argument('--policy',type=Path,required=True)
p.add_argument('--network',default='hyperliquid-mainnet')
p.add_argument('--cohort-id',required=True)
p.add_argument('--start-ms',type=int,required=True)
p.add_argument('--end-ms',type=int,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
# rw requires an existing DB; no Store initialization or unrelated migrations.
c=sqlite3.connect(a.db.resolve().as_uri()+'?mode=rw',uri=True,timeout=10)
c.row_factory=sqlite3.Row
try:
 out=register(SimpleNamespace(connection=c),a.network,a.cohort_id,json.loads(a.policy.read_text()),start_ms=a.start_ms,end_ms=a.end_ms)
finally:c.close()
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({'matching_id':out['matching_id'],'pairs':len(out['pairs']),
                 'excluded':len(out['excluded']),'unmatched':len(out['unmatched_selected']),
                 'economic_qualification':False,'replayed':out['replayed']}))
