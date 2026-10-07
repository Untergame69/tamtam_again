#!/usr/bin/env python3
"""Explicit extension dispatcher; replay does not grant paper promotion."""
import argparse,json
from pathlib import Path
from tamtam_again.harness_extensions import replay
p=argparse.ArgumentParser();p.add_argument('--spec',type=Path,required=True);p.add_argument('--events',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--block-ms',type=int,default=1000);p.add_argument('--stress',default='1');a=p.parse_args()
result=replay(json.loads(a.spec.read_text()),json.loads(a.events.read_text()),block_ms=a.block_ms,stress=a.stress)
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n')
print('Replay complete; no paper promotion or live orders')
