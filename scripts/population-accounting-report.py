#!/usr/bin/env python3
"""Read population-only accounting evidence; never reserved pilot archives."""
import argparse
import json
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace
from tamtam_again.account_batch import report_population

p = argparse.ArgumentParser()
p.add_argument('--db', type=Path, required=True)
p.add_argument('--network', default='hyperliquid-mainnet')
p.add_argument('--start-ms', type=int, required=True)
p.add_argument('--end-ms', type=int, required=True)
p.add_argument('--as-of-ms', type=int)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
asof = int(time.time()*1000) if a.as_of_ms is None else a.as_of_ms
with sqlite3.connect(a.db.resolve().as_uri()+'?mode=ro', uri=True) as connection:
    connection.row_factory = sqlite3.Row
    out = report_population(SimpleNamespace(connection=connection), a.network,
                            a.start_ms, a.end_ms, as_of_ms=asof)
a.output.parent.mkdir(parents=True, exist_ok=True)
a.output.write_text(json.dumps(out, indent=2)+'\n')
print(json.dumps({key: out[key] for key in ('accounts_inventoried', 'accounts_reported', 'economically_validated')}))
