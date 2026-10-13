#!/usr/bin/env python3
"""Exploratory, read-only cash-flow attribution for locally bounded a880/HYPE episodes.

Run from the repository root:
  PYTHONPATH=src python scripts/analyze_a880_hype_episode_economics.py \
    --database data/tamtam.sqlite3 --as-of-ms 1791789394195 \
    --output docs/continuous-research/A880-HYPE-EPISODE-ECONOMICS-20261013.json
"""
from __future__ import annotations

import argparse
import bisect
import json
import sqlite3
import zlib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from tamtam_again.hype_diagnostics import quantiles, start_position_chain_summary
from tamtam_again.research_memory import authorized_account_history

ADDRESS = "0xa880d6cc607a05ea617307ab3b0d335e8d8424ee"
COIN = "HYPE"


def decode(row):
    body = row["response_json"]
    if row["response_encoding"] == "zlib+json":
        body = zlib.decompress(body).decode()
    elif isinstance(body, bytes):
        body = body.decode()
    return json.loads(body)


def number(value, default=0):
    return Decimal(str(default if value is None else value))


def rounded(value, places=8):
    if value is None:
        return None
    return round(float(value), places)


def funding_key(event):
    return (event["hash"], event["time_ms"], str(event["usdc"]), str(event["szi"]))


def utc(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds")


def fee_part(fill, portion_qty, total_qty):
    if fill.get("fee") is None or total_qty == 0:
        return None
    return number(fill["fee"]) * portion_qty / total_qty


def make_part(fill, qty, role):
    full_qty = number(fill["sz"])
    px = number(fill["px"])
    buy = fill.get("side") == "B"
    return {
        "tid": str(fill["tid"]), "time_ms": int(fill["time"]), "side": fill["side"],
        "px": px, "qty": qty, "role": role,
        "cashflow_usdc": -px * qty if buy else px * qty,
        "fee_usdc": fee_part(fill, qty, full_qty),
        "crossed": fill.get("crossed"),
        "full_fill_qty": full_qty,
    }


def attribute_episodes(ordered_events):
    segments = []
    event_cursor = 0
    for offset in ordered_events["ordered_segment_event_offsets"]:
        raw_events = ordered_events["ordered_segment_fill_events"][event_cursor:event_cursor + offset["event_count"]]
        event_cursor += offset["event_count"]
        segment_no = offset["segment"]
        initial = number(raw_events[0]["pre_position"])
        active = None
        episodes = []
        tails = []
        reversals = []

        def begin(fill, segment_left_censored=False, position_after_fill=None):
            return {
                "segment": segment_no, "start_ms": int(fill["time"]), "entry_tid": str(fill["tid"]),
                "left_censored": segment_left_censored, "parts": [], "api_control_tids": set(),
                "api_exit_tid": None,
                "observed_start_position": str(number(fill["startPosition"]) if segment_left_censored else Decimal(0)),
                "position_sign": (1 if number(position_after_fill) > 0 else -1 if number(position_after_fill) < 0 else None),
            }

        def add_part(ep, fill, qty, role, include_api=True):
            part = make_part(fill, qty, role)
            ep["parts"].append(part)
            if include_api:
                ep["api_control_tids"].add(str(fill["tid"]))

        def finish(ep, fill, end_type, end_position):
            ep.update({"end_ms": int(fill["time"]), "exit_tid": str(fill["tid"]),
                       "end_type": end_type, "end_position": str(end_position),
                       "api_exit_tid": str(fill["tid"]), "right_censored": False})
            if ep["left_censored"]:
                tails.append(ep)
            else:
                episodes.append(ep)

        for event in raw_events:
            fill = event["fill"]
            pre, post = number(event["pre_position"]), number(event["post_position"])
            size = number(fill["sz"])
            if active is None:
                if pre != 0:
                    active = begin(fill, segment_left_censored=True, position_after_fill=pre)
                elif post != 0:
                    active = begin(fill, position_after_fill=post)
                else:
                    continue

            if pre * post < 0:
                closing_qty, opening_qty = abs(pre), abs(post)
                add_part(active, fill, closing_qty, "inversion_close")
                # The close leg reaches zero before the residual opening leg starts.
                finish(active, fill, "position_reversal", Decimal(0))
                reversals.append({"time_ms": int(fill["time"]), "tid": str(fill["tid"]),
                                  "close_qty": closing_qty, "open_qty": opening_qty,
                                  "fee_close_usdc": fee_part(fill, closing_qty, size),
                                  "fee_open_usdc": fee_part(fill, opening_qty, size),
                                  "total_qty": size, "total_fee_usdc": number(fill["fee"]) if fill.get("fee") is not None else None,
                                  "crossed": fill.get("crossed")})
                active = begin(fill, position_after_fill=post)
                # The API closedPnl value on an inversion belongs in the close-side control once only.
                add_part(active, fill, opening_qty, "inversion_open", include_api=False)
            elif pre != 0 and post == 0:
                add_part(active, fill, size, "flat_close")
                finish(active, fill, "returned_to_zero", post)
                active = None
            else:
                add_part(active, fill, size, "fill")

        if active is not None:
            active.update({"right_censored": True,
                           "end_ms": int(raw_events[-1]["fill"]["time"]),
                           "end_position": raw_events[-1]["post_position"]})
            tails.append(active)

        episodes.extend([])
        segments.append({"segment": segment_no, "start_ms": int(raw_events[0]["fill"]["time"]),
                         "end_ms": int(raw_events[-1]["fill"]["time"]), "initial_position": str(initial),
                         "final_position": raw_events[-1]["post_position"],
                         "episodes": episodes, "censored_tails": tails, "reversals": reversals,
                         "event_count": len(raw_events)})
    return segments


def summarize_episode(ep, raw_by_tid, funding_events):
    parts = ep["parts"]
    buy_qty = sum((p["qty"] for p in parts if p["side"] == "B"), Decimal(0))
    sell_qty = sum((p["qty"] for p in parts if p["side"] == "A"), Decimal(0))
    buy_notional = sum((-p["cashflow_usdc"] for p in parts if p["side"] == "B"), Decimal(0))
    sell_notional = sum((p["cashflow_usdc"] for p in parts if p["side"] == "A"), Decimal(0))
    price_result = sell_notional - buy_notional
    fee_total = sum((p["fee_usdc"] for p in parts if p["fee_usdc"] is not None), Decimal(0))
    missing_fee_parts = sum(p["fee_usdc"] is None for p in parts)
    end_ms = int(ep["end_ms"])
    start_ms = int(ep["start_ms"])
    attributed_funding = funding_events
    funding_total = sum((f["usdc"] for f in attributed_funding), Decimal(0))
    unique_tids = sorted(ep["api_control_tids"])
    api_pnl = sum((number(raw_by_tid[tid].get("closedPnl")) for tid in unique_tids
                   if tid in raw_by_tid and raw_by_tid[tid].get("closedPnl") is not None), Decimal(0))
    crossed_qty = {"taker": Decimal(0), "non_crossed": Decimal(0), "unknown": Decimal(0)}
    crossed_fees = {"taker": Decimal(0), "non_crossed": Decimal(0), "unknown": Decimal(0)}
    for p in parts:
        cls = "taker" if p["crossed"] is True else "non_crossed" if p["crossed"] is False else "unknown"
        crossed_qty[cls] += p["qty"]
        if p["fee_usdc"] is not None:
            crossed_fees[cls] += p["fee_usdc"]
    categories = [k for k, q in crossed_qty.items() if q]
    behavior = categories[0] if len(categories) == 1 and categories[0] != "unknown" else "mixed" if len(categories) > 1 else "unknown"
    duration = end_ms - start_ms
    result = price_result - fee_total + funding_total
    return {
        "segment": ep["segment"], "start_ms": start_ms, "end_ms": end_ms,
        "start_utc": utc(start_ms), "end_utc": utc(end_ms), "duration_ms": duration,
        "close_type": ep["end_type"], "entry_tid": ep["entry_tid"], "exit_tid": ep["exit_tid"],
        "buy_qty": rounded(buy_qty), "sell_qty": rounded(sell_qty),
        "buy_notional_usdc": rounded(buy_notional), "sell_notional_usdc": rounded(sell_notional),
        "price_result_usdc": rounded(price_result), "signed_fee_field_usdc": rounded(fee_total),
        "funding_usdc_strictly_inside_episode": rounded(funding_total),
        "result_after_observed_fee_and_attributed_funding_usdc": rounded(result),
        "api_closedPnl_control_sum_usdc": rounded(api_pnl),
        "api_closedPnl_control_fill_count": len(unique_tids),
        "fee_parts_missing": missing_fee_parts,
        "funding_event_count": len(attributed_funding), "crossed_behavior": behavior,
        "non_crossed_qty": rounded(crossed_qty["non_crossed"]), "taker_qty": rounded(crossed_qty["taker"]),
        "unknown_crossed_qty": rounded(crossed_qty["unknown"]),
        "non_crossed_signed_fee_usdc": rounded(crossed_fees["non_crossed"]),
        "taker_signed_fee_usdc": rounded(crossed_fees["taker"]),
        "parts": [{k: (rounded(v) if isinstance(v, Decimal) else v) for k, v in p.items()} for p in parts],
    }


def collect_funding(con, cutoff):
    rows = con.execute("""SELECT * FROM raw_observations WHERE source='hyperliquid-population-rest-v1'
        AND entity_type='account' AND entity_id=? AND endpoint='userFunding' AND observed_at<=?
        ORDER BY observation_id""", (ADDRESS, cutoff)).fetchall()
    unique = {}
    for row in rows:
        payload = decode(row)
        values = payload if isinstance(payload, list) else payload.get("fundings", [])
        for item in values:
            delta = item.get("delta", {})
            if delta.get("coin") != COIN:
                continue
            key = (str(item.get("hash")), int(item.get("time", 0)), str(delta.get("coin")),
                   str(delta.get("usdc")), str(delta.get("szi")))
            unique[key] = {"time_ms": int(item["time"]), "usdc": number(delta.get("usdc")),
                           "szi": number(delta.get("szi")), "hash": str(item.get("hash")),
                           "funding_rate": delta.get("fundingRate")}
    coverage = {"pages": len(rows), "incomplete_pages": sum(not r["complete"] for r in rows),
                "first_observation_id": min((int(r["observation_id"]) for r in rows), default=None),
                "last_observation_id": max((int(r["observation_id"]) for r in rows), default=None),
                "all_rows_incomplete": bool(rows) and all(not r["complete"] for r in rows)}
    return sorted(unique.values(), key=lambda x: (x["time_ms"], x["hash"])), coverage


def collect_book(con, endpoint, cutoff, fill_times):
    # Include a full day before the first fill to retain stale as well as fresh candidates.
    lower = datetime.fromtimestamp((min(fill_times) - 86_400_000) / 1000, timezone.utc).isoformat(timespec="milliseconds")
    rows = con.execute("""SELECT * FROM raw_observations WHERE source='hyperliquid-websocket-v1'
        AND network='hyperliquid-mainnet' AND entity_type='market' AND entity_id=? AND endpoint=?
        AND observed_at>=? AND observed_at<=? ORDER BY observation_id""", (COIN, endpoint, lower, cutoff)).fetchall()
    snapshots = {}
    nested = 0
    receipt_clock_rows = 0
    for row in rows:
        body = decode(row)
        frames = body.get("events") or [{"message": body, "received_at": row["requested_at"]}]
        for frame in frames:
            message = frame.get("message", {})
            data = message.get("data", {})
            t = data.get("time")
            if t is None:
                continue
            nested += 1
            if endpoint == "bbo":
                levels = data.get("bbo") or []
                if len(levels) < 2 or not levels[0] or not levels[1]:
                    continue
                bid, ask = levels[0], levels[1]
            else:
                levels = data.get("levels") or []
                if len(levels) < 2 or not levels[0] or not levels[1]:
                    continue
                bid, ask = levels[0][0], levels[1][0]
            snapshots[int(t)] = {
                "time_ms": int(t), "bid_px": number(bid.get("px")),
                "bid_sz": number(bid.get("sz")), "ask_px": number(ask.get("px")),
                "ask_sz": number(ask.get("sz")), "observation_id": int(row["observation_id"]),
            }
    times = sorted(snapshots)
    return times, snapshots, {"observations": len(rows), "nested_events": nested,
                              "observation_id_range": [min((int(r["observation_id"]) for r in rows), default=None),
                                                       max((int(r["observation_id"]) for r in rows), default=None)],
                              "unique_event_times": len(times), "lower_archive_bound": lower,
                              "first_event_ms": times[0] if times else None,
                              "last_event_ms": times[-1] if times else None}


def book_match(times, snapshots, fill):
    fill_ms = int(fill["time"])
    index = bisect.bisect_left(times, fill_ms) - 1  # strict prior event time; equal-ms order is unknown
    if index < 0:
        return None
    q = snapshots[times[index]]
    age = fill_ms - q["time_ms"]
    px, sz = number(fill["px"]), number(fill["sz"])
    if fill["side"] == "B":
        touch, touch_sz = q["ask_px"], q["ask_sz"]
        mid = (q["bid_px"] + q["ask_px"]) / 2
        touch_cost_bps = (px - touch) / touch * Decimal(10_000)
        mid_cost_bps = (px - mid) / mid * Decimal(10_000)
    else:
        touch, touch_sz = q["bid_px"], q["bid_sz"]
        mid = (q["bid_px"] + q["ask_px"]) / 2
        touch_cost_bps = (touch - px) / touch * Decimal(10_000)
        mid_cost_bps = (mid - px) / mid * Decimal(10_000)
    return {"age_ms": age, "touch_cost_bps": touch_cost_bps,
            "mid_cost_bps": mid_cost_bps, "fill_to_touch_size_ratio": sz / touch_sz if touch_sz else None,
            "quote_time_ms": q["time_ms"], "quote_observation_id": q["observation_id"]}


def summarize_quotes(fills, times_by_ep, snaps_by_ep, diagnostics):
    rows = []
    by_age = defaultdict(list)
    for fill in fills:
        hit = book_match(times_by_ep, snaps_by_ep, fill)
        rows.append((fill, hit))
        if hit is not None:
            age = hit["age_ms"]
            age_key = "0_100ms" if age <= 100 else "100ms_1s" if age <= 1_000 else "1_5s" if age <= 5_000 else "5_30s" if age <= 30_000 else "over_30s"
            by_age[age_key].append(hit)
    ages = [float(hit["age_ms"]) for _, hit in rows if hit is not None]
    touch = [float(hit["touch_cost_bps"]) for _, hit in rows if hit is not None]
    mid = [float(hit["mid_cost_bps"]) for _, hit in rows if hit is not None]
    buckets = Counter()
    for _, hit in rows:
        if hit is None:
            buckets["no_prior_quote"] += 1
        elif hit["age_ms"] <= 100:
            buckets["0_100ms"] += 1
        elif hit["age_ms"] <= 1_000:
            buckets["100ms_1s"] += 1
        elif hit["age_ms"] <= 5_000:
            buckets["1_5s"] += 1
        elif hit["age_ms"] <= 30_000:
            buckets["5_30s"] += 1
        else:
            buckets["over_30s"] += 1
    age_rows = {}
    for key in ("0_100ms", "100ms_1s", "1_5s", "5_30s", "over_30s"):
        hits = by_age[key]
        age_rows[key] = {"fills": len(hits), "touch_cost_bps": quantiles([float(h["touch_cost_bps"]) for h in hits]),
                         "mid_cost_bps": quantiles([float(h["mid_cost_bps"]) for h in hits]),
                         "fill_to_touch_size_ratio": quantiles([float(h["fill_to_touch_size_ratio"]) for h in hits if h["fill_to_touch_size_ratio"] is not None])}
    up_to_1s = [hit for _, hit in rows if hit is not None and hit["age_ms"] <= 1_000]
    age_rows["up_to_1s_descriptive_only"] = {"fills": len(up_to_1s),
        "touch_cost_bps": quantiles([float(h["touch_cost_bps"]) for h in up_to_1s]),
        "mid_cost_bps": quantiles([float(h["mid_cost_bps"]) for h in up_to_1s]),
        "fill_to_touch_size_ratio": quantiles([float(h["fill_to_touch_size_ratio"]) for h in up_to_1s if h["fill_to_touch_size_ratio"] is not None])}
    return {"coverage": diagnostics, "matched_fills": len(ages), "unmatched_fills": buckets["no_prior_quote"],
            "quote_age_ms": quantiles(ages), "age_buckets": dict(sorted(buckets.items())),
            "fill_vs_opposite_touch_cost_bps": quantiles(touch),
            "fill_vs_mid_cost_bps": quantiles(mid),
            "cost_and_depth_by_age": age_rows,
            "method": "Latest archived quote with strictly earlier exchange event timestamp; no maximum age filter. Equal-ms order is ambiguous. Cross-clock receipt-to-fill availability cannot be established here."}


def stats_for_episodes(episodes, raw_by_tid):
    if not episodes:
        return {"episode_count": 0}
    total = lambda key: sum(number(e.get(key, 0)) for e in episodes)
    prices = [number(e["price_result_usdc"]) for e in episodes]
    fees = [number(e["signed_fee_field_usdc"]) for e in episodes]
    funding = [number(e["funding_usdc_strictly_inside_episode"]) for e in episodes]
    adjusted = [number(e["result_after_observed_fee_and_attributed_funding_usdc"]) for e in episodes]
    abs_sum = lambda xs: sum((abs(x) for x in xs), Decimal(0))
    by_abs = sorted(adjusted, key=abs, reverse=True)
    raw_pnl_tids = set()
    # Use a closed-episode fill set once; inversion-opening pieces are excluded by the helper's API controls.
    for e in episodes:
        raw_pnl_tids.update(e["_api_control_tids"])
    api_pnl = sum((number(raw_by_tid[tid].get("closedPnl")) for tid in raw_pnl_tids
                   if tid in raw_by_tid and raw_by_tid[tid].get("closedPnl") is not None), Decimal(0))
    return {
        "episode_count": len(episodes), "return_to_zero_count": sum(e["close_type"] == "returned_to_zero" for e in episodes),
        "closed_by_position_reversal_count": sum(e["close_type"] == "position_reversal" for e in episodes),
        "buy_qty": rounded(total("buy_qty")), "sell_qty": rounded(total("sell_qty")),
        "buy_notional_usdc": rounded(total("buy_notional_usdc")), "sell_notional_usdc": rounded(total("sell_notional_usdc")),
        "taker_qty": rounded(total("taker_qty")), "non_crossed_qty": rounded(total("non_crossed_qty")),
        "unknown_crossed_qty": rounded(total("unknown_crossed_qty")),
        "taker_signed_fee_usdc": rounded(total("taker_signed_fee_usdc")),
        "non_crossed_signed_fee_usdc": rounded(total("non_crossed_signed_fee_usdc")),
        "price_result_usdc": rounded(sum(prices, Decimal(0))),
        "signed_fee_field_usdc": rounded(sum(fees, Decimal(0))),
        "fee_cost_after_signed_fee_usdc": rounded(-sum(fees, Decimal(0))),
        "strictly_attributed_funding_usdc": rounded(sum(funding, Decimal(0))),
        "result_after_observed_fee_and_attributed_funding_usdc": rounded(sum(adjusted, Decimal(0))),
        "api_closedPnl_control_raw_sum_usdc": rounded(api_pnl),
        "concentration": {
            "gross_abs_adjusted_episode_result_usdc": rounded(abs_sum(adjusted)),
            "largest_1_episode_abs_share": rounded(abs(by_abs[0]) / abs_sum(adjusted)) if abs_sum(adjusted) else None,
            "largest_5_episode_abs_share": rounded(sum((abs(x) for x in by_abs[:5]), Decimal(0)) / abs_sum(adjusted)) if abs_sum(adjusted) else None,
            "gross_positive_adjusted_usdc": rounded(sum((x for x in adjusted if x > 0), Decimal(0))),
            "gross_negative_adjusted_usdc": rounded(sum((x for x in adjusted if x < 0), Decimal(0))),
        },
    }


def analyze(db_path, as_of_ms):
    cutoff = datetime.fromtimestamp(as_of_ms / 1000, timezone.utc).isoformat(timespec="milliseconds")
    con = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute("BEGIN")
        class StoreView:
            connection = con
        if not authorized_account_history(StoreView(), "hyperliquid-mainnet", ADDRESS, as_of_ms):
            raise PermissionError("Account history is not released for this cutoff")
        raw_rows = con.execute("""SELECT * FROM raw_observations WHERE source='hyperliquid-population-rest-v1'
            AND entity_type='account' AND entity_id=? AND endpoint IN ('userFills','userFillsByTime')
            AND observed_at<=? ORDER BY observation_id""", (ADDRESS, cutoff)).fetchall()
        fills_by_tid = {}
        for row in raw_rows:
            payload = decode(row)
            fills = payload if isinstance(payload, list) else payload.get("data", {}).get("fills", payload.get("fills", []))
            for fill in fills:
                if fill.get("coin") == COIN and fill.get("tid") is not None:
                    fills_by_tid[str(fill["tid"])] = fill
        fills = sorted(fills_by_tid.values(), key=lambda f: (int(f["time"]), str(f["tid"])))
        chain = start_position_chain_summary(fills, include_fill_events=True)
        segments = attribute_episodes(chain)
        funding, funding_coverage = collect_funding(con, cutoff)
        timeline_by_segment = {}
        cursor = 0
        for offset in chain["ordered_segment_event_offsets"]:
            events = chain["ordered_segment_fill_events"][cursor:cursor + offset["event_count"]]
            cursor += offset["event_count"]
            timeline_by_segment[offset["segment"]] = [(int(e["fill"]["time"]), number(e["post_position"])) for e in events]
        raw_by_tid = fills_by_tid
        flat_eps = []
        attributed_funding_keys = set()
        funding_unmatched_interior_keys = set()
        for segment in segments:
            current = []
            for ep in segment["episodes"]:
                timeline = timeline_by_segment[segment["segment"]]
                timeline_times = [row[0] for row in timeline]
                episode_funding = []
                for event in funding:
                    if not ep["start_ms"] < event["time_ms"] < ep["end_ms"]:
                        continue
                    time_index = bisect.bisect_left(timeline_times, event["time_ms"])
                    if time_index == len(timeline_times) or timeline_times[time_index] == event["time_ms"] or time_index == 0:
                        funding_unmatched_interior_keys.add(funding_key(event))
                        continue
                    observed_position = timeline[time_index - 1][1]
                    if event["szi"] != 0 and event["szi"] == observed_position:
                        episode_funding.append(event)
                        attributed_funding_keys.add(funding_key(event))
                    else:
                        funding_unmatched_interior_keys.add(funding_key(event))
                summarized = summarize_episode(ep, raw_by_tid, episode_funding)
                summarized["_api_control_tids"] = sorted(ep["api_control_tids"])
                summarized["position_sign"] = ep.get("position_sign")
                summarized["_funding_keys"] = [funding_key(f) for f in episode_funding]
                current.append(summarized)
                flat_eps.append(summarized)
            segment["summarized_episodes"] = current

        funding_unattributed = [f for f in funding if funding_key(f) not in attributed_funding_keys]
        funding_unattributed_reasons = defaultdict(lambda: {"count": 0, "usdc": Decimal(0)})
        for event in funding_unattributed:
            if any(s["start_ms"] <= event["time_ms"] <= s["end_ms"] for s in segments):
                reason = "inside_observed_segment_but_outside_strict_episode_or_exact_position_match"
            elif any(a["end_ms"] < event["time_ms"] < b["start_ms"] for a, b in zip(segments, segments[1:])):
                reason = "inside_position_chain_rupture_gap"
            else:
                reason = "outside_observed_position_segments"
            funding_unattributed_reasons[reason]["count"] += 1
            funding_unattributed_reasons[reason]["usdc"] += event["usdc"]

        by_segment = []
        by_day = defaultdict(list)
        for segment in segments:
            eps = segment["summarized_episodes"]
            stats = stats_for_episodes(eps, raw_by_tid)
            stats.update({"segment": segment["segment"], "initial_position": segment["initial_position"],
                          "final_position": segment["final_position"], "event_count": segment["event_count"],
                          "censored_tail_count": len(segment["censored_tails"]),
                          "censored_tail_positions": [{"start_tid": t.get("entry_tid"), "exit_tid": t.get("exit_tid"),
                                                        "left_censored": t.get("left_censored", False),
                                                        "right_censored": t.get("right_censored", False),
                                                        "start_position": t.get("observed_start_position"),
                                                        "end_position": t.get("end_position")} for t in segment["censored_tails"]]})
            by_segment.append(stats)
            for ep in eps:
                by_day[datetime.fromtimestamp(ep["end_ms"] / 1000, timezone.utc).date().isoformat()].append(ep)

        by_day_rows = []
        for day, eps in sorted(by_day.items()):
            stats = stats_for_episodes(eps, raw_by_tid)
            stats["utc_exit_day"] = day
            by_day_rows.append(stats)

        duration_bins = {"under_1m": [], "1_5m": [], "5_30m": [], "30m_plus": []}
        for ep in flat_eps:
            d = ep["duration_ms"]
            key = "under_1m" if d < 60_000 else "1_5m" if d < 300_000 else "5_30m" if d < 1_800_000 else "30m_plus"
            duration_bins[key].append(ep)
        duration_rows = []
        for name, eps in duration_bins.items():
            stats = stats_for_episodes(eps, raw_by_tid)
            stats["duration_bin"] = name
            stats["duration_ms"] = quantiles([e["duration_ms"] for e in eps])
            duration_rows.append(stats)

        behavior_groups = defaultdict(list)
        for ep in flat_eps:
            behavior_groups[ep["crossed_behavior"]].append(ep)
        maker_taker = []
        for behavior, eps in sorted(behavior_groups.items()):
            stats = stats_for_episodes(eps, raw_by_tid)
            stats["behavior"] = behavior
            maker_taker.append(stats)

        fill_times = [int(f["time"]) for f in fills]
        quote_by_endpoint, quote_diagnostics = {}, {}
        bounded_tids = {str(part["tid"]) for segment in segments for ep in segment["episodes"] for part in ep["parts"]}
        bounded_fills = [f for f in fills if str(f["tid"]) in bounded_tids]
        for endpoint in ("bbo", "l2Book"):
            qtimes, qsnapshots, diagnostics = collect_book(con, endpoint, cutoff, fill_times)
            quote_by_endpoint[endpoint] = {
                "all_source_fills": summarize_quotes(fills, qtimes, qsnapshots, diagnostics),
                "bounded_episode_fills": summarize_quotes(bounded_fills, qtimes, qsnapshots, diagnostics),
            }
            quote_diagnostics[endpoint] = diagnostics

        # Daily/segment closedPnl control over raw fills, including censored tails, is kept separate from episode flow results.
        raw_pnl_daily = defaultdict(Decimal)
        raw_pnl_segment = defaultdict(Decimal)
        for event in chain["ordered_segment_fill_events"]:
            fill = event["fill"]
            if fill.get("closedPnl") is not None:
                day = datetime.fromtimestamp(int(fill["time"]) / 1000, timezone.utc).date().isoformat()
                raw_pnl_daily[day] += number(fill["closedPnl"])

        for segment in segments:
            segment_fill_tids = {str(part["tid"]) for ep in segment["episodes"] + segment["censored_tails"]
                                 for part in ep["parts"]}
            raw_pnl_segment[segment["segment"]] = sum((number(raw_by_tid[tid].get("closedPnl")) for tid in segment_fill_tids
                                                        if tid in raw_by_tid and raw_by_tid[tid].get("closedPnl") is not None), Decimal(0))

        # Preserve the split on every reversal event, including signed fee allocation proportional to size.
        reversal_rows = []
        for segment in segments:
            for rev in segment["reversals"]:
                reversal_rows.append({k: (rounded(v) if isinstance(v, Decimal) else v) for k, v in rev.items()})
        reversal_by_crossed = {}
        for crossed, label in ((True, "crossed_taker"), (False, "non_crossed"), (None, "unknown")):
            selected = [rev for segment in segments for rev in segment["reversals"] if rev["crossed"] is crossed]
            reversal_by_crossed[label] = {"count": len(selected),
                "close_qty": rounded(sum((r["close_qty"] for r in selected), Decimal(0))),
                "open_qty": rounded(sum((r["open_qty"] for r in selected), Decimal(0))),
                "fee_close_usdc": rounded(sum((r["fee_close_usdc"] for r in selected if r["fee_close_usdc"] is not None), Decimal(0))),
                "fee_open_usdc": rounded(sum((r["fee_open_usdc"] for r in selected if r["fee_open_usdc"] is not None), Decimal(0)))}
        return {
            "artifact_type": "a880_hype_episode_economic_attribution_exploratory",
            "version": "1.0.0",
            "cutoff_utc": cutoff,
            "account": ADDRESS, "coin": COIN,
            "source_fill_count": len(fills), "source_fill_page_count": len(raw_rows),
            "source_fill_page_incomplete_count": sum(not r["complete"] for r in raw_rows),
            "source_fill_observation_id_range": [min(int(r["observation_id"]) for r in raw_rows), max(int(r["observation_id"]) for r in raw_rows)],
            "position_chain": {k: chain[k] for k in ("timestamp_groups", "multi_fill_timestamp_groups", "ambiguous_timestamp_groups", "invalid_timestamp_groups", "position_chain_segments", "position_chain_ruptures")},
            "definitions": {
                "price_result": "sell notional proceeds minus buy notional outflows over an episode whose observed position starts at zero and returns to zero or reverses; no ending inventory valuation.",
                "signed_fee_field": "API fee field; positive is debit, negative is rebate. Net calculation subtracts this signed field.",
                "inversion_fee_allocation": "A crossing fill is split into abs(pre-position) close quantity and abs(post-position) new-open quantity; fee is allocated proportionally to quantity/notional at the same fill price. This is an explicit allocation assumption, not an exchange-provided split.",
                "funding_attribution": "HYPE userFunding rows with nonzero szi are attributed only when their timestamp falls strictly inside one locally bounded episode. Funding at boundaries, censored tails, or outside a unique episode remains unattributed.",
                "closedPnl": "Raw API field summed separately as an episode fill control. It is not added to or substituted for price flows, fees, or funding; no API/UI equivalence is assumed.",
                "book_match": "Latest BBO/l2Book event strictly before fill event timestamp; no maximum-age cutoff is imposed. Equal-millisecond ordering is unknown; receipt-clock availability relative to exchange fill time is not established.",
            },
            "episode_summary": stats_for_episodes(flat_eps, raw_by_tid),
            "by_segment": by_segment,
            "by_utc_exit_day": by_day_rows,
            "duration_groups": duration_rows,
            "maker_taker_groups": maker_taker,
            "episodes": [{k: v for k, v in ep.items() if not k.startswith("_") and k != "parts"}
                         for ep in flat_eps],
            "inversion_count": len(reversal_rows),
            "inversion_splits": reversal_rows,
            "inversion_split_by_crossed": reversal_by_crossed,
            "censored_segment_flows": [{"segment": s["segment"], "initial_position": s["initial_position"],
                "final_position": s["final_position"], "censored_tails": len(s["censored_tails"]),
                "left_censored_tails": sum(t.get("left_censored", False) for t in s["censored_tails"]),
                "right_censored_tails": sum(t.get("right_censored", False) for t in s["censored_tails"]),
                "tail_fill_count": sum(len(t["parts"]) for t in s["censored_tails"]),
                "cashflow_and_fee_by_tail": [{"start_position": t.get("observed_start_position"),
                    "end_position": t.get("end_position"), "left_censored": t.get("left_censored", False),
                    "right_censored": t.get("right_censored", False),
                    "buy_qty": rounded(sum((p["qty"] for p in t["parts"] if p["side"] == "B"), Decimal(0))),
                    "sell_qty": rounded(sum((p["qty"] for p in t["parts"] if p["side"] == "A"), Decimal(0))),
                    "net_cashflow_usdc": rounded(sum((p["cashflow_usdc"] for p in t["parts"]), Decimal(0))),
                    "signed_fee_field_usdc": rounded(sum((p["fee_usdc"] for p in t["parts"] if p["fee_usdc"] is not None), Decimal(0)))}
                    for t in s["censored_tails"]],
                "price_flow_result_not_reported_as_pnl": True} for s in segments],
            "funding": {"source_coverage": funding_coverage, "hype_funding_rows_deduplicated": len(funding),
                "hype_funding_amount_observed_usdc": rounded(sum((f["usdc"] for f in funding), Decimal(0))),
                "strictly_attributed_event_count": len(attributed_funding_keys),
                "strictly_attributed_amount_usdc": rounded(sum((f["usdc"] for f in funding if funding_key(f) in attributed_funding_keys), Decimal(0))),
                "interior_events_without_exact_position_match": len(funding_unmatched_interior_keys),
                "unattributed_event_count": len(funding_unattributed),
                "unattributed_amount_usdc": rounded(sum((f["usdc"] for f in funding_unattributed), Decimal(0))),
                "unattributed_event_count_by_reason": {reason: {"count": row["count"], "usdc": rounded(row["usdc"])}
                    for reason, row in funding_unattributed_reasons.items()},
                "unattributed_examples": [{"time_utc": utc(f["time_ms"]), "usdc": rounded(f["usdc"]), "szi": rounded(f["szi"]), "hash": f["hash"]} for f in funding_unattributed[:20]]},
            "closedPnl_raw_control": {"sum_usdc": rounded(sum((number(f.get("closedPnl")) for f in fills if f.get("closedPnl") is not None), Decimal(0))),
                "daily_usdc": {day: rounded(value) for day, value in sorted(raw_pnl_daily.items())},
                "segment_usdc": {str(k): rounded(v) for k, v in raw_pnl_segment.items()},
                "interpretation": "Raw API field only; not a reconciled account return."},
            "order_book": quote_by_endpoint,
            "limitations": [
                "REST fill and funding pages are incomplete; local segment coherence does not prove complete history.",
                "Flat-to-flat episodes are dependent events from one account, not independent statistical observations.",
                "Cash-flow price result ignores external capital, any missing fills, inventory at censored boundaries, and mark-to-market of residual positions.",
                "Funding is attributed only to strict interior rows; absent or unmatched funding is unknown, not zero.",
                "Inversion fees are quantity-proportioned because the fill has one price; exchange-level allocation is not observed.",
                "Quote event timestamps can be compared to fill event timestamps; local receipt-clock availability and the clock offset are unknown.",
            ],
        }
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="data/tamtam.sqlite3")
    parser.add_argument("--as-of-ms", type=int, default=1791789394195)
    parser.add_argument("--output", default="docs/continuous-research/A880-HYPE-EPISODE-ECONOMICS-20261013.json")
    args = parser.parse_args()
    result = analyze(args.database, args.as_of_ms)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
