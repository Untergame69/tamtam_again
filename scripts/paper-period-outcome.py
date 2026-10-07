#!/usr/bin/env python3
"""Read immutable model paper evidence; does not inspect raw market archives."""
import argparse
import json
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.paper_outcome import period_outcome

p=argparse.ArgumentParser()
p.add_argument('--db',type=Path,required=True)
p.add_argument('--session-id',required=True)
p.add_argument('--start-ms',type=int,required=True)
p.add_argument('--end-ms',type=int,required=True)
p.add_argument('--as-of-ms',type=int,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
with Store(a.db) as store:
    result=period_outcome(store,a.session_id,start_ms=a.start_ms,end_ms=a.end_ms,as_of_ms=a.as_of_ms)
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(result,indent=2)+'\n')
print('Paper period:',result['status'])
