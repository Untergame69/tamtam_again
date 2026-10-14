#!/usr/bin/env python3
"""Export a reproducible inventory-conditioned execution cross-tab from local archives."""
import argparse
import json
from pathlib import Path

from tamtam_again.engine import canonical
from tamtam_again.population_descriptive import prepare_inventory_execution_association
from tamtam_again.storage import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--network', required=True)
    parser.add_argument('--address', required=True)
    parser.add_argument('--market', required=True)
    parser.add_argument('--cutoff-ms', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with Store(args.db) as store:
        result = prepare_inventory_execution_association(store, args.network, args.address,
            cutoff_ms=args.cutoff_ms, market=args.market)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(canonical(result) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'analysis_fingerprint': result['analysis_fingerprint'],
        'coverage': result['coverage'], 'cross_tab_rows': len(result['by_position_side_inventory_bucket_and_crossed']),
        'segment_day_rows': len(result['by_segment_utc_day_inventory_side_bucket_and_crossed'])},
        ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
