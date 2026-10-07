#!/usr/bin/env python3
"""Describe mechanisms from public metadata; no account or reserved event reads."""
import argparse,json,time
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.market_rules import mechanism_profile
p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
asof=int(time.time()*1000)
with Store(a.db) as store:
 row=store.connection.execute('select payload_json from collateral_catalogs where network=? and available_ms<=? order by available_ms desc limit 1',('hyperliquid-mainnet',asof)).fetchone()
 if not row:raise ValueError('No available public metadata catalog')
 catalog=json.loads(row[0])
 profiles=[mechanism_profile(catalog,coin) for coin in sorted(catalog['instruments'])]
out={'schema_version':1,'as_of_ms':asof,'profiles':profiles,'economic_validation':False,'synthetic':False}
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,indent=2)+'\n')
print('Mechanism profiles:',len(profiles),'economic validations: 0')
