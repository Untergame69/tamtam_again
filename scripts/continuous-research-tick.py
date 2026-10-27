#!/usr/bin/env python3
"""Run one bounded transition of the continuous research worker."""
import argparse
import json
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.continuous_research import tick

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--db',type=Path,required=True)
p.add_argument('--policy',type=Path,required=True)
p.add_argument('--experiment-policy',type=Path)
p.add_argument('--collection-policy',type=Path,help='Reconcile existing bounded acquisition; no independent REST calls')
p.add_argument('--prepare-only',action='store_true',help='Prepare and resolve only; never call an inference provider')
p.add_argument('--max-candidates',type=int,default=4)
a=p.parse_args()
with Store(a.db) as store:
    result=tick(store,json.loads(a.policy.read_text()),dispatch=not a.prepare_only,
        experiment_policy=json.loads(a.experiment_policy.read_text()) if a.experiment_policy else None,
        collection_policy=json.loads(a.collection_policy.read_text()) if a.collection_policy else None,
        max_candidates=a.max_candidates)
print(json.dumps(result,ensure_ascii=False,indent=2))
