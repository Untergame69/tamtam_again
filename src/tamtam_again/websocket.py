from __future__ import annotations

import json
import random
import sys
import threading
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from websockets.sync.client import connect

from .storage import Store, decode_observation_payload, utc_now


WEBSOCKET_URLS = {
    "hyperliquid-mainnet": "wss://api.hyperliquid.xyz/ws",
    "hyperliquid-testnet": "wss://api.hyperliquid-testnet.xyz/ws",
}
MAX_USER_SUBSCRIPTIONS = 10


def _subscriptions(store: Store, network: str, market_limit: int
                   ) -> tuple[list[str], list[str]]:
    accounts = [row["address"] for row in store.candidates(network)
                if row["status"] == "tracked"]
    accounts = accounts[:MAX_USER_SUBSCRIPTIONS]
    usage: dict[str, tuple[int, Decimal]] = {}
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
        for (_, coin, _, _), fill in unique.items():
            try:
                notional = Decimal(str(fill.get("px", "0"))) * Decimal(
                    str(fill.get("sz", "0"))
                )
            except (InvalidOperation, ValueError):
                notional = Decimal(0)
            count, total = usage.get(coin, (0, Decimal(0)))
            usage[coin] = (count + 1, total + notional)
    if usage:
        markets = [coin for coin, _ in sorted(
            usage.items(), key=lambda item: (-item[1][1], -item[1][0], item[0])
        )]
    else:
        selection = store.latest_market_selection(network)
        markets = [row["coin"] for row in selection["markets"]] if selection else []
    return accounts, list(dict.fromkeys(markets))[:market_limit]


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
                  pending: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]]) -> None:
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
    store.save_observation(
        network=network, source="hyperliquid-websocket-v1",
        entity_type=entity_type, entity_id=entity_id, endpoint=channel,
        payload=message, request_payload={"channel": channel},
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
    while not stop_event.is_set():
        pending: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = {}
        connected_at: float | None = None
        try:
            with connect(WEBSOCKET_URLS[network], ping_interval=None,
                         open_timeout=15, close_timeout=5,
                         max_size=8 * 1024 * 1024) as websocket:
                connected_at = time.monotonic()
                active: set[str] = set()
                market_coins: list[str] = []
                depth_coins: list[str] = []
                accounts, markets = _subscriptions(store, network, market_limit)
                for address in accounts:
                    _subscribe(websocket, {"type": "userFills", "user": address}, active)
                for coin in markets:
                    market_coins.append(coin)
                    _subscribe(websocket, {"type": "trades", "coin": coin}, active)
                    if len(depth_coins) < depth_limit:
                        depth_coins.append(coin)
                        _subscribe(websocket, {"type": "bbo", "coin": coin}, active)
                        _subscribe(websocket, {"type": "l2Book", "coin": coin,
                                              "fast": True}, active)
                next_heartbeat = time.monotonic() + 30
                next_refresh = time.monotonic() + 60
                next_flush = time.monotonic() + 1
                print(json.dumps({"collector": "websocket", "state": "connected",
                                  "tracked_accounts": len(accounts),
                                  "market_symbols": market_coins,
                                  "full_book_symbols": depth_coins}, ensure_ascii=False),
                      flush=True)
                while not stop_event.is_set():
                    now = time.monotonic()
                    if now >= next_heartbeat:
                        websocket.send(json.dumps({"method": "ping"}))
                        next_heartbeat = now + 30
                    if now >= next_refresh:
                        current_accounts, current_markets = _subscriptions(
                            store, network, market_limit
                        )
                        for address in current_accounts:
                            _subscribe(websocket, {"type": "userFills", "user": address}, active)
                        new_depth = current_markets[:depth_limit]
                        for coin in list(market_coins):
                            if coin not in current_markets:
                                _unsubscribe(websocket, {"type": "trades", "coin": coin}, active)
                                market_coins.remove(coin)
                        for coin in list(depth_coins):
                            if coin not in new_depth:
                                _unsubscribe(websocket, {"type": "bbo", "coin": coin}, active)
                                _unsubscribe(websocket, {"type": "l2Book", "coin": coin,
                                                         "fast": True}, active)
                                depth_coins.remove(coin)
                        for coin in current_markets:
                            if coin not in market_coins:
                                market_coins.append(coin)
                                _subscribe(websocket, {"type": "trades", "coin": coin}, active)
                            if coin in new_depth and coin not in depth_coins:
                                depth_coins.append(coin)
                                _subscribe(websocket, {"type": "bbo", "coin": coin}, active)
                                _subscribe(websocket, {"type": "l2Book", "coin": coin,
                                                      "fast": True}, active)
                        next_refresh = now + 60
                    try:
                        raw = websocket.recv(timeout=1)
                    except TimeoutError:
                        if time.monotonic() >= next_flush:
                            _flush_market_events(store, network, pending)
                            next_flush = time.monotonic() + 1
                        continue
                    if not isinstance(raw, str):
                        continue
                    message = json.loads(raw)
                    _save_message(store, network, message, pending)
                    if time.monotonic() >= next_flush:
                        _flush_market_events(store, network, pending)
                        next_flush = time.monotonic() + 1
        except Exception as exc:
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
                _flush_market_events(store, network, pending)
            except Exception as exc:
                print(json.dumps({"collector": "websocket", "state": "storage_error",
                                  "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False),
                      file=sys.stderr, flush=True)
    store.close()
