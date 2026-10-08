import tempfile,unittest
from pathlib import Path
from tamtam_again.procedure_recipe import run_recipe
class RecipeTests(unittest.TestCase):
 def test_recorded_wait_then_rule_against_fixed_and_cash(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=run_recipe(Path(tmp));self.assertTrue(r['synthetic'])
   self.assertFalse(r['real_strategy_validated']);self.assertTrue(r['restart_reproducible'])
   self.assertTrue(r['missing_cost_propagated']);self.assertEqual(r['real_provider_calls'],0)
