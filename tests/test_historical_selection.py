import json
import sqlite3
import unittest
from datetime import datetime, timezone

from tamtam_again.historical_selection import build_report, persist_decisions
from tamtam_again.historical_selection import DAY_MS, _curve_metric, _period_consistency
from tamtam_again.population_scheduler import historical_research_gate


def stamp(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()


class HistoricalSelectionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          create table account_scope_reports(report_id text, network text, address text, available_ms integer, payload_json text);
          create table raw_observations(observation_id integer primary key,network text,source text,entity_type text,entity_id text,
            endpoint text,request_json text,requested_at text,observed_at text,window_start_ms integer,window_end_ms integer,
            record_count integer,complete integer,response_encoding text,response_sha256 text,response_json text);
        """)
        self.cut = 20_000 * DAY_MS
        self.address = "0x" + "1" * 40
        self.db.execute("insert into account_scope_reports values (?,?,?,?,?)",
                        ("r1", "hyperliquid-mainnet", self.address, self.cut, "{}"))

    def add_observation(self, endpoint, payload, available, request=None):
        self.db.execute("insert into raw_observations(network,source,entity_type,entity_id,endpoint,request_json,requested_at,observed_at,"
                        "window_start_ms,window_end_ms,record_count,complete,response_encoding,response_sha256,response_json) "
                        "values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("hyperliquid-mainnet", "hyperliquid-population-rest-v1", "account", self.address, endpoint,
                         json.dumps(request or {}), stamp(available), stamp(available), None, None,
                         len(payload) if isinstance(payload, list) else 1, 0, "json", "fixture", json.dumps(payload)))

    def test_fixed_window_boundary_never_interpolates_and_labels_sampled_drawdown(self):
        pts = [(self.cut - 190 * DAY_MS, 100), (self.cut - 100 * DAY_MS, 80), (self.cut, 110)]
        result = _curve_metric(pts, self.cut, 180)
        self.assertEqual(result["delta"], "10")
        self.assertEqual(result["max_sampled_curve_peak_to_trough"], "-20")
        misaligned = _curve_metric([(self.cut - 160 * DAY_MS, 10), (self.cut, 20)], self.cut, 180)
        self.assertEqual(misaligned["status"], "unknown_missing_or_stale_boundary")
        self.assertIsNone(misaligned["delta"])

    def test_calendar_buckets_attribute_boundary_change_once_and_report_gaps(self):
        def ms(year, month, day):
            return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)
        points = [(ms(2026, 1, 1), 100), (ms(2026, 1, 15), 100), (ms(2026, 1, 30), 101),
                  (ms(2026, 2, 1), 1101), (ms(2026, 2, 15), 1101), (ms(2026, 2, 27), 1102),
                  (ms(2026, 3, 1), 1102), (ms(2026, 3, 15), 1103), (ms(2026, 3, 30), 1104),
                  (ms(2026, 4, 1), 1105)]
        result = _period_consistency(points, points[0][0], points[-1][0], "month")
        measured = result["observed_bucket_deltas"]
        self.assertEqual(result["horizon_delta"], "1005")
        self.assertEqual(sum((int(x["delta"]) for x in measured if x["status"] == "measured"), 0), 1005)
        self.assertEqual(result["unattributed_delta"], "0")
        self.assertEqual(result["largest_positive_bucket_share_of_positive_delta"], "0.9960199004975124")
        sparse = _period_consistency([(points[0][0], 0), (points[-1][0], 10)], points[0][0], points[-1][0], "month")
        self.assertFalse(sparse["coverage_complete_for_concentration"])
        self.assertGreater(sparse["unknown_buckets"], 0)

    def test_deposit_does_not_turn_account_value_increase_into_pnl(self):
        pnl = [[self.cut - 190 * DAY_MS, "100"], [self.cut - 100 * DAY_MS, "90"], [self.cut, "110"]]
        value = [[self.cut - 190 * DAY_MS, "1000"], [self.cut, "4451000"]]
        self.add_observation("portfolio", [["allTime", {"pnlHistory": pnl, "accountValueHistory": value, "vlm": "9000"}],
                                             ["perpAllTime", {"pnlHistory": pnl, "accountValueHistory": value, "vlm": "8000"}],
                                             ["month", {"vlm": "300"}]], self.cut)
        self.add_observation("userNonFundingLedgerUpdates",
                             [{"time": self.cut-1000, "hash": "fixture-deposit", "delta": {"type": "deposit", "usdc": "4450000"}}],
                             self.cut)
        report = build_report(self.db, network="hyperliquid-mainnet", as_of_ms=self.cut)
        account = report["accounts"][0]
        self.assertEqual(account["horizons"]["180"]["delta"], "10")
        self.assertEqual(account["account_value_horizons"]["180"]["delta"], "4450000")
        self.assertEqual(account["declared_vlm"]["month"][1], "300")
        self.assertEqual(account["observed_flow_diagnostics"]["normalized_amounts_by_kind_currency_scope"][0]["amount"], "4450000")
        self.assertFalse(account["economic_validation"])

    def test_realized_fill_does_not_hide_declared_total_loss_and_multimarket_is_kept(self):
        pnl = [[self.cut - 190 * DAY_MS, "100"], [self.cut - 100 * DAY_MS, "70"], [self.cut, "80"]]
        self.add_observation("portfolio", [["allTime", {"pnlHistory": pnl, "accountValueHistory": pnl}],
                                             ["perpAllTime", {"pnlHistory": pnl, "accountValueHistory": pnl}]], self.cut)
        fills = [{"time": self.cut - 1000, "coin": "BTC", "tid": 1, "oid": 11, "closedPnl": "1000"},
                 {"time": self.cut - 2000, "coin": "xyz:XYZ100", "tid": 2, "oid": 12, "closedPnl": "1000"}]
        self.add_observation("userFillsByTime", fills, self.cut,
                             {"startTime": self.cut - 30 * DAY_MS, "endTime": self.cut, "pagination_status": "page_budget_exhausted"})
        account = build_report(self.db, network="hyperliquid-mainnet", as_of_ms=self.cut)["accounts"][0]
        self.assertEqual(account["horizons"]["180"]["delta"], "-20")
        self.assertEqual(account["fill_activity"]["markets_observed"], ["BTC", "xyz:XYZ100"])
        self.assertEqual(account["fill_activity"]["fills_30d_observed"], 2)
        self.assertEqual(account["activity_quality"], "some_activity_observed_lower_bound")

    def test_revisions_deduplication_and_future_unavailable_data(self):
        sample_end = self.cut - 2000
        pnl = [[self.cut - 190 * DAY_MS, "1"], [sample_end, "2"]]
        payload = [["allTime", {"pnlHistory": pnl, "accountValueHistory": pnl}],
                   ["perpAllTime", {"pnlHistory": pnl, "accountValueHistory": pnl}]]
        old = self.cut - 1000
        self.add_observation("portfolio", payload, old)
        revised = [["allTime", {"pnlHistory": [[self.cut - 190 * DAY_MS, "1"], [sample_end, "3"]], "accountValueHistory": pnl}],
                   ["perpAllTime", {"pnlHistory": pnl, "accountValueHistory": pnl}]]
        self.add_observation("portfolio", revised, self.cut)
        fill = {"time": sample_end, "coin": "BTC", "tid": 99, "oid": 7}
        self.add_observation("userFillsByTime", [fill], self.cut - 1000,
                             {"startTime": sample_end, "endTime": self.cut - 1000, "pagination_status": "pagination_exhausted"})
        self.add_observation("userFillsByTime", [fill], self.cut,
                             {"startTime": sample_end, "endTime": self.cut, "pagination_status": "pagination_exhausted"})
        self.add_observation("portfolio", [["allTime", {"pnlHistory": [[self.cut, "999"]], "accountValueHistory": []}]], self.cut + DAY_MS)
        account = build_report(self.db, network="hyperliquid-mainnet", as_of_ms=self.cut)["accounts"][0]
        curve = account["evidence"]["series"]["allTime.pnlHistory"]
        self.assertEqual(curve["revision_count"], 1)
        self.assertEqual(curve["points"][-1][1], "3")
        self.assertEqual(account["evidence"]["payloads_decoded"], 4)
        self.assertEqual(account["fill_activity"]["fills_observed"], 1)

    def test_old_incomplete_fill_page_does_not_block_recent_observed_activity(self):
        recent_start = self.cut - 30 * DAY_MS
        self.add_observation("userFillsByTime", [], self.cut,
                             {"startTime": recent_start, "endTime": self.cut,
                              "covered_until_ms": self.cut, "pagination_status": "pagination_exhausted"})
        self.add_observation("userFillsByTime", [], self.cut - 40 * DAY_MS,
                             {"startTime": self.cut - 70 * DAY_MS, "endTime": self.cut - 40 * DAY_MS,
                              "covered_until_ms": self.cut - 50 * DAY_MS, "pagination_status": "page_budget_exhausted"})
        fills = [{"time": self.cut - (i % 4) * DAY_MS, "coin": "BTC", "tid": i} for i in range(20)]
        self.add_observation("userFillsByTime", fills, self.cut,
                             {"startTime": recent_start, "endTime": self.cut,
                              "covered_until_ms": self.cut, "pagination_status": "page_budget_exhausted"})
        account = build_report(self.db, network="hyperliquid-mainnet", as_of_ms=self.cut)["accounts"][0]
        activity = account["fill_activity"]
        self.assertEqual(activity["fills_30d_observed"], 20)
        self.assertEqual(activity["active_days_30d_observed"], 4)
        self.assertEqual(account["activity_quality"], "frequent_activity_observed_lower_bound")
        self.assertEqual(activity["query_coverage_30d_days"], 30)
        self.assertIn("page_budget_exhausted", activity["pagination_statuses"])

    def test_identical_rerun_is_idempotent_and_does_not_call_provider(self):
        report = build_report(self.db, network="hyperliquid-mainnet", as_of_ms=self.cut)
        first = persist_decisions(self.db, report)
        second = persist_decisions(self.db, report)
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertEqual(report["provider_calls"], 0)
        self.assertEqual(self.db.execute("select count(*) from population_historical_decisions").fetchone()[0], 1)

    def test_missing_curve_is_unknown_separate_from_negative(self):
        self.add_observation("portfolio", [["allTime", {"pnlHistory": [], "accountValueHistory": []}]], self.cut)
        account = build_report(self.db, network="hyperliquid-mainnet", as_of_ms=self.cut)["accounts"][0]
        self.assertEqual(account["performance_quality"], "unknown")
        self.assertEqual(account["status"], "insufficiently_documented")

    def test_ai_gate_uses_observations_inside_cutoff_and_sealed_packet_survives_restart(self):
        from tamtam_again.engine import fingerprint
        self.db.execute("create table population_historical_decisions(decision_id text,network text,address text,status text,as_of_ms integer,decision_json text)")
        self.db.execute("create table population_research_jobs(request_id text,network text,address text,input_fingerprint text,packet_json text,created_ms integer,status text)")
        self.db.execute("create table paper_research_jobs(request_id text)")
        decision = {"economic_validation": True, "economic_research_readiness": {
            "status": "approved_for_re", "eligible_for_ai_research": True, "evidence_refs": ["review:fixture"]}}
        self.db.execute("insert into population_historical_decisions values(?,?,?,?,?,?)",
                        ("decision", "hyperliquid-mainnet", self.address, "credible_deep_dive_candidate", self.cut, json.dumps(decision)))
        self.db.execute("insert into population_research_jobs values(?,?,?,?,?,?,?)",
                        ("old", "hyperliquid-mainnet", self.address, "input", "{}", self.cut - 1000, "complete"))
        self.add_observation("portfolio", [], self.cut - 500)
        self.add_observation("portfolio", [], self.cut + 500)
        store = type("S", (), {"connection": self.db})()
        allowed = historical_research_gate(store, "hyperliquid-mainnet", self.address, as_of_ms=self.cut, max_requests=8)
        self.assertTrue(allowed["allowed"])
        self.assertTrue(allowed["new_data"])
        exhausted = historical_research_gate(store, "hyperliquid-mainnet", self.address, as_of_ms=self.cut, max_requests=1)
        self.assertFalse(exhausted["budget"])

        packet_body = {"research_input_fingerprint": "sealed-input", "address": self.address,
                       "network": "hyperliquid-mainnet", "available_ms": self.cut - 100}
        packet = {**packet_body, "fingerprint": fingerprint(packet_body)}
        self.db.execute("insert into population_historical_decisions values(?,?,?,?,?,?)",
                        ("sealed-decision", "hyperliquid-mainnet", self.address, "credible_deep_dive_candidate", self.cut - 50, json.dumps(decision)))
        self.db.execute("insert into population_research_jobs values(?,?,?,?,?,?,?)",
                        ("sealed", "hyperliquid-mainnet", self.address, "sealed-input", json.dumps(packet), self.cut, "sealed"))
        resumed = historical_research_gate(store, "hyperliquid-mainnet", self.address, as_of_ms=self.cut + DAY_MS,
                                           max_requests=3, request_id="sealed")
        self.assertTrue(resumed["allowed"])
        self.assertTrue(resumed["new_data"])
        broken = dict(packet)
        broken["fingerprint"] = "tampered"
        self.db.execute("update population_research_jobs set packet_json=? where request_id='sealed'", (json.dumps(broken),))
        rejected = historical_research_gate(store, "hyperliquid-mainnet", self.address, as_of_ms=self.cut + DAY_MS,
                                            max_requests=3, request_id="sealed")
        self.assertFalse(rejected["allowed"])
        self.assertIn("immutable reservation", rejected["reason"])

    def test_recovery_watch_uses_fixed_30_90_180_day_windows(self):
        points = [[self.cut - 190 * DAY_MS, "200"], [self.cut - 95 * DAY_MS, "150"],
                  [self.cut - 32 * DAY_MS, "100"], [self.cut, "110"]]
        payload = [["allTime", {"pnlHistory": points, "accountValueHistory": points}],
                   ["perpAllTime", {"pnlHistory": points, "accountValueHistory": points}]]
        self.add_observation("portfolio", payload, self.cut)
        account = build_report(self.db, network="hyperliquid-mainnet", as_of_ms=self.cut)["accounts"][0]
        self.assertEqual(account["horizons"]["30"]["delta"], "10")
        self.assertLess(float(account["horizons"]["90"]["delta"]), 0)
        self.assertLess(float(account["horizons"]["180"]["delta"]), 0)
        self.assertEqual(account["recovery_watch"]["status"], "watch_recovery_signal")
        self.assertIn(30, account["recovery_watch"]["fixed_windows_days"])


if __name__ == "__main__":
    unittest.main()
