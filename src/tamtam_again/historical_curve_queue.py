"""Bounded low-cost portfolio-curve acquisition over the public candidate registry."""
from __future__ import annotations

import hashlib
import json
import time
from uuid import uuid4

from .discovery import protected_addresses
from .research_memory import authorized_account_history
from .storage import utc_now

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
    if policy.get("version") != "historical-curve-queue-v1" or not policy.get("sampling_seed"):
        raise ValueError("Versioned deterministic historical-curve queue policy required")
    for key in ("max_requests_per_tick", "tick_seconds", "retry_seconds", "lease_seconds", "max_attempts"):
        if type(policy.get(key)) is not int or policy[key] < 1:
            raise ValueError("Positive bounded curve-queue setting required: " + key)
    if policy["max_requests_per_tick"] > 4:
        raise ValueError("Historical queue may use at most four portfolio requests per tick")


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
    scanned = requests = failures = deferred = already_covered = 0
    max_scan = max(policy["max_requests_per_tick"] * 20, policy["max_requests_per_tick"])
    while requests < policy["max_requests_per_tick"] and scanned < max_scan:
        row = store.connection.execute(
            "select address,attempts from historical_curve_queue where network=? and status in ('pending','retry','deferred_protected') "
            "and next_due_ms<=? and attempts<? order by queue_rank limit 1",
            (network, now_ms, policy["max_attempts"])).fetchone()
        if not row:
            break
        address = row["address"].lower()
        scanned += 1
        lease = uuid4().hex
        store.connection.execute("begin immediate")
        try:
            claimed = store.connection.execute(
                "update historical_curve_queue set status='running',lease_token=?,lease_until_ms=?,last_attempt_ms=?,updated_ms=? "
                "where network=? and address=? and status in ('pending','retry','deferred_protected') and next_due_ms<=?",
                (lease, now_ms + policy["lease_seconds"] * 1000, now_ms, now_ms, network, address, now_ms)).rowcount
            store.connection.commit()
        except BaseException:
            store.connection.rollback()
            raise
        if not claimed:
            continue
        if address in blocked or not authorized_account_history(store, network, address, now_ms):
            deferred += 1
            _finish(store, network, address, lease, status="deferred_protected", now_ms=now_ms,
                    retry_ms=now_ms + 86_400_000)
            continue
        # Existing observations are detected by metadata only. The screen will
        # decode payloads only after the same protection checks at its cutoff.
        existing = store.connection.execute(
            "select observation_id from raw_observations where network=? and source='hyperliquid-population-rest-v1' "
            "and entity_type='account' and entity_id=? and endpoint='portfolio' and observed_at<=? order by observed_at desc,observation_id desc limit 1",
            (network, address, utc_now())).fetchone()
        if existing:
            already_covered += 1
            _finish(store, network, address, lease, status="already_covered", now_ms=now_ms,
                    observation_id=existing[0])
            continue
        requested_at = utc_now()
        client.task = "population-historical-curve-queue"
        try:
            store.connection.execute("update historical_curve_queue set attempts=attempts+1,updated_ms=? where network=? and address=? and lease_token=?",
                                     (now_ms, network, address, lease))
            store.connection.commit()
            response = client.post_info({"type": "portfolio", "user": address})
            if not isinstance(response, list):
                raise ValueError("portfolio response shape invalid")
            if address in protected_addresses(store) or not authorized_account_history(store, network, address, int(time.time() * 1000)):
                deferred += 1
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
            requests += 1
            _finish(store, network, address, lease, status="fetched", now_ms=now_ms,
                    observation_id=observation[0] if observation else None)
        except Exception as exc:
            failures += 1
            _finish(store, network, address, lease, status="retry", now_ms=now_ms,
                    error_type=type(exc).__name__, retry_ms=now_ms + policy["retry_seconds"] * 1000)
    return {"prepared": prepared, "scanned": scanned, "portfolio_requests": requests,
            "portfolio_failures": failures, "deferred_protected": deferred,
            "already_covered": already_covered, "ai_calls": 0,
            "max_requests_per_tick": policy["max_requests_per_tick"],
            "average_reserved_weight_per_minute_at_cadence": round(
                policy["max_requests_per_tick"] * 20 * 60 / policy["tick_seconds"], 3)}
