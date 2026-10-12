import sqlite3
import unittest
from unittest.mock import patch

from tamtam_again.historical_curve_queue import prepare, tick


POLICY = {"version": "historical-curve-queue-v1", "sampling_seed": "fixture-seed",
          "max_requests_per_tick": 4, "tick_seconds": 900, "retry_seconds": 21600,
          "lease_seconds": 300, "max_attempts": 3}


class Store:
    def __init__(self, addresses):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
          create table candidates(network text,address text,discovery_source text,added_at text);
          create table raw_observations(observation_id integer primary key,network text,source text,entity_type text,
            entity_id text,endpoint text,request_json text,requested_at text,observed_at text,window_start_ms integer,
            window_end_ms integer,record_count integer,complete integer,response_encoding text,response_sha256 text,response_json text);
        """)
        self.connection.executemany("insert into candidates values(?,?,?,?)",
                                    [("hyperliquid-mainnet", a, "public", "2026-01-01") for a in addresses])
        self.connection.commit()

    def save_observation(self, **kw):
        import hashlib, json
        payload = kw["payload"]
        encoded = json.dumps(payload, separators=(",", ":"))
        self.connection.execute("insert into raw_observations(network,source,entity_type,entity_id,endpoint,request_json,requested_at,observed_at,record_count,complete,response_encoding,response_sha256,response_json) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (kw["network"], kw["source"], kw["entity_type"], kw["entity_id"], kw["endpoint"],
             json.dumps(kw["request_payload"]), kw["requested_at"], kw["requested_at"], len(payload), 1,
             "json", hashlib.sha256(encoded.encode()).hexdigest(), encoded))
        self.connection.commit()


class Client:
    def __init__(self):
        self.calls = []
    def post_info(self, payload):
        self.calls.append(payload)
        return [["allTime", {"pnlHistory": [], "accountValueHistory": []}]]


class HistoricalCurveQueueTests(unittest.TestCase):
    def addresses(self, n):
        return ["0x" + format(i, "040x") for i in range(1, n + 1)]

    def test_address_uniform_rank_is_stable_and_does_not_use_performance(self):
        first, second = Store(self.addresses(8)), Store(list(reversed(self.addresses(8))))
        prepare(first, "hyperliquid-mainnet", POLICY, now_ms=100)
        prepare(second, "hyperliquid-mainnet", POLICY, now_ms=100)
        ranks = lambda db: db.connection.execute("select address,queue_rank from historical_curve_queue order by address").fetchall()
        self.assertEqual([tuple(r) for r in ranks(first)], [tuple(r) for r in ranks(second)])
        self.assertEqual(first.connection.execute("pragma table_info(historical_curve_queue)").fetchall()[-1][1], "updated_ms")

    def test_tick_obeys_four_request_cap_and_keeps_queue_population_independent(self):
        store, client = Store(self.addresses(8)), Client()
        with patch("tamtam_again.historical_curve_queue.protected_addresses", return_value=set()), \
             patch("tamtam_again.historical_curve_queue.authorized_account_history", return_value=True):
            result = tick(store, client, "hyperliquid-mainnet", POLICY, now_ms=1_800_000_000_000)
        self.assertEqual(result["portfolio_requests"], 4)
        self.assertEqual(len(client.calls), 4)
        self.assertTrue(all(call["type"] == "portfolio" for call in client.calls))
        self.assertEqual(result["ai_calls"], 0)
        self.assertEqual(result["average_reserved_weight_per_minute_at_cadence"], 5.333)
        self.assertEqual(store.connection.execute("select count(*) from historical_curve_queue").fetchone()[0], 8)
        self.assertEqual(store.connection.execute("select count(*) from raw_observations").fetchone()[0], 4)

    def test_protected_address_is_not_queried_or_written(self):
        addresses = self.addresses(1)
        store, client = Store(addresses), Client()
        with patch("tamtam_again.historical_curve_queue.protected_addresses", return_value={addresses[0]}), \
             patch("tamtam_again.historical_curve_queue.authorized_account_history", return_value=True):
            result = tick(store, client, "hyperliquid-mainnet", POLICY, now_ms=1_800_000_000_000)
        self.assertEqual(result["portfolio_requests"], 0)
        self.assertEqual(result["deferred_protected"], 1)
        self.assertEqual(store.connection.execute("select count(*) from raw_observations").fetchone()[0], 0)
        self.assertEqual(store.connection.execute("select status from historical_curve_queue").fetchone()[0], "deferred_protected")
        self.assertEqual(store.connection.execute("select attempts from historical_curve_queue").fetchone()[0], 0)
        with patch("tamtam_again.historical_curve_queue.protected_addresses", return_value=set()), \
             patch("tamtam_again.historical_curve_queue.authorized_account_history", return_value=True):
            resumed = tick(store, client, "hyperliquid-mainnet", POLICY, now_ms=1_800_086_400_000)
        self.assertEqual(resumed["portfolio_requests"], 1)
        self.assertEqual(store.connection.execute("select attempts from historical_curve_queue").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
