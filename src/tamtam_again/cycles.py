"""Conservative reconstruction of complete perpetual position episodes."""
from __future__ import annotations

from bisect import bisect_right
from decimal import Decimal, InvalidOperation
import hashlib
from typing import Any


ZERO = Decimal(0)
TOLERANCE = Decimal("0.00000001")


def reconstruct_position_cycles(
    fills: list[dict[str, Any]],
    bbo_times: list[int],
    complete_history_intervals: list[tuple[int, int]],
    *,
    bbo_tolerance_ms: int = 1_000,
) -> list[dict[str, Any]]:
    """Return only flat-to-flat perp episodes whose fills have complete context.

    startPosition is the authoritative pre-fill position. Fills at the same
    timestamp are ordered by matching each pre-position to the preceding
    fill's post-position. Ambiguous or truncated episodes are discarded.
    """
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for fill in fills:
        stamp = _integer(fill.get("time"))
        tid = str(fill.get("tid", fill.get("hash", "")))
        if stamp and tid:
            unique[(str(stamp), tid)] = fill

    groups: dict[int, list[dict[str, Any]]] = {}
    for fill in unique.values():
        groups.setdefault(_integer(fill.get("time")), []).append(fill)

    market_times = sorted(set(bbo_times))
    intervals = sorted(complete_history_intervals)
    output: list[dict[str, Any]] = []
    position: Decimal | None = None
    active: dict[str, Any] | None = None

    for stamp in sorted(groups):
        pending = list(groups[stamp])
        pending.sort(key=lambda item: str(item.get("tid", "")))
        while pending:
            parsed = [(fill, _fill_positions(fill)) for fill in pending]
            parsed = [(fill, values) for fill, values in parsed if values is not None]
            pending = [fill for fill, _ in parsed]
            if not parsed:
                active = None
                position = None
                break

            if position is None:
                # A flat opening gives an episode a known start. Otherwise we
                # track the unknown episode only until it returns to flat.
                first = next((pair for pair in parsed
                              if _near_zero(pair[1][0]) and _is_open(pair[0])), parsed[0])
            else:
                matches = [pair for pair in parsed if _near(pair[1][0], position)]
                if len(matches) == 1:
                    first = matches[0]
                elif len(matches) > 1:
                    # Multiple executions from the same net position at one
                    # timestamp cannot be ordered safely from public fields.
                    active = None
                    position = None
                    first = parsed[0]
                else:
                    # A missing transition means history is truncated or the
                    # same-timestamp fills are ambiguous; do not bridge it.
                    active = None
                    position = None
                    first = parsed[0]

            fill, values = first
            pending.remove(fill)
            before, after = values
            if position is None:
                position = before
            if not _near(before, position):
                active = None
                position = before

            if _near_zero(before) and _is_open(fill):
                active = _new_episode(fill, stamp)

            if active is not None:
                _add_fill(active, fill, stamp, market_times, intervals, bbo_tolerance_ms)

            crossed = (before > ZERO and after < ZERO) or (before < ZERO and after > ZERO)
            flat = _near_zero(after)
            if flat and active is not None:
                active["closed_at_ms"] = stamp
                active["closed_position"] = True
                episode = _finish_episode(active, bbo_tolerance_ms)
                if episode["exploitable"]:
                    output.append(episode)
                active = None
            elif crossed:
                if active is not None:
                    active["closed_at_ms"] = stamp
                    active["closed_position"] = True
                    episode = _finish_episode(active, bbo_tolerance_ms)
                    if episode["exploitable"]:
                        output.append(episode)
                active = _new_episode(fill, stamp)
                active["side"] = "long" if after > ZERO else "short"
                # A flip fill closes the old side and opens the new one. Its
                # close PnL belongs only to the episode that just ended.
                _add_fill(active, fill, stamp, market_times, intervals,
                          bbo_tolerance_ms, include_realized=False)
            elif _near_zero(after):
                position = ZERO
            position = after

    # Open or truncated position episodes intentionally do not count.
    return output


def _new_episode(fill: dict[str, Any], stamp: int) -> dict[str, Any]:
    before, after = _fill_positions(fill) or (ZERO, ZERO)
    return {
        "opened_at_ms": stamp,
        "closed_at_ms": None,
        "side": "long" if after > before else "short",
        "fills": [],
        "notional": ZERO,
        "fees": ZERO,
        "realized_pnl": ZERO,
        "all_bbo_context": True,
        "all_history_covered": True,
    }


def _add_fill(episode: dict[str, Any], fill: dict[str, Any], stamp: int,
              market_times: list[int], intervals: list[tuple[int, int]],
              tolerance_ms: int, *, include_realized: bool = True) -> None:
    episode["fills"].append(fill)
    episode["notional"] += _decimal(fill.get("px")) * _decimal(fill.get("sz"))
    episode["fees"] += _decimal(fill.get("fee"))
    if include_realized:
        episode["realized_pnl"] += _decimal(fill.get("closedPnl"))
    bbo_index = bisect_right(market_times, stamp) - 1
    bbo_ok = (bbo_index >= 0 and 0 <= stamp - market_times[bbo_index] <= tolerance_ms)
    episode["all_bbo_context"] = episode["all_bbo_context"] and bbo_ok
    episode["all_history_covered"] = (
        episode["all_history_covered"] and _covered(stamp, intervals)
    )


def _finish_episode(episode: dict[str, Any], tolerance_ms: int) -> dict[str, Any]:
    identifiers = sorted(str(fill.get("tid", fill.get("hash", "")))
                         for fill in episode["fills"])
    fingerprint = hashlib.sha256("|".join(identifiers).encode()).hexdigest()
    count = len(episode["fills"])
    return {
        "cycle_id": fingerprint,
        "opened_at_ms": episode["opened_at_ms"],
        "closed_at_ms": episode["closed_at_ms"],
        "side": episode["side"],
        "fill_count": count,
        "order_count": len({str(fill.get("oid")) for fill in episode["fills"]}),
        "notional": format(episode["notional"], "f"),
        "fees": format(episode["fees"], "f"),
        "realized_pnl": format(episode["realized_pnl"], "f"),
        "bbo_tolerance_ms": tolerance_ms,
        "fill_ids": identifiers,
        "all_bbo_context": episode["all_bbo_context"],
        "all_history_covered": episode["all_history_covered"],
        "exploitable": (count > 0 and episode["all_bbo_context"]
                        and episode["all_history_covered"]),
    }


def _fill_positions(fill: dict[str, Any]) -> tuple[Decimal, Decimal] | None:
    direction = str(fill.get("dir", ""))
    if direction not in {"Open Long", "Close Long", "Open Short", "Close Short",
                         "Long > Short", "Short > Long"}:
        return None
    try:
        before = Decimal(str(fill.get("startPosition", "0")))
        size = abs(Decimal(str(fill.get("sz", "0"))))
    except (InvalidOperation, ValueError):
        return None
    if not size:
        return None
    side = str(fill.get("side", ""))
    if side == "B":
        return before, before + size
    if side == "A":
        return before, before - size
    return None


def _is_open(fill: dict[str, Any]) -> bool:
    return str(fill.get("dir", "")).startswith("Open ")


def _covered(stamp: int, intervals: list[tuple[int, int]]) -> bool:
    return any(start <= stamp <= end for start, end in intervals)


def _near(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= max(TOLERANCE, abs(left) * Decimal("1e-10"))


def _near_zero(value: Decimal) -> bool:
    return abs(value) <= TOLERANCE


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return ZERO


def _integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
