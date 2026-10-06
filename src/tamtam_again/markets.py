from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


TOP_MARKET_COUNT = 5
# Archive market context for the leading whale-traded symbols as well as the
# separate global top-five volume ranking.
STREAM_MARKET_COUNT = 26


def top_markets(snapshot: Any, limit: int = TOP_MARKET_COUNT) -> list[dict[str, Any]]:
    """Rank spot and all perp DEX instruments by 24h notional volume."""
    if limit < 1:
        raise ValueError("limit doit être positif.")
    groups: list[tuple[str, str, Any]] = []
    if isinstance(snapshot, list):
        # Keep the original single-perp-snapshot shape usable by old data/tests.
        groups.append(("perp", "perps-main", snapshot))
    elif isinstance(snapshot, dict):
        perp_universes = snapshot.get("perpUniverses")
        if not isinstance(perp_universes, list) or not perp_universes:
            raise ValueError("Snapshots perpétuels absents ou invalides.")
        perp_dexes = snapshot.get("perpDexs", [])
        for dex_index, pair in enumerate(perp_universes):
            dex = perp_dexes[dex_index] if dex_index < len(perp_dexes) else None
            dex_name = dex.get("name") if isinstance(dex, dict) else None
            venue = "perps-main" if dex_index == 0 else (
                f"perps:{dex_name}" if dex_name else f"perps-dex-{dex_index}"
            )
            groups.append(("perp", venue, pair))
        spot = snapshot.get("spotMetaAndAssetCtxs")
        if spot is not None:
            groups.append(("spot", "spot", spot))
    else:
        raise ValueError("Format des univers de marché inattendu.")

    ranked = []
    for market_type, venue, pair in groups:
        if not isinstance(pair, list) or len(pair) < 2:
            raise ValueError(f"Format univers {venue} inattendu.")
        metadata, contexts = pair[0], pair[1]
        if not isinstance(metadata, dict) or not isinstance(contexts, list):
            raise ValueError(f"Méta-données ou contextes {venue} invalides.")
        universe = metadata.get("universe")
        if not isinstance(universe, list):
            raise ValueError(f"Univers {venue} invalide.")
        if market_type == "spot":
            contexts_by_coin = {
                context.get("coin"): context for context in contexts
                if isinstance(context, dict) and context.get("coin")
            }
            pairs = [(instrument, contexts_by_coin.get(instrument.get("name")))
                     for instrument in universe if isinstance(instrument, dict)]
        elif len(universe) == len(contexts):
            pairs = zip(universe, contexts)
        else:
            raise ValueError(f"Univers et contextes {venue} désalignés.")
        for instrument, context in pairs:
            if not isinstance(instrument, dict) or not isinstance(context, dict):
                continue
            coin = instrument.get("name")
            volume = _decimal(context.get("dayNtlVlm"))
            if not coin or volume <= 0 or instrument.get("isDelisted"):
                continue
            ranked.append({
                "coin": str(coin),
                "market_type": market_type,
                "venue": venue,
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
