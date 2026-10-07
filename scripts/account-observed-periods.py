#!/usr/bin/env python3
"""Report latest observed standard-perp periods, without economic selection."""
import argparse
import json
import time
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.discovery import protected_addresses
from tamtam_again.account_periods import observed_periods
from tamtam_again.account_adapter import report_account

p=argparse.ArgumentParser()
p.add_argument('--db',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
now=int(time.time()*1000)
with Store(a.db) as store:
    blocked=protected_addresses(store)
    addresses=[r[0] for r in store.connection.execute(
        'select distinct address from account_scope_reports order by address') if r[0] not in blocked]
    results=[]
    for address in addresses:
        selection=observed_periods(store,'hyperliquid-mainnet',address,as_of_ms=now)
        report=None
        if selection['periods']:
            period=selection['periods'][-1]
            report=report_account(store,'hyperliquid-mainnet',address,
                                  period['start_ms'],period['end_ms'],as_of_ms=now)
        results.append({'selection':selection,'accounting':report})
output={'as_of_ms':now,'accounts':results,'synthetic':False,
        'selection_rule':'latest adjacent observed valuations; no PnL ranking',
        'economic_validation':False}
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(output,indent=2)+'\n')
print(json.dumps({'accounts':len(results),'reports':sum(r['accounting'] is not None for r in results)}))
