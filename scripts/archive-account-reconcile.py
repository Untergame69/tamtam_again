#!/usr/bin/env python3
"""Reconcile one archived public-account interval without network access.

Reads the local SQLite archive in read-only mode. Account-history release and
reservation checks run before any response payload is decoded.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tamtam_again.account_events import normalize_event  # noqa: E402
from tamtam_again.discovery import protected_addresses  # noqa: E402
from tamtam_again.research_memory import authorized_account_history  # noqa: E402
from tamtam_again.storage import decode_observation_payload  # noqa: E402

DEFAULT_ADDRESS = "0xa880d6cc607a05ea617307ab3b0d335e8d8424ee"
DEFAULT_START_MS = 1791473085724  # 2026-10-08T15:24:45.724Z
DEFAULT_END_MS = 1791476235515    # 2026-10-08T16:17:15.515Z
PAGE_GROUPS = {
    "userFillsByTime": "fill_pages_with_unique_30d_events",
    "userFunding": "funding_pages_with_normalized_30d_events",
    "userNonFundingLedgerUpdates": "ledger_pages_with_normalized_30d_events",
}


def iso_ms(value: int | None) -> str | None:
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat() if value is not None else None


def decimal_text(value: Decimal) -> str:
    return format(value, "f")


def add_sum(target: dict[str, Decimal], key: str, value: str | int | float) -> None:
    target[key] = target.get(key, Decimal(0)) + Decimal(str(value))


def open_readonly(path: Path) -> sqlite3.Connection:
    uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def source_rows(conn: sqlite3.Connection, ids: list[int], *, network: str,
                address: str, cutoff_ms: int) -> list[sqlite3.Row]:
    if not ids:
        return []
    cutoff = iso_ms(cutoff_ms)
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        "select * from raw_observations where observation_id in (" + placeholders + ") "
        "and network=? and source='hyperliquid-population-rest-v1' "
        "and entity_type='account' and entity_id=? and observed_at<=? "
        "order by observed_at,observation_id",
        (*ids, network, address, cutoff),
    ).fetchall()
    return rows


def latest_curve_point(points: list, stamp: int) -> Decimal:
    matches = [Decimal(str(value)) for time_ms, value in points if int(time_ms) == stamp]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one curve point at {stamp}; found {len(matches)}")
    return matches[0]


def page_metadata(row: sqlite3.Row) -> dict:
    request = json.loads(row["request_json"])
    return {
        "evidence_ref": f"raw_observations:{row['observation_id']}",
        "observed_at": row["observed_at"],
        "requested_interval_ms": [request.get("startTime"), request.get("endTime")],
        "record_count": row["record_count"],
        "complete": bool(row["complete"]),
        "pagination_status": request.get("pagination_status"),
        "coverage_status": request.get("coverage_status"),
    }


def select_position_snapshot(conn: sqlite3.Connection, *, network: str,
                             address: str, acquisition_id: str,
                             cutoff_ms: int) -> dict | None:
    rows = conn.execute(
        "select * from raw_observations where network=? "
        "and source='hyperliquid-population-rest-v1' and entity_type='account' "
        "and entity_id=? and endpoint='clearinghouseState' and observed_at<=? "
        "and request_json like ? order by observed_at,observation_id",
        (network, address, iso_ms(cutoff_ms), f"%{acquisition_id}%"),
    ).fetchall()
    standard = None
    for row in rows:
        request = json.loads(row["request_json"])
        if request.get("dex", "") == "":
            standard = row
            break
    if standard is None:
        return None

    payload = decode_observation_payload(standard)
    if not isinstance(payload, dict):
        return None
    positions = {}
    gross_value = Decimal(0)
    unrealized = Decimal(0)
    for entry in payload.get("assetPositions", []):
        position = entry.get("position") if isinstance(entry, dict) else None
        if not isinstance(position, dict) or not isinstance(position.get("coin"), str):
            continue
        coin = position["coin"]
        positions[coin] = {
            "szi": str(position.get("szi", "0")),
            "position_value": str(position.get("positionValue", "0")),
            "unrealized_pnl": str(position.get("unrealizedPnl", "0")),
        }
        gross_value += abs(Decimal(positions[coin]["position_value"]))
        unrealized += Decimal(positions[coin]["unrealized_pnl"])

    return {
        "acquisition_id": acquisition_id,
        "observed_at": standard["observed_at"],
        "evidence_ref": f"raw_observations:{standard['observation_id']}",
        "dex_scope": "default perp DEX only; no cross-DEX sum",
        "position_count": len(positions),
        "gross_position_value_reported": decimal_text(gross_value),
        "summed_unrealized_pnl_reported": decimal_text(unrealized),
        "positions": positions,
    }


def build_result(db_path: Path, audit_path: Path, address: str,
                 start_ms: int, end_ms: int) -> dict:
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    cutoff_ms = int(audit["source_cutoff_ms"])
    network = audit["network"]
    account = next((item for item in audit["accounts"] if item["address"].lower() == address.lower()), None)
    if account is None:
        raise ValueError("Address is not present in the archived audit manifest")
    if type(start_ms) is not int or type(end_ms) is not int or not (0 <= start_ms < end_ms <= cutoff_ms):
        raise ValueError("Require an ordered interval ending no later than the audit cutoff")

    conn = open_readonly(db_path)
    try:
        # These checks are deliberately completed before any source response is decoded.
        class StoreView:
            connection = conn

        authorized = authorized_account_history(StoreView(), network, address.lower(), cutoff_ms)
        blocked = address.lower() in protected_addresses(StoreView())
        if not authorized or blocked:
            raise PermissionError("Account history is not currently authorized at the source cutoff")

        all_ref_ids: list[int] = []
        refs_by_endpoint: dict[str, list[int]] = {}
        portfolio_ids = [int(ref.split(":", 1)[1]) for ref in account["evidence_refs"]["portfolio_observations"]]
        all_ref_ids.extend(portfolio_ids)
        for endpoint, field in PAGE_GROUPS.items():
            ids = [int(ref.split(":", 1)[1]) for ref in account["evidence_refs"][field]]
            refs_by_endpoint[endpoint] = ids
            all_ref_ids.extend(ids)
        rows = source_rows(conn, sorted(set(all_ref_ids)), network=network,
                           address=address.lower(), cutoff_ms=cutoff_ms)
        by_id = {int(row["observation_id"]): row for row in rows}
        missing_refs = sorted(set(all_ref_ids) - set(by_id))
        if missing_refs:
            raise ValueError(f"Missing authorized source rows for ids: {missing_refs[:10]}")

        portfolio_rows = [by_id[item] for item in portfolio_ids if item in by_id]
        # Select source responses whose newest allTime sample is each chosen bound.
        start_curve_row = None
        end_curve_row = None
        for row in reversed(portfolio_rows):
            response = decode_observation_payload(row)
            sections = dict(response) if isinstance(response, list) else {}
            candidate = sections.get("allTime")
            if not isinstance(candidate, dict):
                continue
            series = {name: candidate.get(name, []) for name in ("pnlHistory", "accountValueHistory")}
            has_start = all(any(int(point[0]) == start_ms for point in values if isinstance(point, list) and len(point) == 2)
                            for values in series.values())
            has_end = all(any(int(point[0]) == end_ms for point in values if isinstance(point, list) and len(point) == 2)
                          for values in series.values())
            latest_times = [max((int(point[0]) for point in values if isinstance(point, list) and len(point) == 2),
                                default=-1) for values in series.values()]
            if start_curve_row is None and has_start and latest_times == [start_ms, start_ms]:
                start_curve_row = row
            if end_curve_row is None and has_end and latest_times == [end_ms, end_ms]:
                end_curve_row = row
        if start_curve_row is None or end_curve_row is None:
            raise ValueError("No archived allTime source response at one or both exact curve boundaries")
        start_sections = dict(decode_observation_payload(start_curve_row))["allTime"]
        end_sections = dict(decode_observation_payload(end_curve_row))["allTime"]
        pnl_start = latest_curve_point(start_sections["pnlHistory"], start_ms)
        pnl_end = latest_curve_point(end_sections["pnlHistory"], end_ms)
        value_start = latest_curve_point(start_sections["accountValueHistory"], start_ms)
        value_end = latest_curve_point(end_sections["accountValueHistory"], end_ms)
        pnl_delta = pnl_end - pnl_start
        value_delta = value_end - value_start

        event_rows = {endpoint: [by_id[item] for item in refs_by_endpoint[endpoint]]
                      for endpoint in PAGE_GROUPS}
        fills: dict[tuple, dict] = {}
        fill_page_ids: set[int] = set()
        for row in event_rows["userFillsByTime"]:
            payload = decode_observation_payload(row)
            if not isinstance(payload, list):
                continue
            for fill in payload:
                if not isinstance(fill, dict) or type(fill.get("time")) is not int:
                    continue
                stamp = fill["time"]
                if not start_ms <= stamp <= end_ms:
                    continue
                identity = (fill.get("coin"), stamp, fill.get("tid", fill.get("hash")))
                if identity not in fills:
                    fills[identity] = fill
                fill_page_ids.add(int(row["observation_id"]))
        fee_totals: dict[str, Decimal] = {}
        for fill in fills.values():
            add_sum(fee_totals, str(fill.get("feeToken") or "UNKNOWN"), fill.get("fee", "0"))

        normalized_events: dict[str, dict[str, dict]] = {"userFunding": {}, "userNonFundingLedgerUpdates": {}}
        event_pages: dict[str, set[int]] = {key: set() for key in normalized_events}
        event_page_metadata: dict[str, dict[int, dict]] = {key: {} for key in normalized_events}
        for endpoint in normalized_events:
            for row in event_rows[endpoint]:
                observed_ms = int(datetime.fromisoformat(row["observed_at"]).timestamp() * 1000)
                payload = decode_observation_payload(row)
                if not isinstance(payload, list):
                    continue
                for raw_event in payload:
                    if not isinstance(raw_event, dict) or type(raw_event.get("time")) is not int:
                        continue
                    if not start_ms <= raw_event["time"] <= end_ms:
                        continue
                    normalized = normalize_event(
                        endpoint, raw_event, address=address.lower(), available_ms=observed_ms,
                        evidence_ref=f"raw_observations:{row['observation_id']}",
                    )
                    event = normalized.get("event")
                    if not isinstance(event, dict):
                        continue
                    normalized_events[endpoint][event["id"]] = event
                    event_pages[endpoint].add(int(row["observation_id"]))
                    event_page_metadata[endpoint][int(row["observation_id"])] = page_metadata(row)

        external_flows: dict[str, Decimal] = {}
        internal_flows: dict[str, Decimal] = {}
        for event in normalized_events["userNonFundingLedgerUpdates"].values():
            target = external_flows if event.get("boundary_classification") == "external" else internal_flows
            add_sum(target, event.get("currency", "UNKNOWN"), event["amount"])
        funding: dict[str, Decimal] = {}
        funding_scopes: dict[str, int] = {}
        for event in normalized_events["userFunding"].values():
            add_sum(funding, event.get("currency", "UNKNOWN"), event["amount"])
            scope = event.get("scope_id", "unknown")
            funding_scopes[scope] = funding_scopes.get(scope, 0) + 1

        start_acquisition = json.loads(start_curve_row["request_json"]).get("acquisition_id")
        end_acquisition = json.loads(end_curve_row["request_json"]).get("acquisition_id")
        start_positions = select_position_snapshot(conn, network=network, address=address.lower(),
                                                   acquisition_id=start_acquisition,
                                                   cutoff_ms=cutoff_ms) if start_acquisition else None
        end_positions = select_position_snapshot(conn, network=network, address=address.lower(),
                                                 acquisition_id=end_acquisition,
                                                 cutoff_ms=cutoff_ms) if end_acquisition else None
        position_changes = {}
        if start_positions and end_positions:
            for coin in sorted(set(start_positions["positions"]) | set(end_positions["positions"])):
                left = start_positions["positions"].get(coin, {})
                right = end_positions["positions"].get(coin, {})
                position_changes[coin] = {
                    "szi_start": left.get("szi", "0"),
                    "szi_end": right.get("szi", "0"),
                    "position_value_start": left.get("position_value", "0"),
                    "position_value_end": right.get("position_value", "0"),
                }

        net_flow_usdc = external_flows.get("USDC", Decimal(0))
        conditional_pnl_from_equity_and_flows = value_delta - net_flow_usdc
        conditional_residual = pnl_delta - conditional_pnl_from_equity_and_flows
        return {
            "schema_version": "archived-public-account-reconciliation-v1",
            "source_cutoff_ms": cutoff_ms,
            "network": network,
            "address": address.lower(),
            "authorization": {"authorized_at_cutoff": authorized, "currently_protected": blocked,
                              "checked_before_payload_decoding": True},
            "selected_interval": {
                "rule": "shortest interval in this archive with exact allTime curve samples at both ends, same-acquisition default-perp snapshots, and archived flow/funding request windows overlapping both bounds",
                "start_ms": start_ms, "start_utc": iso_ms(start_ms),
                "end_ms": end_ms, "end_utc": iso_ms(end_ms),
                "elapsed_minutes": decimal_text(Decimal(end_ms - start_ms) / Decimal(60000)),
                "curve_evidence_refs": [f"raw_observations:{start_curve_row['observation_id']}",
                                         f"raw_observations:{end_curve_row['observation_id']}"],
                "start_acquisition_id": start_acquisition,
                "end_acquisition_id": end_acquisition,
            },
            "curve": {
                "series": "allTime",
                "pnl_history": {"start": decimal_text(pnl_start), "end": decimal_text(pnl_end),
                                "change": decimal_text(pnl_delta)},
                "account_value_history": {"start": decimal_text(value_start), "end": decimal_text(value_end),
                                          "change": decimal_text(value_delta)},
                "pnl_change_minus_account_value_change": decimal_text(pnl_delta - value_delta),
            },
            "cashflow_bridge": {
                "observed_external_flows_by_currency": {k: decimal_text(v) for k, v in sorted(external_flows.items())},
                "conditional_convention": "For arithmetic only: declared PnL change = account-value change - signed external flow (outflow negative). This is not asserted as the provider formula for every scope.",
                "conditional_pnl_from_account_value_and_observed_flows_usdc": decimal_text(conditional_pnl_from_equity_and_flows),
                "conditional_residual_reported_minus_bridge_usdc": decimal_text(conditional_residual),
                "amount_attributed_as_provider_pnl": "not independently proven; the transfer explains the direction and most of the difference only under the stated signed-flow convention",
            },
            "fills_and_fees": {
                "dedupe_key": "(coin,time,tid-or-hash)", "unique_fills_in_interval": len(fills),
                "observed_fees_by_currency": {k: decimal_text(v) for k, v in sorted(fee_totals.items())},
                "fee_page_refs_with_interval_fills": [f"raw_observations:{i}" for i in sorted(fill_page_ids)],
                "fee_total_subtracted_again": False,
                "treatment": "Displayed separately. The provider portfolio graph is defined from account value plus net deposits/withdrawals; fees are not subtracted again from that graph. Per-event inclusion is not separately exposed by the API.",
            },
            "funding": {
                "dedupe": "normalized event identity (time,hash,type,coin,nonce/account fields)",
                "event_count": len(normalized_events["userFunding"]),
                "observed_by_currency": {k: decimal_text(v) for k, v in sorted(funding.items())},
                "event_counts_by_scope": dict(sorted(funding_scopes.items())),
                "evidence_pages": [event_page_metadata["userFunding"][i] for i in sorted(event_pages["userFunding"])],
                "funding_subtracted_again": False,
                "treatment": "Displayed separately; the portfolio graph has no separate funding term. If settlement is reflected in account value, subtracting it again would double count. The account-level inclusion is not separately decomposed by the API.",
            },
            "external_ledger_events": {
                "dedupe": "normalized event identity (time,hash,type,coin,nonce/account fields)",
                "events": list(normalized_events["userNonFundingLedgerUpdates"].values()),
                "evidence_pages": [event_page_metadata["userNonFundingLedgerUpdates"][i] for i in sorted(event_pages["userNonFundingLedgerUpdates"])],
                "relation_of_destination_to_related_accounts": "unknown; external here means outside this address boundary",
            },
            "positions": {
                "start_snapshot": start_positions,
                "end_snapshot": end_positions,
                "delta_by_coin": position_changes,
                "treatment": "Default perp DEX only. Position snapshots and their reported unrealized PnL are explanatory state, not extra gains to add to the portfolio curve. Other DEX, spot, vault and related addresses are not consolidated.",
            },
            "source_coverage": {
                "fills": {"query_coverage_days_in_30d_archive": account["activity"]["query_coverage_30d_days"],
                          "archive_statuses": account["activity"]["pagination_statuses"],
                          "limit": "userFillsByTime returns up to 2,000 per response; only the most recent 10,000 fills are available",
                          "selected_interval_page_metadata": [page_metadata(by_id[i]) for i in sorted(fill_page_ids)]},
                "funding": {"pages_with_interval_events": len(event_pages["userFunding"]),
                            "coverage_status": "pagination/retention completeness unproven; source rows have complete=0",
                            "event_time_range_utc": ([iso_ms(min(e["event_ms"] for e in normalized_events["userFunding"].values())),
                                                       iso_ms(max(e["event_ms"] for e in normalized_events["userFunding"].values()))]
                                                      if normalized_events["userFunding"] else None)},
                "ledger": {"pages_with_interval_events": len(event_pages["userNonFundingLedgerUpdates"]),
                           "coverage_status": "pagination/retention completeness unproven; source rows have complete=0",
                           "event_time_range_utc": ([iso_ms(min(e["event_ms"] for e in normalized_events["userNonFundingLedgerUpdates"].values())),
                                                      iso_ms(max(e["event_ms"] for e in normalized_events["userNonFundingLedgerUpdates"].values()))]
                                                     if normalized_events["userNonFundingLedgerUpdates"] else None)},
            },
            "provider_semantics": {
                "portfolio_graph_documentation": "https://hyperliquid.gitbook.io/hyperliquid-docs/trading/portfolio-graphs",
                "info_endpoint_documentation": "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint",
                "documented_formula": "Pnl is account value plus net deposits (account value + deposits - withdrawals); graphs sample on deposits/withdrawals and every 15 minutes.",
                "documented_account_value_scope": "includes unrealized PnL from cross and isolated margin positions, as well as vault balances",
                "fill_fee_semantics": "The API fill fee is total fee inclusive of builderFee; do not add builderFee a second time.",
                "limits": ["The archived formula does not independently reconcile this address's event pages or define whether the sent-to address is a linked account.",
                           "The short curve gap, partial fill pages and complete=0 event pages prevent a full accounting certification."],
            },
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "data/tamtam.sqlite3")
    parser.add_argument("--archive-audit", type=Path,
                        default=ROOT / "docs/continuous-research/economic-performance-archive-check-20261012.json")
    parser.add_argument("--address", default=DEFAULT_ADDRESS)
    parser.add_argument("--start-ms", type=int, default=DEFAULT_START_MS)
    parser.add_argument("--end-ms", type=int, default=DEFAULT_END_MS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = build_result(args.db, args.archive_audit, args.address, args.start_ms, args.end_ms)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
