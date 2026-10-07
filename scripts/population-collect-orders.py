#!/usr/bin/env python3
"""Explicit targeted public collection, using the shared REST telemetry quota."""
import argparse,json
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.providers.hyperliquid import HyperliquidInfo
from tamtam_again.population_orders import collect_orders
p=argparse.ArgumentParser()
p.add_argument('--db',type=Path,required=True)
p.add_argument('--telemetry-db',type=Path,required=True)
p.add_argument('--network',default='hyperliquid-mainnet')
p.add_argument('--address',required=True)
p.add_argument('--dex',action='append',required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args();HyperliquidInfo.telemetry_path=a.telemetry_db
with Store(a.db) as store:
    result=collect_orders(store,HyperliquidInfo(a.network),a.network,a.address,dexes=a.dex)
a.output.write_text(json.dumps({k:v for k,v in result.items() if k!='responses'},indent=2)+'\n')
print('Public order report:',result['report_id'])
