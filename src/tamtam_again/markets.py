from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


TOP_MARKET_COUNT = 5


def top_markets(snapshot: Any, limit: int = TOP_MARKET_COUNT) -> list[dict[str, Any]]:
    """Rank the first perp DEX universe by 24h notional volume."""
    if not isinstance(snapshot, list) or len(snapshot) < 2:
        raise ValueError("Format metaAndAssetCtxs inattendu.")
    metadata, contexts = snapshot[0], snapshot[1]
    if not isinstance(metadata, dict) or not isinstance(contexts, list):
        raise ValueError("Méta-données ou contextes de marché invalides.")
    universe = metadata.get("universe")
    if not isinstance(universe, list) or len(universe) != len(contexts):
        raise ValueError("Univers et contextes de marché désalignés.")
    ranked = []
    for instrument, context in zip(universe, contexts):
        if not isinstance(instrument, dict) or not isinstance(context, dict):
            continue
        coin = instrument.get("name")
        volume = _decimal(context.get("dayNtlVlm"))
        if not coin or volume <= 0 or instrument.get("isDelisted"):
            continue
        ranked.append({
            "coin": str(coin),
            "day_notional_volume": format(volume, "f"),
            "instrument": instrument,
            "context": context,
        })
    ranked.sort(key=lambda item: (-_decimal(item["day_notional_volume"],
                                            Decimal("0")), item["coin"]))
    return [{"rank": index, **item} for index, item in enumerate(ranked[:limit], start=1)]


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else default
    except (InvalidOperation, ValueError, TypeError):
        return default
