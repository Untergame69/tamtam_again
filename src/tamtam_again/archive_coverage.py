"""Bounded, read-only inventory of selected Hyperliquid archive coverage.

This module deliberately reports observed evidence, not completeness or
economic qualification. Queries are restricted to a fixed address set and an
explicit half-open event/availability interval. Market-book discovery uses a
bounded newest-tail sample because the operational archive has no
market-leading index.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from .storage import decode_observation_payload

NETWORK = "hyperliquid-mainnet"
REST_SOURCE = "hyperliquid-population-rest-v1"
WS_SOURCE = "hyperliquid-websocket-v1"
FILL_ENDPOINTS = ((REST_SOURCE, "userFillsByTime", "rest"),
                  (WS_SOURCE, "userFills", "websocket"))
ACCOUNT_HISTORY_ENDPOINTS = ("userFillsByTime", "userFunding",
                             "userNonFundingLedgerUpdates")
BOOK_ENDPOINTS = ("bbo", "l2Book")
ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}")


def parse_selection_addresses(text: str) -> list[str]:
    """Extract only rows explicitly marked as a curve/activity preselection."""
    result: list[str] = []
    for line in text.splitlines():
        if not line.startswith("|") or "présélection courbes + activité" not in line:
            continue
        match = ADDRESS_RE.search(line)
        if match:
            address = match.group(0).lower()
            if address not in result:
                result.append(address)
    return result


def iso_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat(timespec="milliseconds")


def parse_cutoff(value: str) -> int:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Cutoff must include a UTC offset")
    return int(dt.timestamp() * 1000)


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}


def protected_accounts(conn: sqlite3.Connection, *, as_of_ms: int) -> set[str]:
    """Mirror the operational address guard using plan metadata only."""
    tables = _tables(conn)
    if "validation_plans" not in tables:
        return set()
    cols = {r[1] for r in conn.execute("pragma table_info(validation_plans)")}
    if not {"plan_id", "plan_json"} <= cols or "research_window_releases" not in tables:
        return {r[0].lower() for r in conn.execute(
            "select distinct address from validation_plans where synthetic=0")}
    blocked: set[str] = set()
    for row in conn.execute("select plan_id,address,plan_json from validation_plans where synthetic=0"):
        plan = json.loads(row["plan_json"])
        if not plan.get("population_origin"):
            blocked.add(row["address"].lower())
            continue
        stages = {r[0] for r in conn.execute(
            "select stage from research_window_releases where plan_id=? and released_ms<=?",
            (row["plan_id"], as_of_ms))}
        if stages != {"comparison", "final"}:
            blocked.add(row["address"].lower())
    return blocked


def _walk(value: Any) -> Iterable[dict[str, Any]]:
    """Flatten common websocket batch envelopes without assuming one schema."""
    if isinstance(value, list):
        for item in value:
            yield from _walk(item)
        return
    if not isinstance(value, dict):
        return
    yield value
    for key in ("events", "data", "message", "fills", "updates"):
        child = value.get(key)
        if isinstance(child, (dict, list)):
            yield from _walk(child)


def _fill_rows(payload: Any) -> tuple[list[dict[str, Any]], int]:
    nodes = list(_walk(payload))
    events_batches = sum(isinstance(x, dict) and isinstance(x.get("events"), list) for x in nodes)
    fills = []
    for item in nodes:
        if (isinstance(item.get("coin"), str) and item.get("coin")
                and type(item.get("time")) is int
                and (item.get("tid") is not None or item.get("hash"))
                and any(k in item for k in ("side", "dir", "sz", "px"))):
            fills.append(item)
    # Nested walks can visit the same object through both `events` and `data`.
    unique_object_ids: set[int] = set()
    out = []
    for row in fills:
        identity = id(row)
        if identity not in unique_object_ids:
            unique_object_ids.add(identity)
            out.append(row)
    return out, events_batches


def _market_events(payload: Any, market: str) -> tuple[list[dict[str, Any]], int]:
    nodes = list(_walk(payload))
    batches = sum(isinstance(x, dict) and isinstance(x.get("events"), list) for x in nodes)
    out = []
    for item in nodes:
        coin = item.get("coin") or item.get("market")
        if coin == market and type(item.get("time")) is int:
            out.append(item)
    dedup: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in out:
        key = (row.get("channel"), row.get("time"), row.get("coin"),
               row.get("hash") or row.get("tid"),
               hashlib.sha256(json.dumps(row, sort_keys=True, default=str,
                                          separators=(",", ":")).encode()).hexdigest())
        dedup[key] = row
    return list(dedup.values()), batches


def _identity(fill: dict[str, Any]) -> tuple[str, int, str] | None:
    tid = fill.get("tid") if fill.get("tid") is not None else fill.get("hash")
    if not fill.get("coin") or type(fill.get("time")) is not int or tid is None:
        return None
    return str(fill["coin"]), fill["time"], str(tid)


def _page_overlaps_reserved(row: sqlite3.Row, intervals: list[dict[str, Any]]) -> bool:
    request = json.loads(row["request_json"])
    left = row["window_start_ms"] if row["window_start_ms"] is not None else request.get("startTime")
    right = row["window_end_ms"] if row["window_end_ms"] is not None else request.get("endTime")
    if type(left) is not int or type(right) is not int:
        return bool(intervals)
    return any(left < x["end_ms"] and right > x["start_ms"] for x in intervals)


def _plan_intervals(conn: sqlite3.Connection, addresses: set[str], cutoff_ms: int) -> dict[str, list[dict[str, Any]]]:
    tables = _tables(conn)
    if "validation_plans" not in tables:
        return {}
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    cols = {r[1] for r in conn.execute("pragma table_info(validation_plans)")}
    selected = "plan_id,address,coin,plan_json" if "coin" in cols else "plan_id,address,plan_json"
    for row in conn.execute(f"select {selected} from validation_plans where synthetic=0"):
        address = row["address"].lower()
        if address not in addresses:
            continue
        plan = json.loads(row["plan_json"])
        windows = plan.get("windows", {})
        if not isinstance(windows, dict):
            continue
        for stage, window in windows.items():
            if not isinstance(window, dict):
                continue
            left = window.get("start_ms", window.get("start"))
            right = window.get("end_ms", window.get("end"))
            if type(left) is int and type(right) is int and 0 <= left < right:
                result[address].append({
                    "stage": stage, "market": row["coin"] if "coin" in cols else None,
                    "start_ms": left, "end_ms": right,
                    "state": "reserved_or_used_plan_window",
                    "plan_ref": "validation_plans:" + row["plan_id"],
                })
    return result


def _latest_scope(conn: sqlite3.Connection, address: str, cutoff_ms: int) -> dict[str, Any] | None:
    if "account_scope_reports" not in _tables(conn):
        return None
    row = conn.execute("select report_id,available_ms,payload_json from account_scope_reports "
                       "where network=? and address=? and available_ms<=? "
                       "order by available_ms desc limit 1",
                       (NETWORK, address, cutoff_ms)).fetchone()
    if not row:
        return None
    payload = json.loads(row["payload_json"])
    profile = payload.get("current_pass_behavior_profile") or {}
    markets = {str(m) for m in payload.get("markets", []) if isinstance(m, str)}
    markets.update(str(m) for m in profile.get("markets", []) if isinstance(m, str))
    return {"ref": "account_scope_reports:" + row["report_id"],
            "available_ms": row["available_ms"], "markets": sorted(markets),
            "fill_coverage": payload.get("fill_coverage"),
            "fills_requested_start_ms": payload.get("fills_requested_start_ms"),
            "fills_requested_end_ms": payload.get("fills_requested_end_ms"),
            "profile": {k: profile.get(k) for k in
                        ("fills_observed", "market_count", "conflicting_fill_identities", "rejected_rows", "period")
                        if k in profile}}


def _fetch_account_pages(conn: sqlite3.Connection, address: str, *, since_ms: int,
                         cutoff_ms: int, max_pages: int) -> tuple[list[sqlite3.Row], bool, dict[str, dict[str, bool]]]:
    since, cutoff = iso_ms(since_ms), iso_ms(cutoff_ms)
    rows: list[sqlite3.Row] = []
    capped = False
    endpoint_limits: dict[str, dict[str, bool]] = {}
    for source, endpoint, _ in FILL_ENDPOINTS:
        endpoint_key = f"{source}:{endpoint}"
        room = max_pages - len(rows)
        if room <= 0:
            endpoint_limits[endpoint_key] = {"possibly_truncated_at_page_budget": True,
                                             "query_skipped_for_page_budget": True}
            return rows, True, endpoint_limits
        query = ("select observation_id,source,endpoint,request_json,requested_at,observed_at,"
                 "window_start_ms,window_end_ms,record_count,complete,response_encoding,response_sha256,response_json "
                 "from raw_observations where network=? and entity_type='account' and entity_id=? "
                 "and observed_at>? and observed_at<=? and source=? and endpoint=? "
                 "order by observed_at desc,observation_id desc limit ?")
        batch = conn.execute(query, (NETWORK, address, since, cutoff, source, endpoint, room)).fetchall()
        rows.extend(batch)
        hit = len(batch) == room
        endpoint_limits[endpoint_key] = {"possibly_truncated_at_page_budget": hit,
                                         "query_skipped_for_page_budget": False}
        if hit:
            capped = True
    return rows, capped, endpoint_limits


def _fetch_account_endpoint_pages(conn: sqlite3.Connection, address: str, endpoint: str, *,
                                  since_ms: int, cutoff_ms: int, max_pages: int) -> list[sqlite3.Row]:
    since, cutoff = iso_ms(since_ms), iso_ms(cutoff_ms)
    return conn.execute(
        "select observation_id,source,endpoint,request_json,requested_at,observed_at,"
        "window_start_ms,window_end_ms,record_count,complete,response_encoding,response_sha256,response_json "
        "from raw_observations where network=? and entity_type='account' and entity_id=? "
        "and observed_at>? and observed_at<=? and source=? and endpoint=? "
        "order by observed_at desc,observation_id desc limit ?",
        (NETWORK, address, since, cutoff, REST_SOURCE, endpoint, max_pages)).fetchall()


def _fee_summary(fills: list[dict[str, Any]]) -> dict[str, Any]:
    present = sum(1 for f in fills if "fee" in f and f.get("fee") is not None)
    currencies = sorted({str(f.get("feeToken")) for f in fills if f.get("feeToken") is not None})
    return {"unique_fills": len(fills), "fee_field_present": present,
            "fee_field_missing": len(fills) - present, "fee_currencies_observed": currencies,
            "completeness": "observed_fields_only; fee or rebate semantics not inferred"}


def _read_fill_pages(conn: sqlite3.Connection, address: str, rows: list[sqlite3.Row],
                     blocked_intervals: list[dict[str, Any]], *, event_cap: int,
                     since_ms: int, cutoff_ms: int) -> dict[str, Any]:
    items: dict[tuple[str, int, str], dict[str, Any]] = {}
    contents_by_id: dict[tuple[str, int, str], set[str]] = {}
    conflicts_by_market: dict[str, set[tuple[str, int, str]]] = defaultdict(set)
    conflict_refs_by_market: dict[str, set[str]] = defaultdict(set)
    conflicted_ids: set[tuple[str, int, str]] = set()
    pair_pages: dict[str, dict[str, Any]] = defaultdict(lambda: {"pages": 0, "incomplete_pages": 0,
        "events_batches": 0, "observation_refs": [], "request_windows_ms": []})
    ws_sessions_by_market: dict[str, set[str]] = defaultdict(set)
    skipped_reserved = []
    decoded_page_count = 0
    batch_total = 0
    duplicates = conflicts = malformed = 0
    for row in rows:
        ref = "raw_observations:" + str(row["observation_id"])
        source_kind = "websocket" if row["source"] == WS_SOURCE else "rest"
        if _page_overlaps_reserved(row, blocked_intervals):
            skipped_reserved.append(ref)
            continue
        request = json.loads(row["request_json"])
        stream_meta = request.get("user_fills_stream") if source_kind == "websocket" else None
        connection_id = stream_meta.get("connection_id") if isinstance(stream_meta, dict) else None
        payload = decode_observation_payload(row)
        fills, batches = _fill_rows(payload)
        decoded_page_count += 1
        batch_total += batches
        for fill in fills:
            coin = str(fill.get("coin"))
            summary = pair_pages[coin]
            if connection_id and since_ms <= fill["time"] < cutoff_ms:
                ws_sessions_by_market[coin].add(str(connection_id))
            if not since_ms <= fill["time"] < cutoff_ms:
                continue
            if fill["time"] < 0:
                malformed += 1
                continue
            key = _identity(fill)
            if key is None:
                malformed += 1
                continue
            content = json.dumps(fill, sort_keys=True, separators=(",", ":"), default=str)
            if key in contents_by_id:
                if content in contents_by_id[key]:
                    duplicates += 1
                else:
                    conflicts += 1
                    conflicted_ids.add(key)
                    conflicts_by_market[coin].add(key)
                    conflict_refs_by_market[coin].add(ref)
                    if key in items:
                        conflict_refs_by_market[coin].add(items[key]["evidence_ref"])
                    contents_by_id[key].add(content)
                    # No payload version is safe for derived metrics.
                continue
            if len(items) >= event_cap:
                return {"pairs": {}, "decoded_pages": decoded_page_count,
                        "pages_capped": True, "events_capped": True,
                        "events_batches": batch_total,
                        "duplicate_events": duplicates, "conflicting_events": conflicts,
                        "malformed_events": malformed,
                        "skipped_reserved_pages": skipped_reserved,
                        "error": "event_cap_reached_after_page_decode"}
            items[key] = {"fill": fill, "available_ms": parse_cutoff(row["observed_at"]),
                          "requested_ms": parse_cutoff(row["requested_at"]), "source": source_kind,
                          "evidence_ref": ref}
            contents_by_id[key] = {content}
    by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for key, item in items.items():
        if key in conflicted_ids:
            continue
        by_market[str(item["fill"]["coin"])].append(item)
    pair_result = {}
    timing_by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_markets = set(by_market) | set(conflicts_by_market)
    for market in sorted(all_markets):
        market_rows = by_market.get(market, [])
        market_rows.sort(key=lambda x: (x["fill"]["time"], x["available_ms"], x["evidence_ref"]))
        ev = [x["fill"]["time"] for x in market_rows]
        av = [x["available_ms"] for x in market_rows]
        per_source = defaultdict(list)
        for item in market_rows:
            per_source[item["source"]].append(item)
            timing_by_market[market].append({"event_ms": item["fill"]["time"],
                "available_ms": item["available_ms"], "source": item["source"],
                "side": item["fill"].get("side"), "sz": item["fill"].get("sz")})
        fill_list = [x["fill"] for x in market_rows]
        fee = _fee_summary(fill_list)
        position = _position_delta(fill_list)
        conflict_count = len(conflicts_by_market.get(market, set()))
        if conflict_count:
            position = {**position, "status": "unknown_conflicting_fill_identities",
                        "net_size_delta": None,
                        "reason": "conflicted fill identities were excluded from derived position delta"}
            fee["completeness"] = "incomplete_conflicting_fill_identities; observed fields only"
        pair_result[market] = {
            "fills": {"unique_events": len(market_rows), "event_period_ms": [min(ev), max(ev)] if ev else None,
                      "local_available_period_ms": [min(av), max(av)] if av else None,
                      "conflicting_identity_count": conflict_count,
                      "conflicting_identity_refs": sorted(conflict_refs_by_market.get(market, set()))[:25],
                      "provenance": {k: {"unique_events": len(v),
                          "event_period_ms": [min(x["fill"]["time"] for x in v), max(x["fill"]["time"] for x in v)],
                          "available_period_ms": [min(x["available_ms"] for x in v), max(x["available_ms"] for x in v)],
                          "evidence_refs": sorted({x["evidence_ref"] for x in v})[:25],
                          "refs_truncated": len({x["evidence_ref"] for x in v}) > 25}
                          for k, v in per_source.items()}},
            "fees": fee,
            "position_reconstruction": position,
            "websocket_connection_ids": sorted(ws_sessions_by_market.get(market, set())),
            "evidence_refs": sorted({x["evidence_ref"] for x in market_rows})[:25],
        }
    return {"pairs": pair_result, "decoded_pages": decoded_page_count,
            "pages_capped": False, "events_capped": False,
            "events_batches": batch_total,
            "duplicate_events": duplicates, "conflicting_events": conflicts,
            "malformed_events": malformed, "skipped_reserved_pages": skipped_reserved,
            "unique_fills": len(items), "timing_by_market": timing_by_market,
            "websocket_connection_ids": sorted({sid for ids in ws_sessions_by_market.values() for sid in ids})}


def _summarize_stream_health(events: list[dict[str, Any]], *, heartbeat_gap_ms: int = 65_000) -> dict[str, Any]:
    events.sort(key=lambda x: (x["available_ms"], x["evidence_ref"]))
    heartbeats = [x["available_ms"] for x in events if x.get("kind") == "heartbeat"]
    gaps = [right - left for left, right in zip(heartbeats, heartbeats[1:])]
    disconnects = [x["available_ms"] for x in events
                   if x.get("kind") == "connection" and x.get("connected") is False]
    kinds: dict[str, int] = defaultdict(int)
    for event in events:
        kinds[str(event.get("kind", "unknown"))] += 1
    return {
        "status": "observed_session_health_not_account_subscription_proof" if events else "session_health_not_exported",
        "events_observed": len(events), "event_kinds": dict(sorted(kinds.items())),
        "available_period_ms": [events[0]["available_ms"], events[-1]["available_ms"]] if events else None,
        "heartbeat_gap_threshold_ms": heartbeat_gap_ms,
        "heartbeat_gaps_over_threshold": sum(gap > heartbeat_gap_ms for gap in gaps),
        "maximum_heartbeat_gap_ms": max(gaps, default=None),
        "explicit_disconnect_count": len(disconnects),
        "first_explicit_disconnect_ms": min(disconnects) if disconnects else None,
        "right_censored_at_cutoff": bool(events and not disconnects),
        "evidence_refs": sorted({x["evidence_ref"] for x in events})[:25],
        "refs_truncated": len({x["evidence_ref"] for x in events}) > 25,
    }


def _read_stream_health(conn: sqlite3.Connection, sessions_to_accounts: dict[str, set[str]], *,
                        since_ms: int, cutoff_ms: int, max_events: int = 50_000) -> dict[str, Any]:
    """Read only bounded health events for connections proven by selected user-fill frames."""
    since, cutoff = iso_ms(since_ms), iso_ms(cutoff_ms)
    remaining = max_events
    result = {}
    events_decoded = 0
    capped_sessions = []
    for session in sorted(sessions_to_accounts):
        if remaining <= 0:
            capped_sessions.extend(sorted(set(sessions_to_accounts) - set(result)))
            break
        # One predecessor supplies boundary context; it is not counted in the requested interval.
        before = conn.execute(
            "select observation_id,observed_at,response_encoding,response_json from raw_observations "
            "where network=? and source=? and entity_type='stream' and entity_id=? and endpoint='streamHealth' "
            "and observed_at<=? order by observed_at desc,observation_id desc limit 1",
            (NETWORK, WS_SOURCE, session, since)).fetchone()
        rows = conn.execute(
            "select observation_id,observed_at,response_encoding,response_json from raw_observations "
            "where network=? and source=? and entity_type='stream' and entity_id=? and endpoint='streamHealth' "
            "and observed_at>? and observed_at<=? order by observed_at,observation_id limit ?",
            (NETWORK, WS_SOURCE, session, since, cutoff, remaining + 1)).fetchall()
        capped = len(rows) > remaining
        if capped:
            rows = rows[:remaining]
            capped_sessions.append(session)
        selected = ([before] if before else []) + rows
        events = []
        for row in selected:
            payload = decode_observation_payload(row)
            if not isinstance(payload, dict):
                continue
            available = parse_cutoff(row["observed_at"])
            events.append({"kind": payload.get("kind"), "connected": payload.get("connected"),
                           "available_ms": available, "evidence_ref": "raw_observations:" + str(row["observation_id"])})
        events.sort(key=lambda x: (x["available_ms"], x["evidence_ref"]))
        in_window = [x for x in events if since_ms < x["available_ms"] <= cutoff_ms]
        summary = _summarize_stream_health(events)
        # Keep in-window metrics separate from the predecessor used only for boundary context.
        summary["events_observed"] = len(in_window)
        summary["status"] = ("observed_session_health_not_account_subscription_proof" if in_window
                             else "session_health_not_exported_in_window")
        summary["available_period_ms"] = ([in_window[0]["available_ms"], in_window[-1]["available_ms"]]
                                           if in_window else None)
        summary["event_kinds"] = dict(sorted((kind, sum(x.get("kind") == kind for x in in_window))
                                             for kind in {str(x.get("kind", "unknown")) for x in in_window}))
        summary["evidence_refs"] = sorted({x["evidence_ref"] for x in in_window})[:25]
        summary["refs_truncated"] = len({x["evidence_ref"] for x in in_window}) > 25
        summary["explicit_disconnect_count"] = sum(x.get("kind") == "connection" and x.get("connected") is False for x in in_window)
        summary["first_explicit_disconnect_ms"] = min((x["available_ms"] for x in in_window
            if x.get("kind") == "connection" and x.get("connected") is False), default=None)
        window_heartbeats = [x["available_ms"] for x in in_window if x.get("kind") == "heartbeat"]
        all_heartbeats = [x["available_ms"] for x in events if x.get("kind") == "heartbeat"]
        gaps = [right-left for left,right in zip(all_heartbeats,all_heartbeats[1:])]
        summary["heartbeat_gaps_over_threshold"] = sum(g > summary["heartbeat_gap_threshold_ms"] for g in gaps)
        summary["maximum_heartbeat_gap_ms"] = max(gaps, default=None)
        summary["right_censored_at_cutoff"] = bool(in_window and not summary["explicit_disconnect_count"])
        summary["boundary_predecessor_ref"] = "raw_observations:" + str(before["observation_id"]) if before else None
        summary["associated_account_refs"] = sorted(sessions_to_accounts[session])
        summary["event_cap_reached"] = capped
        result[session] = summary
        events_decoded += len(rows)
        remaining -= len(rows)
    return {"sessions": result, "sessions_observed": len(result), "events_decoded": events_decoded,
            "max_events": max_events, "event_cap_reached": bool(capped_sessions),
            "capped_session_ids": sorted(set(capped_sessions)),
            "method": "health sessions mapped only from selected account userFills frames; no per-account subscription acknowledgement is archived"}


def _position_delta(fills: list[dict[str, Any]]) -> dict[str, Any]:
    signed = Decimal(0)
    signed_count = 0
    bad = 0
    for fill in fills:
        try:
            size = Decimal(str(fill["sz"]))
            side = fill.get("side")
            if side not in ("B", "A", "S") or not size.is_finite() or size < 0:
                # Hyperliquid public fills use B/S, but variants and other
                # payloads are retained as unknown instead of guessed.
                bad += 1
                continue
            signed += size if side == "B" else -size
            signed_count += 1
        except (KeyError, TypeError, ValueError, InvalidOperation):
            bad += 1
    return {"status": "net_fill_delta_only" if signed_count and not bad else "unknown",
            "signed_event_count": signed_count, "direction_or_size_unknown": bad,
            "net_size_delta": str(signed) if signed_count and not bad else None,
            "initial_position": "unknown", "final_position": "unknown",
            "coherent_position_proven": False,
            "reason": "fills alone cannot establish boundary positions or prove no missing fills"}


def _state_snapshots(conn: sqlite3.Connection, address: str, *, since_ms: int, cutoff_ms: int,
                     reserved: list[dict[str, Any]], cap: int = 50) -> dict[str, Any]:
    """Read bounded state snapshots only after checking their times against reserves."""
    since, cutoff = iso_ms(since_ms), iso_ms(cutoff_ms)
    columns = "observation_id,observed_at,request_json"
    before = conn.execute(
        "select " + columns + " from raw_observations where network=? and entity_type='account' "
        "and entity_id=? and source=? and endpoint='clearinghouseState' and observed_at<=? "
        "order by observed_at desc,observation_id desc limit 1",
        (NETWORK, address, REST_SOURCE, since)).fetchall()
    room = max(0, cap - len(before))
    earlier = conn.execute(
        "select " + columns + " from raw_observations where network=? and entity_type='account' "
        "and entity_id=? and source=? and endpoint='clearinghouseState' and observed_at>? and observed_at<=? "
        "order by observed_at,observation_id limit ?",
        (NETWORK, address, REST_SOURCE, since, cutoff, room // 2)).fetchall() if room else []
    latest = conn.execute(
        "select " + columns + " from raw_observations where network=? and entity_type='account' "
        "and entity_id=? and source=? and endpoint='clearinghouseState' and observed_at>? and observed_at<=? "
        "order by observed_at desc,observation_id desc limit ?",
        (NETWORK, address, REST_SOURCE, since, cutoff, room - len(earlier))).fetchall() if room > len(earlier) else []
    metadata = {r["observation_id"]: r for r in (*before, *earlier, *latest)}
    snapshots = []
    skipped = []
    for row in sorted(metadata.values(), key=lambda r: (r["observed_at"], r["observation_id"])):
        available = parse_cutoff(row["observed_at"])
        if any(x["start_ms"] <= available < x["end_ms"] for x in reserved):
            skipped.append("raw_observations:" + str(row["observation_id"]))
            continue
        payload_row = conn.execute("select response_encoding,response_json from raw_observations where observation_id=?",
                                   (row["observation_id"],)).fetchone()
        payload = decode_observation_payload(payload_row)
        request = json.loads(row["request_json"])
        positions = {}
        if isinstance(payload, dict):
            for entry in payload.get("assetPositions", []):
                position = entry.get("position") if isinstance(entry, dict) else None
                if isinstance(position, dict) and isinstance(position.get("coin"), str):
                    try:
                        positions[position["coin"]] = str(Decimal(str(position.get("szi", "0"))))
                    except (InvalidOperation, TypeError, ValueError):
                        continue
        snapshots.append({"available_ms": available, "event_ms": _snapshot_event_ms(request, payload),
                          "dex": request.get("dex", ""),
                          "positions": positions,
                          "evidence_ref": "raw_observations:" + str(row["observation_id"])})
    return {"snapshots": snapshots, "skipped_reserved_refs": skipped,
            "metadata_rows_selected": len(metadata), "sample_cap": cap,
            "sample_is_boundary_biased": True}


def _snapshot_event_ms(request: dict[str, Any], payload: Any) -> int | None:
    """Read the response event time used by the account adapter, never request or receipt time."""
    del request  # A requested as-of value is not evidence of when the returned state was true.
    value = payload.get("time") if isinstance(payload, dict) else None
    return value if type(value) is int and value >= 0 else None


def _position_boundary_check(market: str, fill_points: list[dict[str, Any]],
                             snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    dex = market.split(":", 1)[0] if ":" in market else ""
    compatible = sorted((s for s in snapshots if s["dex"] == dex),
                        key=lambda s: s.get("event_ms") if s.get("event_ms") is not None else -1)
    if len(compatible) < 2:
        return {"status": "missing_boundary_snapshots", "coherent_position_proven": False,
                "snapshots_available": len(compatible),
                "reason": "fewer than two nonreserved snapshots for market dex"}
    start, end = compatible[0], compatible[-1]
    # Do not compare local observation availability with exchange event time.
    if type(start.get("event_ms")) is not int or type(end.get("event_ms")) is not int:
        return {"status": "unknown_noncomparable_boundaries", "coherent_position_proven": False,
                "snapshots_available": len(compatible),
                "snapshot_refs": [start["evidence_ref"], end["evidence_ref"]],
                "reason": "snapshot source event timestamps are absent; receipt time cannot be compared with fill event time"}
    if start["event_ms"] >= end["event_ms"]:
        return {"status": "missing_boundary_snapshots", "coherent_position_proven": False,
                "snapshots_available": len(compatible), "reason": "no distinct snapshot boundaries"}
    try:
        start_size = Decimal(start["positions"].get(market, "0"))
        end_size = Decimal(end["positions"].get(market, "0"))
        fill_delta = Decimal(0)
        n = 0
        unknown = 0
        for fill in fill_points:
            if not start["event_ms"] <= fill["event_ms"] < end["event_ms"]:
                continue
            if fill.get("side") not in ("B", "A", "S"):
                unknown += 1
                continue
            size = Decimal(str(fill["sz"]))
            if not size.is_finite() or size < 0:
                unknown += 1
                continue
            fill_delta += size if fill["side"] == "B" else -size
            n += 1
        state_delta = end_size - start_size
        matched = unknown == 0 and n > 0 and state_delta == fill_delta
        return {"status": "arithmetic_match_on_observed_interval" if matched else
                "observed_fill_state_delta_mismatch_or_incomplete",
                "coherent_position_proven": False, "observed_signed_fill_delta": str(fill_delta),
                "state_size_delta": str(state_delta), "fills_compared": n,
                "fills_with_unknown_direction_or_size": unknown,
                "snapshot_refs": [start["evidence_ref"], end["evidence_ref"]],
                "boundary_event_ms": [start["event_ms"], end["event_ms"]],
                "boundary_availability_ms": [start["available_ms"], end["available_ms"]],
                "reason": "comparable source event clocks; pagination and API retention are not a completeness proof"}
    except (InvalidOperation, TypeError, ValueError):
        return {"status": "unknown_state_or_fill_size", "coherent_position_proven": False,
                "snapshot_refs": [start["evidence_ref"], end["evidence_ref"]]}


def _history_pages(conn: sqlite3.Connection, address: str, *, since_ms: int,
                   cutoff_ms: int, max_pages: int, reserved: list[dict[str, Any]],
                   fill_rows: list[sqlite3.Row],
                   fill_endpoint_limits: dict[str, dict[str, bool]] | None = None) -> tuple[dict[str, Any], int]:
    result = {}
    pages_read = 0
    capped = False
    for endpoint in ACCOUNT_HISTORY_ENDPOINTS:
        endpoint_possibly_truncated = False
        query_skipped_for_budget = False
        if endpoint == "userFillsByTime":
            rows = [r for r in fill_rows if r["endpoint"] == endpoint and r["source"] == REST_SOURCE]
            fill_limit = (fill_endpoint_limits or {}).get(f"{REST_SOURCE}:{endpoint}", {})
            endpoint_possibly_truncated = bool(fill_limit.get("possibly_truncated_at_page_budget"))
            query_skipped_for_budget = bool(fill_limit.get("query_skipped_for_page_budget"))
        else:
            room = max_pages - pages_read
            if room <= 0:
                rows = []
                capped = True
                endpoint_possibly_truncated = True
                query_skipped_for_budget = True
            else:
                rows = _fetch_account_endpoint_pages(conn, address, endpoint, since_ms=since_ms,
                                                     cutoff_ms=cutoff_ms, max_pages=room)
                if len(rows) == room:
                    capped = True
                    endpoint_possibly_truncated = True
        pages_read += len(rows) if endpoint != "userFillsByTime" else 0
        decoded = 0
        events = 0
        batches = 0
        refs = []
        skipped = []
        incomplete = 0
        funding_by_market: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "event_ms": [], "available_ms": [], "evidence_refs": []})
        intervals = []
        for row in rows:
            ref = "raw_observations:" + str(row["observation_id"])
            if _page_overlaps_reserved(row, reserved):
                skipped.append(ref)
                continue
            request = json.loads(row["request_json"])
            left = row["window_start_ms"] if row["window_start_ms"] is not None else request.get("startTime")
            right = row["window_end_ms"] if row["window_end_ms"] is not None else request.get("endTime")
            if type(left) is int and type(right) is int:
                intervals.append([left, right])
            if not row["complete"] or request.get("pagination_status") not in (None, "pagination_exhausted"):
                incomplete += 1
            payload = decode_observation_payload(row)
            nodes = list(_walk(payload))
            batches += sum(isinstance(x, dict) and isinstance(x.get("events"), list) for x in nodes)
            if isinstance(payload, list):
                events += len(payload)
            else:
                events += sum(1 for x in nodes if x.get("time") is not None and x.get("delta") is not None)
            if endpoint == "userFunding":
                for event in nodes:
                    delta = event.get("delta")
                    if (isinstance(delta, dict) and delta.get("type") == "funding"
                            and isinstance(delta.get("coin"), str) and type(event.get("time")) is int
                            and since_ms <= event["time"] < cutoff_ms):
                        bucket = funding_by_market[delta["coin"]]
                        bucket["event_ms"].append(event["time"])
                        bucket["available_ms"].append(parse_cutoff(row["observed_at"]))
                        if ref not in bucket["evidence_refs"] and len(bucket["evidence_refs"]) < 20:
                            bucket["evidence_refs"].append(ref)
            refs.append(ref)
            decoded += 1
        refs = sorted(set(refs))
        result[endpoint] = {"pages_observed": len(rows), "pages_decoded": decoded,
            "event_rows_observed": events, "events_batches": batches,
            "incomplete_pages": incomplete,
            "skipped_reserved_pages": skipped[:25], "skipped_reserved_page_count": len(skipped),
            "possibly_truncated_at_page_budget": endpoint_possibly_truncated,
            "query_skipped_for_page_budget": query_skipped_for_budget,
            "request_intervals_ms": _merge_ms_intervals(intervals), "evidence_refs": refs[:25],
            "refs_truncated": len(refs) > 25,
            "coverage_claim": "observed pages only; pagination and local retention do not prove endpoint-history completeness"}
        if endpoint == "userFunding":
            result[endpoint]["by_market"] = {market: {
                "events_observed": len(info["event_ms"]),
                "event_period_ms": [min(info["event_ms"]), max(info["event_ms"])],
                "available_period_ms": [min(info["available_ms"]), max(info["available_ms"])],
                "evidence_refs": info["evidence_refs"],
                "currency_scope": "funding row observed; currency semantics require perps/deployer metadata"}
                for market, info in sorted(funding_by_market.items())}
    return result, pages_read


def _merge_ms_intervals(intervals: list[list[int]]) -> list[list[int]]:
    merged: list[list[int]] = []
    for left, right in sorted(intervals):
        if merged and left <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], right)
        else:
            merged.append([left, right])
    return merged


def _read_book_tail(conn: sqlite3.Connection, markets: set[str], *, since_ms: int, cutoff_ms: int,
                    sample_rows_per_endpoint: int) -> dict[str, Any]:
    since, cutoff = iso_ms(since_ms), iso_ms(cutoff_ms)
    by_market: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    endpoint_counts = {}
    capped = {}
    for endpoint in BOOK_ENDPOINTS:
        rows = conn.execute(
            "select observation_id,entity_id,observed_at,record_count,complete "
            "from raw_observations where network=? and source=? and endpoint=? and observed_at>? and observed_at<=? "
            "order by observed_at desc,observation_id desc limit ?",
            (NETWORK, WS_SOURCE, endpoint, since, cutoff, sample_rows_per_endpoint)).fetchall()
        endpoint_counts[endpoint] = len(rows)
        capped[endpoint] = len(rows) == sample_rows_per_endpoint
        selected = [r for r in rows if r["entity_id"] in markets]
        by_id = {r["observation_id"]: r for r in selected}
        for start in range(0, len(selected), 400):
            ids = list(by_id)[start:start + 400]
            if not ids:
                continue
            marks = ",".join("?" for _ in ids)
            payload_rows = conn.execute(
                f"select observation_id,response_encoding,response_json from raw_observations where observation_id in ({marks})",
                ids).fetchall()
            from .storage import decode_observation_payload
            for payload_row in payload_rows:
                meta = by_id[payload_row["observation_id"]]
                market = meta["entity_id"]
                payload = decode_observation_payload(payload_row)
                events, batches = _market_events(payload, market)
                summary = by_market[market].setdefault(endpoint, {"observations": 0,
                    "events": 0, "batches": 0, "available_ms": [], "event_ms": [],
                    "evidence_refs": [], "join_points": []})
                summary["observations"] += 1
                summary["events"] += len(events)
                summary["batches"] += batches
                available = parse_cutoff(meta["observed_at"])
                summary["available_ms"].append(available)
                summary["event_ms"].extend(x["time"] for x in events)
                if len(summary["join_points"]) < 100000:
                    summary["join_points"].extend((x["time"], available) for x in events[:100000-len(summary["join_points"])])
                ref = "raw_observations:" + str(meta["observation_id"])
                if len(summary["evidence_refs"]) < 10:
                    summary["evidence_refs"].append(ref)
    result = {}
    for market, summaries in sorted(by_market.items()):
        result[market] = {}
        for endpoint in BOOK_ENDPOINTS:
            summary = summaries.get(endpoint, {"observations": 0, "events": 0, "batches": 0,
                "available_ms": [], "event_ms": [], "evidence_refs": [], "join_points": []})
            result[market][endpoint] = {
                "sampled_observations": summary["observations"],
                "nested_events": summary["events"],
                "events_batches": summary["batches"],
                "available_period_ms": ([min(summary["available_ms"]), max(summary["available_ms"])]
                                        if summary["available_ms"] else None),
                "event_period_ms": ([min(summary["event_ms"]), max(summary["event_ms"])]
                                    if summary["event_ms"] else None),
                "sample_is_tail": True,
                "global_endpoint_sample_rows": endpoint_counts[endpoint],
                "sample_cap_reached": capped[endpoint],
                "evidence_refs": summary["evidence_refs"],
                "_join_points": summary["join_points"],
            }
    return {"markets": result, "global_sample_rows": endpoint_counts,
            "global_sample_caps_reached": capped,
            "method": "newest websocket rows by endpoint, global bounded tail; no market-leading index, so unsampled intervals are unknown"}


def _book_join(fill_points: list[dict[str, Any]], market_book: dict[str, Any], *, sample_capped: dict[str, bool]) -> dict[str, Any]:
    result = {"matched_fill_events": {}, "sample_capped": sample_capped,
              "proof": "strictly prior event timestamp and local observation available by fill receipt; sample only"}
    for endpoint in BOOK_ENDPOINTS:
        raw = market_book.get(endpoint, {}).get("_join_points", [])
        points = sorted(raw)
        event_times = [x[0] for x in points]
        counts = {"websocket": {"prior_within_1s": 0, "prior_within_5s": 0, "prior_within_30s": 0},
                  "rest": {"prior_within_1s": 0, "prior_within_5s": 0, "prior_within_30s": 0}}
        for fill in fill_points:
            i = bisect_right(event_times, fill["event_ms"] - 1) - 1
            while i >= 0 and points[i][1] > fill["available_ms"]:
                i -= 1
            if i < 0:
                continue
            age = fill["event_ms"] - points[i][0]
            for threshold, name in ((1000, "prior_within_1s"), (5000, "prior_within_5s"), (30000, "prior_within_30s")):
                if 0 <= age <= threshold:
                    counts[fill["source"]][name] += 1
        result["matched_fill_events"][endpoint] = counts
    return result


def build_manifest(conn: sqlite3.Connection, selection_addresses: list[str], *,
                   since_ms: int, cutoff_ms: int, max_accounts: int = 64,
                   max_pages_per_account: int = 300,
                   max_total_pages: int = 25000,
                   max_book_rows_per_endpoint: int = 20000,
                   max_events_per_account: int = 250000) -> dict[str, Any]:
    if not 0 <= since_ms < cutoff_ms:
        raise ValueError("Require an explicit nonempty [since, cutoff) window")
    conn.row_factory = sqlite3.Row
    conn.execute("pragma query_only=on")
    blocked = protected_accounts(conn, as_of_ms=cutoff_ms)
    selected = list(dict.fromkeys(x.lower() for x in selection_addresses))
    tracked = [r[0].lower() for r in conn.execute(
        "select address from candidates where network=? and status='tracked' order by address",
        (NETWORK,))]
    # Keep the currently collected websocket cohort in the budget before the
    # historical preselection set, while preserving report order within each.
    target_addresses = list(dict.fromkeys(tracked + selected))
    if len(target_addresses) > max_accounts:
        raise ValueError(f"address cap exceeded: {len(target_addresses)} > {max_accounts}")
    eligible = [a for a in target_addresses if a not in blocked]
    plan_windows = _plan_intervals(conn, set(target_addresses), cutoff_ms)
    status_rows = {r[0]: r[1] for r in conn.execute(
        "select address,status from candidates where network=? and address in ("+
        ",".join("?" for _ in target_addresses)+")", (NETWORK, *target_addresses))} if target_addresses else {}
    db_counts = {
        "rest_history_accounts": conn.execute("select count(distinct address) from population_history_cursors").fetchone()[0]
            if "population_history_cursors" in _tables(conn) else None,
        "rest_accounts_by_status": [dict(status=r[0], count=r[1]) for r in conn.execute(
            "select status,count(*) from population_accounts group by status")]
            if "population_accounts" in _tables(conn) else [],
        "cursor_statuses": [dict(endpoint=r[0], status=r[1], count=r[2]) for r in conn.execute(
            "select endpoint,status,count(*) from population_history_cursors group by endpoint,status")]
            if "population_history_cursors" in _tables(conn) else [],
        "research_targets": conn.execute("select count(*) from research_targets").fetchone()[0]
            if "research_targets" in _tables(conn) else None,
        "validation_plans": conn.execute("select count(*) from validation_plans where synthetic=0").fetchone()[0]
            if "validation_plans" in _tables(conn) else None,
        "released_periods": conn.execute("select count(*) from research_period_releases").fetchone()[0]
            if "research_period_releases" in _tables(conn) else None,
        "consumed_holdouts": conn.execute("select count(*) from consumed_holdouts").fetchone()[0]
            if "consumed_holdouts" in _tables(conn) else None,
        "validation_evaluations": conn.execute("select count(*) from validation_evaluations").fetchone()[0]
            if "validation_evaluations" in _tables(conn) else None,
    }
    accounts = []
    all_markets: set[str] = set()
    sessions_to_accounts: dict[str, set[str]] = defaultdict(set)
    total_pages_read = 0
    for address in eligible:
        scope = _latest_scope(conn, address, cutoff_ms)
        markets = set(scope["markets"] if scope else [])
        targets = [r[0] for r in conn.execute(
            "select distinct coin from research_targets where network=? and address=? order by coin",
            (NETWORK, address))] if "research_targets" in _tables(conn) else []
        markets.update(targets)
        windows = plan_windows.get(address, [])
        markets.update(str(w["market"]) for w in windows if w.get("market"))
        total_room = max(0, max_total_pages - total_pages_read)
        fill_page_limit = min(max_pages_per_account, total_room)
        rows, page_capped, fill_endpoint_limits = _fetch_account_pages(conn, address, since_ms=since_ms,
                                                 cutoff_ms=cutoff_ms, max_pages=fill_page_limit)
        total_pages_read += len(rows)
        fill_data = _read_fill_pages(conn, address, rows, windows,
                                     event_cap=max_events_per_account,
                                     since_ms=since_ms, cutoff_ms=cutoff_ms)
        for session_id in fill_data.get("websocket_connection_ids", []):
            sessions_to_accounts[session_id].add(address)
        markets.update(fill_data.get("pairs", {}).keys())
        total_room = max(0, max_total_pages - total_pages_read)
        histories, history_pages_read = _history_pages(conn, address, since_ms=since_ms, cutoff_ms=cutoff_ms,
                                   max_pages=min(max_pages_per_account, total_room), reserved=windows,
                                   fill_rows=rows, fill_endpoint_limits=fill_endpoint_limits)
        total_pages_read += history_pages_read
        markets.update(histories.get("userFunding", {}).get("by_market", {}).keys())
        snapshots = _state_snapshots(conn, address, since_ms=since_ms, cutoff_ms=cutoff_ms,
                                     reserved=windows, cap=50)
        cursor_statuses = {}
        if "population_history_cursors" in _tables(conn):
            cursor_statuses = {r["endpoint"]: {"status": r["status"], "cursor_ms": r["cursor_ms"],
                "target_end_ms": r["target_end_ms"], "updated_at": r["updated_at"]}
                for r in conn.execute("select endpoint,status,cursor_ms,target_end_ms,updated_at "
                    "from population_history_cursors where network=? and address=?",
                    (NETWORK, address))}
        all_markets.update(markets)
        pairs = {}
        for market in sorted(markets):
            fill_record = fill_data.get("pairs", {}).get(market, {
                    "fills": {"unique_events": 0, "event_period_ms": None, "local_available_period_ms": None,
                        "conflicting_identity_count": 0, "conflicting_identity_refs": [], "provenance": {}},
                    "fees": {"unique_fills": 0, "fee_field_present": 0,
                        "fee_field_missing": 0, "fee_currencies_observed": [],
                        "completeness": "no decoded fills in interval; absence does not prove no activity"},
                    "position_reconstruction": {"status": "unknown", "coherent_position_proven": False,
                        "reason": "no locally decoded fills in bounded interval"}, "evidence_refs": []})
            boundary_check = _position_boundary_check(market,
                fill_data.get("timing_by_market", {}).get(market, []), snapshots["snapshots"])
            conflict_count = fill_record.get("fills", {}).get("conflicting_identity_count", 0)
            if conflict_count:
                boundary_check = {"status": "unknown_conflicting_fill_identities",
                    "coherent_position_proven": False, "conflicting_identity_count": conflict_count,
                    "reason": "state-boundary reconciliation is unknown because conflicting fill identities were excluded"}
            pairs[market] = {
                "fills": fill_record.get("fills", {}),
                "fees": fill_record.get("fees", {}),
                "websocket_connection_ids": fill_record.get("websocket_connection_ids", []),
                "book_evidence": "pending_bounded_market_sample",
                "funding": histories.get("userFunding", {}).get("by_market", {}).get(market, {
                    "events_observed": 0, "event_period_ms": None, "available_period_ms": None,
                    "evidence_refs": [], "status": "no funding rows decoded in bounded interval; absence is not a zero-funding proof"}),
                "period_access": [w for w in windows if w.get("market") in (None, market)],
                "position_reconstruction": {**boundary_check,
                    "fill_delta_only": fill_record.get("position_reconstruction")},
                "evidence_refs": fill_record.get("evidence_refs", []),
            }
        accounts.append({"address": address,
            "selection_candidate": address in selected,
            "currently_tracked": address in tracked,
            "candidate_status": status_rows.get(address),
            "protected": False,
            "scope_report": scope,
            "account_page_refs": sorted({ref for pair in fill_data.get("pairs", {}).values()
                                           for ref in pair.get("evidence_refs", [])}),
            "scan": {"observations_decoded": fill_data.get("decoded_pages", 0),
                     "account_page_query_capped": page_capped or fill_data.get("pages_capped", False),
                     "global_page_budget_exhausted": total_pages_read >= max_total_pages,
                     "event_cap_reached": fill_data.get("events_capped", False),
                     "events_batches": fill_data.get("events_batches", 0),
                     "duplicate_events": fill_data.get("duplicate_events", 0),
                     "conflicting_events": fill_data.get("conflicting_events", 0),
                     "malformed_events": fill_data.get("malformed_events", 0),
                     "skipped_reserved_pages": fill_data.get("skipped_reserved_pages", []),
                     "fill_endpoint_limits": fill_endpoint_limits,
                     "unprocessed_reason": fill_data.get("error")},
            "pairs": pairs,
            "accounting_history": histories,
            "history_cursor_statuses": cursor_statuses,
            "position_snapshot_inventory": {k: v for k, v in snapshots.items() if k != "snapshots"},
            "websocket_connection_ids": fill_data.get("websocket_connection_ids", []),
            "_fill_timing": fill_data.get("timing_by_market", {}),
            "allowed_periods": {"exploration": "public archived data only; no validation permission inferred",
                                "reserved_or_used_windows": windows},
        })
    # Keep protected addresses visible by reference only; never query their payloads.
    protected_in_scope = [a for a in target_addresses if a in blocked]
    stream_health = _read_stream_health(conn, sessions_to_accounts, since_ms=since_ms,
                                        cutoff_ms=cutoff_ms, max_events=50_000)
    book = _read_book_tail(conn, all_markets, since_ms=since_ms, cutoff_ms=cutoff_ms,
                           sample_rows_per_endpoint=max_book_rows_per_endpoint)
    for account in accounts:
        for market, pair in account["pairs"].items():
            sampled = book["markets"].get(market, {})
            pair["book_join"] = _book_join(account.get("_fill_timing", {}).get(market, []), sampled,
                sample_capped=book["global_sample_caps_reached"])
            pair["book_evidence"] = {endpoint: {k: v for k, v in details.items() if not k.startswith("_")}
                                      for endpoint, details in sampled.items()}
        account.pop("_fill_timing", None)
    return {"schema_version": "archive-coverage-v1",
        "network": NETWORK,
        "window": {"since_ms": since_ms, "since_utc": iso_ms(since_ms),
                   "cutoff_ms": cutoff_ms, "cutoff_utc": iso_ms(cutoff_ms),
                   "event_interval": "[since, cutoff)",
                   "receipt_rule": "raw observations with observed_at <= cutoff; fills additionally require event time < cutoff"},
        "limits": {"max_accounts": max_accounts, "max_pages_per_account": max_pages_per_account,
                   "max_total_pages": max_total_pages, "pages_read": total_pages_read,
                   "max_events_per_account": max_events_per_account,
                   "max_book_rows_per_endpoint": max_book_rows_per_endpoint},
        "inventory": db_counts,
        "selection": {"candidate_count": len(selected), "candidate_addresses": selected,
                      "currently_tracked_count": len(tracked), "tracked_addresses": tracked,
                      "detailed_eligible_count": len(eligible),
                      "protected_addresses_excluded": protected_in_scope,
                      "protected_address_count_in_database": len(blocked)},
        "book_sample": book,
        "stream_health": stream_health,
        "accounts": accounts,
        "global_period_policy": {
            "used_validation_intervals": "see plan windows and release/consumed counters; this inventory does not release periods",
            "newly_observed_data_is_virgin": False,
            "historical_studies": [
                {"account": "0xa880d6cc607a05ea617307ab3b0d335e8d8424ee",
                 "markets": "account-wide descriptive archive; market-specific slices remain in the source packet",
                 "event_window_ms": [1791398759000, 1791761829001],
                 "status": "used_historical_evidence_preserved",
                 "source": "docs/continuous-research/POPULATION-DESCRIPTIVE-PACKETS-20261014.md"},
                {"account": "0x67f7aa8fb95c47e6ea9c517b623e0701cbf9d9ba",
                 "markets": ["ETH", "xyz:DRAM"], "event_window_ms": [1791278662000, 1791761360001],
                 "status": "used_historical_evidence_preserved",
                 "source": "docs/continuous-research/POPULATION-DESCRIPTIVE-PACKETS-20261014.md",
                 "related_analysis": "docs/continuous-research/POPULATION-67F7-ETH-EXECUTION-CONTRIBUTION-20261014.md"},
                {"account": "0xbe504fbfc1ad30708a79f5821ed5ea6eef1a877b",
                 "markets": "account-wide descriptive archive; market-specific slices remain in the source packet",
                 "event_window_ms": [1791336309000, 1791761508001],
                 "status": "used_historical_evidence_preserved",
                 "source": "docs/continuous-research/POPULATION-DESCRIPTIVE-PACKETS-20261014.md"},
                {"account": "0x67f7aa8fb95c47e6ea9c517b623e0701cbf9d9ba",
                 "markets": ["ETH"], "event_window_ms": [1791990000000, 1792076400000],
                 "status": "used_historical_evidence_preserved",
                 "artifact": "docs/continuous-research/POPULATION-67F7-ETH-EXISTING-WINDOW-RESOLUTION-20261016-v1.json.gz",
                 "artifact_fingerprint": "697a4b00d599d15fabbfa2ab530efd7fdfb24dfb162a49b6e3f7bc9440e65da1"}],
            "previous_report_event_cutoff_ms": 1792076400000,
            "no_rule_defined_for_autonomous_study": True,
        },
    }


def render_markdown(manifest: dict[str, Any], *, selection_report: str,
                    selection_sha256: str, db_path: str) -> str:
    window = manifest["window"]
    rows = []
    all_pairs = []
    totals = {"fills": 0, "rest": 0, "websocket": 0, "fees_present": 0,
              "fees_missing": 0, "funding": 0, "funding_pairs": 0,
              "duplicates": 0, "conflicts": 0, "batches": 0,
              "accounts_page_capped": 0, "accounts_event_capped": 0,
              "accounts_global_budget_exhausted": 0,
              "history_endpoints_possibly_truncated": 0,
              "history_endpoints_skipped_for_budget": 0,
              "position_match": 0, "position_mismatch": 0, "position_missing": 0,
              "position_noncomparable": 0,
              "book_bbo_30s": 0, "book_l2_30s": 0}
    health = manifest.get("stream_health", {})
    health_sessions = health.get("sessions", {})
    health_totals = {"events": health.get("events_decoded", 0), "sessions": len(health_sessions),
                     "gaps": sum(x.get("heartbeat_gaps_over_threshold", 0) for x in health_sessions.values()),
                     "disconnects": sum(x.get("explicit_disconnect_count", 0) for x in health_sessions.values()),
                     "capped": health.get("event_cap_reached", False)}
    book_available = [stamp for market in manifest.get("book_sample", {}).get("markets", {}).values()
                      for endpoint in BOOK_ENDPOINTS
                      for stamp in (market.get(endpoint, {}).get("available_period_ms") or [])]
    book_period_note = (f"L’échantillon global borné des carnets couvre les disponibilités locales "
        f"[{iso_ms(min(book_available))}, {iso_ms(max(book_available))}] seulement; la couverture carnet du reste de la fenêtre est inconnue."
        if book_available else "Aucune période de disponibilité de carnet n’est présente dans l’échantillon borné.")
    # Funding history can contain markets absent from the fill/scope market set.
    # Count the endpoint evidence directly so those rows are not silently lost.
    for account in manifest["accounts"]:
        funding_by_market = account.get("accounting_history", {}).get("userFunding", {}).get("by_market", {})
        totals["funding"] += sum(x.get("events_observed", 0) for x in funding_by_market.values())
        totals["funding_pairs"] += sum(bool(x.get("events_observed", 0)) for x in funding_by_market.values())
    for account in manifest["accounts"]:
        scan = account["scan"]
        totals["duplicates"] += scan["duplicate_events"]
        totals["conflicts"] += scan["conflicting_events"]
        totals["batches"] += scan["events_batches"]
        totals["accounts_page_capped"] += bool(scan["account_page_query_capped"])
        totals["accounts_event_capped"] += bool(scan["event_cap_reached"])
        totals["accounts_global_budget_exhausted"] += bool(scan["global_page_budget_exhausted"])
        for endpoint_info in account.get("accounting_history", {}).values():
            totals["history_endpoints_possibly_truncated"] += bool(endpoint_info.get("possibly_truncated_at_page_budget"))
            totals["history_endpoints_skipped_for_budget"] += bool(endpoint_info.get("query_skipped_for_page_budget"))
        for market, pair in account["pairs"].items():
            fills = pair["fills"]
            provenance = fills.get("provenance", {})
            rest = provenance.get("rest", {}).get("unique_events", 0)
            websocket = provenance.get("websocket", {}).get("unique_events", 0)
            totals["fills"] += fills.get("unique_events", 0)
            totals["rest"] += rest
            totals["websocket"] += websocket
            totals["fees_present"] += pair.get("fees", {}).get("fee_field_present", 0)
            totals["fees_missing"] += pair.get("fees", {}).get("fee_field_missing", 0)
            position_status = pair.get("position_reconstruction", {}).get("status")
            if position_status == "arithmetic_match_on_observed_interval":
                totals["position_match"] += 1
            elif position_status == "observed_fill_state_delta_mismatch_or_incomplete":
                totals["position_mismatch"] += 1
            elif position_status == "missing_boundary_snapshots":
                totals["position_missing"] += 1
            elif position_status in ("unknown_noncomparable_boundaries", "unknown_noncomparable_historical_artifact",
                                     "unknown_conflicting_fill_identities",
                                     "unknown_state_or_fill_size"):
                totals["position_noncomparable"] += 1
            prov = ", ".join(f"{k}:{v['unique_events']}" for k, v in provenance.items()) or "aucun fill décodé"
            book = pair.get("book_evidence", {})
            bbo = book.get("bbo", {})
            bbo_period = bbo.get("available_period_ms")
            book_label = f"BBO échantillonné {bbo_period}" if bbo_period else "BBO non retrouvé dans l’échantillon borné"
            rows.append(f"| `{account['address']}` | `{market}` | {fills.get('unique_events',0)} | {prov} | {book_label} | {fills.get('position_reconstruction',{}).get('status','unknown')} |")
            joins = pair.get("book_join", {}).get("matched_fill_events", {})
            bbo30 = joins.get("bbo", {}).get("websocket", {}).get("prior_within_30s", 0)
            l230 = joins.get("l2Book", {}).get("websocket", {}).get("prior_within_30s", 0)
            totals["book_bbo_30s"] += bbo30
            totals["book_l2_30s"] += l230
            if fills.get("unique_events", 0):
                all_pairs.append({"address": account["address"], "market": market,
                    "fills": fills.get("unique_events", 0), "rest": rest, "websocket": websocket,
                    "event_period": fills.get("event_period_ms"),
                    "available_period": fills.get("local_available_period_ms"),
                    "bbo30": bbo30, "l230": l230})
    descriptive = sorted((p for p in all_pairs if p["rest"]), key=lambda p: p["rest"], reverse=True)[:5]
    follower = sorted((p for p in all_pairs if p["websocket"] and p["bbo30"] and p["l230"]),
                      key=lambda p: min(p["bbo30"], p["l230"]), reverse=True)[:5]
    def shortlist(items: list[dict[str, Any]], count_key: str) -> list[str]:
        return [f"- `{p['address']}` / `{p['market']}` : {p[count_key]} fills; "
                f"événements {p['event_period']}, disponibilité locale {p['available_period']}."
                for p in items]
    lines = ["# Couverture d’archives — inventaire borné — 2026-10-26", "",
        f"Fenêtre d’observation : **[{window['since_utc']}, {window['cutoff_utc']})**. Les dates sont en UTC; l’instant de disponibilité locale est `raw_observations.observed_at`.", "",
        "## Périmètre et preuve", "",
        f"Rapport de présélection : `{selection_report}` (SHA-256 `{selection_sha256}`). Base lue en mode SQLite read-only : `{db_path}`.",
        f"Le rapport source contenait {manifest['selection']['candidate_count']} comptes présélectionnés. Le registre compte {manifest['selection']['currently_tracked_count']} comptes `tracked`; {manifest['inventory'].get('rest_history_accounts')} comptes ont un curseur d’historique REST. Détail de cette mission : {manifest['selection']['detailed_eligible_count']} comptes après exclusion de {len(manifest['selection']['protected_addresses_excluded'])} compte(s) protégé(s).",
        f"Plafonds : {manifest['limits']['max_pages_per_account']} pages fills par compte; {manifest['limits']['max_total_pages']} pages au total ({manifest['limits']['pages_read']} lues), {manifest['limits']['max_events_per_account']} fills décodés par compte, {manifest['limits']['max_book_rows_per_endpoint']} observations globales récentes par canal de carnet.",
        f"La fenêtre commence exactement à la fin événementielle du bilan précédent, 2026-10-15T15:00:00Z; elle ne recouvre pas sa fenêtre 67f7/ETH déjà utilisée.",
        "Les études descriptives déjà utilisées sur a880, 67f7 et be504 (6–11 octobre) ainsi que la résolution bornée 67f7/ETH du 14–15 octobre sont explicitement conservées comme preuves historiques dans `global_period_policy.historical_studies`; aucune n’est requalifiée vierge.",
        "Les comptes protégés sont listés uniquement par leur référence d’adresse, sans lecture de leurs charges utiles. Le carnet n’a pas d’index dont la première clé est le marché : la période de carnet est donc un échantillon global récent et plafonné, pas un inventaire exhaustif de la fenêtre.",
        book_period_note, "",
        "## Résumé des éléments décodés", "",
        f"{totals['fills']:,} fills uniques ({totals['rest']:,} REST, {totals['websocket']:,} WebSocket) sur {len(all_pairs)} couples avec activité. Champ de frais présent sur {totals['fees_present']:,}/{totals['fees_present']+totals['fees_missing']:,} fills; {totals['funding']:,} lignes de funding observées sur {totals['funding_pairs']} couples compte/marché. Déduplication des seules identités de fills : {totals['duplicates']:,} répétitions exactes, {totals['conflicts']:,} identités conflictuelles exclues des métriques dérivées; enveloppes `events[]` de fills : {totals['batches']:,}.",
        (f"Plafond pages fills atteint pour {totals['accounts_page_capped']} comptes; plafond événements atteint pour {totals['accounts_event_capped']}; budget global épuisé : {totals['accounts_global_budget_exhausted']}. Les plafonds par endpoint historique ne sont pas enregistrés dans cet artefact historique."
         if manifest.get("historical_artifact_limitations", {}).get("per_endpoint_page_caps_not_recorded") else
         f"Plafond pages fills atteint pour {totals['accounts_page_capped']} comptes; plafond événements atteint pour {totals['accounts_event_capped']}; budget global épuisé : {totals['accounts_global_budget_exhausted']}. {totals['history_endpoints_possibly_truncated']} endpoints d’historique sont possiblement tronqués au plafond et {totals['history_endpoints_skipped_for_budget']} n’ont pas été interrogés faute de budget.") +
        " Un hit de plafond classe les portions non projetées `present_not_exported`; sans preuve locale admissible, zéro décodé reste `absent` dans ce scan seulement.",
        f"Le contrôle de bornes d’état donne {totals['position_match']} correspondances arithmétiques, {totals['position_mismatch']} écarts ou intervalles incomplets, {totals['position_missing']} couples sans deux snapshots, et {totals['position_noncomparable']} limites non comparables. La disponibilité locale d’un snapshot n’est pas son temps économique; seules des bornes source horodatées dans le même domaine que les fills sont comparées. Aucune correspondance ne prouve une position cohérente complète.",
        f"Dans l’échantillon de carnets, des snapshots strictement antérieurs et déjà disponibles dans les 30 s du reçu fill correspondent à {totals['book_bbo_30s']} fills WebSocket pour BBO et {totals['book_l2_30s']} pour L2; les deux canaux sont nécessaires à un rejeu avec carnet.", "",
        f"Santé des flux : {health_totals['sessions']} sessions reliées à des frames de fills WebSocket, {health_totals['events']:,} événements santé décodés, {health_totals['gaps']} intervalles heartbeat >65 s et {health_totals['disconnects']} déconnexions explicites dans la fenêtre; plafond global atteint : {health_totals['capped']}. Cette association prouve une activité de flux pour ces sessions, sans preuve d’ACK d’abonnement par compte.", "",
        *([f"Limite de reprise de l’artefact : {manifest['historical_artifact_limitations'].get('summary')}" ]
          if manifest.get("historical_artifact_limitations") else []),
        "### Meilleures pistes descriptives observées", "", *shortlist(descriptive, "rest"), "",
        "### Meilleures pistes de rejeu follower observées", "",
        *(shortlist(follower, "websocket") or ["Aucun couple ne réunit des fills WebSocket et des correspondances BBO et L2 dans l’échantillon borné."]),
        "Ces listes classent la quantité observée et le recouvrement technique. Elles ne mesurent ni performance ni complétude; les bornes par couple figurent dans le manifeste.", "",
        "## Inventaire de collecte", "",
        "| Mesure | Valeur | Ce que cela prouve |", "|---|---:|---|",
        f"| Comptes avec curseur REST | {manifest['inventory'].get('rest_history_accounts')} | Au moins un curseur archivé, pas continuité ni complétude de marché |",
        f"| Cibles de recherche compte/marché | {manifest['inventory'].get('research_targets')} | Registre de cibles, pas preuve de fills |",
        f"| Plans réels / périodes libérées / holdouts consommés / évaluations | {manifest['inventory'].get('validation_plans')} / {manifest['inventory'].get('released_periods')} / {manifest['inventory'].get('consumed_holdouts')} / {manifest['inventory'].get('validation_evaluations')} | Compteurs aux tables opérationnelles, ne libèrent aucun intervalle |",
        "", "### Curseurs d’historique observés", "",
        "| Endpoint | Statut | Comptes |", "|---|---|---:|",
        *[f"| `{x['endpoint']}` | `{x['status']}` | {x['count']} |" for x in manifest['inventory'].get('cursor_statuses', [])],
        "", "## Couples détaillés", "", "| Compte | Marché | Fills uniques observés | Provenance | Carnet | Position |", "|---|---|---:|---|---|---|", *rows, "",
        "## Interprétation par question", "",
        "- **Descriptif** : les couples avec fills décodés, bornes événement/réception et références REST peuvent soutenir une description de l’activité observée. REST et pages agrégées ne prouvent pas que tous les fills sont conservés. Frais et funding doivent rester des champs observés, pas une comptabilité complète.",
        "- **Rejeu d’un suivi** : seules des lignes `websocket` portent une disponibilité locale de flux utilisateur. Une réponse REST arrivée après l’événement ne reconstitue pas le signal de suivi. Les correspondances de carnet de l’échantillon borné ne prouvent pas encore un chemin complet exploitable.",
        "- **Interruptions/récupération** : les preuves de santé sont jointes aux sessions observées sur les fills WebSocket; les intervalles heartbeat dépassant 65 s et les déconnexions explicites sont comptés séparément. La session n’archive pas l’ACK userFills par compte, et les sessions sans fill visible ne sont pas attribuables à un compte. Les trous peuvent refléter interruption ou export manquant; leur cause ne se déduit pas du seul silence.",
        "- **Règle autonome** : aucune règle n’est définie par ce livrable; aucun résultat ne permet une étude économique autonome.",
        "- **Positions** : le delta signé des fills ne fixe ni position initiale, ni exposition simultanée, ni continuité. `coherent_position_proven=false` tant que les deux bornes d’état et l’exhaustivité des fills ne sont pas établies.",
        "- **Périodes** : les fenêtres issues des plans sont reportées comme réservées/utilisées; aucune période n’est libérée. Les données collectées depuis une pause ne sont pas requalifiées vierges.", "",
        "## Limites de récupération et catégories", "",
        "`absent` signifie seulement qu’aucun élément admissible n’a été décodé dans la fenêtre et les bornes de ce scan. `present_not_exported` signifie que le canal ou la référence existe mais que le plafond a empêché une projection complète. `reconciliation_missing` correspond à des fills/pages sans rapprochement de cotation ou d’état. `calculation_missing` désigne une métrique qui n’a pas été calculée. `unrecoverable` est réservé aux limites contractuelles de l’API ou à une frontière d’archive non récupérable; l’absence locale seule ne suffit pas.",
        "La documentation API locale et [le contrat officiel Hyperliquid](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint) fixent `userFillsByTime` aux 10 000 dernières exécutions et 2 000 par réponse : un préfixe plus ancien absent de la rétention est irrécupérable par cet endpoint; pagination réussie ne le restaure pas. Un curseur `saturated_timestamp_unresolvable` indique aussi une frontière non résolue. Un intervalle cohérent en fills n’est pas un historique complet. Voir TAMTAM_AGAIN-A-1 et le manifeste pour le compte/cursor concernés.", "",
        "## Reproduction", "", "```sh",
        "PYTHONPATH=src /home/Untergame/tamtam_again/.venv/bin/python scripts/archive-coverage.py \\",
        "  --db /home/Untergame/tamtam_again/data/tamtam.sqlite3 \\",
        f"  --selection-report {selection_report} \\",
        f"  --since {window['since_utc']} \\",
        f"  --cutoff {window['cutoff_utc']} \\",
        "  --max-accounts 64 --max-pages-per-account 300 --max-total-pages 25000 \\",
        "  --max-events-per-account 250000 --max-book-rows-per-endpoint 20000 \\",
        "  --output-dir docs/continuous-research/archive-coverage-20261026",
        "```", "", "Aucun changement de service, quota, autorisation ou base n’est inclus dans ce livrable."
    ]
    return "\n".join(lines) + "\n"
