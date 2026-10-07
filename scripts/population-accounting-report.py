#!/usr/bin/env python3
"""Read population-only accounting evidence; never reserved pilot archives."""
import argparse,json,time
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.account_adapter import report_account
p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--start-ms',type=int,required=True);p.add_argument('--end-ms',type=int,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
asof=int(time.time()*1000)
with Store(a.db) as s:
 addresses=[r[0] for r in s.connection.execute('select distinct address from account_scope_reports order by address')]
 reports=[report_account(s,'hyperliquid-mainnet',address,a.start_ms,a.end_ms,as_of_ms=asof) for address in addresses]
 out={'as_of_ms':asof,'period':{'start_ms':a.start_ms,'end_ms':a.end_ms},'accounts':reports,'accounts_reported':len(reports),'economically_validated':0,'synthetic':False,'scope':'real public inventory and archived population REST evidence; incomplete coverage yields unknown, not zero PnL'}
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,indent=2)+'\n');print('Real accounting evidence reports:',len(reports),'economic validations:',0)
