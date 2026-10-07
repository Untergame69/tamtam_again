#!/usr/bin/env python3
"""Export causal registry metadata without reserved data or result payloads."""
import argparse
import json
import time
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.procedure_trace import registry_trace

p=argparse.ArgumentParser()
p.add_argument('--db',type=Path,required=True)
p.add_argument('--as-of-ms',type=int)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
with Store(a.db) as store:
    result=registry_trace(store,as_of_ms=a.as_of_ms if a.as_of_ms is not None else int(time.time()*1000))
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(result,indent=2)+'\n')
print('Registry events exported:',len(result['events']))
