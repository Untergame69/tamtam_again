import json,tempfile,unittest
from pathlib import Path
from tamtam_again.adaptation_recipe import run_recipe

class AdaptationRecipeTests(unittest.TestCase):
 def test_chronological_service_path_reaches_new_prospective_decision(self):
  with tempfile.TemporaryDirectory() as directory:
   result=run_recipe(directory)
   self.assertEqual(json.loads((Path(directory)/'adaptation-recipe-result.json').read_text()),result)
  self.assertFalse(result['real_strategy_validated'])
  self.assertEqual(result['simulated_role_calls'],4)
  self.assertEqual(result['real_model_calls'],0)
  self.assertEqual(result['real_provider_calls'],0)
  self.assertEqual(result['counts']['validation_plans'],2)
  self.assertEqual(result['counts']['paper_adaptation_requests'],1)
  self.assertTrue(result['restart_and_duplicate_verified'])
  self.assertTrue(result['old_session_preserved'])

 def test_chronological_path_with_observation_acquisition_and_paper_reassessment(self):
  with tempfile.TemporaryDirectory() as directory:
   result=run_recipe(directory,observation_followup=True)
  self.assertTrue(result['observation_followup_verified'])
  self.assertEqual(result['simulated_role_calls'],6)
  self.assertEqual(result['counts']['population_research_jobs'],1)
  self.assertEqual(result['counts']['paper_research_jobs'],2)
  self.assertEqual(result['counts']['validation_plans'],2)
  self.assertEqual(result['real_provider_calls'],0)
  self.assertEqual(result['real_model_calls'],0)
  self.assertTrue(result['restart_and_duplicate_verified'])
