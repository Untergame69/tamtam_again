"""Bounded low-cost portfolio-curve acquisition over the public candidate registry."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from uuid import uuid4

from .discovery import protected_addresses
from .research_memory import authorized_account_history


def _iso_at_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()

SCHEMA = """
CREATE TABLE IF NOT EXISTS historical_curve_queue (
 network TEXT NOT NULL,
 address TEXT NOT NULL,
 discovery_source TEXT NOT NULL,
 added_at TEXT NOT NULL,
 queue_rank TEXT NOT NULL,
 status TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0,
 next_due_ms INTEGER NOT NULL,
 lease_token TEXT,
 lease_until_ms INTEGER,
 last_attempt_ms INTEGER,
 observation_id INTEGER,
 last_error_type TEXT,
 updated_ms INTEGER NOT NULL,
 PRIMARY KEY(network,address)
);
CREATE INDEX IF NOT EXISTS idx_historical_curve_queue_due
 ON historical_curve_queue(network,status,next_due_ms,queue_rank);
"""


def validate_policy(policy: dict) -> None:
    if policy.get("version") != "historical-curve-queue-v3" or not policy.get("sampling_seed"):
        raise ValueError("Versioned deterministic historical-curve queue policy required")
    for key in ("max_requests_per_tick", "tick_seconds", "retry_seconds", "lease_seconds", "max_attempts", "refresh_after_seconds"):
        if type(policy.get(key)) is not int or policy[key] < 1:
            raise ValueError("Positive bounded curve-queue setting required: " + key)
    if policy["max_requests_per_tick"] > 4:
        raise ValueError("Historical queue may use at most four portfolio requests per tick")
    for key in ("discovery_requests_per_tick", "retry_requests_per_tick"):
        if type(policy.get(key)) is not int or policy[key] < 1:
            raise ValueError("Reserve at least one logical attempt for " + key)
    if sum(policy[key] for key in ("discovery_requests_per_tick", "retry_requests_per_tick")) >= policy["max_requests_per_tick"]:
        raise ValueError("Keep at least one logical attempt available for refreshes")


def prepare(store, network: str, policy: dict, *, now_ms: int | None = None) -> dict:
    validate_policy(policy)
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    store.connection.executescript(SCHEMA)
    inserted = 0
    for row in store.connection.execute(
            "select address,discovery_source,added_at from candidates where network=? order by address", (network,)):
        address = row[0].lower()
        rank = hashlib.sha256((policy["sampling_seed"] + ":" + network + ":" + address).encode()).hexdigest()
        cursor = store.connection.execute(
            "insert or ignore into historical_curve_queue(network,address,discovery_source,added_at,queue_rank,status,attempts,next_due_ms,updated_ms) "
            "values(?,?,?,?,?,'pending',0,?,?)", (network, address, row[1], row[2], rank, now_ms, now_ms))
        inserted += cursor.rowcount
    store.connection.execute(
        "update historical_curve_queue set status='pending',lease_token=NULL,lease_until_ms=NULL,next_due_ms=?,updated_ms=? "
        "where network=? and status='running' and lease_until_ms<=?",
        (now_ms, now_ms, network, now_ms))
    store.connection.execute(
        "update historical_curve_queue set status='failed_exhausted',lease_token=NULL,lease_until_ms=NULL,updated_ms=? "
        "where network=? and status='retry' and attempts>=?",
        (now_ms, network, policy["max_attempts"]))
    store.connection.commit()
    return {"new_queue_entries": inserted,
            "registry_candidates": store.connection.execute("select count(*) from candidates where network=?", (network,)).fetchone()[0],
            "queue_status_counts": {row[0]: row[1] for row in store.connection.execute(
                "select status,count(*) from historical_curve_queue where network=? group by status", (network,))}}


def _finish(store, network: str, address: str, lease: str, *, status: str, now_ms: int,
            observation_id: int | None = None, error_type: str | None = None, retry_ms: int | None = None) -> None:
    store.connection.execute(
        "update historical_curve_queue set status=?,lease_token=NULL,lease_until_ms=NULL,observation_id=coalesce(?,observation_id),"
        "last_error_type=?,next_due_ms=?,updated_ms=? where network=? and address=? and lease_token=?",
        (status, observation_id, error_type, retry_ms if retry_ms is not None else now_ms,
         now_ms, network, address, lease))
    store.connection.commit()


def tick(store, client, network: str, policy: dict, *, now_ms: int | None = None) -> dict:
    """Fetch only portfolio curves; one four-request batch, using the shared REST limiter."""
    validate_policy(policy)
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    prepared = prepare(store, network, policy, now_ms=now_ms)
    blocked = protected_addresses(store)
    scanned = attempts = saved = failures = deferred_before = deferred_after = already_covered = 0
    discovery_attempts = retry_attempts = refresh_attempts = 0
    quotas = {"discovery": policy["discovery_requests_per_tick"],
              "retry": policy["retry_requests_per_tick"],
              "refresh": policy["max_requests_per_tick"] - policy["discovery_requests_per_tick"] - policy["retry_requests_per_tick"]}
    lane_counts = {lane: 0 for lane in quotas}
    max_scan = max(policy["max_requests_per_tick"] * 20, policy["max_requests_per_tick"])
    while attempts < policy["max_requests_per_tick"] and scanned < max_scan:
        # Keep a reserved share for first observations and another for refreshes.
        # Each lane advances independently by age, so a fixed address hash cannot
        # reclaim every refresh slot forever. If one lane is empty, borrow its slots.
        lane = next((name for name in ("discovery", "retry", "refresh")
                     if lane_counts[name] < quotas[name]), "")
        row = _next_candidate(store, network, now_ms, policy, lane) if lane else None
        if not row:
            preferred_lane = lane
            lane = ""
            fallback_lanes = [name for name in ("discovery", "retry", "refresh")
                              if name != preferred_lane and lane_counts[name] < quotas[name]]
            fallback_lanes += [name for name in ("discovery", "retry", "refresh")
                               if name != preferred_lane and lane_counts[name] >= quotas[name]]
            for candidate_lane in fallback_lanes:
                if candidate_lane not in quotas:
                    continue
                row = _next_candidate(store, network, now_ms, policy, candidate_lane)
                if row:
                    lane = candidate_lane
                    break
        if not row:
            break
        address = row["address"].lower()
        scanned += 1
        lease = uuid4().hex
        store.connection.execute("begin immediate")
        try:
            claimed = store.connection.execute(
                "update historical_curve_queue set status='running',lease_token=?,lease_until_ms=?,last_attempt_ms=?,updated_ms=? "
                "where network=? and address=? and status in ('pending','retry','deferred_protected','fetched','already_covered') and next_due_ms<=?",
                (lease, now_ms + policy["lease_seconds"] * 1000, now_ms, now_ms, network, address, now_ms)).rowcount
            store.connection.commit()
        except BaseException:
            store.connection.rollback()
            raise
        if not claimed:
            continue
        if address in blocked or not authorized_account_history(store, network, address, now_ms):
            deferred_before += 1
            _finish(store, network, address, lease, status="deferred_protected", now_ms=now_ms,
                    retry_ms=now_ms + 86_400_000)
            continue
        # Existing observations are detected by metadata only. The screen will
        # decode payloads only after the same protection checks at its cutoff.
        existing = store.connection.execute(
            "select observation_id,observed_at from raw_observations where network=? and source='hyperliquid-population-rest-v1' "
            "and entity_type='account' and entity_id=? and endpoint='portfolio' and observed_at<=? order by observed_at desc,observation_id desc limit 1",
            (network, address, _iso_at_ms(now_ms))).fetchone()
        if existing:
            freshness_ms = policy["refresh_after_seconds"] * 1000
            age_ms = now_ms - int(datetime.fromisoformat(existing["observed_at"]).timestamp() * 1000)
            if age_ms < freshness_ms:
                already_covered += 1
                _finish(store, network, address, lease, status="already_covered", now_ms=now_ms,
                        observation_id=existing["observation_id"], retry_ms=now_ms + freshness_ms - age_ms)
                continue
        requested_at = _iso_at_ms(now_ms)
        client.task = "population-historical-curve-queue"
        try:
            store.connection.execute("update historical_curve_queue set attempts=attempts+1,updated_ms=? where network=? and address=? and lease_token=?",
                                     (now_ms, network, address, lease))
            store.connection.commit()
            attempts += 1
            if lane == "discovery":
                discovery_attempts += 1
            elif lane == "retry":
                retry_attempts += 1
            else:
                refresh_attempts += 1
            lane_counts[lane] += 1
            response = client.post_info({"type": "portfolio", "user": address})
            if not isinstance(response, list):
                raise ValueError("portfolio response shape invalid")
            if address in protected_addresses(store) or not authorized_account_history(store, network, address, int(time.time() * 1000)):
                deferred_after += 1
                store.connection.execute("update historical_curve_queue set attempts=0 where network=? and address=? and lease_token=?",
                                         (network, address, lease))
                store.connection.commit()
                _finish(store, network, address, lease, status="deferred_protected", now_ms=now_ms,
                        retry_ms=now_ms + 86_400_000)
                continue
            store.save_observation(network=network, source="hyperliquid-population-rest-v1",
                entity_type="account", entity_id=address, endpoint="portfolio", payload=response,
                request_payload={"type": "portfolio", "user": address, "transport": "rest",
                    "phase": "historical_curve_queue", "queue_version": policy["version"],
                    "discovery_source": store.connection.execute(
                        "select discovery_source from historical_curve_queue where network=? and address=?",
                        (network, address)).fetchone()[0]}, requested_at=requested_at)
            observation = store.connection.execute(
                "select observation_id from raw_observations where network=? and source='hyperliquid-population-rest-v1' "
                "and entity_type='account' and entity_id=? and endpoint='portfolio' and requested_at=? order by observation_id desc limit 1",
                (network, address, requested_at)).fetchone()
            saved += 1
            store.connection.execute("update historical_curve_queue set attempts=0 where network=? and address=? and lease_token=?",
                                     (network, address, lease))
            store.connection.commit()
            _finish(store, network, address, lease, status="fetched", now_ms=now_ms,
                    observation_id=observation[0] if observation else None,
                    retry_ms=now_ms + policy["refresh_after_seconds"] * 1000)
        except Exception as exc:
            failures += 1
            _finish(store, network, address, lease, status="retry", now_ms=now_ms,
                    error_type=type(exc).__name__, retry_ms=now_ms + policy["retry_seconds"] * 1000)
    waiting = store.connection.execute(
        "select count(*) from historical_curve_queue where network=? and status in ('pending','retry','deferred_protected','fetched','already_covered') and next_due_ms<=? and attempts<?",
        (network, now_ms, policy["max_attempts"])).fetchone()
    never_examined = store.connection.execute(
        "select count(*),min(added_at) from historical_curve_queue where network=? and last_attempt_ms is null",
        (network,)).fetchone()
    oldest_unexamined_age = (max(0, now_ms - int(datetime.fromisoformat(never_examined[1]).timestamp() * 1000))
                             if never_examined[1] else 0)
    oldest_eligible = store.connection.execute(
        "select min(added_at) from historical_curve_queue where network=? and status in ('pending','retry','deferred_protected','fetched','already_covered') and next_due_ms<=? and attempts<?",
        (network, now_ms, policy["max_attempts"])).fetchone()[0]
    oldest_wait_age = (max(0, now_ms - int(datetime.fromisoformat(oldest_eligible).timestamp() * 1000))
                       if oldest_eligible else 0)
    retry_rows = store.connection.execute(
        "select next_due_ms from historical_curve_queue where network=? and status='retry' and attempts<?",
        (network, policy["max_attempts"])).fetchall()
    due_retries = [row[0] for row in retry_rows if row[0] <= now_ms]
    refresh_rows = store.connection.execute(
        "select q.next_due_ms,(select max(o.observed_at) from raw_observations o where o.network=q.network "
        "and o.source='hyperliquid-population-rest-v1' and o.entity_type='account' "
        "and o.entity_id=q.address and o.endpoint='portfolio' and o.observed_at<=?) as last_observed "
        "from historical_curve_queue q where q.network=? and q.status in ('pending','deferred_protected','fetched','already_covered') "
        "and q.attempts<?",
        (_iso_at_ms(now_ms), network, policy["max_attempts"])).fetchall()
    refresh_due_times = []
    refresh_ms = policy["refresh_after_seconds"] * 1000
    for row in refresh_rows:
        if row[1]:
            observed_ms = int(datetime.fromisoformat(row[1]).timestamp() * 1000)
            refresh_due_times.append(max(row[0], observed_ms + refresh_ms))
    due_refreshes = [due for due in refresh_due_times if due <= now_ms]
    return {"prepared": prepared, "scanned": scanned, "logical_attempts": attempts,
            "new_discovery_requests": discovery_attempts, "refresh_requests": refresh_attempts,
            "retry_requests": retry_attempts,
            "eligible_queue_entries": waiting[0], "never_attempted_queue_entries": never_examined[0],
            "oldest_never_attempted_added_at": never_examined[1],
            "oldest_never_attempted_age_seconds": oldest_unexamined_age // 1000,
            "oldest_eligible_age_seconds": oldest_wait_age // 1000,
            "due_retry_entries": len(due_retries),
            "oldest_due_retry_wait_seconds": (now_ms - min(due_retries)) // 1000 if due_retries else 0,
            "due_refresh_entries": len(due_refreshes),
            "oldest_due_refresh_wait_seconds": (now_ms - min(due_refreshes)) // 1000 if due_refreshes else 0,
            "portfolio_requests": attempts, "portfolio_saved": saved,
            "portfolio_failures": failures, "deferred_before_call": deferred_before,
            "deferred_after_call": deferred_after, "deferred_protected": deferred_before + deferred_after,
            "already_covered": already_covered, "ai_calls": 0,
            "max_requests_per_tick": policy["max_requests_per_tick"],
            "average_reserved_weight_per_minute_at_cadence": round(
                policy["max_requests_per_tick"] * 20 * 60 / policy["tick_seconds"], 3)}


def _next_candidate(store, network: str, now_ms: int, policy: dict, lane: str):
    """Select the oldest unexamined discovery or the stalest due refresh."""
    last_observed = ("(select max(o.observed_at) from raw_observations o where o.network=q.network "
                     "and o.source='hyperliquid-population-rest-v1' and o.entity_type='account' "
                     "and o.entity_id=q.address and o.endpoint='portfolio' and o.observed_at<=?)")
    lane_filter = {"discovery": "last_observed is null and status<>'retry'",
                   "retry": "status='retry'",
                   "refresh": "last_observed is not null and last_observed<=?"}[lane]
    order = ("case when last_attempt_ms is null then 0 else 1 end,"
             "case when last_attempt_ms is null then updated_ms else last_attempt_ms end,added_at,address"
             if lane == "discovery" else
             "last_attempt_ms,added_at,address" if lane == "retry" else "last_observed,last_attempt_ms,address")
    params = [_iso_at_ms(now_ms), network, now_ms, policy["max_attempts"]]
    if lane == "refresh":
        params.append(_iso_at_ms(now_ms - policy["refresh_after_seconds"] * 1000))
    row = store.connection.execute(
        "with due as (select q.address,q.status,q.attempts,q.added_at,q.last_attempt_ms,q.updated_ms," + last_observed + " as last_observed "
        "from historical_curve_queue q where q.network=? "
        "and q.status in ('pending','retry','deferred_protected','fetched','already_covered') "
        "and q.next_due_ms<=? and q.attempts<?) "
        "select * from due where " + lane_filter + " order by " + order + " limit 1", params).fetchone()
    return row
