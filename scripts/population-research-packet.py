#!/usr/bin/env python3
"""Export bounded available REST descriptions, without model calls or raw archives."""
import argparse
import json
import time
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.population_packet import packet_for_account

p=argparse.ArgumentParser()
p.add_argument('--db',type=Path,required=True)
p.add_argument('--network',default='hyperliquid-mainnet')
p.add_argument('--address',required=True)
p.add_argument('--as-of-ms',type=int)
p.add_argument('--max-chars',type=int,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
with Store(a.db) as store:
    result=packet_for_account(store,a.network,a.address,
        as_of_ms=a.as_of_ms if a.as_of_ms is not None else int(time.time()*1000),max_chars=a.max_chars)
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(result,indent=2)+'\n')
print('Population packet:',result['status'])
