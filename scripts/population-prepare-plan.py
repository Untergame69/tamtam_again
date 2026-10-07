#!/usr/bin/env python3
"""Create and bind future windows from explicit policy and experiment profile."""
import argparse,json
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.population_plans import prepare_plan
p=argparse.ArgumentParser()
p.add_argument('--db',type=Path,required=True)
p.add_argument('--request-id',required=True)
p.add_argument('--policy',type=Path,required=True)
p.add_argument('--profile',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
with Store(a.db) as s:
 result=prepare_plan(s,a.request_id,json.loads(a.policy.read_text()),json.loads(a.profile.read_text()))
a.output.write_text(json.dumps(result,indent=2)+'\n')
print('Prospective population plan:',result['status'])
