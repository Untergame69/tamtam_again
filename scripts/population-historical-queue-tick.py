#!/usr/bin/env python3
"""Bounded public portfolio-curve queue tick; no AI or detailed-account slots."""
import argparse
import json
from pathlib import Path

from tamtam_again.storage import Store
from tamtam_again.providers.hyperliquid import HyperliquidInfo
from tamtam_again.historical_curve_queue import tick

p = argparse.ArgumentParser()
p.add_argument("--db", type=Path, required=True)
p.add_argument("--policy", type=Path, required=True)
p.add_argument("--network", default="hyperliquid-mainnet")
args = p.parse_args()
policy = json.loads(args.policy.read_text())
HyperliquidInfo.telemetry_path = args.db.with_suffix(".telemetry.sqlite3")
with Store(args.db) as store:
    result = tick(store, HyperliquidInfo(args.network), args.network, policy)
print(json.dumps(result, sort_keys=True))
