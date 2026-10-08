#!/usr/bin/env python3
"""Seal one paper diagnostic under an explicit policy; no model invocation."""
import argparse,json
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.paper_research import seal
p=argparse.ArgumentParser()
p.add_argument('--db',type=Path,required=True)
p.add_argument('--adaptation-request-id',required=True)
p.add_argument('--policy',type=Path,required=True)
a=p.parse_args()
with Store(a.db) as store:
 print(json.dumps(seal(store,a.adaptation_request_id,json.loads(a.policy.read_text()))))
