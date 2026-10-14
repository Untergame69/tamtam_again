#!/usr/bin/env python3
"""Persist the versioned 67f7/ETH execution contribution analysis from local archives."""
import argparse
import json
from pathlib import Path

from tamtam_again.population_eth_execution_contribution import execute
from tamtam_again.storage import Store


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database',default='data/tamtam.sqlite3')
    p.add_argument('--request-id',default='2b7bf5b9d35a8059bba6d0af645000f357d6494577ec99a8377fbff8f1a3c6f6')
    p.add_argument('--output',default='docs/continuous-research/POPULATION-67F7-ETH-EXECUTION-CONTRIBUTION-20261014-v1.json.gz')
    args=p.parse_args()
    with Store(Path(args.database)) as store:
        result=execute(store,request_id=args.request_id,output_path=args.output)
    summary=result['artifact']['fill_consequences']['summary']
    print(json.dumps({'status':result['status'],'analysis_fingerprint':result['analysis_fingerprint'],
        'fill_count':result['artifact']['coverage']['fills']['selected_market_fill_count'],
        'bbo_usable_quotes':result['artifact']['coverage']['bbo']['usable_quotes'],
        'summary_groups':{k:len(v) for k,v in summary.items()}},indent=2))


if __name__=='__main__':main()
