import unittest
from tamtam_again.capacity import workload_budget


class CapacityTests(unittest.TestCase):
    def test_backfill_separate_and_unknown_task_retained(self):
        r=workload_budget({'window_minutes':10,'groups':[
            {'task':'population-rest-history_backfill','reserved_weight':1000},
            {'task':'population-rest-incremental','reserved_weight':2000},
            {'task':'new-client','reserved_weight':5000}]})
        self.assertEqual(r['phases']['history_backfill']['reserved_weight_per_minute'],100)
        self.assertEqual(r['phases']['unclassified']['reserved_weight_per_minute'],500)
        self.assertEqual(r['additional_headroom_with_recovery_per_minute'],0)
        self.assertIsNone(r['sustainable_account_capacity'])

    def test_reserve_is_explicit_and_configurable(self):
        report={'window_minutes':1,'groups':[{'task':'unknown','reserved_weight':850}]}
        self.assertEqual(workload_budget(report,recovery_fraction=0)['additional_headroom_with_recovery_per_minute'],50)
        self.assertEqual(workload_budget(report)['excess_above_operational_budget_per_minute'],130)

    def test_invalid_window_rejected(self):
        for value in (0,-1,float('nan')):
            with self.assertRaises(ValueError):
                workload_budget({'window_minutes':value,'groups':[]})
