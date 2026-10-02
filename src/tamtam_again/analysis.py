from __future__ import annotations

import json
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from typing import Any

from .storage import Store, decode_observation_payload


def observed_account_summary(store: Store, network: str, address: str,
                             start_ms: int, end_ms: int) -> dict[str, Any]:
    """Summarize directly observed perp components without claiming total return."""
    rows = store.observations(network, "account", address.lower(), start_ms, end_ms)
    fills: dict[str, dict[str, Any]] = {}
    funding: dict[str, dict[str, Any]] = {}
    ledger_events: dict[str, Any] = {}
    coverage_intervals: defaultdict[str, list[tuple[int, int]]] = defaultdict(list)
    observed_endpoints: set[str] = set()

    for observation in rows:
        endpoint = observation["endpoint"]
        observed_endpoints.add(endpoint)
        if (bool(observation["complete"])
                and observation["window_start_ms"] is not None
                and observation["window_end_ms"] is not None):
            coverage_intervals[endpoint].append((
                int(observation["window_start_ms"]),
                int(observation["window_end_ms"]),
            ))
        try:
            data = decode_observation_payload(observation)
        except ValueError:
            continue
        if endpoint in {"userFillsByTime", "userFills"}:
            for item in _fills_from_observation(endpoint, data):
                # The REST endpoint pages inclusive time ranges; the WebSocket
                # snapshot can overlap those pages. Include time in the key so
                # the same tid on another market/time cannot collapse a fill.
                identity = (item.get("coin"), item.get("time"),
                            item.get("tid", item.get("hash")))
                fills[json.dumps(identity, ensure_ascii=False, separators=(",", ":"))] = item
        elif endpoint == "userFunding" and isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                key = f"{item.get('time')}:{item.get('hash')}:{repr(item.get('delta'))}"
                funding[key] = item
        elif endpoint == "userNonFundingLedgerUpdates" and isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                event_hash = item.get("hash")
                if event_hash:
                    key = str(event_hash).lower()
                else:
                    key = json.dumps(item, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"))
                ledger_events[key] = item

    fill_counts: Counter[str] = Counter()
    realized_by_kind: defaultdict[str, Decimal] = defaultdict(Decimal)
    fees_by_kind_token: defaultdict[str, Decimal] = defaultdict(Decimal)
    perp_fee_tokens: Counter[str] = Counter()
    for row in fills.values():
        kind = _market_kind(str(row.get("coin", "")))
        fill_counts[kind] += 1
        realized_by_kind[kind] += _decimal(row.get("closedPnl"))
        token = str(row.get("feeToken") or "unknown").strip().upper()
        fees_by_kind_token[f"{kind}:{token}"] += _decimal(row.get("fee"))
        if kind == "perp":
            perp_fee_tokens[token] += 1
    funding_usdc = Decimal(0)
    for item in funding.values():
        delta = item.get("delta") or {}
        if isinstance(delta, dict) and delta.get("usdc") is not None:
            funding_usdc += _decimal(delta["usdc"])

    expected_history = {"userFillsByTime", "userFunding",
                       "userNonFundingLedgerUpdates"}
    missing_history = sorted(expected_history - observed_endpoints)
    coverage_by_endpoint = {
        endpoint: _covers_window(coverage_intervals[endpoint], start_ms, end_ms)
        for endpoint in sorted(expected_history)
    }
    coverage_incomplete = not all(coverage_by_endpoint.values())

    return {
        "network": network,
        "address": address.lower(),
        "window_start_ms": start_ms,
        "window_end_ms": end_ms,
        "unique_fill_count_observed": len(fills),
        "fill_count_by_market_kind": dict(sorted(fill_counts.items())),
        "realized_closed_pnl_by_market_kind_observed": {
            kind: _format(value) for kind, value in sorted(realized_by_kind.items())
        },
        "fees_by_market_kind_and_fee_token_observed": {
            key: _format(value) for key, value in sorted(fees_by_kind_token.items())
        },
        "perp_fee_tokens_observed": dict(sorted(perp_fee_tokens.items())),
        "perp_realized_closed_pnl_usdc_observed": _format(realized_by_kind["perp"]),
        "perp_fees_usdc_observed": _format(fees_by_kind_token["perp:USDC"]),
        "funding_usdc_observed": _format(funding_usdc),
        "perp_pnl_less_known_usdc_fees_plus_funding_observed_usdc": _format(
            realized_by_kind["perp"] - fees_by_kind_token["perp:USDC"] + funding_usdc
        ),
        "non_funding_ledger_event_count_observed": len(ledger_events),
        "history_endpoints_observed": sorted(expected_history & observed_endpoints),
        "history_endpoints_missing": missing_history,
        "history_coverage_by_endpoint": coverage_by_endpoint,
        "history_coverage_complete": not coverage_incomplete and not missing_history,
        "coverage_incomplete": coverage_incomplete or bool(missing_history),
        "observation_data_present": bool(observed_endpoints),
        "limitations": [
            "Somme des fills effectivement collectés; elle ne prouve pas la couverture complète du compte.",
            "N’inclut pas le PnL latent, la valorisation spot, les comptes liés ni les flux de capital dans un rendement total.",
            "Les comptes maître, sous-comptes, wallets d’agent et éventuelles migrations peuvent fragmenter l’historique.",
            "Le résultat est un indicateur exploratoire, pas une validation de rentabilité reproductible.",
        ],
    }


def cohort_research_status(store: Store, network: str) -> dict[str, Any]:
    """Report what the tracked cohort and market archive can support today."""
    candidates = store.candidates(network)
    tracked = [row for row in candidates if row["status"] == "tracked"]
    all_observations = list(store.connection.execute(
        """SELECT * FROM raw_observations WHERE network=?
           AND entity_type IN ('account','market') ORDER BY observed_at""",
        (network,),
    ))
    tracked_addresses = {row["address"].lower(): f"compte-{i:02d}"
                         for i, row in enumerate(tracked, 1)}
    fills: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    history_complete: defaultdict[str, dict[str, bool]] = defaultdict(dict)
    ws_fills_last: dict[str, str] = {}
    market_counts: Counter[str] = Counter()
    account_times: defaultdict[str, list[int]] = defaultdict(list)
    market_stream: defaultdict[str, Counter[str]] = defaultdict(Counter)
    market_first: dict[tuple[str, str], int] = {}
    market_last: dict[tuple[str, str], int] = {}
    candles: defaultdict[str, list[int]] = defaultdict(list)
    endpoint_counts: Counter[str] = Counter()

    for observation in all_observations:
        endpoint = observation["endpoint"]
        endpoint_counts[f"{observation['entity_type']}:{endpoint}"] += 1
        if observation["entity_type"] == "account":
            address = observation["entity_id"].lower()
            if address not in tracked_addresses:
                continue
            if endpoint in {"userFillsByTime", "userFills"}:
                if endpoint == "userFills":
                    ws_fills_last[address] = observation["observed_at"]
                try:
                    payload = decode_observation_payload(observation)
                except (ValueError, TypeError, OSError):
                    continue
                for fill in _fills_from_observation(endpoint, payload):
                    coin = str(fill.get("coin", ""))
                    stamp = str(fill.get("time", ""))
                    tid = str(fill.get("tid", fill.get("hash", "")))
                    fills[(address, coin, stamp, tid)] = fill
                    try:
                        account_times[address].append(int(stamp))
                    except ValueError:
                        pass
            if endpoint in {"userFillsByTime", "userFunding",
                            "userNonFundingLedgerUpdates"}:
                history_complete[address][endpoint] = (
                    history_complete[address].get(endpoint, True)
                    and bool(observation["complete"])
                )
        else:
            coin = observation["entity_id"]
            try:
                payload = decode_observation_payload(observation)
            except (ValueError, TypeError, OSError):
                continue
            if endpoint == "candleSnapshot:1m" and isinstance(payload, list):
                for candle in payload:
                    if isinstance(candle, dict):
                        try:
                            candles[coin].append(int(candle.get("t")))
                        except (TypeError, ValueError):
                            pass
            elif endpoint in {"trades", "bbo", "l2Book"}:
                events = payload.get("events", []) if isinstance(payload, dict) else []
                for event in events:
                    message = event.get("message", {}) if isinstance(event, dict) else {}
                    data = message.get("data") if isinstance(message, dict) else None
                    values = data if isinstance(data, list) else [data]
                    for value in values:
                        if not isinstance(value, dict):
                            continue
                        symbol = str(value.get("coin") or message.get("coin") or coin)
                        market_stream[symbol][endpoint] += 1
                        try:
                            stamp = int(value.get("time", value.get("t")) or 0)
                        except (TypeError, ValueError):
                            stamp = 0
                        if stamp:
                            key = (symbol, endpoint)
                            market_first[key] = min(stamp, market_first.get(key, stamp))
                            market_last[key] = max(stamp, market_last.get(key, stamp))

    by_address: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (address, _coin, _stamp, _tid), fill in fills.items():
        by_address[address].append(fill)
        market_counts[str(fill.get("coin", ""))] += 1
    accounts = []
    for address, alias in tracked_addresses.items():
        rows = by_address[address]
        times = account_times[address]
        top_coins = Counter(str(row.get("coin", "")) for row in rows)
        endpoints = history_complete[address]
        incomplete = sorted(name for name, complete in endpoints.items() if not complete)
        expected = {"userFillsByTime", "userFunding", "userNonFundingLedgerUpdates"}
        missing = sorted(expected - set(endpoints))
        accounts.append({
            "account": alias,
            "observed_fills": len(rows),
            "first_fill_utc": _iso_ms(min(times)) if times else None,
            "last_fill_utc": _iso_ms(max(times)) if times else None,
            "active_span_days": round((max(times) - min(times)) / 86_400_000, 2)
                if len(times) > 1 else 0,
            "markets_traded": len(top_coins),
            "top_markets": [{"coin": coin, "fills": count}
                            for coin, count in top_coins.most_common(5)],
            "history_endpoints_missing": missing,
            "history_endpoints_with_incomplete_pages": incomplete,
            "requested_history_pages_complete": not missing and not incomplete,
            "profitability_claim_ready": False,
            "websocket_fills_seen": address in ws_fills_last,
            "last_websocket_fill_observed_at": ws_fills_last.get(address),
        })

    ranking = store.latest_market_selection(network)
    global_markets = [{"coin": row["coin"], "rank": row["rank"],
                       "venue": row["venue"], "market_type": row["market_type"]}
                      for row in (ranking["markets"] if ranking else [])]
    whale_top = [{"coin": coin, "fills": count}
                 for coin, count in market_counts.most_common(10) if coin]
    analyzed_symbols = set(market_counts)
    market_coverage = []
    for coin in sorted(analyzed_symbols):
        market_coverage.append({
            "coin": coin,
            "observed_account_fills": market_counts[coin],
            "public_trade_messages": market_stream[coin]["trades"],
            "bbo_messages": market_stream[coin]["bbo"],
            "order_book_messages": market_stream[coin]["l2Book"],
            "one_minute_candles": len(set(candles[coin])),
            "trade_feed_first_utc": _iso_ms(market_first.get((coin, "trades"))),
            "trade_feed_last_utc": _iso_ms(market_last.get((coin, "trades"))),
        })
    coverage_by_coin = {row["coin"]: row for row in market_coverage}
    whale_focus = [row["coin"] for row in whale_top[:5]]
    market_gaps = []
    for coin in whale_focus:
        coverage = coverage_by_coin.get(coin, {})
        missing = []
        if not coverage.get("public_trade_messages"):
            missing.append("trades")
        if not coverage.get("bbo_messages") and not coverage.get("order_book_messages"):
            missing.append("BBO/carnet")
        if not coverage.get("one_minute_candles"):
            missing.append("bougies 1m")
        if missing:
            market_gaps.append({"coin": coin, "missing": missing})
    return {
        "network": network,
        "candidate_accounts_retained": len(candidates),
        "accounts_currently_tracked": len(tracked),
        "tracked_accounts_with_observed_fills_http_or_websocket": sum(
            bool(by_address[row["address"].lower()]) for row in tracked
        ),
        "tracked_unique_observed_fills": len(fills),
        "tracked_markets_by_fill_count": whale_top,
        "latest_top_markets_by_24h_volume": global_markets,
        "accounts": accounts,
        "market_coverage_for_observed_whale_markets": market_coverage,
        "paper_replay_readiness": {
            "ready": False,
            "market_data_ready_for_top_5_whale_markets": not market_gaps,
            "top_5_whale_markets": whale_focus,
            "market_data_gaps": market_gaps,
            "reason": "La durée et la couverture des flux de marché ne recouvrent pas encore de façon démontrée les historiques de fills. Une stratégie de copie doit aussi être définie avant de chiffrer une performance simulée.",
            "requirements": [
                "Une période de fills et de données marché qui se recouvre sans trou significatif.",
                "Carnet ou au minimum BBO archivé sur chaque marché candidat.",
                "Une règle de copie/reconstruction définie avant de calculer une performance simulée.",
            ],
        },
        "retention_policy": {
            "keep_untracked_observations": True,
            "poll_only_tracked_accounts": True,
            "candidate_accounts_retained": len(candidates),
        },
        "observation_counts_by_endpoint": dict(sorted(endpoint_counts.items())),
    }


def _fills_from_observation(endpoint: str, payload: Any) -> list[dict[str, Any]]:
    if endpoint == "userFillsByTime":
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
    if endpoint == "userFills":
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        fills = data.get("fills", []) if isinstance(data, dict) else []
        return [item for item in fills if isinstance(item, dict)] if isinstance(fills, list) else []
    return []


def _iso_ms(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat(timespec="seconds")


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _format(value: Decimal) -> str:
    return format(value, "f")


def _market_kind(coin: str) -> str:
    # Spot symbols use names such as @107 or PURR/USDC; perp symbols may include
    # a HIP-3 dex prefix but do not contain a slash.
    return "spot" if coin.startswith("@") or "/" in coin else "perp"


def _covers_window(intervals: list[tuple[int, int]], start_ms: int,
                   end_ms: int) -> bool:
    cursor = start_ms
    for interval_start, interval_end in sorted(intervals):
        if interval_end < cursor:
            continue
        if interval_start > cursor + 1:
            return False
        cursor = max(cursor, interval_end)
        if cursor >= end_ms:
            return True
    return cursor >= end_ms
