#!/usr/bin/env python3
"""Collect one public latest-fill witness through the shared REST quota."""
import argparse,json
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.providers.hyperliquid import HyperliquidInfo
from tamtam_again.fill_retention_collection import collect_witness
p=argparse.ArgumentParser()
p.add_argument('--db',type=Path,required=True)
p.add_argument('--telemetry-db',type=Path,required=True)
p.add_argument('--network',default='hyperliquid-mainnet')
p.add_argument('--address',required=True)
a=p.parse_args();HyperliquidInfo.telemetry_path=a.telemetry_db
with Store(a.db) as s:
    result=collect_witness(s,HyperliquidInfo(a.network),a.network,a.address)
print(json.dumps(result))
