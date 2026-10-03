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
    """Return complete flat-to-flat or baseline-return perp excursions.

    startPosition is the authoritative pre-fill position. Fills at the same
    timestamp are ordered by matching each pre-position to the preceding
    fill's post-position. If a whale starts the archive with an existing
    position, a cycle may be an opening excursion that later returns to its
    observed starting position; closes against the pre-existing baseline alone
    do not count. Ambiguous or truncated episodes are discarded.
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
    baseline: Decimal | None = None
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
                baseline = None
                break

            if position is None:
                # With truncated history, begin from the first observed
                # position. An opening fill can start a relative excursion.
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
                    baseline = None
                    first = parsed[0]
                else:
                    # A missing transition means history is truncated or the
                    # same-timestamp fills are ambiguous; do not bridge it.
                    active = None
                    position = None
                    baseline = None
                    first = parsed[0]

            fill, values = first
            pending.remove(fill)
            before, after = values
            if position is None:
                position = before
                baseline = before
            if not _near(before, position):
                active = None
                position = before
                baseline = before

            if active is None:
                if _is_flip(fill) and not _near_zero(after):
                    # A flip opens the new side from flat after closing the
                    # old side. The original fill also closes pre-existing
                    # inventory, so allocate only the residual size beyond
                    # zero to the new-side excursion.
                    baseline = ZERO
                    original_size = abs(_decimal(fill.get("sz")))
                    remainder_size = abs(after)
                    fraction = (remainder_size / original_size
                                if original_size else ZERO)
                    remainder = dict(fill)
                    remainder["startPosition"] = format(ZERO, "f")
                    remainder["sz"] = format(remainder_size, "f")
                    remainder["fee"] = format(_decimal(fill.get("fee")) * fraction, "f")
                    remainder["closedPnl"] = "0"
                    active = _new_episode(remainder, stamp, baseline)
                    active["side"] = "long" if after > ZERO else "short"
                    active["partial_fill_allocations"].append({
                        "fill_id": str(fill.get("tid", fill.get("hash", ""))),
                        "allocated_size": remainder["sz"],
                        "original_size": format(original_size, "f"),
                        "allocated_fee": remainder["fee"],
                        "allocated_realized_pnl": "0",
                        "allocated_start_position": format(ZERO, "f"),
                    })
                    _add_fill(active, remainder, stamp, market_times, intervals,
                              bbo_tolerance_ms, include_realized=False)
                elif _is_open(fill):
                    # Count an opening excursion relative to the position
                    # immediately before the whale increased exposure.
                    baseline = before
                    active = _new_episode(fill, stamp, baseline)
                    _add_fill(active, fill, stamp, market_times, intervals,
                              bbo_tolerance_ms)
                else:
                    # A close of inventory already present when observation
                    # began is not a complete research cycle. Move the
                    # baseline forward until a newly observed open occurs.
                    baseline = after
            else:
                episode_baseline = active["baseline_position"]
                returned = _near(after, episode_baseline)
                crossed_baseline = ((before - episode_baseline)
                                    * (after - episode_baseline) < ZERO)
                if returned:
                    _add_fill(active, fill, stamp, market_times, intervals,
                              bbo_tolerance_ms)
                    active["closed_at_ms"] = stamp
                    active["closed_position"] = True
                    active["ending_position"] = after
                    episode = _finish_episode(active, bbo_tolerance_ms)
                    if episode["exploitable"]:
                        output.append(episode)
                    active = None
                    baseline = after
                    if _is_flip(fill) and not _near_zero(after):
                        baseline = ZERO
                        active = _new_episode(fill, stamp, baseline)
                        active["side"] = "long" if after > ZERO else "short"
                        # This fill contains both the old-side exit and the
                        # new-side entry; count its fee/notional once per
                        # excursion but assign realized PnL only to the exit.
                        _add_fill(active, fill, stamp, market_times, intervals,
                                  bbo_tolerance_ms, include_realized=False)
                elif crossed_baseline:
                    # A fill can pass across a non-zero baseline while closing
                    # inventory that predates the observed excursion. Allocate
                    # only the executed fraction needed to return to baseline.
                    displacement = after - before
                    fraction = abs((episode_baseline - before) / displacement)
                    allocated = dict(fill)
                    original_size = abs(_decimal(fill.get("sz")))
                    allocated["sz"] = format(original_size * fraction, "f")
                    for field in ("fee", "closedPnl"):
                        allocated[field] = format(_decimal(fill.get(field)) * fraction, "f")
                    _add_fill(active, allocated, stamp, market_times, intervals,
                              bbo_tolerance_ms)
                    active["partial_fill_allocations"].append({
                        "fill_id": str(fill.get("tid", fill.get("hash", ""))),
                        "allocated_size": allocated["sz"],
                        "original_size": format(original_size, "f"),
                        "allocated_fee": allocated["fee"],
                        "allocated_realized_pnl": allocated["closedPnl"],
                        "allocated_start_position": str(allocated.get("startPosition", before)),
                    })
                    active["closed_at_ms"] = stamp
                    active["closed_position"] = True
                    active["ending_position"] = episode_baseline
                    episode = _finish_episode(active, bbo_tolerance_ms)
                    if episode["exploitable"]:
                        output.append(episode)
                    active = None
                    baseline = after
                    if _is_flip(fill) and not _near(after, episode_baseline):
                        # The remainder of a flip opens the opposite side
                        # after the prior excursion has returned to baseline.
                        remainder = dict(fill)
                        original_size = abs(_decimal(fill.get("sz")))
                        remainder_size = original_size * (Decimal(1) - fraction)
                        remainder["startPosition"] = format(episode_baseline, "f")
                        remainder["sz"] = format(remainder_size, "f")
                        remainder["fee"] = format(
                            _decimal(fill.get("fee")) * (Decimal(1) - fraction), "f"
                        )
                        remainder["closedPnl"] = "0"
                        baseline = episode_baseline
                        active = _new_episode(remainder, stamp, baseline)
                        active["partial_fill_allocations"].append({
                            "fill_id": str(fill.get("tid", fill.get("hash", ""))),
                            "allocated_size": remainder["sz"],
                            "original_size": format(original_size, "f"),
                            "allocated_fee": remainder["fee"],
                            "allocated_realized_pnl": "0",
                            "allocated_start_position": format(episode_baseline, "f"),
                        })
                        _add_fill(active, remainder, stamp, market_times, intervals,
                                  bbo_tolerance_ms, include_realized=False)
                else:
                    _add_fill(active, fill, stamp, market_times, intervals,
                              bbo_tolerance_ms)
            position = after

    # Open or truncated excursions intentionally do not count.
    return output


def _new_episode(fill: dict[str, Any], stamp: int, baseline: Decimal) -> dict[str, Any]:
    before, after = _fill_positions(fill) or (ZERO, ZERO)
    return {
        "opened_at_ms": stamp,
        "closed_at_ms": None,
        "side": "long" if after > before else "short",
        "cycle_kind": "flat_to_flat" if _near_zero(baseline) else "baseline_excursion",
        "baseline_position": baseline,
        "fills": [],
        "partial_fill_allocations": [],
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
        "cycle_kind": episode["cycle_kind"],
        "baseline_position": format(episode["baseline_position"], "f"),
        "ending_position": format(episode["ending_position"], "f"),
        "fill_count": count,
        "order_count": len({str(fill.get("oid")) for fill in episode["fills"]}),
        "notional": format(episode["notional"], "f"),
        "fees": format(episode["fees"], "f"),
        "realized_pnl": format(episode["realized_pnl"], "f"),
        "bbo_tolerance_ms": tolerance_ms,
        "fill_ids": identifiers,
        "partial_fill_allocations": episode["partial_fill_allocations"],
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


def _is_flip(fill: dict[str, Any]) -> bool:
    return str(fill.get("dir", "")) in {"Long > Short", "Short > Long"}


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
