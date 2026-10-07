from __future__ import annotations

import json
import random
import sys
import threading
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import uuid4

from websockets.sync.client import connect

from .storage import Store, decode_observation_payload, utc_now
from .telemetry import Telemetry


WEBSOCKET_URLS = {
    "hyperliquid-mainnet": "wss://api.hyperliquid.xyz/ws",
    "hyperliquid-testnet": "wss://api.hyperliquid-testnet.xyz/ws",
}
MAX_USER_SUBSCRIPTIONS = 10


def _subscriptions(store: Store, network: str, market_limit: int,
                   depth_limit: int = 30) -> tuple[list[str], list[str], list[str]]:
    accounts = [row["address"] for row in store.candidates(network)
                if row["status"] == "tracked"]
    accounts = accounts[:MAX_USER_SUBSCRIPTIONS]
    usage: dict[str, tuple[int, Decimal]] = {}
    latest_fill_by_pair: dict[tuple[str, str], int] = {}
    now_ms = int(time.time() * 1000)
    usage_cutoff_ms = now_ms - 86_400_000
    if accounts:
        placeholders = ",".join("?" for _ in accounts)
        rows = store.connection.execute(
            f"""SELECT * FROM raw_observations
                WHERE network=? AND entity_type='account'
                  AND endpoint IN ('userFillsByTime', 'userFills')
                  AND entity_id IN ({placeholders})""",
            [network, *accounts],
        ).fetchall()
        unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for row in rows:
            try:
                payload = decode_observation_payload(row)
            except (ValueError, TypeError):
                continue
            if row["endpoint"] == "userFills":
                payload = payload.get("data", {}).get("fills", []) if isinstance(payload, dict) else []
            if not isinstance(payload, list):
                continue
            for fill in payload:
                if not isinstance(fill, dict) or not fill.get("coin"):
                    continue
                key = (row["entity_id"], str(fill["coin"]), str(fill.get("time", "")),
                       str(fill.get("tid", fill.get("hash", ""))))
                unique[key] = fill
        for (address, coin, stamp, _), fill in unique.items():
            try:
                fill_ms = int(stamp)
            except (TypeError, ValueError):
                continue
            pair_key = (address, coin)
            latest_fill_by_pair[pair_key] = max(
                latest_fill_by_pair.get(pair_key, 0), fill_ms
            )
            if fill_ms < usage_cutoff_ms:
                continue
            try:
                notional = Decimal(str(fill.get("px", "0"))) * Decimal(
                    str(fill.get("sz", "0"))
                )
            except (InvalidOperation, ValueError):
                notional = Decimal(0)
            count, total = usage.get(coin, (0, Decimal(0)))
            usage[coin] = (count + 1, total + notional)
    if usage:
        ranked_markets = [coin for coin, _ in sorted(
            usage.items(), key=lambda item: (-item[1][1], -item[1][0], item[0])
        )]
    else:
        selection = store.latest_market_selection(network)
        ranked_markets = [row["coin"] for row in selection["markets"]] if selection else []

    # Research pairs whose reviewers requested a larger cumulative sample get
    # scarce L2 capacity first. Within the same target size, the most recently
    # updated decision comes first, then current activity. This lets the next
    # RE sample acquire the context that was missing without increasing the
    # overall market/depth caps or using a calendar-time maturity gate.
    if accounts:
        placeholders = ",".join("?" for _ in accounts)
        target_rows = store.connection.execute(
            f"""SELECT address,coin,updated_at,attempt,required_cycles
                FROM research_targets WHERE network=? AND status='collecting'
                  AND (required_cycles>? OR attempt>1)
                  AND address IN ({placeholders})""",
            [network, 5, *accounts],
        ).fetchall()
    else:
        target_rows = []
    active_targets = []
    quiet_targets = []
    for row in target_rows:
        last_fill_ms = latest_fill_by_pair.get((row["address"], row["coin"]), 0)
        item = (last_fill_ms, row)
        (active_targets if last_fill_ms >= now_ms - 86_400_000 else quiet_targets).append(item)
    target_sort = lambda item: (
        int(item[1]["required_cycles"]),
        int(item[1]["attempt"]),
        str(item[1]["updated_at"]),
        item[0],
        item[1]["coin"], item[1]["address"],
    )
    active_targets.sort(key=target_sort, reverse=True)
    quiet_targets.sort(
        key=lambda item: (
            int(item[1]["required_cycles"]),
            str(item[1]["updated_at"]),
            int(item[1]["attempt"]), item[1]["coin"], item[1]["address"],
        ),
        reverse=True,
    )
    research_markets = list(dict.fromkeys(
        str(row["coin"]) for _, row in [*active_targets, *quiet_targets]
    ))
    markets = list(dict.fromkeys([*research_markets, *ranked_markets]))[:market_limit]
    depth_markets = list(dict.fromkeys([*research_markets, *ranked_markets]))[:depth_limit]
    return accounts, markets, depth_markets


def tracked_market_symbols(store: Store, network: str,
                           market_limit: int) -> list[str]:
    """Return the cohort's highest-notional symbols, with global fallback."""
    return _subscriptions(store, network, market_limit)[1]


def _subscribe(websocket: Any, subscription: dict[str, Any], active: set[str]) -> bool:
    key = json.dumps(subscription, sort_keys=True, separators=(",", ":"))
    if key in active:
        return False
    websocket.send(json.dumps({"method": "subscribe", "subscription": subscription}))
    active.add(key)
    return True


def _unsubscribe(websocket: Any, subscription: dict[str, Any], active: set[str]) -> None:
    key = json.dumps(subscription, sort_keys=True, separators=(",", ":"))
    if key in active:
        websocket.send(json.dumps({"method": "unsubscribe", "subscription": subscription}))
        active.discard(key)


def _save_message(store: Store, network: str, message: dict[str, Any],
                  pending: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]],
                  user_fills_stream: dict[str, Any] | None = None) -> None:
    channel = message.get("channel")
    data = message.get("data")
    if not isinstance(channel, str) or channel in {"pong", "subscriptionResponse"}:
        return
    address = data.get("user") if isinstance(data, dict) else None
    if channel in {"userFills", "userEvents", "userFundings",
                   "userNonFundingLedgerUpdates", "orderUpdates"}:
        if not isinstance(address, str):
            return
        entity_type, entity_id = "account", address.lower()
    elif channel in {"trades", "l2Book", "bbo", "candle"}:
        coin = None
        if isinstance(data, dict):
            coin = data.get("coin")
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            coin = data[0].get("coin") or data[0].get("s")
        if not isinstance(coin, str):
            return
        entity_type, entity_id = "market", coin
    else:
        return
    received_at = utc_now()
    if entity_type == "market":
        pending.setdefault((channel, entity_id), []).append((received_at, message))
        return
    request_payload = {"channel": channel}
    if channel == "userFills" and user_fills_stream:
        request_payload["user_fills_stream"] = user_fills_stream
    store.save_observation(
        network=network, source="hyperliquid-websocket-v1",
        entity_type=entity_type, entity_id=entity_id, endpoint=channel,
        payload=message, request_payload=request_payload,
        requested_at=received_at,
        record_count=(len(data) if isinstance(data, list) else None),
    )


def _flush_market_events(store: Store, network: str,
                         pending: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]]) -> None:
    if not pending:
        return
    for (channel, coin), events in pending.items():
        server_times = []
        for _, message in events:
            data = message.get("data")
            for value in data if isinstance(data, list) else [data]:
                if not isinstance(value, dict):
                    continue
                stamp = value.get("time", value.get("t"))
                try:
                    if stamp is not None:
                        server_times.append(int(stamp))
                except (TypeError, ValueError):
                    pass
        store.save_observation(
            network=network, source="hyperliquid-websocket-v1",
            entity_type="market", entity_id=coin, endpoint=channel,
            payload={"events": [{"received_at": received_at, "message": message}
                                for received_at, message in events]},
            request_payload={"channel": channel},
            requested_at=events[0][0],
            window_start_ms=min(server_times) if server_times else None,
            window_end_ms=max(server_times) if server_times else None,
            record_count=len(events),
        )
    pending.clear()


def _stream_health(store: Store, network: str, session: str, kind: str,
                   markets: list[str], connected: bool = True) -> None:
    stamp = utc_now()
    payload = {"kind": kind, "session": session, "connected": connected,
               "markets": sorted(markets), "recorded_at": stamp}
    store.save_observation(network=network, source="hyperliquid-websocket-v1",
                           entity_type="stream", entity_id=session, endpoint="streamHealth",
                           payload=payload, requested_at=stamp)


def run_websocket_collector(stop_event: threading.Event, db_path: Path,
                            network: str, market_limit: int,
                            depth_limit: int) -> None:
    """Stream tracked-user fills and bounded market feeds with reconnects."""
    if network not in WEBSOCKET_URLS:
        raise ValueError(f"Réseau WebSocket inconnu : {network}")
    if not 1 <= market_limit <= 100:
        raise ValueError("max-stream-markets doit être compris entre 1 et 100.")
    if not 1 <= depth_limit <= market_limit:
        raise ValueError("max-depth-markets doit être compris entre 1 et max-stream-markets.")
    retry_delay = 1.0
    store = Store(db_path)
    telemetry = Telemetry(db_path.with_suffix(".telemetry.sqlite3"))
    metrics = {"frames": 0, "bytes": 0, "queue_peak_messages": 0, "max_flush_lag_seconds": 0.0, "flush_seconds": 0.0, "reconnections": 0}
    measurement_started = time.monotonic()
    def flush_measured():
        started = time.monotonic()
        queued = sum(len(events) for events in pending.values())
        metrics["queue_peak_messages"] = max(metrics["queue_peak_messages"], queued)
        for events in pending.values():
            if events:
                from datetime import datetime
                lag = time.time()-datetime.fromisoformat(events[0][0]).timestamp()
                metrics["max_flush_lag_seconds"] = max(metrics["max_flush_lag_seconds"], lag)
        _flush_market_events(store, network, pending)
        metrics["flush_seconds"] += time.monotonic()-started
    while not stop_event.is_set():
        pending: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = {}
        connected_at: float | None = None
        user_fills_session_id = None
        bbo_coins = []
        try:
            with connect(WEBSOCKET_URLS[network], ping_interval=None,
                         open_timeout=15, close_timeout=5,
                         max_size=8 * 1024 * 1024) as websocket:
                connected_at = time.monotonic()
                active: set[str] = set()
                acknowledged_bbo: set[str] = set()
                user_fills_session_id = uuid4().hex
                user_fills_sequences: dict[str, int] = {}
                user_fills_subscription_at: dict[str, str] = {}
                market_coins: list[str] = []
                bbo_coins: list[str] = []
                depth_coins: list[str] = []
                accounts, markets, depth_markets = _subscriptions(
                    store, network, market_limit, depth_limit
                )
                for address in accounts:
                    _subscribe(websocket, {"type": "userFundings", "user": address}, active)
                    if _subscribe(websocket, {"type": "userFills", "user": address}, active):
                        user_fills_subscription_at[address.lower()] = utc_now()
                for coin in markets:
                    market_coins.append(coin)
                    _subscribe(websocket, {"type": "trades", "coin": coin}, active)
                    bbo_coins.append(coin)
                    _subscribe(websocket, {"type": "bbo", "coin": coin}, active)
                for coin in depth_markets:
                    depth_coins.append(coin)
                    _subscribe(websocket, {"type": "l2Book", "coin": coin,
                                          "fast": True}, active)
                _stream_health(store, network, user_fills_session_id, "connection", [])
                next_heartbeat = time.monotonic() + 30
                next_refresh = time.monotonic() + 60
                next_flush = time.monotonic() + 1
                last_server_message = time.monotonic()
                print(json.dumps({"collector": "websocket", "state": "connected",
                                  "tracked_accounts": len(accounts),
                                  "market_symbols": market_coins,
                                  "full_book_symbols": depth_coins}, ensure_ascii=False),
                      flush=True)
                while not stop_event.is_set():
                    now = time.monotonic()
                    if now - last_server_message > 65:
                        raise TimeoutError("No server frame/heartbeat for 65 seconds")
                    if now >= next_heartbeat:
                        websocket.send(json.dumps({"method": "ping"}))
                        next_heartbeat = now + 30
                    if now >= next_refresh:
                        current_accounts, current_markets, current_depth = _subscriptions(
                            store, network, market_limit, depth_limit
                        )
                        for address in current_accounts:
                            _subscribe(websocket, {"type": "userFundings", "user": address}, active)
                            if _subscribe(websocket, {"type": "userFills", "user": address}, active):
                                user_fills_subscription_at[address.lower()] = utc_now()
                        for address in accounts:
                            if address not in current_accounts:
                                _unsubscribe(websocket, {"type": "userFills", "user": address}, active)
                                _unsubscribe(websocket, {"type": "userFundings", "user": address}, active)
                        accounts = current_accounts
                        new_depth = current_depth
                        for coin in list(market_coins):
                            if coin not in current_markets:
                                _unsubscribe(websocket, {"type": "trades", "coin": coin}, active)
                                market_coins.remove(coin)
                        for coin in list(bbo_coins):
                            if coin not in current_markets:
                                _unsubscribe(websocket, {"type": "bbo", "coin": coin}, active)
                                bbo_coins.remove(coin)
                                acknowledged_bbo.discard(coin)
                        for coin in list(depth_coins):
                            if coin not in new_depth:
                                _unsubscribe(websocket, {"type": "l2Book", "coin": coin,
                                                         "fast": True}, active)
                                depth_coins.remove(coin)
                        for coin in current_markets:
                            if coin not in market_coins:
                                market_coins.append(coin)
                                _subscribe(websocket, {"type": "trades", "coin": coin}, active)
                            if coin not in bbo_coins:
                                bbo_coins.append(coin)
                                _subscribe(websocket, {"type": "bbo", "coin": coin}, active)
                            if coin in new_depth and coin not in depth_coins:
                                depth_coins.append(coin)
                                _subscribe(websocket, {"type": "l2Book", "coin": coin,
                                                      "fast": True}, active)
                        _stream_health(store, network, user_fills_session_id, "subscriptions", sorted(acknowledged_bbo))
                        next_refresh = now + 60
                    try:
                        raw = websocket.recv(timeout=1)
                    except TimeoutError:
                        if time.monotonic() >= next_flush:
                            flush_measured()
                            next_flush = time.monotonic() + 1
                        continue
                    if not isinstance(raw, str):
                        continue
                    metrics["frames"] += 1
                    metrics["bytes"] += len(raw.encode("utf-8"))
                    message = json.loads(raw)
                    last_server_message = time.monotonic()
                    if message.get("channel") == "subscriptionResponse":
                        ack = message.get("data", {})
                        sub = ack.get("subscription", {})
                        if sub.get("type") == "bbo":
                            if ack.get("method") == "subscribe":
                                acknowledged_bbo.add(sub["coin"])
                            elif ack.get("method") == "unsubscribe":
                                acknowledged_bbo.discard(sub["coin"])
                    if message.get("channel") == "pong":
                        telemetry.measure("websocket", {**metrics, "window_seconds": time.monotonic()-measurement_started,
                            "user_addresses": len(accounts), "subscriptions_sent": len(active),
                            "acknowledged_bbo": len(acknowledged_bbo), "connections": 1,
                            "queue_current_messages": sum(len(v) for v in pending.values()),
                            "session": user_fills_session_id})
                        measurement_started = time.monotonic()
                        metrics = {k: 0 for k in metrics}
                        _stream_health(store, network, user_fills_session_id, "heartbeat", sorted(acknowledged_bbo))
                    message["_stream"] = {"connection_id": user_fills_session_id}
                    stream_metadata = None
                    if message.get("channel") == "userFills":
                        data = message.get("data")
                        address = data.get("user") if isinstance(data, dict) else None
                        if isinstance(address, str):
                            address = address.lower()
                            sequence = user_fills_sequences.get(address, 0) + 1
                            user_fills_sequences[address] = sequence
                            stream_metadata = {
                                "connection_id": user_fills_session_id,
                                "sequence": sequence,
                                "subscription_sent_at": user_fills_subscription_at.get(address),
                                "first_frame_after_subscription": sequence == 1,
                            }
                    _save_message(store, network, message, pending, stream_metadata)
                    if time.monotonic() >= next_flush:
                        flush_measured()
                        next_flush = time.monotonic() + 1
        except Exception as exc:
            metrics["reconnections"] += 1
            telemetry.measure("websocket_error", {"type": type(exc).__name__, "session": user_fills_session_id})
            if not stop_event.is_set():
                if connected_at is not None and time.monotonic() - connected_at >= 60:
                    retry_delay = 1.0
                print(json.dumps({"collector": "websocket", "state": "reconnecting",
                                  "error": f"{type(exc).__name__}: {exc}",
                                  "retry_seconds": round(retry_delay, 1)}, ensure_ascii=False),
                      flush=True)
                stop_event.wait(retry_delay + random.random() * 0.5)
                retry_delay = min(60.0, retry_delay * 2)
        finally:
            try:
                if user_fills_session_id:
                    _stream_health(store, network, user_fills_session_id, "connection", bbo_coins, connected=False)
                _flush_market_events(store, network, pending)
            except Exception as exc:
                print(json.dumps({"collector": "websocket", "state": "storage_error",
                                  "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False),
                      file=sys.stderr, flush=True)
    store.close()
