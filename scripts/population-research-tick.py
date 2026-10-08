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
p.add_argument('--prepare-only',action='store_true')
p.add_argument('--max-jobs',type=int,default=1)
a=p.parse_args()
with Store(a.db) as store:
    result=tick(store,a.network,json.loads(a.policy.read_text()),dispatch=not a.prepare_only,max_jobs=a.max_jobs,plan_policies=json.loads(a.plan_policies.read_text()) if a.plan_policies else None,experiment_policy=json.loads(a.experiment_policy.read_text()) if a.experiment_policy else None)
print(json.dumps(result,indent=2))
