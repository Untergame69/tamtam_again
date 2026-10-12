from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tamtam_again.pipeline import _coverage_failure_is_frozen
from tamtam_again.storage import Store
from tamtam_again.validation import decision, initialize


class PipelineSchedulerTests(unittest.TestCase):
    def test_completed_coverage_failure_is_not_redecoded_each_tick(self):
        with tempfile.TemporaryDirectory() as directory:
            with Store(Path(directory) / "pipeline.sqlite3") as store:
                initialize(store)
                args = ("hyperliquid-mainnet", "0xabc", "HYPE")
                decision(store, *args, "needs_data", "Heartbeat gap inside validation window",
                         {"archive_or_plan_correction_required": True},
                         "inspect_validation_evidence",
                         {"variant_id": "variant-a", "stage": "comparison"})
                self.assertTrue(_coverage_failure_is_frozen(
                    store, *args, "variant-a", "comparison"))
                self.assertFalse(_coverage_failure_is_frozen(
                    store, *args, "variant-b", "comparison"))
                self.assertFalse(_coverage_failure_is_frozen(
                    store, *args, "variant-a", "final"))


if __name__ == "__main__":
    unittest.main()
