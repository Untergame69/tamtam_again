#!/usr/bin/env python3
"""Reproducible readonly qualification over all eligible observed accounts."""
import argparse,json,sqlite3
from pathlib import Path
from types import SimpleNamespace
from tamtam_again.account_batch import qualify_observed_population
p=argparse.ArgumentParser()
p.add_argument('--db',type=Path,required=True)
p.add_argument('--network',default='hyperliquid-mainnet')
p.add_argument('--as-of-ms',type=int,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--period-policy',type=Path,help='Select a declared duration on exact observed valuation boundaries')
a=p.parse_args()
policy=json.loads(a.period_policy.read_text()) if a.period_policy else None
with sqlite3.connect(a.db.resolve().as_uri()+'?mode=ro',uri=True) as c:
    c.row_factory=sqlite3.Row
    c.execute('begin')
    result=qualify_observed_population(SimpleNamespace(connection=c),a.network,as_of_ms=a.as_of_ms,period_policy=policy)
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ('accounts_considered','public_scopes_measured','economically_validated','contrast_cases')}))
