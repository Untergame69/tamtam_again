"""Small, read-only diagnostics for the a880/HYPE archive."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from math import ceil
from typing import Iterable


def ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def quantiles(values: Iterable[float]) -> dict[str, float | int | None]:
    xs = sorted(values)
    if not xs:
        return {"n": 0, "p50": None, "p95": None, "max": None}

    def pick(q: float) -> float:
        return xs[max(0, ceil(q * len(xs)) - 1)]

    return {"n": len(xs), "p50": pick(.50), "p95": pick(.95), "max": xs[-1]}


def gap_summary(receipts: Iterable[int]) -> dict[str, int | None]:
    xs = sorted(receipts)
    gaps = [b-a for a, b in zip(xs, xs[1:])]
    return {
        "observations": len(xs),
        "gaps_gt_1s": sum(x > 1_000 for x in gaps),
        "gaps_gt_5s": sum(x > 5_000 for x in gaps),
        "gaps_gt_60s": sum(x > 60_000 for x in gaps),
        "max_gap_ms": max(gaps) if gaps else None,
    }


def live_fills(payload: dict, request: dict, coin: str) -> list[dict]:
    """Extract only live WS HYPE fills; REST and WS snapshots are excluded."""
    data = payload.get("data", {})
    stream = {**request.get("user_fills_stream", {}), **payload.get("_stream", {})}
    flag = data.get("isSnapshot")
    live = flag is False or (
        "isSnapshot" not in data
        and isinstance(stream.get("sequence"), int)
        and stream["sequence"] > 1
        and bool(stream.get("connection_id"))
    )
    if not live:
        return []
    return [x for x in data.get("fills", []) if x.get("coin") == coin]


def count_by_reason(rows: Iterable[dict]) -> dict[str, int]:
    return dict(Counter(str(x.get("reason", "unknown")) for x in rows))


def fee_crossed_summary(fills: Iterable[dict]) -> dict:
    """Describe signed fee and crossed fields without inferring fee tier."""
    groups = {"crossed": [], "not_crossed": [], "unknown": []}
    for fill in fills:
        crossed = fill.get("crossed")
        bucket = "crossed" if crossed is True else "not_crossed" if crossed is False else "unknown"
        groups[bucket].append(fill)
    result = {}
    for name, rows in groups.items():
        fee_rows = [r for r in rows if r.get("fee") is not None]
        negative = [float(r["fee"]) for r in fee_rows if float(r["fee"]) < 0]
        positive = [float(r["fee"]) for r in fee_rows if float(r["fee"]) > 0]
        result[name] = {
            "fills": len(rows),
            "fee_rows": len(fee_rows),
            "negative_fee_rows_rebate_per_official_schema": len(negative),
            "positive_fee_rows": len(positive),
            "signed_fee_sum": round(sum(float(r["fee"]) for r in fee_rows), 8),
            "negative_rebate_sum_signed": round(sum(negative), 8),
            "positive_charge_sum": round(sum(positive), 8),
            "builder_fee_rows": sum(r.get("builderFee") is not None for r in rows),
        }
    return result
