import unittest
from tamtam_again.paper_monitor import diagnose, validate_policy


class MonitorTests(unittest.TestCase):
    def test_loss_boundary_and_recovery_do_not_select_replacement(self):
        policy={'version':'paper-loss-budget-v1','max_net_loss_usdc':'5',
                'justification':'fixture chosen risk budget'}
        self.assertEqual(diagnose(policy,{'net_pnl':'-4.99'}),[])
        self.assertEqual(diagnose(policy,{'net_pnl':'-5'}),['paper_net_loss_budget_exhausted'])
        self.assertEqual(diagnose(policy,{'net_pnl':'2'}),[])

    def test_invalid_budget_or_missing_justification_rejected(self):
        for limit in ('0','-1','NaN','Infinity'):
            with self.assertRaises(ValueError):
                validate_policy({'version':'paper-loss-budget-v1','max_net_loss_usdc':limit,'justification':'fixture'})
        with self.assertRaises(ValueError):
            validate_policy({'version':'paper-loss-budget-v1','max_net_loss_usdc':'5'})
