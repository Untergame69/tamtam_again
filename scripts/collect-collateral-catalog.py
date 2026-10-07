#!/usr/bin/env python3
"""Collect shared public metadata without reading pilot observations."""
import argparse,json
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.providers.hyperliquid import HyperliquidInfo
from tamtam_again.collateral import refresh_catalog
p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--force',action='store_true');a=p.parse_args()
HyperliquidInfo.telemetry_path=a.db.with_suffix('.telemetry.sqlite3')
client=HyperliquidInfo('hyperliquid-mainnet')
with Store(a.db) as store:catalog=refresh_catalog(store,client,force=a.force)
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(catalog,indent=2)+'\n')
print('Collateral metadata:',len(catalog['dexes']),'dexes,',len(catalog['instruments']),'instruments; no economic validation')
