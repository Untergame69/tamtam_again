import sqlite3
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from tamtam_again.historical_curve_queue import prepare, tick


POLICY = {"version": "historical-curve-queue-v3", "sampling_seed": "fixture-seed",
          "max_requests_per_tick": 4, "tick_seconds": 900, "retry_seconds": 21600,
          "lease_seconds": 300, "max_attempts": 3, "refresh_after_seconds": 86400,
          "discovery_requests_per_tick": 1, "retry_requests_per_tick": 1}


def stamp_ms(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()


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


class FailingClient(Client):
    def post_info(self, payload):
        self.calls.append(payload)
        raise TimeoutError("fixture timeout")


class AlternatingClient(Client):
    def post_info(self, payload):
        self.calls.append(payload)
        if len(self.calls) % 2:
            raise TimeoutError("fixture timeout")
        return [["allTime", {"pnlHistory": [], "accountValueHistory": []}]]


class FailOnceByAddressClient(Client):
    def __init__(self):
        super().__init__()
        self.failed = set()
    def post_info(self, payload):
        self.calls.append(payload)
        address = payload["user"]
        if int(address[-2:], 16) % 13 == 0 and address not in self.failed:
            self.failed.add(address)
            raise TimeoutError("one transient fixture timeout")
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
        self.assertEqual(store.connection.execute("select attempts from historical_curve_queue").fetchone()[0], 0)

    def test_protected_scan_prefix_does_not_hide_candidates_after_eighty(self):
        addresses = self.addresses(100)
        store, client = Store(addresses), Client()
        first = 1_800_000_000_000
        with patch("tamtam_again.historical_curve_queue.protected_addresses", return_value=set(addresses)), \
             patch("tamtam_again.historical_curve_queue.authorized_account_history", return_value=True):
            blocked = tick(store, client, "hyperliquid-mainnet", POLICY, now_ms=first)
        self.assertEqual(blocked["scanned"], 80)
        self.assertEqual(blocked["deferred_before_call"], 80)
        self.assertEqual(client.calls, [])
        with patch("tamtam_again.historical_curve_queue.protected_addresses", return_value=set()), \
             patch("tamtam_again.historical_curve_queue.authorized_account_history", return_value=True):
            resumed = tick(store, client, "hyperliquid-mainnet", POLICY, now_ms=first + 900_000)
        self.assertEqual(resumed["logical_attempts"], 4)
        self.assertEqual(len(client.calls), 4)
        self.assertTrue(all(call["user"] in set(addresses[80:]) for call in client.calls))

    def test_eighty_immediate_failures_consume_only_four_logical_attempts(self):
        store, client = Store(self.addresses(80)), FailingClient()
        with patch("tamtam_again.historical_curve_queue.protected_addresses", return_value=set()), \
             patch("tamtam_again.historical_curve_queue.authorized_account_history", return_value=True):
            result = tick(store, client, "hyperliquid-mainnet", POLICY, now_ms=1_800_000_000_000)
        self.assertEqual(len(client.calls), 4)
        self.assertEqual(result["logical_attempts"], 4)
        self.assertEqual(result["portfolio_failures"], 4)
        self.assertEqual(result["portfolio_saved"], 0)

    def test_mixed_success_and_error_outcomes_still_consume_exactly_four_attempts(self):
        store, client = Store(self.addresses(12)), AlternatingClient()
        with patch("tamtam_again.historical_curve_queue.protected_addresses", return_value=set()), \
             patch("tamtam_again.historical_curve_queue.authorized_account_history", return_value=True):
            result = tick(store, client, "hyperliquid-mainnet", POLICY, now_ms=1_800_000_000_000)
        self.assertEqual(len(client.calls), 4)
        self.assertEqual(result["logical_attempts"], 4)
        self.assertEqual(result["portfolio_failures"], 2)
        self.assertEqual(result["portfolio_saved"], 2)

    def test_after_call_exclusion_counts_toward_cap_and_is_reported_separately(self):
        addresses = self.addresses(8)
        store, client = Store(addresses), Client()
        protected = [set(), {addresses[0]}, set(), set(), set()]
        with patch("tamtam_again.historical_curve_queue.protected_addresses", side_effect=protected), \
             patch("tamtam_again.historical_curve_queue.authorized_account_history", return_value=True):
            result = tick(store, client, "hyperliquid-mainnet", POLICY, now_ms=1_800_000_000_000)
        self.assertEqual(result["logical_attempts"], 4)
        self.assertEqual(len(client.calls), 4)
        self.assertEqual(result["deferred_after_call"], 1)
        self.assertEqual(result["portfolio_saved"], 3)

    def test_successful_refresh_resets_consecutive_failure_count(self):
        store, client = Store(self.addresses(1)), Client()
        with patch("tamtam_again.historical_curve_queue.protected_addresses", return_value=set()), \
             patch("tamtam_again.historical_curve_queue.authorized_account_history", return_value=True):
            first = tick(store, client, "hyperliquid-mainnet", POLICY, now_ms=1_800_000_000_000)
            self.assertEqual(first["portfolio_saved"], 1)
            self.assertEqual(store.connection.execute("select attempts from historical_curve_queue").fetchone()[0], 0)
            refreshed = tick(store, client, "hyperliquid-mainnet", POLICY, now_ms=1_800_086_400_000)
        self.assertEqual(refreshed["logical_attempts"], 1)
        self.assertEqual(refreshed["portfolio_saved"], 1)
        self.assertEqual(len(client.calls), 2)

    def test_discovery_and_refresh_both_progress_over_periodic_ticks_with_arrivals(self):
        start = 1_800_000_000_000
        initial = self.addresses(500)
        store, client = Store(initial), FailOnceByAddressClient()
        store.connection.execute("update candidates set added_at=?", (stamp_ms(start),))
        store.connection.commit()
        daily = []
        prior_seen = set()
        for day in range(3):
            day_start = start + day * 86_400_000
            if day:
                arrivals = ["0x" + format(10_000 + day * 100 + i, "040x") for i in range(80)]
                store.connection.executemany(
                    "insert into candidates values(?,?,?,?)",
                    [("hyperliquid-mainnet", address, "continuous-arrival", stamp_ms(day_start)) for address in arrivals])
                store.connection.commit()
            day_discovery = day_retry = day_refresh = day_failures = day_max_calls = 0
            max_discovery_wait = max_refresh_wait = 0
            for tick_index in range(96):
                now = day_start + tick_index * POLICY["tick_seconds"] * 1000
                with patch("tamtam_again.historical_curve_queue.protected_addresses", return_value=set()), \
                     patch("tamtam_again.historical_curve_queue.authorized_account_history", return_value=True):
                    result = tick(store, client, "hyperliquid-mainnet", POLICY, now_ms=now)
                self.assertLessEqual(result["logical_attempts"], POLICY["max_requests_per_tick"])
                self.assertLessEqual(result["new_discovery_requests"] + result["refresh_requests"], 4)
                self.assertIn("retry_requests", result)
                self.assertIn("oldest_due_refresh_wait_seconds", result)
                self.assertIn("oldest_never_attempted_age_seconds", result)
                day_discovery += result["new_discovery_requests"]
                day_retry += result["retry_requests"]
                day_refresh += result["refresh_requests"]
                day_failures += result["portfolio_failures"]
                day_max_calls = max(day_max_calls, result["logical_attempts"])
                max_discovery_wait = max(max_discovery_wait, result["oldest_never_attempted_age_seconds"])
                max_refresh_wait = max(max_refresh_wait, result["oldest_due_refresh_wait_seconds"])
            seen = {row[0] for row in store.connection.execute(
                "select distinct entity_id from raw_observations where endpoint='portfolio'")}
            newly_seen = len(seen - prior_seen)
            prior_seen = seen
            daily.append({"day": day + 1, "discovery_attempts": day_discovery,
                          "retry_attempts": day_retry, "refresh_attempts": day_refresh,
                          "oldest_never_attempted_age_seconds_observed": max_discovery_wait,
                          "oldest_due_refresh_wait_seconds_observed": max_refresh_wait,
                          "saved_distinct_cumulative": len(seen),
                          "newly_saved_distinct": newly_seen, "failures": day_failures,
                          "max_calls_per_tick": day_max_calls})
        self.assertTrue(all(row["discovery_attempts"] > 0 for row in daily))
        self.assertTrue(all(row["refresh_attempts"] > 0 for row in daily[1:]))
        self.assertTrue(all(row["retry_attempts"] > 0 for row in daily))
        self.assertTrue(all(row["newly_saved_distinct"] > 0 for row in daily))
        self.assertGreater(sum(row["failures"] for row in daily), 0)
        self.assertLessEqual(max(row["max_calls_per_tick"] for row in daily), 4)
        self.assertGreater(daily[-1]["saved_distinct_cumulative"], daily[0]["saved_distinct_cumulative"])
        self.simulation_summary = {"tick_interval_seconds": POLICY["tick_seconds"],
                                   "ticks": 3 * 96, "initial_candidates": 500,
                                   "new_arrivals_per_day": 80, "daily": daily,
                                   "provider_calls": len(client.calls), "ai_calls": 0}


if __name__ == "__main__":
    unittest.main()
