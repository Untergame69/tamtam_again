"""Deterministic, provider-curve historical screening for population accounts.

This module deliberately keeps reported portfolio curves separate from the
accounting reconciler. A positive result is a screening signal, never a return
or a strategy validation.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from .storage import decode_observation_payload
from .discovery import protected_addresses
from .research_memory import authorized_account_history

SOURCE = "hyperliquid-population-rest-v1"
POLICY_VERSION = "historical-curves-v2.0"
DAY_MS = 86_400_000
HORIZONS = {30: 3, 90: 7, 180: 15, 365: 30}  # horizon days: maximum start-boundary lateness

DECISION_SCHEMA = """
CREATE TABLE IF NOT EXISTS population_historical_decisions (
 decision_id TEXT PRIMARY KEY,
 network TEXT NOT NULL,
 address TEXT NOT NULL,
 decision_day_utc TEXT NOT NULL,
 as_of_ms INTEGER NOT NULL,
 policy_version TEXT NOT NULL,
 input_fingerprint TEXT NOT NULL,
 status TEXT NOT NULL,
 sources_json TEXT NOT NULL,
 decision_json TEXT NOT NULL,
 UNIQUE(network,address,decision_day_utc,policy_version,input_fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_historical_decisions_day
 ON population_historical_decisions(network,decision_day_utc,status);
"""


def _iso(ms: int | None) -> str | None:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat() if ms is not None else None


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("not a decimal")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("not finite")
    return result


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _reported_series(rows: list[tuple[int, Decimal]]) -> dict[str, Any]:
    if not rows:
        return {"sample_count": 0, "points": [], "first_ms": None, "last_ms": None,
                "max_gap_days": None, "revision_count": 0, "conflict_count": 0}
    rows = sorted(rows)
    gaps = [b[0] - a[0] for a, b in zip(rows, rows[1:])]
    return {"sample_count": len(rows), "points": rows,
            "first_ms": rows[0][0], "last_ms": rows[-1][0],
            "max_gap_days": max(gaps) / DAY_MS if gaps else 0,
            "revision_count": 0, "conflict_count": 0}


def _curve_metric(points: list[tuple[int, Decimal]], as_of_ms: int, horizon_days: int) -> dict[str, Any]:
    target = as_of_ms - horizon_days * DAY_MS
    tol = HORIZONS[horizon_days] * DAY_MS
    eligible = [(t, v) for t, v in points if t <= as_of_ms]
    start = next(((t, v) for t, v in reversed(eligible) if t <= target), None)
    end = eligible[-1] if eligible else None
    if start and target - start[0] > tol:
        start = None
    if end and as_of_ms - end[0] > 3 * DAY_MS:
        end = None
    out = {"horizon_days": horizon_days, "target_start_ms": target,
           "start_ms": start[0] if start else None, "end_ms": end[0] if end else None,
           "start_value": str(start[1]) if start else None,
           "end_value": str(end[1]) if end else None,
           "delta": str(end[1] - start[1]) if start and end else None,
           "actual_days": round((end[0] - start[0]) / DAY_MS, 3) if start and end else None,
           "start_boundary_lateness_days": round((target - start[0]) / DAY_MS, 3) if start else None,
           "end_age_days": round((as_of_ms - end[0]) / DAY_MS, 3) if end else None,
           "status": "reported_change" if start and end else "unknown_missing_or_stale_boundary"}
    if start and end:
        # The reported PnL curve's point-to-point fall from any earlier observed
        # peak is a sampled nominal-unit drawdown, not a percentage return.
        scoped = [(t, v) for t, v in eligible if start[0] <= t <= end[0]]
        peak = None
        deepest = Decimal(0)
        for _, value in scoped:
            peak = value if peak is None else max(peak, value)
            deepest = min(deepest, value - peak)
        out["max_sampled_curve_peak_to_trough"] = str(deepest)
    return out


def _period_consistency(points: list[tuple[int, Decimal]], start_ms: int, end_ms: int,
                        period: str) -> dict[str, Any]:
    """Attribute every measured boundary-to-boundary change exactly once.

    Adjacent calendar buckets share the same observed boundary value. A bucket
    uses the last sample at or before each common boundary; no interpolation is
    used. A missing/late boundary is left unattributed and included in the
    residual against the full horizon delta.
    """
    if period not in ("week", "month") or end_ms <= start_ms:
        raise ValueError("Comparable non-empty period required")
    day = 86_400_000
    tolerance_days = 7
    max_gap_days = 15 if period == "month" else 10
    min_bucket_days = 14 if period == "month" else 3
    min_inside_samples = 2 if period == "month" else 1
    points = sorted((t, v) for t, v in points if start_ms <= t <= end_ms)
    if not points:
        return {"calendar_period": period, "status": "unknown_no_samples", "observed_bucket_deltas": []}

    def floor_bucket(ms: int) -> datetime:
        dt = datetime.fromtimestamp(ms / 1000, timezone.utc)
        if period == "week":
            dt = (dt - timedelta(days=dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            dt = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return dt

    def next_bucket(dt: datetime) -> datetime:
        if period == "week":
            return dt + timedelta(days=7)
        return datetime(dt.year + (dt.month == 12), 1 if dt.month == 12 else dt.month + 1, 1, tzinfo=timezone.utc)

    first_bucket = floor_bucket(start_ms)
    buckets = []
    cursor = first_bucket
    while int(cursor.timestamp() * 1000) < end_ms:
        following = next_bucket(cursor)
        calendar_start = int(cursor.timestamp() * 1000)
        calendar_end = int(following.timestamp() * 1000)
        lo, hi = max(start_ms, calendar_start), min(end_ms, calendar_end)
        if hi > lo and (hi - lo) >= min_bucket_days * day:
            key = cursor.strftime("%G-W%V") if period == "week" else cursor.strftime("%Y-%m")
            # Shared boundary sample belongs to the interval that ends at the
            # boundary. The next bucket starts from the same prior sample, so
            # the change ending on the first sample after the boundary is
            # attributed once to that later bucket.
            left = next(((t, v) for t, v in reversed(points) if (t == lo if lo == start_ms else t < lo)), None)
            right = next(((t, v) for t, v in reversed(points) if (t <= hi if hi == end_ms else t < hi)), None)
            inside = [(t, v) for t, v in points if lo <= t < hi or (hi == end_ms and t == end_ms)]
            anchors = []
            for item in ([left] if left else []) + inside + ([right] if right else []):
                if not anchors or item[0] != anchors[-1][0]:
                    anchors.append(item)
            gaps = [b[0] - a[0] for a, b in zip(anchors, anchors[1:])]
            left_late = (lo - left[0]) / day if left else None
            right_late = (hi - right[0]) / day if right else None
            valid = bool(left and right and len(inside) >= min_inside_samples and
                         left_late <= tolerance_days and right_late <= tolerance_days and
                         (not gaps or max(gaps) <= max_gap_days * day))
            delta = right[1] - left[1] if valid else None
            buckets.append({"period": key, "window_start_ms": lo, "window_end_ms": hi,
                            "first_sample_ms": inside[0][0] if inside else None,
                            "last_sample_ms": inside[-1][0] if inside else None,
                            "start_boundary_sample_ms": left[0] if left else None,
                            "end_boundary_sample_ms": right[0] if right else None,
                            "start_boundary_lateness_days": round(left_late, 4) if left_late is not None else None,
                            "end_boundary_lateness_days": round(right_late, 4) if right_late is not None else None,
                            "max_sample_gap_days": round(max(gaps) / day, 4) if gaps else 0,
                            "samples": len(inside), "delta": delta,
                            "status": "measured" if valid else "unknown_boundary_or_coverage"})
        cursor = following
    observed = [r for r in buckets if r["delta"] is not None]
    deltas = [r["delta"] for r in observed]
    positive = [x for x in deltas if x > 0]
    negative = [x for x in deltas if x < 0]
    max_streak = streak = 0
    for bucket in buckets:
        value = bucket["delta"]
        streak = streak + 1 if value is not None and value < 0 else 0
        max_streak = max(max_streak, streak)
    total_delta = points[-1][1] - points[0][1] if len(points) >= 2 else None
    attributed_delta = sum(deltas, Decimal(0))
    unattributed_delta = total_delta - attributed_delta if total_delta is not None else None
    gross = sum((abs(x) for x in deltas), Decimal(0)) + (abs(unattributed_delta) if unattributed_delta is not None else Decimal(0))
    residual_share = abs(unattributed_delta) / gross if gross else Decimal(0)
    complete = bool(buckets) and len(observed) == len(buckets) and residual_share <= Decimal("0.10")
    concentration = max(positive) / sum(positive) if positive and sum(positive) else None
    if not complete:
        concentration = None
    return {"calendar_period": period, "boundary_rule": "last observed sample at or before each common UTC calendar boundary; no interpolation",
            "bucket_width_days_approx": 7 if period == "week" else 30,
            "expected_scored_buckets": len(buckets),
            "measured_buckets": len(observed),
            "unknown_buckets": len(buckets) - len(observed),
            "buckets_with_two_or_more_samples": sum(r["samples"] >= 2 for r in observed),
            "positive_observed_buckets": len(positive),
            "negative_observed_buckets": len(negative),
            "positive_share_of_observed_buckets": round(len(positive) / len(observed), 4) if observed else None,
            "largest_positive_bucket_share_of_positive_delta": str(concentration) if concentration is not None else None,
            "max_successive_negative_observed_buckets": max_streak,
            "horizon_delta": str(total_delta) if total_delta is not None else None,
            "attributed_delta_sum": str(attributed_delta),
            "unattributed_delta": str(unattributed_delta) if unattributed_delta is not None else None,
            "unattributed_gross_movement_share": str(residual_share),
            "boundary_changes_reconcile": total_delta is not None and attributed_delta + unattributed_delta == total_delta,
            "coverage_complete_for_concentration": complete,
            "observed_bucket_deltas": [{**r, "delta": str(r["delta"])} for r in buckets],
            "coverage_note": "Each adjacent bucket shares a sampled boundary. Periods without tolerant boundaries, enough internal samples, or acceptable gaps remain unknown; the unexplained net change is explicitly reported."}


def _authorized_addresses(connection: sqlite3.Connection, network: str, as_of_ms: int) -> tuple[list[str], list[dict[str, str]]]:
    store = type("StoreView", (), {"connection": connection})()
    cutoff = _iso(as_of_ms)
    query = "select lower(address) from account_scope_reports where network=? and available_ms<=?"
    params: list[Any] = [network, as_of_ms]
    if connection.execute("select 1 from sqlite_master where type='table' and name='candidates'").fetchone():
        query += (" union select distinct lower(c.address) from candidates c join raw_observations o "
                  "on o.network=c.network and lower(o.entity_id)=lower(c.address) "
                  "where c.network=? and c.added_at<=? and o.source=? and o.entity_type='account' "
                  "and o.endpoint='portfolio' and o.observed_at<=?")
        params.extend((network, cutoff, SOURCE, cutoff))
    rows = connection.execute(query + " order by 1", params).fetchall()
    blocked = {x.lower() for x in protected_addresses(store)}
    allowed, excluded = [], []
    for row in rows:
        address = row[0].lower()
        if address in blocked:
            excluded.append({"address": address, "reason": "protected pilot; payload not read"})
        elif not authorized_account_history(store, network, address, as_of_ms):
            excluded.append({"address": address, "reason": "historical interval not released at cutoff; payload not read"})
        else:
            allowed.append(address)
    return allowed, excluded


def _account_evidence(connection: sqlite3.Connection, network: str, address: str, as_of_ms: int) -> dict[str, Any]:
    cutoff = datetime.fromtimestamp(as_of_ms / 1000, timezone.utc).isoformat()
    rows = connection.execute(
        "select * from raw_observations where network=? and source=? and entity_type='account' and entity_id=? and observed_at<=? "
        "and endpoint in ('portfolio','userFillsByTime','historicalOrders','frontendOpenOrders','clearinghouseState','spotClearinghouseState','userAbstraction','userFunding','userNonFundingLedgerUpdates') "
        "order by observed_at,observation_id", (network, SOURCE, address, cutoff)).fetchall()
    values: dict[str, dict[int, tuple[Decimal, int]]] = {
        "allTime.pnlHistory": {}, "allTime.accountValueHistory": {},
        "perpAllTime.pnlHistory": {}, "perpAllTime.accountValueHistory": {}}
    revisions = defaultdict(set)
    invalid = defaultdict(int)
    refs = defaultdict(list)
    source_refs = defaultdict(set)
    vlm: dict[str, tuple[int, str]] = {}
    fills: dict[tuple[Any, ...], dict[str, Any]] = {}
    orders: dict[Any, dict[str, Any]] = {}
    open_orders = []
    fill_intervals, fill_statuses = [], []
    markets = set()
    exposures = []
    modes = []
    spot_inventory = []
    from .account_events import normalize_event
    observed_events = {}
    event_types = defaultdict(int)
    payloads_decoded = 0
    for row in rows:
        available = int(datetime.fromisoformat(row["observed_at"]).timestamp() * 1000)
        endpoint = row["endpoint"]
        request = json.loads(row["request_json"])
        payload = decode_observation_payload(row)
        payloads_decoded += 1
        ref = "raw_observations:" + str(row["observation_id"])
        source_refs[endpoint].add(ref)
        if endpoint == "portfolio":
            if not isinstance(payload, list):
                invalid["malformed_portfolio_response"] += 1
                continue
            windows = {}
            for entry in payload:
                if isinstance(entry, list) and len(entry) == 2 and isinstance(entry[0], str) and isinstance(entry[1], dict):
                    windows[entry[0]] = entry[1]
            for window_name, window_data in windows.items():
                if isinstance(window_data.get("vlm"), (str, int, float)):
                    vlm[window_name] = (available, str(window_data["vlm"]))
            for w in ("allTime", "perpAllTime"):
                data = windows.get(w, {})
                for series_name in ("pnlHistory", "accountValueHistory"):
                    raw = data.get(series_name)
                    key = w + "." + series_name
                    if not isinstance(raw, list):
                        invalid[key + ".missing"] += 1
                        continue
                    for point in raw:
                        try:
                            if not isinstance(point, list) or len(point) != 2 or type(point[0]) is not int:
                                raise ValueError
                            stamp = point[0]
                            amount = _decimal(point[1])
                            if stamp < 0 or stamp > available or stamp > as_of_ms:
                                invalid[key + ".future_or_bad_time"] += 1
                                continue
                            previous = values[key].get(stamp)
                            if previous and previous[0] != amount:
                                revisions[key].add(stamp)
                            if previous is None or available >= previous[1]:
                                values[key][stamp] = (amount, available)
                            refs[key].append(ref)
                        except (ValueError, TypeError, InvalidOperation):
                            invalid[key + ".malformed"] += 1
        elif endpoint == "userFillsByTime":
            if type(request.get("startTime")) is int:
                start = request["startTime"]
                requested_end = request.get("endTime") if type(request.get("endTime")) is int else available
                requested_end = min(requested_end, available)
                status = request.get("pagination_status", "unknown")
                covered = request.get("covered_until_ms", request.get("next_cursor_ms"))
                if type(covered) is not int and status == "pagination_exhausted":
                    covered = requested_end
                if type(covered) is int and start <= covered <= requested_end:
                    fill_intervals.append({"requested_start_ms": start, "requested_end_ms": requested_end,
                                          "covered_until_ms": covered, "pagination_status": status})
            fill_statuses.append(request.get("pagination_status", "unknown"))
            if isinstance(payload, list):
                for item in payload:
                    if not isinstance(item, dict) or type(item.get("time")) is not int:
                        continue
                    ident = (item.get("coin"), item["time"], item.get("tid", item.get("hash")))
                    if ident[-1] is None:
                        ident = ident + (item.get("oid"),)
                    if ident not in fills or available >= fills[ident].get("available_ms", 0):
                        fills[ident] = {**item, "available_ms": available, "evidence_ref": ref}
                    if item.get("coin"):
                        markets.add(str(item["coin"]))
        elif endpoint == "historicalOrders":
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict) and isinstance(item.get("order"), dict):
                        order = item["order"]
                        oid = order.get("oid")
                        if oid is not None:
                            orders[oid] = {"oid": oid, "timestamp": order.get("timestamp"), "evidence_ref": ref}
        elif endpoint == "frontendOpenOrders" and isinstance(payload, list):
            open_orders.append({"available_ms":available,"count":len(payload),"evidence_ref":ref})
        elif endpoint == "clearinghouseState" and isinstance(payload, dict):
            positions=[]
            for item in payload.get("assetPositions",[]) if isinstance(payload.get("assetPositions"),list) else []:
                if not isinstance(item,dict) or not isinstance(item.get("position"),dict):continue
                p=item["position"]
                positions.append({k:p.get(k) for k in ("coin","szi","entryPx","unrealizedPnl","liquidationPx","leverage") if k in p})
            exposures.append({"available_ms": available, "dex": request.get("dex", ""),
                              "event_ms": payload.get("time"), "positions": positions, "evidence_ref": ref})
        elif endpoint == "userAbstraction":
            modes.append({"available_ms": available, "mode": payload if isinstance(payload, str) else None,
                          "evidence_ref": ref})
        elif endpoint == "spotClearinghouseState" and isinstance(payload, dict):
            balances=payload.get("balances") if isinstance(payload.get("balances"),list) else []
            spot_inventory.append({"available_ms":available,"event_ms":payload.get("time"),
                                   "asset_count":len(balances),
                                   "assets":[b.get("coin") for b in balances if isinstance(b,dict) and b.get("coin")],
                                   "status":"observed_not_priced_or_consolidated","evidence_ref":ref})
        elif endpoint in ("userFunding", "userNonFundingLedgerUpdates") and isinstance(payload, list):
            for item in payload:
                normalized = normalize_event(endpoint, item, address=address,
                                             available_ms=available, evidence_ref=ref)
                event = normalized.get("event")
                if event:
                    observed_events[event["id"]] = event
                kind = (item.get("delta", {}).get("type") if isinstance(item, dict) and isinstance(item.get("delta"), dict)
                        else "unknown")
                event_types[str(kind)] += 1
    series = {}
    for key, points in values.items():
        ordered = sorted((t, pair[0]) for t, pair in points.items())
        item = _reported_series(ordered)
        item["revision_count"] = len(revisions[key])
        item["revision_times_ms"] = sorted(revisions[key])
        item["points"] = ordered
        item["evidence_refs"] = sorted(set(refs[key]))
        series[key] = item
    # Fills returned by pages are observations, not a proof that no other fills exist.
    covered_ranges = sorted((x["requested_start_ms"], x["covered_until_ms"], x["pagination_status"])
                            for x in fill_intervals)
    merged = []
    for start, end, status in covered_ranges:
        if not merged or start > merged[-1][1]:
            merged.append([start, end, [status]])
        else:
            merged[-1][1] = max(merged[-1][1], end)
            merged[-1][2].append(status)
    query_union_ms = sum(max(0, item[1] - item[0]) for item in merged)
    lower = min((x[0] for x in covered_ranges), default=None)
    upper = max((x[1] for x in covered_ranges), default=None)
    recent_lo, recent_hi = as_of_ms - 30 * DAY_MS, as_of_ms
    recent_ranges = []
    for start, end, _ in covered_ranges:
        lo, hi = max(start, recent_lo), min(end, recent_hi)
        if hi > lo:
            if not recent_ranges or lo > recent_ranges[-1][1]:
                recent_ranges.append([lo, hi])
            else:
                recent_ranges[-1][1] = max(recent_ranges[-1][1], hi)
    recent_query_ms = sum(hi - lo for lo, hi in recent_ranges)
    recent_latest_end = max((hi for _, hi in recent_ranges), default=None)
    fill_report = {"fills_observed": len(fills), "oldest_fill_ms": min((f["time"] for f in fills.values()), default=None),
                   "newest_fill_ms": max((f["time"] for f in fills.values()), default=None),
                   "query_start_ms": lower, "query_end_ms": upper,
                   "query_span_days": round(query_union_ms / DAY_MS, 3),
                   "query_contiguous_segments_days": [round((x[1] - x[0]) / DAY_MS, 3) for x in merged],
                   "query_coverage_30d_days": round(recent_query_ms / DAY_MS, 3),
                   "query_coverage_30d_segments_days": [round((x[1] - x[0]) / DAY_MS, 3) for x in recent_ranges],
                   "latest_query_coverage_age_30d_days": round((as_of_ms - recent_latest_end) / DAY_MS, 3) if recent_latest_end is not None else None,
                   "query_coverage_30d_at_least_25d": recent_query_ms >= 25 * DAY_MS,
                   "pagination_statuses": sorted(set(str(x) for x in fill_statuses)),
                   "truncated_or_retention_unknown": True,
                   "markets_observed": sorted(markets),
                   "orders_observed_from_fills": len({f.get("oid") for f in fills.values() if f.get("oid") is not None}),
                   "historical_order_records": len(orders),
                   "current_open_order_snapshot": sorted(open_orders,key=lambda x:x["available_ms"])[-1] if open_orders else None,
                   "order_note": "Fill-associated order ids are a lower bound; the separate historicalOrders endpoint may be absent or truncated."}
    for days in HORIZONS:
        lo, hi = as_of_ms - days * DAY_MS, as_of_ms
        count = sum(lo <= f["time"] <= hi for f in fills.values())
        active_days = len({f["time"] // DAY_MS for f in fills.values() if lo <= f["time"] <= hi})
        fill_report[f"fills_{days}d_observed"] = count
        fill_report[f"active_days_{days}d_observed"] = active_days
        fill_report[f"orders_from_fills_{days}d_observed"] = len({f.get("oid") for f in fills.values()
                                                                   if lo <= f["time"] <= hi and f.get("oid") is not None})
        fill_report[f"historical_orders_{days}d_observed"] = sum(
            type(o.get("timestamp")) is int and lo <= o["timestamp"] <= hi for o in orders.values())
        fill_report[f"markets_{days}d_observed"] = sorted({str(f.get("coin")) for f in fills.values()
                                                              if lo <= f["time"] <= hi and f.get("coin")})
    fill_report["coverage_by_requested_ranges"] = fill_intervals
    flow_totals = defaultdict(Decimal)
    flow_counts = defaultdict(int)
    for event in observed_events.values():
        key = (event.get("kind"), event.get("currency", "unknown"), event.get("boundary_classification", "unknown"))
        try:
            flow_totals[key] += _decimal(event.get("amount"))
            flow_counts[key] += 1
        except (ValueError, InvalidOperation):
            pass
    event_summary = {"normalized_event_count": len(observed_events), "observed_event_type_rows": dict(event_types),
                     "normalized_amounts_by_kind_currency_scope": [
                         {"kind": k[0], "currency": k[1], "scope": k[2], "amount": str(v), "event_count": flow_counts[k]}
                         for k, v in sorted(flow_totals.items())],
                     "coverage": "unknown; observed pages are not evidence of a complete ledger",
                     "withdrawal_semantics": "some withdrawal fee/principal semantics may remain unclassified"}
    flow_periods={}
    for days in HORIZONS:
        lo=as_of_ms-days*DAY_MS;totals=defaultdict(Decimal);counts=defaultdict(int)
        for event in observed_events.values():
            if not lo<=event.get("event_ms",-1)<=as_of_ms:continue
            key=(event.get("kind"),event.get("currency","unknown"),event.get("boundary_classification","unknown"))
            try:totals[key]+=_decimal(event.get("amount"));counts[key]+=1
            except (ValueError,InvalidOperation):pass
        flow_periods[str(days)]=[{"kind":k[0],"currency":k[1],"scope":k[2],"observed_amount":str(v),"event_count":counts[k]}
                                 for k,v in sorted(totals.items())]
    event_summary["observed_amounts_by_horizon_days"]=flow_periods
    return {"series": series, "fill_activity": fill_report, "vlm": vlm,
            "current_exposure_observations": sorted(exposures, key=lambda x: x["available_ms"])[-8:],
            "account_mode_observations": modes,
            "current_account_mode": modes[-1]["mode"] if modes else "unknown",
            "account_mode_changed_in_available_history": len({m["mode"] for m in modes if m["mode"]}) > 1,
            "spot_inventory_observations": sorted(spot_inventory,key=lambda x:x["available_ms"])[-4:],
            "observed_flow_diagnostics": event_summary,
            "invalid_sample_counts": dict(invalid), "payloads_decoded": payloads_decoded,
            "evidence_refs_by_endpoint": {k:sorted(v) for k,v in source_refs.items()},
            "source_refs": ["population REST portfolio/fill/order/state observations only"]}


def _analyze_account(connection: sqlite3.Connection, network: str, address: str, as_of_ms: int) -> dict[str, Any]:
    evidence = _account_evidence(connection, network, address, as_of_ms)
    alltime = evidence["series"]["allTime.pnlHistory"]["points"]
    account_values = evidence["series"]["allTime.accountValueHistory"]["points"]
    horizons = {str(days): _curve_metric(alltime, as_of_ms, days) for days in HORIZONS}
    value_horizons = {str(days): _curve_metric(account_values, as_of_ms, days) for days in HORIZONS}
    perp_points = evidence["series"]["perpAllTime.pnlHistory"]["points"]
    perp_values = evidence["series"]["perpAllTime.accountValueHistory"]["points"]
    perp_horizons = {str(days): _curve_metric(perp_points, as_of_ms, days) for days in HORIZONS}
    perp_value_horizons = {str(days): _curve_metric(perp_values, as_of_ms, days) for days in HORIZONS}
    for metric in horizons.values():
        metric["max_sampled_pnl_peak_to_trough"] = metric.pop("max_sampled_curve_peak_to_trough", None)
    for metric in value_horizons.values():
        metric["curve"] = "accountValueHistory"
        metric["max_sampled_account_value_peak_to_trough"] = metric.pop("max_sampled_curve_peak_to_trough", None)
    for metric in perp_horizons.values():
        metric["curve"] = "perpAllTime.pnlHistory"
        metric["max_sampled_pnl_peak_to_trough"] = metric.pop("max_sampled_curve_peak_to_trough", None)
    for metric in perp_value_horizons.values():
        metric["curve"] = "perpAllTime.accountValueHistory"
        metric["max_sampled_account_value_peak_to_trough"] = metric.pop("max_sampled_curve_peak_to_trough", None)
    consistency = {}
    for days in (90, 180):
        item = horizons[str(days)]
        if item["start_ms"] is not None and item["end_ms"] is not None:
            consistency[str(days)] = {period: _period_consistency(alltime, item["start_ms"], item["end_ms"], period)
                                      for period in ("week", "month")}
        else:
            consistency[str(days)] = {period: {"calendar_period": period, "status": "unknown_no_comparable_bounds"}
                                      for period in ("week", "month")}
    p90, p180 = horizons["90"], horizons["180"]
    available_deltas = [Decimal(horizons[str(d)]["delta"]) for d in (90, 180)
                        if horizons[str(d)]["status"] == "reported_change"]
    reported_positive = all(horizons[str(d)]["status"] == "reported_change" and
                            Decimal(horizons[str(d)]["delta"]) > 0 for d in (90, 180))
    has_negative_declared = any(value < 0 for value in available_deltas)
    active_30 = evidence["fill_activity"]["active_days_30d_observed"]
    fills_30 = evidence["fill_activity"]["fills_30d_observed"]
    if fills_30 >= 20 and active_30 >= 4:
        activity_quality = "frequent_activity_observed_lower_bound"
    elif fills_30 >= 20:
        activity_quality = "clustered_activity_observed_lower_bound"
    elif fills_30 > 0:
        activity_quality = "some_activity_observed_lower_bound"
    else:
        activity_quality = "no_recent_activity_observed_history_unknown"
    frequent = activity_quality == "frequent_activity_observed_lower_bound"
    months = consistency.get("180", {}).get("month", {})
    concentration = months.get("largest_positive_bucket_share_of_positive_delta")
    diversified = (months.get("coverage_complete_for_concentration") is True and
                   months.get("buckets_with_two_or_more_samples", 0) >= 4 and
                   concentration is not None and Decimal(concentration) <= Decimal("0.50"))
    credible = reported_positive and frequent and diversified
    if credible:
        status = "credible_deep_dive_candidate"
    elif reported_positive:
        status = "reported_positive_pending_activity" if diversified else "reported_positive_concentrated_or_sparse"
    elif has_negative_declared:
        status = "non_prioritaire_performance_declared_negative"
    else:
        status = "insufficiently_documented"
    reasons = []
    if reported_positive: reasons.append("provider-reported PnL change is positive for both comparable 90d and 180d sampled windows")
    else: reasons.append("90d/180d declared PnL result is not positive and proven on both fixed boundary rules")
    if not frequent:
        reasons.append("frequent activity is not positively observed on at least 4 UTC days; fill counts are lower bounds and pagination/retention remain separate unknowns")
    if not diversified:
        reasons.append("multi-month boundary changes are incomplete, sparse, or concentrated; unexplained changes remain explicit")
    reasons.append("economic validation is false; provider curves alone do not qualify an account for research RE")
    decision = {"address": address, "status": status,
                "performance_quality": "positive_declared" if reported_positive else
                                      "negative_declared_some_horizons" if has_negative_declared else "unknown",
                "performance_horizon_states": {str(d): {"status": horizons[str(d)]["status"],
                                                           "delta": horizons[str(d)]["delta"]}
                                                for d in (90, 180)},
                "data_quality": {"allTime_pnl_samples": evidence["series"]["allTime.pnlHistory"]["sample_count"],
                                 "allTime_first_ms": evidence["series"]["allTime.pnlHistory"]["first_ms"],
                                 "allTime_last_ms": evidence["series"]["allTime.pnlHistory"]["last_ms"],
                                 "allTime_max_gap_days": evidence["series"]["allTime.pnlHistory"]["max_gap_days"],
                                 "revisions": evidence["series"]["allTime.pnlHistory"]["revision_count"],
                                 "economic_reconciliation": "unknown"},
                "horizons": horizons, "account_value_horizons": value_horizons,
                "perp_all_time_horizons": perp_horizons,
                "perp_all_time_account_value_horizons": perp_value_horizons,
                "weekly_monthly_consistency": consistency,
                "activity_quality": activity_quality, "fill_activity": evidence["fill_activity"],
                "economic_research_readiness": {"status": "blocked_pending_economic_review",
                    "eligible_for_ai_research": False,
                    "reason": "declared-curve selection is a data-screen only; no account-specific economic validation has been approved",
                    "economic_validation": False},
                "declared_vlm": evidence["vlm"],
                "observed_flow_diagnostics": evidence["observed_flow_diagnostics"],
                "current_exposure_observations": evidence["current_exposure_observations"],
                "account_mode": evidence["current_account_mode"],
                "account_mode_changed_in_available_history": evidence["account_mode_changed_in_available_history"],
                "spot_inventory_observations": evidence["spot_inventory_observations"],
                "risk_unknowns": ["historical leverage and open exposure cannot be inferred from the sampled portfolio PnL curve",
                                  "spot inventory valuation, external vaults, HIP-3 scope, debt and external hedges are not fully established"],
                "reasons": reasons,
                "confidence": "low; provider-declared sampled curve, not reconciled economic performance",
                "economic_validation": False,
                "evidence": {"portfolio_source": SOURCE, "series": evidence["series"],
                             "invalid_sample_counts": evidence["invalid_sample_counts"],
                             "evidence_refs_by_endpoint": evidence["evidence_refs_by_endpoint"],
                             "markets_observed_in_fills": evidence["fill_activity"]["markets_observed"],
                             "payloads_decoded": evidence["payloads_decoded"]}}
    recent = horizons["30"]["delta"] if horizons["30"]["status"] == "reported_change" else None
    long_values = [horizons[str(d)]["delta"] for d in (90,180) if horizons[str(d)]["status"] == "reported_change"]
    recovery = recent is not None and Decimal(recent) > 0 and len(long_values) == 2 and any(Decimal(x) < 0 for x in long_values)
    recent_external_flows=evidence["observed_flow_diagnostics"]["observed_amounts_by_horizon_days"]["30"]
    recent_external_flows=[x for x in recent_external_flows if x["kind"]=="flow" and x["scope"]=="external" and Decimal(x["observed_amount"])!=0]
    decision["recovery_watch"] = {"status":"watch_recovery_signal" if recovery else "not_on_recovery_watch",
                                  "fixed_windows_days":[30,90,180],
                                  "reason":"30d provider-reported PnL is positive after a negative 90d or 180d provider-reported period; monitor only, no strategy-adaptation claim" if recovery else None,
                                  "observed_external_flows_30d":recent_external_flows,
                                  "flow_warning":"external flows were observed in the last 30d; they can explain account value changes and their full coverage is unknown" if recent_external_flows else None}
    decision["evidence"]["series"] = {k: {**{x: y for x, y in v.items() if x != "points"},
                                          "points": [[t, str(amount)] for t, amount in v["points"]]}
                                        for k, v in evidence["series"].items()}
    fingerprint_input=dict(decision)
    fingerprint_input["data_quality"]={k:v for k,v in decision["data_quality"].items() if k!="allTime_max_gap_days"}
    decision["input_fingerprint"] = _fingerprint(fingerprint_input)
    return {"decision": decision, "input_fingerprint": decision["input_fingerprint"]}


def build_report(connection: sqlite3.Connection, *, network: str, as_of_ms: int) -> dict[str, Any]:
    if type(as_of_ms) is not int or as_of_ms < 0:
        raise ValueError("An explicit UTC cutoff in milliseconds is required")
    allowed, excluded = _authorized_addresses(connection, network, as_of_ms)
    accounts = []
    for address in allowed:
        try:
            accounts.append(_analyze_account(connection, network, address, as_of_ms))
        except (ValueError, TypeError, KeyError, InvalidOperation) as exc:
            accounts.append({"decision": {"address": address, "status": "insufficiently_documented",
                            "performance_quality": "unknown", "data_quality": {"error_type": type(exc).__name__},
                            "economic_validation": False, "reasons": ["evidence could not be safely reduced"]},
                            "input_fingerprint": _fingerprint([address, as_of_ms, type(exc).__name__])})
    def priority_key(d):
        rank = {"credible_deep_dive_candidate": 0, "reported_positive_pending_activity": 1,
                "reported_positive_concentrated_or_sparse": 2, "insufficiently_documented": 3,
                "non_prioritaire_performance_declared_negative": 4}.get(d["status"], 5)
        month = d.get("weekly_monthly_consistency", {}).get("180", {}).get("month", {})
        concentration = month.get("largest_positive_bucket_share_of_positive_delta")
        return (rank, float(concentration) if concentration is not None else 2.0,
                -month.get("positive_observed_buckets", 0), -month.get("buckets_with_two_or_more_samples", 0), d["address"])
    ordered = sorted((x["decision"] for x in accounts), key=priority_key)
    counts = defaultdict(int)
    for item in ordered: counts[item["status"]] += 1
    recovery_watch = [d for d in ordered if d.get("recovery_watch",{}).get("status")=="watch_recovery_signal"]
    decoded=sum(a.get("evidence",{}).get("payloads_decoded",0) for a in ordered)
    registry_count = connection.execute("select count(*) from candidates where network=? and added_at<=?", (network, _iso(as_of_ms))).fetchone()[0] \
        if connection.execute("select 1 from sqlite_master where type='table' and name='candidates'").fetchone() else 0
    return {"schema_version": 2, "policy_version": POLICY_VERSION, "network": network,
            "as_of_ms": as_of_ms, "as_of_utc": _iso(as_of_ms), "decision_day_utc": _iso(as_of_ms)[:10],
            "cutoff_policy": {"rule": "latest data available at or before the fixed as_of_ms; no future availability",
                              "horizon_rule": "for 30/90/180/365 days use the latest sample at or before cutoff minus horizon; require start boundary lateness <= 3/7/15/30 days respectively and endpoint age <= 3 days; never interpolate",
                              "economic_claim": "allTime pnlHistory change is provider-declared only; not net validated performance"},
            "population": {"inventory": len(allowed) + len(excluded), "authorized_analyzed": len(allowed),
                           "registry_candidates_available_at_cutoff": registry_count,
                           "excluded_before_payload_read": excluded},
            "status_counts": dict(counts), "accounts": ordered,
            "recovery_watch_count":len(recovery_watch), "recovery_watch_list":recovery_watch,
            "selection_policy": {"positive_declared": "positive pnlHistory deltas at both fixed 90d and 180d bounds",
                                 "candidate_order": "credible candidates first; then positive declared accounts passing the monthly concentration guard ordered by lower concentration, then by more positive observed months, then by more observed months; dollar gains are not a ranking input",
                                 "credible_candidate": "positive declared at 90d and 180d, at least 20 observed fills on 4 UTC days, plus at least 4 measured 180d monthly boundary intervals, complete concentration coverage, and no single positive month >50% of positive observed monthly changes; fill counts are lower bounds and pagination/retention stay separate",
                                 "economic_research_gate": "requires a separate approved economic-validation record; curve-only candidates cannot open AI research",
                                 "insufficient": "missing/stale/misaligned curves or insufficient activity / period coverage; unknown is not negative",
                                 "purpose": "route for additional observation or manual review; none of these states validates a strategy"},
            "provider_calls": 0,
            "provider_requests": 0, "raw_observation_payloads_read": decoded,
            "limits": ["portfolio graph points are nominal provider samples, documented at deposits/withdrawals and 15-minute intervals; actual archive is sparse and may be revised",
                       "allTime and perpAllTime may overlap; never added together; allTime chosen as primary only",
                       "pnlHistory convention is stated by the provider but not independently reconciled; a documentation formula may be ambiguous",
                       "vlm is retained as declared volume, never interpreted as number of decisions or trades",
                       "fills and orders are partial observations; historical fills are capped/retained and pagination does not prove full account history",
                       "account-value changes are not flow-adjusted returns; sampled declines miss intraperiod drawdowns",
                       "current exposure samples do not prove historical risk; market lists reflect observed fills only"]}


def persist_decisions(connection: sqlite3.Connection, report: dict[str, Any]) -> int:
    connection.executescript(DECISION_SCHEMA)
    day = report["decision_day_utc"]
    inserted = 0
    connection.execute("BEGIN IMMEDIATE")
    try:
        for account in report["accounts"]:
            address = account["address"]
            fp = account.get("input_fingerprint") or _fingerprint([report["network"], address, report["as_of_ms"], account])
            decision_id = _fingerprint([report["network"], address, day, POLICY_VERSION, fp])
            sources = {"portfolio_source": SOURCE, "as_of_ms": report["as_of_ms"], "input_fingerprint": fp,
                       "evidence_refs_by_endpoint": account.get("evidence", {}).get("evidence_refs_by_endpoint", {})}
            cur = connection.execute(
                "insert or ignore into population_historical_decisions values (?,?,?,?,?,?,?,?,?,?)",
                (decision_id, report["network"], address, day, report["as_of_ms"], POLICY_VERSION, fp,
                 account["status"], json.dumps(sources, sort_keys=True), json.dumps(account, sort_keys=True)))
            inserted += cur.rowcount
        for excluded in report["population"]["excluded_before_payload_read"]:
            address = excluded["address"]
            fp = _fingerprint([report["network"], address, day, POLICY_VERSION, excluded["reason"]])
            decision_id = _fingerprint([report["network"], address, day, POLICY_VERSION, fp])
            summary = {"address": address, "status": "excluded_before_payload_read", "reason": excluded["reason"],
                       "economic_validation": False}
            cur = connection.execute(
                "insert or ignore into population_historical_decisions values (?,?,?,?,?,?,?,?,?,?)",
                (decision_id, report["network"], address, day, report["as_of_ms"], POLICY_VERSION, fp,
                 summary["status"], json.dumps({"registry_only": True, "as_of_ms": report["as_of_ms"]}, sort_keys=True),
                 json.dumps(summary, sort_keys=True)))
            inserted += cur.rowcount
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return inserted
