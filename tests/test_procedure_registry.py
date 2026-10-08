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

 def test_binding_prospective_immutable_and_missing_outcome_unknown(self):
  from tamtam_again.procedure_registry import bind_session,bound_outcomes
  self.contract.update(network='synthetic',address='account')
  self.contract['references'].append({'name':'fixed','kind':'fixed_rule','variant_id':'v','available_ms':0,'evidence_ref':'fixture:rule'})
  i=self.register()
  with patch('tamtam_again.procedure_registry.now_ms',return_value=2):record_choice(self.s,i,0,self.choice)
  self.s.connection.execute('create table paper_sessions(session_id text,variant_id text,network text,address text,started_ms integer,status text)')
  self.s.connection.execute("insert into paper_sessions values('s','v','synthetic','account',2,'active')")
  with patch('tamtam_again.procedure_registry.now_ms',return_value=3):
   bind_session(self.s,i,0,'fixed','s')
   with self.assertRaises(ValueError):bind_session(self.s,i,0,'adaptive','s')
  with patch('tamtam_again.procedure_registry.now_ms',return_value=30):
   self.assertTrue(bind_session(self.s,i,0,'fixed','s')['replayed'])
   with self.assertRaises(ValueError):bind_session(self.s,i,0,'fixed','other')
  self.assertEqual(bound_outcomes(self.s,i,0,as_of_ms=15)['reason'],'period not yet completed')
  r=bound_outcomes(self.s,i,0,as_of_ms=30)
  self.assertEqual(r['status'],'unknown');self.assertEqual(r['outcomes']['adaptive']['net_pnl'],'0')
  self.assertIsNone(r['outcomes']['fixed']['net_pnl'])
 def test_late_binding_rejected(self):
  from tamtam_again.procedure_registry import bind_session
  i=self.register()
  with patch('tamtam_again.procedure_registry.now_ms',return_value=2):record_choice(self.s,i,0,self.choice)
  with patch('tamtam_again.procedure_registry.now_ms',return_value=10):
   with self.assertRaisesRegex(ValueError,'precede'):bind_session(self.s,i,0,'fixed','s')

 def test_resolves_actual_immutable_paper_snapshots(self):
  from test_paper_outcome import OutcomeTests
  from tamtam_again.procedure_registry import bind_session,bound_outcomes
  fixture=OutcomeTests();fixture.setUp()
  try:
   store=fixture.s
   for column in ('network text','address text','started_ms integer','status text'):
    store.connection.execute('alter table paper_sessions add column '+column)
   store.connection.execute("update paper_sessions set network='synthetic',address='account',started_ms=2,status='active'")
   contract={**self.contract,'network':'synthetic','address':'account',
    'references':[{'name':'fixed','kind':'fixed_rule','variant_id':'variant','available_ms':0,'evidence_ref':'fixture:fixed'}]}
   with patch('tamtam_again.procedure_registry.now_ms',return_value=1):i=register(store,contract)['procedure_id']
   choice={**self.choice,'selected_variant_id':'variant','considered_variant_ids':['variant']}
   with patch('tamtam_again.procedure_registry.now_ms',return_value=3):
    record_choice(store,i,0,choice);bind_session(store,i,0,'adaptive','session');bind_session(store,i,0,'fixed','session')
   r=bound_outcomes(store,i,0,as_of_ms=30)
   self.assertEqual(r['status'],'bound_model_outcomes')
   self.assertEqual(r['outcomes']['adaptive']['net_pnl'],'2')
   self.assertTrue(r['outcomes']['fixed']['synthetic'])
  finally:fixture.tearDown()

 def test_control_scope_is_predeclared_and_binding_checked(self):
  from tamtam_again.procedure_registry import bind_session
  self.contract.update(network='synthetic',address='adaptive-account')
  self.contract['references'].append({'name':'control','kind':'selection_control','variant_id':'control-v',
   'available_ms':0,'evidence_ref':'fixture:control','scope':{'network':'synthetic','address':'control-account'},
   'cohort_evidence_ref':'fixture:dated-cohort','matching_justification':'same observed market and risk policy; fixture only'})
  i=self.register()
  with patch('tamtam_again.procedure_registry.now_ms',return_value=2):record_choice(self.s,i,0,self.choice)
  self.s.connection.execute('create table paper_sessions(session_id text,variant_id text,network text,address text,started_ms integer,status text)')
  self.s.connection.execute("insert into paper_sessions values('wrong','control-v','synthetic','adaptive-account',2,'active')")
  self.s.connection.execute("insert into paper_sessions values('right','control-v','synthetic','control-account',2,'active')")
  with patch('tamtam_again.procedure_registry.now_ms',return_value=3):
   with self.assertRaisesRegex(ValueError,'scope'):bind_session(self.s,i,0,'control','wrong')
   bind_session(self.s,i,0,'control','right')
 def test_control_without_matching_rationale_rejected(self):
  self.contract['references'].append({'name':'control','kind':'selection_control','variant_id':'v',
   'available_ms':0,'evidence_ref':'fixture','scope':{'network':'synthetic','address':'control'}})
  with self.assertRaisesRegex(ValueError,'matching'):self.register()

 def test_adaptive_boundary_binding_requires_new_session(self):
  from tamtam_again.procedure_registry import bind_session
  self.contract.update(network='synthetic',address='account')
  i=self.register()
  with patch('tamtam_again.procedure_registry.now_ms',return_value=2):
   record_choice(self.s,i,0,{**self.choice,'selected_variant_id':'v','considered_variant_ids':['v']})
  self.s.connection.execute('create table paper_sessions(session_id text,variant_id text,network text,address text,started_ms integer,status text)')
  self.s.connection.execute("insert into paper_sessions values('old','v','synthetic','account',9,'active')")
  self.s.connection.execute("insert into paper_sessions values('new','v','synthetic','account',10,'active')")
  with patch('tamtam_again.procedure_registry.now_ms',return_value=10):
   with self.assertRaisesRegex(ValueError,'newly initialized'):bind_session(self.s,i,0,'adaptive','old')
   bind_session(self.s,i,0,'adaptive','new')
  self.s.connection.execute('delete from procedure_session_bindings')
  with patch('tamtam_again.procedure_registry.now_ms',return_value=11):
   with self.assertRaises(ValueError):bind_session(self.s,i,0,'adaptive','new')
