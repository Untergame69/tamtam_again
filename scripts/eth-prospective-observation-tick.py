#!/usr/bin/env python3
"""Run one bounded tick of the frozen public 67f7/ETH observation."""
import argparse
import json
import subprocess
from pathlib import Path

from tamtam_again.eth_prospective_observation import load_protocol, tick
from tamtam_again.providers.hyperliquid import HyperliquidInfo
from tamtam_again.storage import Store


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,default=Path('data/tamtam.sqlite3'))
    parser.add_argument('--protocol',type=Path,default=Path('config/eth-prospective-observation-67f7-20261014-v1.json'))
    parser.add_argument('--stop-timer',default='tamtam-again-eth-observation.timer')
    args=parser.parse_args()
    protocol=load_protocol(args.protocol)
    HyperliquidInfo.telemetry_path=args.db.with_suffix('.telemetry.sqlite3')
    with Store(args.db) as store:
        result=tick(store,protocol)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,default=str))
    if result.get('status')=='finalised':
        subprocess.run(['systemctl','--user','stop',args.stop_timer],check=False,capture_output=True,text=True)


if __name__=='__main__': main()
