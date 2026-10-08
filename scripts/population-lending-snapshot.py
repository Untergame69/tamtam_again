#!/usr/bin/env python3
"""One targeted public lending snapshot, with shared quota and reserved guard."""
import argparse,json
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.providers.hyperliquid import HyperliquidInfo
from tamtam_again.account_lending import collect_snapshot
p=argparse.ArgumentParser()
p.add_argument('--db',type=Path,required=True)
p.add_argument('--telemetry-db',type=Path,required=True)
p.add_argument('--network',default='hyperliquid-mainnet')
p.add_argument('--address',required=True)
a=p.parse_args();HyperliquidInfo.telemetry_path=a.telemetry_db
with Store(a.db) as s:
 print(json.dumps(collect_snapshot(s,HyperliquidInfo(a.network),a.network,a.address)))
