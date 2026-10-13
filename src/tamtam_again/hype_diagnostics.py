"""Small, read-only diagnostics for the a880/HYPE archive."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
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


def start_position_chain_summary(fills: Iterable[dict], *, include_fill_events: bool = False) -> dict:
    """Reconstruct only locally coherent fill-position chains from startPosition.

    Same-millisecond fills are ordered by their position transitions, not by
    arbitrary tid sorting. Every reported episode remains local to a contiguous
    chain; this does not establish archive completeness.
    """
    by_time: dict[int, list[dict]] = defaultdict(list)
    unique = {}
    missing_start_position = 0
    for fill in fills:
        if fill.get("time") is None or fill.get("tid") is None:
            continue
        if fill.get("startPosition") is None or fill.get("sz") is None or fill.get("side") not in ("A", "B"):
            missing_start_position += 1
            continue
        unique[str(fill["tid"])] = fill
    for fill in unique.values():
        by_time[int(fill["time"])].append(fill)

    groups = []
    ambiguous_groups = 0
    invalid_groups = []
    for stamp, rows in sorted(by_time.items()):
        edges = []
        for fill in rows:
            pre = Decimal(str(fill["startPosition"]))
            size = Decimal(str(fill["sz"]))
            delta = size if fill.get("side") == "B" else -size if fill.get("side") == "A" else Decimal(0)
            edges.append({"pre": pre, "post": pre + delta, "fill": fill})
        outgoing = Counter(e["pre"] for e in edges)
        incoming = Counter(e["post"] for e in edges)
        nodes = set(outgoing) | set(incoming)
        difference = {node: outgoing[node] - incoming[node] for node in nodes}
        starts = [node for node, value in difference.items() if value == 1]
        ends = [node for node, value in difference.items() if value == -1]
        if any(value not in (-1, 0, 1) for value in difference.values()) or len(starts) != len(ends) or len(starts) not in (0, 1):
            invalid_groups.append({"time_ms": stamp, "fills": len(rows), "reason": "position_transition_degrees_invalid"})
            continue
        # A time group with several distinct outgoing position transitions
        # admits multiple state paths. Preserve it as ambiguous instead of
        # choosing a tid order that would manufacture episode boundaries.
        paths = defaultdict(set)
        for edge in edges:
            paths[edge["pre"]].add(edge["post"])
        if any(len(posts) > 1 for posts in paths.values()):
            ambiguous_groups += 1
            invalid_groups.append({"time_ms": stamp, "fills": len(rows), "reason": "position_path_ambiguous"})
            continue
        start = starts[0] if starts else edges[0]["pre"]
        state = start
        unused = list(edges)
        ordered = []
        while unused:
            candidates = [edge for edge in unused if edge["pre"] == state]
            if not candidates:
                invalid_groups.append({"time_ms": stamp, "fills": len(rows), "reason": "position_path_disconnected"})
                ordered = []
                break
            edge = min(candidates, key=lambda e: str(e["fill"].get("tid", "")))
            ordered.append(edge)
            unused.remove(edge)
            state = edge["post"]
        if ordered:
            groups.append({"time_ms": stamp, "start": start, "end": state, "edges": ordered})

    segments = []
    ruptures = []
    current = []
    for group in groups:
        if current and current[-1]["end"] != group["start"]:
            previous = current[-1]
            ruptures.append({
                "after_time_ms": previous["time_ms"],
                "after_tid": str(previous["edges"][-1]["fill"].get("tid")),
                "previous_end_position": str(previous["end"]),
                "before_time_ms": group["time_ms"],
                "before_tid": str(group["edges"][0]["fill"].get("tid")),
                "next_start_position": str(group["start"]),
                "position_discontinuity": str(group["start"] - previous["end"]),
                "elapsed_ms": group["time_ms"] - previous["time_ms"],
            })
            segments.append(current)
            current = []
        current.append(group)
    if current:
        segments.append(current)

    episode_rows = []
    segment_rows = []
    for segment_index, segment in enumerate(segments, 1):
        flattened = [edge for group in segment for edge in group["edges"]]
        started = None
        initial = segment[0]["start"]
        left_censored = initial != 0
        right_censored = False
        for edge in flattened:
            pre, post, fill = edge["pre"], edge["post"], edge["fill"]
            stamp = int(fill["time"])
            tid = str(fill["tid"])
            if pre == 0 and post != 0:
                started = {"start_ms": stamp, "entry_tid": tid, "start_position": str(pre), "end_position": str(post)}
            elif pre != 0 and post == 0:
                if started is not None:
                    episode_rows.append({**started, "end_ms": stamp, "exit_tid": tid,
                                         "duration_ms": stamp - started["start_ms"], "segment": segment_index,
                                         "close_type": "returned_to_zero", "end_position": str(post)})
                started = None
            elif pre * post < 0:
                if started is not None:
                    episode_rows.append({**started, "end_ms": stamp, "exit_tid": tid,
                                         "duration_ms": stamp - started["start_ms"], "segment": segment_index,
                                         "close_type": "position_reversal", "end_position": "0",
                                         "reversal_post_position": str(post),
                                         "reversal_close_qty": str(abs(pre)),
                                         "reversal_open_qty": str(abs(post))})
                started = {"start_ms": stamp, "entry_tid": tid, "start_position": "0", "end_position": str(post)}
        ending = segment[-1]["end"]
        right_censored = ending != 0
        segment_rows.append({
            "segment": segment_index,
            "start_ms": segment[0]["time_ms"], "end_ms": segment[-1]["time_ms"],
            "fill_count": sum(len(g["edges"]) for g in segment),
            "start_position": str(initial), "end_position": str(ending),
            "left_censored": left_censored, "right_censored": right_censored,
        })

    durations = [row["duration_ms"] for row in episode_rows]
    result = {
        "unique_fills_with_start_position": len(unique),
        "fills_skipped_missing_position_fields": missing_start_position,
        "timestamp_groups": len(by_time),
        "multi_fill_timestamp_groups": sum(len(rows) > 1 for rows in by_time.values()),
        "multi_fill_timestamp_group_fill_count": sum(len(rows) for rows in by_time.values() if len(rows) > 1),
        "ambiguous_timestamp_groups": ambiguous_groups,
        "invalid_timestamp_groups": invalid_groups,
        "position_chain_segments": segment_rows,
        "position_chain_ruptures": ruptures,
        "locally_reconstructible_flat_to_flat_episode_count": len(episode_rows),
        "episode_duration_ms": quantiles(durations),
        "episode_examples_first_10": episode_rows[:10],
        "episode_examples_last_10": episode_rows[-10:],
        "coverage_warning": "Local arithmetic coherence is not proof that incomplete REST pages contain every fill. Segment endpoints are censored and ruptures are not bridged.",
    }
    if include_fill_events:
        result["ordered_segment_fill_events"] = [
            {
                "pre_position": str(edge["pre"]),
                "post_position": str(edge["post"]),
                "fill": edge["fill"],
            }
            for segment in segments
            for group in segment
            for edge in group["edges"]
        ]
        result["ordered_segment_event_offsets"] = [
            {"segment": index, "first_event": sum(len(g["edges"]) for part in segments[:index-1] for g in part),
             "event_count": sum(len(g["edges"]) for g in segment)}
            for index, segment in enumerate(segments, 1)
        ]
    return result
