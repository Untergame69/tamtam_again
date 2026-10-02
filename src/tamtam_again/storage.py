from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SCHEMA_LOCK = threading.Lock()


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS candidates (
    network TEXT NOT NULL,
    address TEXT NOT NULL,
    discovery_source TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate',
    PRIMARY KEY (network, address)
);
CREATE TABLE IF NOT EXISTS raw_observations (
    observation_id INTEGER PRIMARY KEY,
    network TEXT NOT NULL,
    source TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    request_json TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    window_start_ms INTEGER,
    window_end_ms INTEGER,
    record_count INTEGER,
    complete INTEGER NOT NULL DEFAULT 1,
    response_encoding TEXT NOT NULL DEFAULT 'json',
    response_sha256 TEXT NOT NULL,
    response_json TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_observation
    ON raw_observations(network, source, entity_type, entity_id, endpoint,
       ifnull(window_start_ms, -1), ifnull(window_end_ms, -1), response_sha256);
CREATE INDEX IF NOT EXISTS idx_observations_entity_time
    ON raw_observations(network, entity_type, entity_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_observations_source_endpoint
    ON raw_observations(source, endpoint, observed_at);
CREATE TABLE IF NOT EXISTS market_rankings (
    snapshot_id TEXT NOT NULL,
    network TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    rank INTEGER NOT NULL,
    coin TEXT NOT NULL,
    day_notional_volume TEXT NOT NULL,
    market_type TEXT NOT NULL DEFAULT 'perp',
    venue TEXT NOT NULL DEFAULT 'perps-main',
    instrument_json TEXT NOT NULL,
    context_json TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, rank),
    UNIQUE (snapshot_id, coin)
);
CREATE INDEX IF NOT EXISTS idx_market_rankings_observed
    ON market_rankings(network, observed_at, rank);
CREATE TABLE IF NOT EXISTS whale_rankings (
    snapshot_id TEXT NOT NULL,
    network TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    window TEXT NOT NULL,
    metric TEXT NOT NULL,
    rank INTEGER NOT NULL,
    address TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    account_value TEXT NOT NULL,
    pnl TEXT NOT NULL,
    roi TEXT NOT NULL,
    volume TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, window, metric, rank),
    UNIQUE (snapshot_id, window, metric, address)
);
CREATE INDEX IF NOT EXISTS idx_whale_rankings_observed
    ON whale_rankings(network, observed_at, window, metric, rank);
CREATE TABLE IF NOT EXISTS collection_cursors (
    network TEXT NOT NULL,
    address TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    last_successful_end_ms INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (network, address, endpoint)
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        with _SCHEMA_LOCK:
            self.connection.executescript(SCHEMA)
            columns = {row[1] for row in self.connection.execute(
                "PRAGMA table_info(raw_observations)"
            )}
            if "response_encoding" not in columns:
                self.connection.execute(
                    "ALTER TABLE raw_observations ADD COLUMN response_encoding "
                    "TEXT NOT NULL DEFAULT 'json'"
                )
            market_columns = {row[1] for row in self.connection.execute(
                "PRAGMA table_info(market_rankings)"
            )}
            if "market_type" not in market_columns:
                self.connection.execute(
                    "ALTER TABLE market_rankings ADD COLUMN market_type "
                    "TEXT NOT NULL DEFAULT 'perp'"
                )
            if "venue" not in market_columns:
                self.connection.execute(
                    "ALTER TABLE market_rankings ADD COLUMN venue "
                    "TEXT NOT NULL DEFAULT 'perps-main'"
                )
            self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def add_candidate(self, network: str, address: str, discovery_source: str,
                      label: str = "") -> bool:
        cursor = self.connection.execute(
            """INSERT OR IGNORE INTO candidates
               (network, address, discovery_source, label, added_at)
               VALUES (?, ?, ?, ?, ?)""",
            (network, address.lower(), discovery_source, label, utc_now()),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def get_candidate(self, network: str, address: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM candidates WHERE network=? AND address=?",
            (network, address.lower()),
        ).fetchone()

    def candidates(self, network: str | None = None) -> list[sqlite3.Row]:
        if network:
            rows = self.connection.execute(
                "SELECT * FROM candidates WHERE network=? ORDER BY added_at, address",
                (network,),
            )
        else:
            rows = self.connection.execute(
                "SELECT * FROM candidates ORDER BY network, added_at, address"
            )
        return list(rows)

    def save_observation(self, *, network: str, source: str,
                         entity_type: str, entity_id: str, endpoint: str,
                         payload: Any, request_payload: Any | None = None,
                         requested_at: str | None = None,
                         window_start_ms: int | None = None,
                         window_end_ms: int | None = None,
                         record_count: int | None = None,
                         complete: bool = True) -> bool:
        response_json = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"))
        request_json = json.dumps(request_payload or {}, ensure_ascii=False,
                                  sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(response_json.encode("utf-8")).hexdigest()
        compressed_response = zlib.compress(response_json.encode("utf-8"), level=6)
        cursor = self.connection.execute(
            """INSERT OR IGNORE INTO raw_observations
               (network, source, entity_type, entity_id, endpoint, request_json,
                requested_at, observed_at, window_start_ms, window_end_ms,
                record_count, complete, response_encoding, response_sha256, response_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (network, source, entity_type, entity_id, endpoint, request_json,
             requested_at or utc_now(), utc_now(), window_start_ms,
             window_end_ms, record_count, int(complete), "zlib+json", digest,
             compressed_response),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def observations(self, network: str, entity_type: str, entity_id: str,
                     start_ms: int | None = None, end_ms: int | None = None
                     ) -> list[sqlite3.Row]:
        clauses = ["network=?", "entity_type=?", "entity_id=?"]
        params: list[Any] = [network, entity_type, entity_id]
        if start_ms is not None:
            clauses.append("(window_end_ms IS NULL OR window_end_ms >= ?)")
            params.append(start_ms)
        if end_ms is not None:
            clauses.append("(window_start_ms IS NULL OR window_start_ms <= ?)")
            params.append(end_ms)
        return list(self.connection.execute(
            "SELECT * FROM raw_observations WHERE " + " AND ".join(clauses)
            + " ORDER BY window_start_ms, observed_at", params
        ))

    def mark_history_observations_complete(self, network: str, address: str,
                                           endpoint: str,
                                           covered_from_ms: int) -> int:
        cursor = self.connection.execute(
            """UPDATE raw_observations SET complete=1
               WHERE network=? AND entity_type='account' AND entity_id=?
                 AND endpoint=? AND complete=0 AND window_end_ms>=?""",
            (network, address.lower(), endpoint, covered_from_ms),
        )
        self.connection.commit()
        return cursor.rowcount

    def latest_observation_at(self, network: str, source: str,
                              entity_type: str, entity_id: str,
                              endpoint: str) -> str | None:
        row = self.connection.execute(
            """SELECT MAX(observed_at) FROM raw_observations
               WHERE network=? AND source=? AND entity_type=?
                 AND entity_id=? AND endpoint=?""",
            (network, source, entity_type, entity_id, endpoint),
        ).fetchone()
        return row[0] if row and row[0] else None

    def save_market_rankings(self, snapshot_id: str, network: str,
                             observed_at: str, rows: list[dict[str, Any]]) -> None:
        self.connection.executemany(
            """INSERT OR IGNORE INTO market_rankings
               (snapshot_id, network, observed_at, rank, coin,
                day_notional_volume, market_type, venue, instrument_json, context_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(snapshot_id, network, observed_at, row["rank"], row["coin"],
              row["day_notional_volume"], row.get("market_type", "perp"),
              row.get("venue", "perps-main"),
              json.dumps(row["instrument"], ensure_ascii=False, sort_keys=True),
              json.dumps(row["context"], ensure_ascii=False, sort_keys=True))
             for row in rows],
        )
        self.connection.commit()

    def save_whale_rankings(self, snapshot_id: str, network: str,
                            observed_at: str, rows: list[dict[str, Any]]) -> None:
        self.connection.executemany(
            """INSERT OR IGNORE INTO whale_rankings
               (snapshot_id, network, observed_at, window, metric, rank,
                address, display_name, account_value, pnl, roi, volume)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(snapshot_id, network, observed_at, row["window"], row["metric"],
              row["rank"], row["address"], row["display_name"],
              row["account_value"], row["pnl"], row["roi"], row["volume"])
             for row in rows],
        )
        self.connection.commit()

    def whale_addresses(self, snapshot_id: str, limit: int) -> list[sqlite3.Row]:
        snapshot = self.connection.execute(
            "SELECT network FROM whale_rankings WHERE snapshot_id=? LIMIT 1",
            (snapshot_id,),
        ).fetchone()
        if not snapshot:
            return []
        return list(self.connection.execute(
            """SELECT candidate.address,
                      COALESCE(NULLIF(MIN(ranked.display_name), ''), candidate.label)
                          AS display_name,
                      COALESCE(MIN(ranked.rank), 2147483647) AS best_rank,
                      COALESCE((SELECT MIN(cursor.last_successful_end_ms)
                                FROM collection_cursors AS cursor
                                WHERE cursor.address=candidate.address
                                  AND cursor.network=candidate.network), 0)
                          AS collection_cursor
               FROM candidates AS candidate
               LEFT JOIN whale_rankings AS ranked
                 ON ranked.snapshot_id=? AND ranked.address=candidate.address
               WHERE candidate.network=? AND candidate.status='tracked'
               GROUP BY candidate.network, candidate.address, candidate.label,
                        candidate.added_at
               ORDER BY collection_cursor, candidate.added_at,
                        MIN(CASE ranked.window WHEN 'allTime' THEN 0
                                               WHEN 'month' THEN 1
                                               WHEN 'week' THEN 2 ELSE 3 END),
                        MIN(CASE ranked.metric WHEN 'pnl' THEN 0
                                               WHEN 'roi' THEN 1 ELSE 2 END),
                        best_rank, candidate.address
               LIMIT ?""", (snapshot_id, snapshot["network"], limit),
        ))

    def promote_top_whales(self, snapshot_id: str, network: str,
                           limit: int) -> list[str]:
        """Pin a small, stable cohort using longer-window leaderboard ranks."""
        if limit < 1:
            raise ValueError("limit doit être positif.")
        existing = self.connection.execute(
            "SELECT address FROM candidates WHERE network=? AND status='tracked' "
            "ORDER BY added_at, address", (network,),
        ).fetchall()
        active = [row["address"] for row in existing]
        capacity = max(0, limit - len(active))
        if capacity:
            rows = self.connection.execute(
                """SELECT address, window, metric, rank
                   FROM whale_rankings WHERE snapshot_id=?""", (snapshot_id,),
            ).fetchall()
            scores: dict[str, float] = {}
            for row in rows:
                if row["metric"] != "pnl":
                    continue
                weight = {"allTime": 1.0, "month": 1.5,
                          "week": 2.0, "day": 4.0}.get(row["window"], 6.0)
                scores[row["address"]] = scores.get(row["address"], 0.0) + (
                    weight * int(row["rank"])
                )
            candidates = sorted(scores, key=lambda address: (scores[address], address))
            for address in candidates:
                if address in active:
                    continue
                cursor = self.connection.execute(
                    "UPDATE candidates SET status='tracked' "
                    "WHERE network=? AND address=? AND status='candidate'",
                    (network, address),
                )
                if cursor.rowcount:
                    active.append(address)
                if len(active) >= limit:
                    break
            self.connection.commit()
        return active[:limit]

    def latest_whale_rankings(self, network: str,
                              limit: int = 25) -> list[sqlite3.Row]:
        latest = self.connection.execute(
            """SELECT snapshot_id FROM whale_rankings WHERE network=?
               ORDER BY observed_at DESC LIMIT 1""", (network,),
        ).fetchone()
        if not latest:
            return []
        return list(self.connection.execute(
            """SELECT window, metric, rank, address, display_name,
                      account_value, pnl, roi, volume
               FROM whale_rankings WHERE snapshot_id=?
               ORDER BY CASE window WHEN 'allTime' THEN 0 WHEN 'month' THEN 1
                                    WHEN 'week' THEN 2 ELSE 3 END,
                        CASE metric WHEN 'pnl' THEN 0 ELSE 1 END, rank
               LIMIT ?""", (latest["snapshot_id"], limit),
        ))

    def collection_cursor(self, network: str, address: str, endpoint: str) -> int | None:
        row = self.connection.execute(
            """SELECT last_successful_end_ms FROM collection_cursors
               WHERE network=? AND address=? AND endpoint=?""",
            (network, address.lower(), endpoint),
        ).fetchone()
        return int(row[0]) if row else None

    def set_collection_cursor(self, network: str, address: str,
                              endpoint: str, end_ms: int) -> None:
        self.connection.execute(
            """INSERT INTO collection_cursors
               (network, address, endpoint, last_successful_end_ms, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(network, address, endpoint) DO UPDATE SET
                 last_successful_end_ms=MAX(last_successful_end_ms, excluded.last_successful_end_ms),
                 updated_at=excluded.updated_at""",
            (network, address.lower(), endpoint, end_ms, utc_now()),
        )
        self.connection.commit()

    def latest_market_selection(self, network: str) -> dict[str, Any] | None:
        latest = self.connection.execute(
            """SELECT snapshot_id, observed_at FROM market_rankings
               WHERE network=? ORDER BY observed_at DESC LIMIT 1""", (network,),
        ).fetchone()
        if not latest:
            return None
        rows = self.connection.execute(
            """SELECT rank, coin, day_notional_volume, market_type, venue,
                      instrument_json, context_json
               FROM market_rankings WHERE snapshot_id=? ORDER BY rank""",
            (latest["snapshot_id"],),
        )
        return {"snapshot_id": latest["snapshot_id"],
                "observed_at": latest["observed_at"],
                "markets": [{"rank": row["rank"], "coin": row["coin"],
                             "day_notional_volume": row["day_notional_volume"],
                             "market_type": row["market_type"], "venue": row["venue"],
                             "instrument": json.loads(row["instrument_json"]),
                             "context": json.loads(row["context_json"])}
                            for row in rows]}


def decode_observation_payload(row: sqlite3.Row) -> Any:
    raw = row["response_json"]
    if row["response_encoding"] == "zlib+json":
        raw = zlib.decompress(raw).decode("utf-8")
    elif isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)
