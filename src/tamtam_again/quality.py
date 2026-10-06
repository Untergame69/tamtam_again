"""Public stream continuity diagnostics; quote-change age is not staleness."""
from __future__ import annotations

from datetime import datetime, timezone
from bisect import bisect_left
from typing import Any
from .storage import Store, decode_observation_payload


def continuous_bbo_fill_times(store: Store, network: str, coin: str, fills: list[dict[str,Any]], *, heartbeat_timeout_ms: int = 65_000) -> list[int]:
    # Old archives have no session health proof: keep their conservative age
    # diagnostics, never retrospectively invent continuity.
    health_rows = list(store.connection.execute("SELECT * FROM raw_observations WHERE network=? AND source='hyperliquid-websocket-v1' AND endpoint='streamHealth' ORDER BY observed_at", (network,)))
    if not health_rows:
        return []
    health_times = [int(datetime.fromisoformat(row["observed_at"]).timestamp()*1000) for row in health_rows]
    valid = []
    for stamp in sorted({int(f["time"]) for f in fills if f.get("time")}):
        iso = datetime.fromtimestamp(stamp/1000,timezone.utc).isoformat(timespec="milliseconds")
        index = bisect_left(health_times, stamp)-1
        if index < 0:
            continue
        health = health_rows[index]
        state = decode_observation_payload(health)
        health_ms = int(datetime.fromisoformat(health["requested_at"]).timestamp()*1000)
        if state.get("kind") == "subscriptions":
            continue
        if not state.get("connected") or coin not in state.get("markets",[]) or stamp-health_ms > heartbeat_timeout_ms:
            continue
        quotes = store.connection.execute("SELECT * FROM raw_observations WHERE network=? AND entity_type='market' AND entity_id=? AND endpoint='bbo' AND observed_at<? ORDER BY observed_at DESC LIMIT 2",(network,coin,iso))
        candidate = None
        for row in quotes:
            payload = decode_observation_payload(row)
            for frame in payload.get("events",[]):
                receipt = int(datetime.fromisoformat(frame["received_at"]).timestamp()*1000)
                message = frame["message"]
                data = message.get("data",{})
                if (receipt < stamp and int(data.get("time",stamp+1)) <= stamp
                        and message.get("_stream",{}).get("connection_id") == state.get("session")):
                    bbo = data.get("bbo",[])
                    if len(bbo) == 2 and all(isinstance(v,dict) and v.get("px") for v in bbo):
                        candidate = receipt if candidate is None else max(candidate,receipt)
        if candidate is not None:
            valid.append(stamp)
    return valid
