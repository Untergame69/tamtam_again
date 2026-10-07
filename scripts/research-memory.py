#!/usr/bin/env python3
"""Explicit knowledge writes/releases or bounded causal exports."""
import argparse,json,time
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.research_memory import save_knowledge,release_period,export_knowledge
p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True)
action=p.add_mutually_exclusive_group(required=True);action.add_argument('--item',type=Path);action.add_argument('--release-evaluation');action.add_argument('--export-address')
p.add_argument('--policy',type=Path);p.add_argument('--network');p.add_argument('--market');p.add_argument('--as-of-ms',type=int);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
with Store(a.db) as store:
 if a.item:result=save_knowledge(store,json.loads(a.item.read_text()))
 elif a.release_evaluation:
  if not a.policy:p.error('Explicit release policy required')
  result=release_period(store,a.release_evaluation,json.loads(a.policy.read_text()))
 else:
  if not a.network or not a.market:p.error('Export network and market required')
  result=export_knowledge(store,as_of_ms=a.as_of_ms if a.as_of_ms is not None else int(time.time()*1000),network=a.network,address=a.export_address,market=a.market)
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n')
print('Research memory operation recorded; no economic validation or IA dispatch')
