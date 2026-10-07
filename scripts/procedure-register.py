#!/usr/bin/env python3
"""Register future procedure/reference contracts or an immutable period choice."""
import argparse,json
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.procedure_registry import register,record_choice
p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True)
p.add_argument('--input',type=Path,required=True);p.add_argument('--procedure-id');p.add_argument('--period-index',type=int)
a=p.parse_args()
if (a.procedure_id is None)!=(a.period_index is None):p.error('procedure-id and period-index required together')
value=json.loads(a.input.read_text())
with Store(a.db) as s:
 r=register(s,value) if a.procedure_id is None else record_choice(s,a.procedure_id,a.period_index,value)
print(json.dumps(r))
