#!/usr/bin/env python3
"""Export research expense metadata without migrations or result/packet reads."""
import argparse,json,sqlite3
from pathlib import Path
from types import SimpleNamespace
from tamtam_again.procedure_costs import provider_cost_ledger
p=argparse.ArgumentParser()
p.add_argument('--db',type=Path,required=True)
p.add_argument('--network',required=True)
p.add_argument('--address')
for name in ('start-ms','end-ms','as-of-ms'):p.add_argument('--'+name,type=int,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
c=sqlite3.connect(a.db.resolve().as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
try:r=provider_cost_ledger(SimpleNamespace(connection=c),network=a.network,address=a.address,start_ms=a.start_ms,end_ms=a.end_ms,as_of_ms=a.as_of_ms)
finally:c.close()
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps({k:r[k] for k in ('status','known_provider_cost_usd','total_provider_cost_usd')}))
