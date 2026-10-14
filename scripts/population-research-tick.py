#!/usr/bin/env python3
"""Bounded isolated population hypotheses; prepare-only performs no model call."""
import argparse
import json
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.population_scheduler import tick

p=argparse.ArgumentParser()
p.add_argument('--db',type=Path,required=True)
p.add_argument('--network',default='hyperliquid-mainnet')
p.add_argument('--policy',type=Path,required=True)
allocation=p.add_mutually_exclusive_group()
allocation.add_argument('--experiment-policy',type=Path,help='Versioned deterministic allocation for every eligible reviewed hypothesis')
allocation.add_argument('--plan-policies',type=Path,help='Explicit request-id to prospective policy mapping; never supplied by model')
p.add_argument('--paper-policy',type=Path,help='Explicit paper diagnosis research policy sharing the total request budget')
p.add_argument('--pilot-policy',type=Path,help='Dedicated non-renewing subscription allowance for the three reviewed candidates')
p.add_argument('--reserve-policy',type=Path,help='Explicit lifecycle for linked population reserves; preserves legacy pilots')
p.add_argument('--prepare-only',action='store_true')
p.add_argument('--resume-local-resolution',help='Explicitly resume only this persisted local archive task; never dispatch IA')
p.add_argument('--max-jobs',type=int,default=1)
a=p.parse_args()
with Store(a.db) as store:
    result=tick(store,a.network,json.loads(a.policy.read_text()),dispatch=not a.prepare_only and not a.resume_local_resolution,max_jobs=a.max_jobs,plan_policies=json.loads(a.plan_policies.read_text()) if a.plan_policies else None,experiment_policy=json.loads(a.experiment_policy.read_text()) if a.experiment_policy else None,reserve_policy=json.loads(a.reserve_policy.read_text()) if a.reserve_policy else None,paper_policy=json.loads(a.paper_policy.read_text()) if a.paper_policy else None,pilot_policy=json.loads(a.pilot_policy.read_text()) if a.pilot_policy else None,resume_local_resolution=a.resume_local_resolution)
print(json.dumps(result,indent=2))
