import gzip
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tamtam_again.descriptive_admission import (
    evaluate_inventory,
    validate_report_paths,
    write_report,
)


CUTOFF = 1_800_000_000_000
NETWORK = "hyperliquid-mainnet"
DAY = "2027-01-15"


def decision(address, *, markets, fills=0, days=0, pnl_status="unknown", mode="unifiedAccount"):
    return {
        "address": address,
        "status": "credible_deep_dive_candidate",
        "economic_validation": False,
        "economic_research_readiness": {"status": "blocked_pending_economic_review"},
        "performance_quality": pnl_status,
        "account_mode": mode,
        "risk_unknowns": ["historical leverage unknown"],
        "data_quality": {"allTime_pnl_samples": 12, "allTime_max_gap_days": 7.0,
                         "economic_reconciliation": "unknown"},
        "horizons": {"30": {"delta": "12.5", "status": "measured"},
                     "90": {"delta": "-3.0", "status": "measured"},
                     "180": {"delta": "8.0", "status": "measured",
                             "max_sampled_pnl_peak_to_trough": "-9.0"}},
        "fill_activity": {"fills_30d_observed": fills, "active_days_30d_observed": days,
                          "markets_30d_observed": markets,
                          "coverage_by_requested_ranges": [{"days": 30, "pages": 2, "complete": False}]},
        "activity_quality": "frequent_activity_observed_lower_bound",
        "evidence": {"markets_observed_in_fills": markets},
        "current_exposure_observations": [{"positions": []}],
    }


class DescriptiveAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "inventory.sqlite3"
        self.conn = sqlite3.connect(self.db)
        self.conn.execute("""create table population_historical_decisions (
            decision_id text primary key, network text not null, address text not null,
            decision_day_utc text not null, as_of_ms integer not null, policy_version text not null,
            input_fingerprint text not null, status text not null, sources_json text not null,
            decision_json text not null, unique(network,address,decision_day_utc,policy_version,input_fingerprint))""")
        self.conn.execute("create index idx_historical_decisions_day on population_historical_decisions(network,decision_day_utc,status)")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def insert(self, address, source_status, payload):
        self.conn.execute("insert into population_historical_decisions values(?,?,?,?,?,?,?,?,?,?)",
                          (address, NETWORK, address, DAY, CUTOFF, "historical-curves-v2.0",
                           "fp-" + address[-4:], source_status, "{}",
                           json.dumps(payload) if isinstance(payload, dict) else payload))
        self.conn.commit()

    def evaluate(self, **kwargs):
        return evaluate_inventory(db_path=self.db, cutoff_ms=CUTOFF, **kwargs)

    def test_scientific_admission_does_not_depend_on_performance_or_mode(self):
        negative = decision("0x0000000000000000000000000000000000005bcf", markets=["ETH"],
                            fills=36, days=2, pnl_status="negative_declared_some_horizons")
        positive = decision("0x0000000000000000000000000000000000005bd0", markets=["ETH"],
                            fills=36, days=2, pnl_status="positive_declared", mode="disabled")
        self.insert(negative["address"], negative["status"], negative)
        self.insert(positive["address"], positive["status"], positive)
        report = self.evaluate()
        rows = report["candidate_evaluations"]
        self.assertEqual([row["disposition"] for row in rows],
                         ["admissible_descriptive", "admissible_descriptive"])
        self.assertEqual(rows[0]["priority"], rows[1]["priority"])
        self.assertFalse(any(row["economic_validation"] for row in rows))
        self.assertTrue(all(row["resource_authorized"] is False for row in rows))
        self.assertEqual(rows[0]["declared_performance"]["status"], "negative_declared_some_horizons")

    def test_multimarket_needs_market_level_proof_but_is_not_excluded(self):
        payload = decision("0x0000000000000000000000000000000000002222",
                           markets=["BTC", "ETH"], fills=100, days=8)
        self.insert(payload["address"], payload["status"], payload)
        row = self.evaluate()["candidate_evaluations"][0]
        self.assertEqual(row["disposition"], "needs_more_evidence")
        self.assertIn("ventilés par marché", row["missing_evidence"][0])
        self.assertEqual(row["scope"]["market_count"], 2)

    def test_under_threshold_is_deferred_with_exact_missing_proof(self):
        payload = decision("0x0000000000000000000000000000000000003333",
                           markets=["SOL"], fills=9, days=1)
        self.insert(payload["address"], payload["status"], payload)
        row = self.evaluate()["candidate_evaluations"][0]
        self.assertEqual(row["disposition"], "needs_more_evidence")
        self.assertIn("10 fills", row["missing_evidence"][0])

    def test_pre_read_exclusion_does_not_decode_decision_json(self):
        self.insert("0x0000000000000000000000000000000000004444",
                    "excluded_before_payload_read", "not-json-protected")
        visible = decision("0x0000000000000000000000000000000000004445",
                           markets=["BTC"], fills=20, days=4)
        self.insert(visible["address"], visible["status"], visible)
        row = next(item for item in self.evaluate()["candidate_evaluations"] if item["disposition"] == "excluded")
        self.assertEqual(row["disposition"], "excluded")
        self.assertIsNone(row["candidate_id"])
        self.assertNotIn("source_ref", row)
        self.assertIsNone(row["declared_performance"])

    def test_malformed_nested_evidence_is_deferred_per_record(self):
        malformed = decision("0x0000000000000000000000000000000000006666",
                             markets=["BTC"], fills=20, days=4)
        malformed["horizons"] = ["not-a-horizon-map"]
        self.insert(malformed["address"], malformed["status"], malformed)
        valid = decision("0x0000000000000000000000000000000000006667",
                         markets=["ETH"], fills=20, days=4)
        self.insert(valid["address"], valid["status"], valid)

        rows = {row["candidate_id"]: row for row in self.evaluate()["candidate_evaluations"]}
        self.assertEqual(rows[malformed["address"]]["disposition"], "deferred")
        self.assertIsNone(rows[malformed["address"]]["activity"])
        self.assertEqual(rows[valid["address"]]["disposition"], "admissible_descriptive")

    def test_report_paths_reject_db_symlinks_and_output_collisions(self):
        db_alias = Path(self.tmp.name) / "db-link.sqlite3"
        db_alias.symlink_to(self.db)
        with self.assertRaisesRegex(ValueError, "source database"):
            validate_report_paths(self.db, db_alias, Path(self.tmp.name) / "report.md")
        with self.assertRaisesRegex(ValueError, "different files"):
            validate_report_paths(self.db, Path(self.tmp.name) / "same.out",
                                  Path(self.tmp.name) / "same.out")

    def test_gzip_report_preserves_json_and_markdown_uses_cutoff_date(self):
        payload = decision("0x0000000000000000000000000000000000007777",
                           markets=["BTC"], fills=20, days=4)
        self.insert(payload["address"], payload["status"], payload)
        report = self.evaluate()
        json_path = Path(self.tmp.name) / "report.json.gz"
        markdown_path = Path(self.tmp.name) / "report.md"
        write_report(report, json_path, markdown_path)

        self.assertEqual(json.loads(gzip.decompress(json_path.read_bytes())), report)
        self.assertIn("# Proposition d’admission à la recherche descriptive — 15 janvier 2027",
                      markdown_path.read_text(encoding="utf-8"))

    def test_cutoff_is_exact_and_cap_is_enforced(self):
        payload = decision("0x0000000000000000000000000000000000005555", markets=["BTC"], fills=20, days=4)
        self.insert(payload["address"], payload["status"], payload)
        second = decision("0x0000000000000000000000000000000000005556", markets=["ETH"], fills=20, days=4)
        self.insert(second["address"], second["status"], second)
        with self.assertRaises(LookupError):
            evaluate_inventory(db_path=self.db, cutoff_ms=CUTOFF + 1)
        with self.assertRaises(ValueError):
            evaluate_inventory(db_path=self.db, cutoff_ms=CUTOFF, max_candidates=0)
        with self.assertRaisesRegex(ValueError, "exceeds explicit cap"):
            evaluate_inventory(db_path=self.db, cutoff_ms=CUTOFF, max_candidates=1)

    def test_threshold_sensitivity_counts_single_market_only(self):
        for suffix, markets, fills, days in (("a001", ["BTC"], 12, 2),
                                             ("a002", ["ETH"], 20, 4),
                                             ("a003", ["BTC", "ETH"], 200, 20)):
            payload = decision("0x0000000000000000000000000000000000" + suffix,
                               markets=markets, fills=fills, days=days)
            self.insert(payload["address"], payload["status"], payload)
        sensitivity = self.evaluate()["threshold_sensitivity"]
        self.assertEqual(sensitivity["single_market_admitted_at_10_fills_2_days"], 2)
        self.assertEqual(sensitivity["single_market_admitted_at_20_fills_4_days_existing_criterion"], 1)
        self.assertEqual(sensitivity["single_market_admitted_at_40_fills_6_days_strict_sensitivity"], 0)

    def test_shortlist_keeps_a_prefixed_market_namespace_visible(self):
        cases = (("0x000000000000000000000000000000000000b001", ["BTC"], 1000, 8),
                 ("0x000000000000000000000000000000000000b002", ["SOL"], 800, 5),
                 ("0x000000000000000000000000000000000000b003", ["xyz:TSLA"], 35, 2))
        for address, markets, fills, days in cases:
            payload = decision(address, markets=markets, fills=fills, days=days)
            self.insert(address, payload["status"], payload)
        queue = self.evaluate()["priority_queue"]
        self.assertIn("xyz:TSLA", [row["scope"]["markets"][0] for row in queue])


if __name__ == "__main__":
    unittest.main()
