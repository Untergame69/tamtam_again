#!/usr/bin/env python3
"""Read-only inventory and v5/source comparison for a880/HYPE.

Run from the repository root:
  PYTHONPATH=src python scripts/analyze_a880_hype.py --database data/tamtam.sqlite3
The command prints JSON and never opens the database for writing.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import zlib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from tamtam_again.hype_diagnostics import fee_crossed_summary, gap_summary, live_fills, ms, quantiles
from tamtam_again.research_memory import authorized_account_history

ADDRESS = "0xa880d6cc607a05ea617307ab3b0d335e8d8424ee"
COIN = "HYPE"
SESSION = "37116951b6654b5c9ab3f116e44b44b4"


def decode(row: sqlite3.Row):
    body = row["response_json"]
    if row["response_encoding"] == "zlib+json":
        body = zlib.decompress(body).decode()
    elif isinstance(body, bytes):
        body = body.decode()
    return json.loads(body)


def utc(ms_value: int | None) -> str | None:
    if ms_value is None:
        return None
    return datetime.fromtimestamp(ms_value / 1000, timezone.utc).isoformat(timespec="milliseconds")


def pct_round(values):
    result = quantiles(values)
    return {k: (round(v, 3) if isinstance(v, (float, int)) and k != "n" else v) for k, v in result.items()}


def analyze(db_path: str, as_of_ms: int | None = None) -> dict:
    con = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute("BEGIN")  # one consistent read snapshot while collectors continue writing
        if as_of_ms is None:
            as_of_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        class ReadOnlyStoreView:
            connection = con
        if not authorized_account_history(ReadOnlyStoreView(), "hyperliquid-mainnet", ADDRESS, as_of_ms):
            raise PermissionError("Account history is not released for this cutoff")
        cutoff_utc = utc(as_of_ms)
        groups = {}
        for r in con.execute("""SELECT source,endpoint,entity_type,entity_id,count(*) n,
             min(requested_at) first_requested,max(requested_at) last_requested,
             min(observed_at) first_archived,max(observed_at) last_archived,
             sum(coalesce(record_count,0)) records,sum(complete=0) incomplete
             FROM raw_observations WHERE network='hyperliquid-mainnet'
             AND observed_at<=? AND ((source='hyperliquid-population-rest-v1' AND ((entity_type='account' AND entity_id=?)
                 OR (entity_type='market' AND entity_id=?)))
               OR (source='hyperliquid-websocket-v1' AND ((entity_type='account' AND entity_id=?)
                 OR (entity_type='market' AND entity_id=?))) )
             GROUP BY source,endpoint,entity_type,entity_id""", (cutoff_utc, ADDRESS, COIN, ADDRESS, COIN)):
            groups[f"{r['source']}:{r['endpoint']}:{r['entity_type']}:{r['entity_id']}"] = {
                "observations": r["n"], "first_requested": r["first_requested"],
                "last_requested": r["last_requested"], "first_archived": r["first_archived"],
                "last_archived": r["last_archived"], "record_count_sum": r["records"],
                "incomplete_pages": r["incomplete"],
            }

        # HYPE account fills from REST are historical trade records, not paper signals.
        rest_rows = con.execute("""SELECT * FROM raw_observations WHERE source='hyperliquid-population-rest-v1'
             AND entity_type='account' AND entity_id=? AND endpoint IN ('userFills','userFillsByTime')
             AND observed_at<=? ORDER BY observation_id""", (ADDRESS, cutoff_utc)).fetchall()
        rest_tids = {}
        rest_hype_times = []
        max_page = 0
        for row in rest_rows:
            payload = decode(row)
            fills = payload if isinstance(payload, list) else payload.get("data", {}).get("fills", payload.get("fills", []))
            max_page = max(max_page, int(row["record_count"] or 0))
            for f in fills:
                if f.get("coin") == COIN:
                    rest_tids[str(f.get("tid", f"{f.get('time')}:{f.get('px')}:{f.get('sz')}"))] = f
                    if f.get("time") is not None:
                        rest_hype_times.append(int(f["time"]))
        rest_fees = [float(f["fee"]) for f in rest_tids.values() if f.get("fee") is not None]
        rest_fee_crossed = fee_crossed_summary(rest_tids.values())

        # Signed directions and sizes describe recorded HYPE fills. Position
        # episodes are deliberately not inferred from the incomplete fill pages.
        history_fills = sorted(rest_tids.values(), key=lambda f: (int(f.get("time", 0)), str(f.get("tid", ""))))
        signed = lambda f: float(f.get("sz", 0)) * (1 if f.get("side") == "B" else -1 if f.get("side") == "A" else 0)
        buys = [f for f in history_fills if f.get("side") == "B"]
        sells = [f for f in history_fills if f.get("side") == "A"]
        sizes = [abs(float(f["sz"])) for f in history_fills if f.get("sz") is not None]
        fill_times = sorted(int(f["time"]) for f in history_fills if f.get("time") is not None)
        fill_gaps = [b-a for a,b in zip(fill_times, fill_times[1:])]
        closed_pnl = [float(f["closedPnl"]) for f in history_fills if f.get("closedPnl") is not None]
        fees_by_token = Counter()
        for f in history_fills:
            if f.get("fee") is not None:
                fees_by_token[str(f.get("feeToken") or "<missing>")] += float(f["fee"])
        notional = lambda rows: sum(abs(float(f.get("px", 0))*float(f.get("sz", 0))) for f in rows)

        # Clearinghouse snapshots prove the sampled position at each instant,
        # but sparse snapshots do not locate the actual entry/exit transitions.
        position_rows = con.execute("""SELECT * FROM raw_observations WHERE
             source='hyperliquid-population-rest-v1' AND entity_type='account' AND entity_id=?
             AND endpoint='clearinghouseState' AND observed_at<=? ORDER BY observed_at,observation_id""",
             (ADDRESS, cutoff_utc)).fetchall()
        position_samples = []
        for row in position_rows:
            body = decode(row)
            found = next((x.get("position", {}) for x in body.get("assetPositions", [])
                          if x.get("position", {}).get("coin") == COIN), None)
            position_samples.append((ms(row["observed_at"]),
                                     float(found.get("szi", 0)) if found else 0.0))
        position_gaps = [b[0]-a[0] for a,b in zip(position_samples, position_samples[1:])]
        occupied_runs = []
        i = 0
        while i < len(position_samples):
            if position_samples[i][1] == 0:
                i += 1
                continue
            j = i
            while j+1 < len(position_samples) and position_samples[j+1][1] != 0:
                j += 1
            occupied_runs.append((i,j))
            i = j+1
        single_sample_brackets = []
        for first,last in occupied_runs:
            if first == last and first > 0 and last+1 < len(position_samples):
                single_sample_brackets.append(position_samples[last+1][0]-position_samples[first-1][0])
        account_behavior = {
            "historical_fill_source": "REST userFillsByTime/userFills, deduplicated by tid",
            "unique_hype_fills": len(history_fills),
            "event_span": [utc(fill_times[0]), utc(fill_times[-1])] if fill_times else None,
            "all_source_pages_marked_incomplete": all(not r["complete"] for r in rest_rows),
            "buys": {"fills": len(buys), "hype": round(sum(abs(float(f["sz"])) for f in buys), 8),
                     "notional_usdc": round(notional(buys), 6)},
            "sells": {"fills": len(sells), "hype": round(sum(abs(float(f["sz"])) for f in sells), 8),
                      "notional_usdc": round(notional(sells), 6)},
            "recorded_signed_net_hype": round(sum(signed(f) for f in history_fills), 8),
            "gross_notional_usdc": round(notional(history_fills), 6),
            "fill_size_hype": pct_round(sizes),
            "inter_fill_gap_ms": pct_round(fill_gaps),
            "inter_fill_gaps_over_1h": sum(gap > 3_600_000 for gap in fill_gaps),
            "fills_per_elapsed_hour": round(len(fill_times) / ((fill_times[-1]-fill_times[0])/3_600_000), 3)
                if len(fill_times) > 1 and fill_times[-1] > fill_times[0] else None,
            "closedPnl_field": {"rows": len(closed_pnl), "sum_usdc": round(sum(closed_pnl), 8),
                "positive_rows": sum(x > 0 for x in closed_pnl), "negative_rows": sum(x < 0 for x in closed_pnl),
                "interpretation": "provider closedPnl field, not account return; it includes fee under the documented per-fill convention"},
            "signed_fee_usdc": round(sum(float(f["fee"]) for f in history_fills if f.get("fee") is not None), 8),
            "fee_by_token": {token: round(amount, 8) for token, amount in sorted(fees_by_token.items())},
            "builderFee_rows": sum(f.get("builderFee") is not None for f in history_fills),
            "position_snapshots": {"count": len(position_samples), "nonzero_samples": sum(x[1] != 0 for x in position_samples),
                "nonzero_sample_runs": len(occupied_runs), "runs_with_multiple_nonzero_samples": sum(a != b for a,b in occupied_runs),
                "sample_spacing_ms": pct_round(position_gaps),
                "bracket_around_isolated_nonzero_samples_ms": pct_round(single_sample_brackets),
                "episode_durations_ms": None,
                "limitation": "Snapshots establish position only at sample instants. Fill pages are incomplete; individual entry/exit times and exact holding durations are not reconstructible."}
        }

        # Paper v5 source signals: use the exact observation cursor and session window.
        session = con.execute("SELECT * FROM paper_sessions WHERE session_id=?", (SESSION,)).fetchone()
        state = json.loads(session["state_json"])
        start_ms = int(session["started_ms"])
        end_ms = int(state.get("last_ms", start_ms))
        start_artifact = Path("docs/continuous-research/PAPER-V5-START-20261013-A880-HYPE.json")
        launch = json.loads(start_artifact.read_text())
        start_cursor = int(launch["initial_observation_cursor"])
        cursor = int(session["last_observation_id"])
        source_rows = con.execute("""SELECT * FROM raw_observations WHERE observation_id>? AND observation_id<=?
             AND source='hyperliquid-websocket-v1' AND endpoint='userFills' AND entity_type='account' AND entity_id=?
             ORDER BY observation_id""", (start_cursor, cursor, ADDRESS)).fetchall()
        source_fills = {}
        event_to_receipt, receipt_to_archive = [], []
        for row in source_rows:
            payload = decode(row)
            request = json.loads(row["request_json"])
            observed_ms = ms(row["observed_at"])
            request_ms = ms(row["requested_at"])
            receipt_to_archive.append(observed_ms - request_ms)
            for f in live_fills(payload, request, COIN):
                t = int(f["time"])
                if not start_ms <= t <= end_ms:
                    continue
                tid = str(f.get("tid"))
                source_fills.setdefault(tid, f)
                event_to_receipt.append(request_ms - t)
        source_net = sum(float(f["sz"]) * (1 if f["side"] == "B" else -1) for f in source_fills.values())
        source_notional = sum(abs(float(f["sz"]) * float(f["px"])) for f in source_fills.values())
        source_fee = sum(float(f.get("fee", 0)) for f in source_fills.values())
        source_fee_crossed = fee_crossed_summary(source_fills.values())
        source_qty = sum(abs(float(f["sz"])) for f in source_fills.values())
        source_buys = sum(f.get("side") == "B" for f in source_fills.values())
        source_sells = sum(f.get("side") == "A" for f in source_fills.values())
        source_vwap = source_notional / source_qty if source_qty else None

        fills = state.get("fills", [])
        paper_qty = sum(abs(float(x["size"])) for x in fills)
        paper_notional = sum(abs(float(x["size"]) * float(x["price"])) for x in fills)
        paper_vwap = paper_notional / paper_qty if paper_qty else None
        paper_signed_qty = sum(float(x["size"]) for x in fills)
        successful = [x for x in state.get("execution_opportunities", []) if x.get("outcome") in ("executed", "partial")]
        execution_lag = [int(x["execution_decision_ms"]) - int(x["signal_decision_ms"]) for x in successful]
        due_overrun = [int(x["execution_decision_ms"]) - int(x["due_ms"])
                       for x in successful]
        quote_ages = [int(x["quote_age_ms"]) for x in state.get("execution_opportunities", [])
                      if x.get("outcome") in ("executed", "partial") and x.get("quote_age_ms") is not None]

        # Full archive quote arrival statistics and in-session comparison. Gaps are per
        # connection so reconnects do not become false continuous-feed intervals.
        quote_stats = {}
        for endpoint in ("bbo", "l2Book", "trades"):
            qrows = con.execute("""SELECT * FROM raw_observations WHERE source='hyperliquid-websocket-v1'
                AND network='hyperliquid-mainnet' AND entity_type='market' AND entity_id=? AND endpoint=?
                AND observed_at<=? ORDER BY observation_id""", (COIN, endpoint, cutoff_utc)).fetchall()
            received, e2r, r2a, in_window_receipts = defaultdict(list), [], [], defaultdict(list)
            conn_known = conn_unknown = 0
            event_count = 0
            for row in qrows:
                body = decode(row)
                archived = ms(row["observed_at"])
                frames = body.get("events") or [{"received_at": row["requested_at"], "message": body}]
                for frame in frames:
                    receipt = ms(frame["received_at"])
                    message = frame.get("message", {})
                    data = message.get("data", {})
                    conn_id = (message.get("_stream") or {}).get("connection_id") or json.loads(row["request_json"]).get("connection_id")
                    if conn_id:
                        conn_known += 1
                        received[conn_id].append(receipt)
                        if start_ms <= receipt < end_ms:
                            in_window_receipts[conn_id].append(receipt)
                    else:
                        conn_unknown += 1
                    event_count += 1
                    r2a.append(max(0, archived - receipt))
                    event_time = data.get("time") if isinstance(data, dict) else None
                    if event_time is not None:
                        e2r.append(receipt - int(event_time))
            gaps_all = [gap_summary(v) for v in received.values()]
            gaps_window = [gap_summary(v) for v in in_window_receipts.values()]
            flat_gaps = lambda xs, k: sum(int(x[k] or 0) for x in xs)
            max_gap = max((int(x["max_gap_ms"] or 0) for x in gaps_all), default=0)
            quote_stats[endpoint] = {
                "observations": len(qrows), "nested_events": event_count,
                "frames_with_connection_id": conn_known, "frames_without_connection_id": conn_unknown,
                "receipt_span_by_observation": [qrows[0]["requested_at"], qrows[-1]["observed_at"]] if qrows else None,
                "event_to_receipt_ms": pct_round(e2r), "receipt_to_archive_ms": pct_round(r2a),
                "all_gaps_by_connection": {"connections": len(gaps_all), "gt_1s": flat_gaps(gaps_all, "gaps_gt_1s"),
                    "gt_5s": flat_gaps(gaps_all, "gaps_gt_5s"), "gt_60s": flat_gaps(gaps_all, "gaps_gt_60s"), "max_ms": max_gap},
                "v5_gaps_by_connection": {"connections": len(gaps_window), "gt_1s": flat_gaps(gaps_window, "gaps_gt_1s"),
                    "gt_5s": flat_gaps(gaps_window, "gaps_gt_5s"), "gt_60s": flat_gaps(gaps_window, "gaps_gt_60s"),
                    "max_ms": max((int(x["max_gap_ms"] or 0) for x in gaps_window), default=0)},
            }

        return {
                "database": str(Path(db_path).resolve()), "snapshot_started_at_utc": cutoff_utc,
            "account": ADDRESS, "coin": COIN,
            "inventory": groups,
            "rest_hype_fills": {"unique_tids": len(rest_tids), "event_span": [utc(min(rest_hype_times)), utc(max(rest_hype_times))] if rest_hype_times else None,
                "max_page_records": max_page, "fee_field_rows": len(rest_fees),
                "signed_fee_field_sum_usdc": round(sum(rest_fees), 8),
                "fee_crossed": rest_fee_crossed,
                "all_rest_rows_marked_incomplete": all(not r["complete"] for r in rest_rows)},
            "account_behavior": account_behavior,
            "session": {"session_id": SESSION, "started": utc(start_ms), "last_ms": utc(end_ms),
                "cursor_start_exclusive": start_cursor, "cursor_end_inclusive": cursor, "status": session["status"],
                "live_hype_fills": len(source_fills), "source_net_hype": round(source_net, 8),
                "source_gross_hype": round(source_qty, 8), "source_buy_fills": source_buys,
                "source_sell_fills": source_sells,
                "scale": 0.001, "scaled_source_net_hype": round(source_net * 0.001, 8),
                "paper_leader_target_hype": state.get("leader_target"), "leader_target_minus_scaled_source": round(float(state.get("leader_target", 0))-source_net*0.001, 8),
                "paper_position_hype": state.get("position"), "position_minus_scaled_source": round(float(state.get("position", 0))-source_net*0.001, 8),
                "source_notional_usdc": round(source_notional, 6), "source_vwap_usdc": round(source_vwap, 8) if source_vwap else None,
                "source_signed_fee_field_sum_usdc": round(source_fee, 8), "source_fee_field_rows": len(source_fills),
                "source_fee_crossed": source_fee_crossed,
                "paper_fill_count": len(fills), "paper_signed_filled_hype": round(paper_signed_qty, 8),
                "paper_abs_filled_hype": round(paper_qty, 8), "paper_fill_notional_usdc": round(paper_notional, 6),
                "paper_fill_vwap_usdc": round(paper_vwap, 8) if paper_vwap else None,
                "paper_fee_usdc": state.get("fees"), "paper_fills": len(fills),
                "paper_position_open": state.get("position"), "pending_orders": state.get("pending", []),
                "event_to_receipt_ms": pct_round(event_to_receipt), "receipt_to_archive_ms": pct_round(receipt_to_archive),
                "execution_decision_minus_signal_ms": pct_round(execution_lag), "execution_decision_minus_due_ms": pct_round(due_overrun),
                "fill_quote_age_ms": pct_round(quote_ages),
                "runtime": state.get("paper_runtime"), "reports": [dict(r) for r in con.execute(
                    "select report_id,review_index,next_action,action_detail,created_at from paper_experimental_reports where session_id=? order by review_index", (SESSION,))]},
            "quotes": quote_stats,
            "limitations": ["REST pagination does not establish exchange retention or complete coverage.",
                "Exchange event times and local collector wall clocks have no recorded offset/uncertainty.",
                "Paper signal decision timestamps are causal replay/availability timestamps; per-fill CPU decision time is not persisted.",
                "Quote silence is an inter-observation gap, not evidence that the book was unchanged or that data was lost."],
        }
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="data/tamtam.sqlite3")
    parser.add_argument("--as-of-ms", type=int, help="Released archive cutoff in Unix milliseconds")
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()
    result = analyze(args.database, args.as_of_ms)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
