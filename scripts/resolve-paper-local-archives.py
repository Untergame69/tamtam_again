#!/usr/bin/env python3
"""Resolve a paper needs-data task from its already-authorized local archives."""
import argparse
import json
from pathlib import Path

from tamtam_again.paper_local_resolution import prepare_from_local_archives
from tamtam_again.storage import Store

parser=argparse.ArgumentParser()
parser.add_argument('--db',type=Path,required=True)
parser.add_argument('--request-id',required=True)
args=parser.parse_args()
with Store(args.db) as store:
    result=prepare_from_local_archives(store,args.request_id)
print(json.dumps(result,ensure_ascii=False,indent=2))
