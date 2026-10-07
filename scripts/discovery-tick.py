#!/usr/bin/env python3
"""Rotate public trade discovery using only already available catalog metadata."""
import argparse
import json
import time
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.discovery_rotation import select_markets
from tamtam_again.discovery_runtime import collect_session
from tamtam_again.discovery import leaderboard_provenance

p = argparse.ArgumentParser()
p.add_argument('--db', type=Path, required=True)
p.add_argument('--seconds', type=int, default=45)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
network = 'hyperliquid-mainnet'
with Store(a.db) as store:
    ranking = store.connection.execute(
        'select snapshot_id, observed_at from whale_rankings where network=? '
        'order by observed_at desc limit 1', (network,)).fetchone()
    if ranking:
        rows = [dict(r) for r in store.connection.execute(
            'select address,window,metric,rank from whale_rankings where snapshot_id=?',
            (ranking['snapshot_id'],))]
        leaderboard_provenance(store, network, ranking['snapshot_id'],
                               ranking['observed_at'], rows,
                               max((r['rank'] for r in rows), default=0))
    row = store.connection.execute(
        'select payload_json from collateral_catalogs where network=? '
        'and available_ms<=? order by available_ms desc limit 1',
        (network, int(time.time()*1000))).fetchone()
    if row is None:
        raise SystemExit('Awaiting collected public catalog; no extra REST calls')
    protected = {r[0] for r in store.connection.execute(
        'select distinct coin from validation_plans where synthetic=0')}
    selection = select_markets(json.loads(row[0]), now_ms=int(time.time()*1000),
                               protected=protected)
    if not selection['markets']:
        raise SystemExit('No eligible discovery markets')
    report = collect_session(store, network, selection['markets'], seconds=a.seconds)
    report['selection'] = selection
    store.connection.execute('create table if not exists discovery_sessions '
        '(session_id text primary key, available_ms integer not null, report_json text not null)')
    store.connection.execute('insert into discovery_sessions values(?,?,?)',
        (report['session'], int(time.time()*1000), json.dumps(report, sort_keys=True)))
    store.connection.commit()
a.output.parent.mkdir(parents=True, exist_ok=True)
temporary = a.output.with_suffix('.tmp')
temporary.write_text(json.dumps(report, indent=2)+'\n')
temporary.replace(a.output)
print(json.dumps({k: report[k] for k in ('session', 'markets', 'outcome',
                                       'new_candidates', 'bytes_received')}))
