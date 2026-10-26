#!/usr/bin/env python3
"""Propose bounded descriptive studies from one exact historical screen."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tamtam_again.descriptive_admission import evaluate_inventory, write_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="SQLite operational DB opened read-only")
    parser.add_argument("--cutoff-ms", required=True, type=int, help="Exact historical-screen cutoff in UTC milliseconds")
    parser.add_argument("--network", default="hyperliquid-mainnet")
    parser.add_argument("--max-candidates", type=int, default=5000,
                        help="Hard row cap for the exact daily snapshot (default: 5000)")
    parser.add_argument("--queue-size", type=int, default=8)
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--markdown-output", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = evaluate_inventory(db_path=args.db, cutoff_ms=args.cutoff_ms,
                                    network=args.network, max_candidates=args.max_candidates,
                                    queue_size=args.queue_size)
        write_report(report, args.json_output, args.markdown_output)
    except (FileNotFoundError, LookupError, ValueError, OSError) as exc:
        parser.error(str(exc))
    print(f"candidates={report['inventory']['candidate_count']} "
          f"admissible={report['inventory']['disposition_counts'].get('admissible_descriptive', 0)} "
          f"needs_more_evidence={report['inventory']['disposition_counts'].get('needs_more_evidence', 0)} "
          f"deferred={report['inventory']['disposition_counts'].get('deferred', 0)} "
          f"excluded={report['inventory']['disposition_counts'].get('excluded', 0)} "
          f"cutoff_ms={report['cutoff_ms']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
