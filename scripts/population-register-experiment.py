#!/usr/bin/env python3
"""Register an explicit reviewed hypothesis, plan and bounded experiment profile."""
import argparse,json
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.population_experiments import register_experiment
p=argparse.ArgumentParser()
p.add_argument('--db',type=Path,required=True)
p.add_argument('--request-id',required=True)
p.add_argument('--plan-id',required=True)
p.add_argument('--profile',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
with Store(a.db) as s:
 result=register_experiment(s,a.request_id,a.plan_id,json.loads(a.profile.read_text()))
a.output.write_text(json.dumps(result,indent=2)+'\n')
print('Population experiment:',result['status'])
