from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .providers.hyperliquid import validate_address


WINDOWS = ("day", "week", "month", "allTime")
METRICS = ("pnl", "roi")


def rank_leaderboard(payload: dict[str, Any], limit_per_window: int = 10
                     ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return capped PnL/ROI rankings and their unique positive-performance accounts."""
    if limit_per_window < 1:
        raise ValueError("limit_per_window doit être positif.")
    source_rows = payload.get("leaderboardRows")
    if not isinstance(source_rows, list):
        raise ValueError("La réponse leaderboard ne contient pas leaderboardRows.")

    normalized = []
    for row in source_rows:
        if not isinstance(row, dict):
            continue
        address = row.get("ethAddress")
        try:
            validate_address(str(address))
        except ValueError:
            continue
        account_value = _decimal(row.get("accountValue"))
        if account_value <= 0:
            continue
        windows = row.get("windowPerformances")
        performance = {}
        if isinstance(windows, list):
            for item in windows:
                if (isinstance(item, list) and len(item) == 2
                        and item[0] in WINDOWS and isinstance(item[1], dict)):
                    performance[item[0]] = item[1]
        normalized.append({
            "address": str(address).lower(),
            "display_name": str(row.get("displayName") or ""),
            "account_value": account_value,
            "performance": performance,
        })

    rankings: list[dict[str, Any]] = []
    candidates: dict[str, dict[str, Any]] = {}
    for window in WINDOWS:
        for metric in METRICS:
            eligible = []
            for row in normalized:
                stats = row["performance"].get(window) or {}
                pnl, roi, volume = (_decimal(stats.get(key)) for key in ("pnl", "roi", "vlm"))
                if pnl <= 0 or volume <= 0:
                    continue
                value = pnl if metric == "pnl" else roi
                eligible.append((value, row, pnl, roi, volume))
            eligible.sort(key=lambda item: (-item[0], item[1]["address"]))
            for rank, (_, row, pnl, roi, volume) in enumerate(eligible[:limit_per_window], start=1):
                ranking = {
                    "window": window,
                    "metric": metric,
                    "rank": rank,
                    "address": row["address"],
                    "display_name": row["display_name"],
                    "account_value": format(row["account_value"], "f"),
                    "pnl": format(pnl, "f"),
                    "roi": format(roi, "f"),
                    "volume": format(volume, "f"),
                }
                rankings.append(ranking)
                candidates.setdefault(row["address"], {
                    "address": row["address"],
                    "display_name": row["display_name"],
                    "best_rank_key": (WINDOWS.index(window), METRICS.index(metric), rank),
                })
    ordered_candidates = sorted(candidates.values(), key=lambda row: row["best_rank_key"])
    return rankings, ordered_candidates


def _decimal(value: Any) -> Decimal:
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else Decimal(0)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)
