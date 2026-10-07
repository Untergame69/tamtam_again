#!/usr/bin/env python3
"""Reconcile a normalized evidenced period without querying reserved archives."""
import argparse,json
from pathlib import Path
from tamtam_again.accounting import reconcile_period
p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
data=json.loads(a.input.read_text());result=reconcile_period(data)
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n');print('Accounting status:',result['status'],'output:',a.output)
