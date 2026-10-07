import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tamtam_again.storage import Store
from tamtam_again.procedure_registry import register,record_choice
from tamtam_again.procedure_report import registered_report

class ReportTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db')
  c={'version':'prospective-procedure-v1','policy_version':'fixture','justification':'fixture',
   'network':'synthetic','address':'account','initial_capital_usdc':'100','risk_budget_id':'fixture',
   'periods':[{'start_ms':10,'end_ms':20}],'references':[{'name':'cash','kind':'cash','available_ms':0,'evidence_ref':'fixture'}]}
  with patch('tamtam_again.procedure_registry.now_ms',return_value=1):self.i=register(self.s,c)['procedure_id']
 def tearDown(self):self.s.close();self.tmp.cleanup()
 def choice(self):
  with patch('tamtam_again.procedure_registry.now_ms',return_value=2):
   record_choice(self.s,self.i,0,{'selected_variant_id':None,'considered_variant_ids':['failed'],'knowledge_available_ms':[0],
    'evidence_refs':['fixture:failure'],'diagnostic':'wait','change_cost':'0'})
 def test_wait_and_missing_decision(self):
  self.assertEqual(registered_report(self.s,self.i,as_of_ms=15)['status'],'waiting')
  self.assertEqual(registered_report(self.s,self.i,as_of_ms=20)['status'],'unknown')
 def test_failed_research_after_last_decision_is_included(self):
  self.choice()
  self.s.connection.execute('create table population_research_jobs(request_id text,network text,address text,created_ms integer,updated_ms integer,status text,actual_cost_usd text,reserved_cost_usd text)')
  self.s.connection.execute("insert into population_research_jobs values('failed','synthetic','account',15,19,'reject','2','4')")
  r=registered_report(self.s,self.i,as_of_ms=20)
  self.assertEqual(r['comparisons']['cash']['adaptive_net_after_research_and_change_costs'],'-2')
  self.assertEqual(r['comparisons']['cash']['procedure_wealth_after_external_research_and_change_costs'],'98')
  self.s.connection.execute('update population_research_jobs set actual_cost_usd=null')
  self.assertIsNone(registered_report(self.s,self.i,as_of_ms=20)['comparisons']['cash']['adaptive_net_after_research_and_change_costs'])

 def test_registered_choices_to_real_snapshot_adapter(self):
  from test_paper_outcome import OutcomeTests
  from tamtam_again.procedure_registry import bind_session
  from tamtam_again.paper_outcome import period_outcome
  fixture=OutcomeTests();fixture.setUp()
  try:
   s=fixture.s
   for column in ('network text','address text','started_ms integer','status text'):
    s.connection.execute('alter table paper_sessions add column '+column)
   s.connection.execute("update paper_sessions set network='synthetic',address='account',started_ms=2,status='active'")
   risk=period_outcome(s,'session',start_ms=10,end_ms=20,as_of_ms=20)['risk_budget_id']
   contract={'version':'prospective-procedure-v1','policy_version':'fixture','justification':'synthetic',
    'network':'synthetic','address':'account','initial_capital_usdc':'101','risk_budget_id':risk,
    'periods':[{'start_ms':10,'end_ms':20}],
    'references':[{'name':'fixed','kind':'fixed_rule','variant_id':'variant','available_ms':0,'evidence_ref':'fixture'}]}
   with patch('tamtam_again.procedure_registry.now_ms',return_value=1):i=register(s,contract)['procedure_id']
   with patch('tamtam_again.procedure_registry.now_ms',return_value=3):
    record_choice(s,i,0,{'selected_variant_id':'variant','considered_variant_ids':['variant'],'knowledge_available_ms':[0],
     'evidence_refs':['fixture'],'diagnostic':'synthetic choice','change_cost':'0'})
    bind_session(s,i,0,'adaptive','session');bind_session(s,i,0,'fixed','session')
   r=registered_report(s,i,as_of_ms=20)
   self.assertTrue(r['synthetic_observations']);self.assertEqual(r['comparisons']['fixed']['adaptive_net_after_research_and_change_costs'],'2')
   self.assertEqual(r['comparisons']['fixed']['trading_capital']['adaptive'],'103')
  finally:fixture.tearDown()
