import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tamtam_again.storage import Store
from tamtam_again.procedure_registry import register,record_choice

class RegistryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db')
  self.contract={'version':'prospective-procedure-v1','policy_version':'fixture','justification':'synthetic test',
    'initial_capital_usdc':'100','risk_budget_id':'fixture-risk','periods':[{'start_ms':10,'end_ms':20},{'start_ms':20,'end_ms':30}],
    'references':[{'name':'cash','kind':'cash','evidence_ref':'fixture','available_ms':0}]}
  self.choice={'selected_variant_id':None,'considered_variant_ids':['failed'],'diagnostic':'waiting for evidence',
    'evidence_refs':['fixture:failure'],'knowledge_available_ms':[0]}
 def tearDown(self):self.s.close();self.tmp.cleanup()
 def register(self):
  with patch('tamtam_again.procedure_registry.now_ms',return_value=1):return register(self.s,self.contract)['procedure_id']
 def test_contract_and_choice_idempotence_after_period(self):
  i=self.register()
  with patch('tamtam_again.procedure_registry.now_ms',return_value=2):record_choice(self.s,i,0,self.choice)
  with patch('tamtam_again.procedure_registry.now_ms',return_value=40):
   self.assertEqual(register(self.s,self.contract)['procedure_id'],i)
   self.assertTrue(record_choice(self.s,i,0,self.choice)['replayed'])
   with self.assertRaises(ValueError):record_choice(self.s,i,0,{**self.choice,'diagnostic':'rewritten'})
 def test_no_late_registration_or_decision(self):
  with patch('tamtam_again.procedure_registry.now_ms',return_value=10):
   with self.assertRaises(ValueError):register(self.s,self.contract)
  i=self.register()
  with patch('tamtam_again.procedure_registry.now_ms',return_value=10):
   with self.assertRaises(ValueError):record_choice(self.s,i,0,self.choice)
 def test_wait_not_skipped_and_future_knowledge_rejected(self):
  i=self.register()
  with patch('tamtam_again.procedure_registry.now_ms',return_value=2):
   with self.assertRaises(ValueError):record_choice(self.s,i,1,self.choice)
   with self.assertRaises(ValueError):record_choice(self.s,i,0,{**self.choice,'knowledge_available_ms':[3]})
 def test_future_reference_rejected(self):
  self.contract['references'][0]['available_ms']=2
  with self.assertRaises(ValueError):self.register()
