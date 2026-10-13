import unittest

from tamtam_again.hype_diagnostics import fee_crossed_summary, gap_summary, live_fills, quantiles


class HypeDiagnosticsTests(unittest.TestCase):
    def test_live_fill_filter_excludes_snapshot_and_other_coins(self):
        request = {"user_fills_stream": {"connection_id": "c1", "sequence": 2}}
        snapshot = {"data": {"isSnapshot": True, "fills": [{"coin": "HYPE"}]}}
        self.assertEqual(live_fills(snapshot, request, "HYPE"), [])
        live = {"data": {"isSnapshot": False, "fills": [
            {"coin": "HYPE", "tid": 1}, {"coin": "BTC", "tid": 2}]}}
        self.assertEqual(live_fills(live, request, "HYPE"), [{"coin": "HYPE", "tid": 1}])

    def test_legacy_live_fill_requires_sequence_and_connection(self):
        payload = {"data": {"fills": [{"coin": "HYPE"}]}}
        self.assertEqual(live_fills(payload, {}, "HYPE"), [])
        self.assertEqual(live_fills(payload, {"user_fills_stream": {"sequence": 2}}, "HYPE"), [])
        self.assertEqual(len(live_fills(payload, {"user_fills_stream": {
            "sequence": 2, "connection_id": "c1"}}, "HYPE")), 1)

    def test_quote_interobservation_gaps_and_delay_quantiles(self):
        self.assertEqual(gap_summary([0, 500, 2_000, 63_000]), {
            "observations": 4, "gaps_gt_1s": 2, "gaps_gt_5s": 1,
            "gaps_gt_60s": 1, "max_gap_ms": 61_000,
        })
        self.assertEqual(quantiles([1, 2, 3, 4]), {"n": 4, "p50": 2, "p95": 4, "max": 4})

    def test_fee_and_crossed_are_separated_without_fee_tier_inference(self):
        summary = fee_crossed_summary([
            {"crossed": True, "fee": "0.02"},
            {"crossed": False, "fee": "-0.01"},
            {"crossed": None, "fee": "0.03", "builderFee": "0.01"},
        ])
        self.assertEqual(summary["crossed"]["positive_charge_sum"], 0.02)
        self.assertEqual(summary["not_crossed"]["negative_fee_rows_rebate_per_official_schema"], 1)
        self.assertEqual(summary["not_crossed"]["negative_rebate_sum_signed"], -0.01)
        self.assertEqual(summary["unknown"]["builder_fee_rows"], 1)


if __name__ == "__main__":
    unittest.main()
