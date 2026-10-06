from __future__ import annotations

import json
from bisect import bisect_right
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from typing import Any

from .cycles import reconstruct_position_cycles
from .storage import Store, decode_observation_payload


HYPOTHESIS_CYCLE_REFERENCE = 5
VALIDATION_CYCLE_REFERENCE = 100
RESEARCH_CYCLE_LEVELS = (HYPOTHESIS_CYCLE_REFERENCE, 10, 30, VALIDATION_CYCLE_REFERENCE)


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


def cohort_research_status(store: Store, network: str, *,
                           workflow_fast: bool = False) -> dict[str, Any]:
    """Report what the tracked cohort and market archive can support today."""
    candidates = store.candidates(network)
    tracked = [row for row in candidates if row["status"] == "tracked"]
    tracked_addresses = {row["address"].lower(): f"compte-{i:02d}"
                         for i, row in enumerate(tracked, 1)}
    if workflow_fast:
        # The workflow gate needs complete whale fills plus preceding BBO only.
        # Reading every archived L2 book, public trade, and candle here made a
        # five-minute eligibility check scan gigabytes and block SQLite writers.
        # The full research-status report still loads those feeds on demand.
        addresses = list(tracked_addresses)
        if addresses:
            placeholders = ",".join("?" for _ in addresses)
            observations_query = f"""SELECT * FROM raw_observations
                WHERE network=? AND (
                  (entity_type='account' AND entity_id IN ({placeholders})
                   AND endpoint IN ('userFillsByTime','userFills','userFunding',
                                    'userNonFundingLedgerUpdates'))
                  OR (entity_type='market' AND endpoint='bbo')
                ) ORDER BY observed_at"""
            observation_params = (network, *addresses)
        else:
            observations_query = """SELECT * FROM raw_observations
                WHERE network=? AND entity_type='market' AND endpoint='bbo'
                ORDER BY observed_at"""
            observation_params = (network,)
    else:
        observations_query = """SELECT * FROM raw_observations WHERE network=?
           AND entity_type IN ('account','market') ORDER BY observed_at"""
        observation_params = (network,)
    all_observations = list(store.connection.execute(
        observations_query, observation_params,
    ))
    fills: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    history_complete: defaultdict[str, dict[str, bool]] = defaultdict(dict)
    fill_history_intervals: defaultdict[str, list[tuple[int, int]]] = defaultdict(list)
    ws_fills_last: dict[str, str] = {}
    market_counts: Counter[str] = Counter()
    market_notional: defaultdict[str, Decimal] = defaultdict(Decimal)
    account_times: defaultdict[str, list[int]] = defaultdict(list)
    market_stream: defaultdict[str, Counter[str]] = defaultdict(Counter)
    market_first: dict[tuple[str, str], int] = {}
    market_last: dict[tuple[str, str], int] = {}
    bbo_times: defaultdict[str, list[int]] = defaultdict(list)
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
                if (endpoint == "userFillsByTime" and bool(observation["complete"])
                        and observation["window_start_ms"] is not None
                        and observation["window_end_ms"] is not None):
                    fill_history_intervals[address].append((
                        int(observation["window_start_ms"]),
                        int(observation["window_end_ms"]),
                    ))
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
                            if endpoint == "bbo":
                                bbo_times[symbol].append(stamp)

    by_address: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_pair: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for (address, _coin, _stamp, _tid), fill in fills.items():
        by_address[address].append(fill)
        coin = str(fill.get("coin", ""))
        by_pair[(address, coin)].append(fill)
        market_counts[coin] += 1
        try:
            market_notional[coin] += Decimal(str(fill.get("px", "0"))) * Decimal(
                str(fill.get("sz", "0"))
            )
        except (InvalidOperation, ValueError):
            pass
    accounts = []
    maturity_by_account: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for (address, coin), pair_rows in by_pair.items():
        expected_history = {"userFillsByTime", "userFunding", "userNonFundingLedgerUpdates"}
        history_is_complete = (
            expected_history <= set(history_complete[address])
            and all(history_complete[address].get(endpoint, False) for endpoint in expected_history)
        )
        target_row = store.connection.execute(
            """SELECT required_cycles,attempt,status FROM research_targets
               WHERE network=? AND address=? AND coin=?""",
            (network,address,coin),
        ).fetchone()
        target_cycles = int(target_row["required_cycles"]) if target_row else HYPOTHESIS_CYCLE_REFERENCE
        maturity_by_account[address].append(_pair_maturity(
            pair_rows, coin, bbo_times.get(coin, []),
            fill_history_intervals[address], history_is_complete, target_cycles,
        ))
        maturity_by_account[address][-1]["research_attempt"] = int(target_row["attempt"]) if target_row else 1
        maturity_by_account[address][-1]["workflow_status"] = target_row["status"] if target_row else "collecting"
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
            "data_maturity_by_market": sorted(
                maturity_by_account[address],
                key=lambda item: (-item["fully_reconstructed_position_excursions"], item["coin"]),
            ),
        })

    ranking = store.latest_market_selection(network)
    global_markets = [{"coin": row["coin"], "rank": row["rank"],
                       "venue": row["venue"], "market_type": row["market_type"]}
                      for row in (ranking["markets"] if ranking else [])]
    whale_by_fill_count = [{"coin": coin, "fills": count}
                           for coin, count in market_counts.most_common(10) if coin]
    whale_top = [{"coin": coin, "notional": format(value, "f"),
                  "fills": market_counts[coin]}
                 for coin, value in sorted(
                     market_notional.items(),
                     key=lambda item: (-item[1], -market_counts[item[0]], item[0]),
                 )[:10] if coin]
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
    candle_gaps = []
    for coin in whale_focus:
        coverage = coverage_by_coin.get(coin, {})
        missing = []
        if not coverage.get("public_trade_messages"):
            missing.append("trades")
        if not coverage.get("bbo_messages") and not coverage.get("order_book_messages"):
            missing.append("BBO/carnet")
        if missing:
            market_gaps.append({"coin": coin, "missing": missing})
        if not coverage.get("one_minute_candles"):
            candle_gaps.append(coin)
    return {
        "network": network,
        "candidate_accounts_retained": len(candidates),
        "accounts_currently_tracked": len(tracked),
        "tracked_accounts_with_observed_fills_http_or_websocket": sum(
            bool(by_address[row["address"].lower()]) for row in tracked
        ),
        "tracked_unique_observed_fills": len(fills),
        "tracked_markets_by_fill_count": whale_by_fill_count,
        "tracked_markets_by_observed_notional": whale_top,
        "latest_top_markets_by_24h_volume": global_markets,
        "accounts": accounts,
        "market_coverage_for_observed_whale_markets": market_coverage,
        "paper_replay_readiness": {
            "ready": False,
            "market_data_ready_for_top_5_whale_markets": not market_gaps,
            "top_5_whale_markets": whale_focus,
            "market_data_gaps": market_gaps,
            "markets_without_one_minute_candles": candle_gaps,
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
        "maturity_model": {
            "hypothesis_cycle_reference": HYPOTHESIS_CYCLE_REFERENCE,
            "validation_cycle_reference": VALIDATION_CYCLE_REFERENCE,
            "research_cycle_levels": list(RESEARCH_CYCLE_LEVELS),
            "unit": "completed perp position excursions (flat-to-flat or opening-and-return-to-observed-baseline) with complete HTTP fill coverage and BBO context",
            "calendar_time_is_only_an_estimate": True,
            "eta_method": "last up to 10 exploitable cycles per account-market pair; rate uses time from the first sampled cycle open through now, including quiet time; estimate available from 2 cycles; low confidence below 10 cycles",
            "limitations": [
            "Partial fills are connected through their startPosition and resulting position. A cycle may return to a non-zero observed baseline; exits of inventory already held when collection begins do not count. Ambiguous same-timestamp paths, truncated episodes, and spot fills are excluded.",
            "When one execution crosses a non-zero baseline, only the proportional size, fee, and realized PnL needed to return to that baseline are allocated to the cycle; the remainder closes pre-existing inventory.",
                "A cycle counts only if every fill timestamp lies in a complete userFillsByTime window and has a preceding BBO no older than 1 second.",
                "The BBO match is a timing proxy, not proof of gap-free depth or complete order-book capture. The stricter 90% in-capture coverage rate remains an additional gate.",
                "ETA uses the observed recent cycle rate through the current time, including quiet time since the latest cycle; a short sample can still misstate future activity or regime changes.",
            ],
        },
    }


def _pair_maturity(rows: list[dict[str, Any]], coin: str,
                   market_bbo_times: list[int],
                   complete_history_intervals: list[tuple[int, int]],
                   history_is_complete: bool,
                   target_cycles: int) -> dict[str, Any]:
    """Estimate data volume per account/market without treating partial fills as samples."""
    ordered = sorted(rows, key=lambda item: (
        _int_or_zero(item.get("time")), _int_or_zero(item.get("tid")),
    ))
    fill_ids = {
        (str(item.get("time", "")), str(item.get("tid", item.get("hash", ""))))
        for item in ordered
    }
    order_ids = {str(item.get("oid")) for item in ordered if item.get("oid") is not None}
    close_orders: set[str] = set()
    close_fills: list[dict[str, Any]] = []
    close_fill_count = 0
    realized = Decimal(0)
    notional = Decimal(0)
    for item in ordered:
        direction = str(item.get("dir", ""))
        if direction.startswith("Close ") or " > " in direction:
            close_fill_count += 1
            close_fills.append(item)
            if item.get("oid") is not None:
                close_orders.add(str(item["oid"]))
            realized += _decimal(item.get("closedPnl"))
        try:
            notional += Decimal(str(item.get("px", "0"))) * Decimal(str(item.get("sz", "0")))
        except (InvalidOperation, ValueError):
            pass

    cycles = reconstruct_position_cycles(
        ordered, market_bbo_times, complete_history_intervals,
        bbo_tolerance_ms=1_000,
    )
    # Retain this strict per-fill diagnostic alongside reconstructed episodes.
    closures: set[str] = set()
    for item in ordered:
        direction = str(item.get("dir", ""))
        if not (direction.startswith("Close ") or " > " in direction):
            continue
        try:
            starting = abs(Decimal(str(item.get("startPosition", "0"))))
            size = abs(Decimal(str(item.get("sz", "0"))))
        except (InvalidOperation, ValueError):
            continue
        if size and starting <= size:
            identity = str(item.get("oid") or item.get("tid") or item.get("time"))
            closures.add(identity)

    stamps = [_int_or_zero(item.get("time")) for item in ordered]
    stamps = [stamp for stamp in stamps if stamp]
    span_hours = max(0.0, (max(stamps) - min(stamps)) / 3_600_000) if len(stamps) > 1 else 0.0
    # Only closing fills aligned to the locally archived BBO count as usable
    # sample. Historical fills before market capture remain visible but do not
    # advance this data-volume gate.
    bbo_times = sorted(market_bbo_times)
    bbo_covered_1s = 0
    bbo_covered_250ms = 0
    bbo_window_start = bbo_times[0] if bbo_times else None
    bbo_window_end = bbo_times[-1] if bbo_times else None
    in_capture_window = 0
    contextualized_orders: set[str] = set()
    contextualized_order_stamps: dict[str, int] = {}
    for item in close_fills:
        stamp = _int_or_zero(item.get("time"))
        if bbo_window_start is None or stamp < bbo_window_start or stamp > bbo_window_end:
            continue
        in_capture_window += 1
        index = bisect_right(bbo_times, stamp) - 1
        age_ms = stamp - bbo_times[index] if index >= 0 else None
        if age_ms is not None and 0 <= age_ms <= 1_000:
            bbo_covered_1s += 1
            order_id = str(item.get("oid") or item.get("tid") or stamp)
            contextualized_orders.add(order_id)
            contextualized_order_stamps[order_id] = stamp
        if age_ms is not None and 0 <= age_ms <= 250:
            bbo_covered_250ms += 1
    usable_actions = len(contextualized_orders)
    rate_stamps = list(contextualized_order_stamps.values())
    usable_span_hours = ((max(rate_stamps) - min(rate_stamps)) / 3_600_000
                         if len(rate_stamps) > 1 else 0.0)
    rate = usable_actions / usable_span_hours if usable_span_hours >= 6 and usable_actions >= 10 else None
    exploitable_cycle_count = len(cycles)
    flat_to_flat_count = sum(cycle["cycle_kind"] == "flat_to_flat" for cycle in cycles)
    missing_hypothesis = max(0, target_cycles - exploitable_cycle_count)
    missing_validation = max(0, VALIDATION_CYCLE_REFERENCE - exploitable_cycle_count)
    context_pct_1s = 100 * bbo_covered_1s / in_capture_window if in_capture_window else None
    context_pct_250ms = 100 * bbo_covered_250ms / in_capture_window if in_capture_window else None
    volume_gate = exploitable_cycle_count >= target_cycles
    context_gate = context_pct_1s is not None and context_pct_1s >= 90
    eta_as_of_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    first_fill_ms = min(stamps) if stamps else None
    last_fill_ms = max(stamps) if stamps else None
    cycle_rate = _recent_cycle_rate(cycles, eta_as_of_ms)
    return {
        "coin": coin,
        "observed_fills": len(fill_ids),
        "first_fill_utc": _iso_ms(first_fill_ms),
        "last_fill_utc": _iso_ms(last_fill_ms),
        "last_fill_age_hours": round(max(0, eta_as_of_ms - last_fill_ms) / 3_600_000, 2)
        if last_fill_ms is not None else None,
        "distinct_order_ids": len(order_ids),
        "closing_fills": close_fill_count,
        "distinct_closing_orders": len(close_orders),
        "verified_flattening_events_proxy": len(closures),
        "usable_closing_order_actions_pilot": usable_actions,
        "fully_reconstructed_position_excursions": exploitable_cycle_count,
        # Compatibility alias for reports created before relative excursions
        # were accepted as complete cycles.
        "fully_reconstructed_position_cycles": exploitable_cycle_count,
        "flat_to_flat_cycles_with_complete_context": flat_to_flat_count,
        "exploitable_cycle_ids": [cycle["cycle_id"] for cycle in cycles],
        "exploitable_cycle_summaries": cycles,
        "hypothesis_cycle_target": target_cycles,
        "hypothesis_cycles_remaining": missing_hypothesis,
        "validation_cycle_target": VALIDATION_CYCLE_REFERENCE,
        "validation_cycles_remaining": missing_validation,
        "hypothesis_cycles_reached": missing_hypothesis == 0,
        "validation_cycles_reached": missing_validation == 0,
        "recent_exploitable_cycle_ids": [cycle["cycle_id"] for cycle in cycles[-100:]],
        "closing_fills_in_bbo_capture_window": in_capture_window,
        "closing_fills_with_bbo_within_1s": bbo_covered_1s,
        "closing_fills_with_bbo_within_250ms": bbo_covered_250ms,
        "bbo_capture_first_utc": _iso_ms(bbo_window_start),
        "bbo_capture_last_utc": _iso_ms(bbo_window_end),
        "closing_fill_bbo_context_pct_1s": round(context_pct_1s, 2) if context_pct_1s is not None else None,
        "closing_fill_bbo_context_pct_250ms": round(context_pct_250ms, 2) if context_pct_250ms is not None else None,
        "account_history_complete_at_collection": history_is_complete,
        "hypothesis_gate_ready": volume_gate and context_gate,
        "hypothesis_gate_blockers": [
            *([] if volume_gate else ["fully reconstructed, market-contextualized position-excursion sample below target"]),
            *([] if context_gate else ["less than 90% of in-capture closing fills have BBO context within 1 second"]),
            *([] if cycles else ["no complete position excursion has full fill history and BBO context"]),
        ],
        "observed_notional": format(notional, "f"),
        "observed_realized_closed_pnl": format(realized, "f"),
        "observed_span_hours": round(span_hours, 2),
        "usable_sample_span_hours": round(usable_span_hours, 2),
        "estimated_closing_order_actions_per_hour": round(rate, 3) if rate is not None else None,
        "estimated_exploitable_cycles_per_hour": round(
            cycle_rate, 3
        ) if cycle_rate is not None else None,
        "eta_observation_span_hours": round(
            _recent_cycle_span_hours(cycles, eta_as_of_ms), 2
        ) if cycle_rate is not None else None,
        "eta_cycles_sampled": min(len(cycles), 10) if cycle_rate is not None else 0,
        "hypothesis_eta_hours": _cycle_eta(cycles, missing_hypothesis, eta_as_of_ms),
        "validation_eta_hours": _cycle_eta(cycles, missing_validation, eta_as_of_ms),
        "eta_confidence": (
            "moderate" if cycle_rate is not None and len(cycles) >= 10
            else "low" if cycle_rate is not None
            else "insufficient_pair_history"
        ),
        "eta_is_informational_only": True,
    }


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _cycle_eta(cycles: list[dict[str, Any]], remaining: int,
               as_of_ms: int) -> float | None:
    if remaining == 0:
        return 0.0
    rate = _recent_cycle_rate(cycles, as_of_ms)
    if rate is None:
        return None
    return round(remaining / rate, 2)


def _recent_cycle_rate(cycles: list[dict[str, Any]],
                       as_of_ms: int) -> float | None:
    recent = cycles[-10:]
    if len(recent) < 2:
        return None
    span_hours = _recent_cycle_span_hours(recent, as_of_ms)
    if span_hours <= 0:
        return None
    return len(recent) / span_hours


def _recent_cycle_span_hours(cycles: list[dict[str, Any]],
                             as_of_ms: int) -> float:
    recent = cycles[-10:]
    if len(recent) < 2:
        return 0.0
    # Include the quiet time since the last completed cycle. Otherwise the ETA
    # remains artificially optimistic when a whale stops completing excursions.
    span_ms = as_of_ms - recent[0]["opened_at_ms"]
    return max(0.0, span_ms / 3_600_000)


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
