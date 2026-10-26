#!/usr/bin/env python3
"""Create a bounded archive coverage manifest without mutating the archive."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tamtam_again.archive_coverage import (  # noqa: E402
    build_manifest, parse_cutoff, parse_selection_addresses, render_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="operational SQLite archive; opened read-only")
    parser.add_argument("--selection-report", type=Path, required=True,
                        help="current Markdown report used to identify preselected accounts")
    parser.add_argument("--since", required=True, help="inclusive UTC ISO timestamp, e.g. 2026-10-16T00:00:00Z")
    parser.add_argument("--cutoff", required=True, help="exclusive event cutoff and inclusive receipt cutoff")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-accounts", type=int, default=64)
    parser.add_argument("--max-pages-per-account", type=int, default=300)
    parser.add_argument("--max-total-pages", type=int, default=25000)
    parser.add_argument("--max-book-rows-per-endpoint", type=int, default=20000)
    parser.add_argument("--max-events-per-account", type=int, default=250000)
    args = parser.parse_args()
    if not args.db.is_file() or not args.selection_report.is_file():
        parser.error("--db and --selection-report must name existing files")
    if args.max_accounts < 1 or args.max_pages_per_account < 1 or args.max_total_pages < 1 or args.max_book_rows_per_endpoint < 1 or args.max_events_per_account < 1:
        parser.error("all processing caps must be positive")

    raw = args.selection_report.read_bytes()
    report_text = raw.decode("utf-8")
    addresses = parse_selection_addresses(report_text)
    if not addresses:
        parser.error("no preselected accounts found in selection report")
    since_ms, cutoff_ms = parse_cutoff(args.since), parse_cutoff(args.cutoff)
    if since_ms >= cutoff_ms:
        parser.error("--since must precede --cutoff")

    uri = "file:" + str(args.db.resolve()) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma query_only=on")
    conn.execute("pragma busy_timeout=20000")
    try:
        manifest = build_manifest(conn, addresses, since_ms=since_ms, cutoff_ms=cutoff_ms,
            max_accounts=args.max_accounts, max_pages_per_account=args.max_pages_per_account,
            max_total_pages=args.max_total_pages,
            max_book_rows_per_endpoint=args.max_book_rows_per_endpoint,
            max_events_per_account=args.max_events_per_account)
    finally:
        conn.close()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "manifest.json"
    md_path = args.output_dir / "report.md"
    manifest["sources"] = {
        "selection_report": str(args.selection_report.resolve()),
        "selection_report_sha256": hashlib.sha256(raw).hexdigest(),
        "database": str(args.db.resolve()),
        "database_access": "sqlite mode=ro; query_only=on",
        "code_schema_version": manifest["schema_version"],
    }
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")) + "\n")
    md_path.write_text(render_markdown(manifest, selection_report=str(args.selection_report.resolve()),
        selection_sha256=manifest["sources"]["selection_report_sha256"], db_path=str(args.db.resolve())))
    print(json.dumps({"manifest": str(json_path), "report": str(md_path),
        "accounts": manifest["selection"]["detailed_eligible_count"],
        "pairs": sum(len(x["pairs"]) for x in manifest["accounts"]),
        "cutoff": manifest["window"]["cutoff_utc"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
