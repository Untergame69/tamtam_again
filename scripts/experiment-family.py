#!/usr/bin/env python3
"""Register a bounded family on a fresh plan; never evaluate real events here."""
import argparse,json
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.experiments import register_family,select_final
p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--plan-id');p.add_argument('--profile',type=Path);p.add_argument('--base-spec',type=Path);p.add_argument('--select-family');a=p.parse_args()
with Store(a.db) as store:
 if a.select_family:
  result=select_final(store,a.select_family)
 else:
  if not a.plan_id or not a.profile or not a.base_spec:p.error('plan-id, profile and base-spec required for registration')
  result=register_family(store,a.plan_id,json.loads(a.profile.read_text()),json.loads(a.base_spec.read_text()))
 print(json.dumps(result,indent=2))
