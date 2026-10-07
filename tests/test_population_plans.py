import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tamtam_again.storage import Store
from tamtam_again.recipe import synthetic_plan,synthetic_spec
from tamtam_again.population_plans import prepare_plan

class PopulationPlanTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db')
  self.s.connection.execute('create table population_research_jobs(request_id text,network text,address text,status text,result_json text,updated_ms integer,packet_json text)')
  self.result={'proposal':{'hypothesis':{'required_data':[],'executable_spec':synthetic_spec(),'markets':['SYNTH'],'type':'follower'}},
   'critique':{'decision':'consistent','diagnostic':'fixture','wake':{}},'promotion_authorized':False,'profitability_proven':False}
  self.s.connection.execute('insert into population_research_jobs values(?,?,?,?,?,?,?)',('request','synthetic','fixture-only','hypothesis_recorded',json.dumps(self.result),100,json.dumps({'available_ms':50,'evidence_refs':['request']})));self.s.connection.commit()
  self.profile={'schema_version':1,'hypothesis_id':'request','justification':'fixture only','max_variants':2,'selection_rule':'comparison_then_one_final',
   'axes':[{'parameter':'horizon_ms','values':[500,1500],'category':'hypothesis','justification':'fixture coverage','evidence_refs':['request'],'measurement_status':'simulated'}]}
  self.policy={'version':'population-plan-v1','justification':'fixture durations only','max_plans':1,
   'comparison_delay_ms':100,'comparison_duration_ms':6000,'selection_gap_ms':2000,'final_duration_ms':6000,
   'criteria':synthetic_plan()['criteria'],'budget':synthetic_plan()['budget'],'isolation':'unavailable'}
 def tearDown(self):self.s.close();self.tmp.cleanup()
 def test_windows_cover_every_variant_and_retry_never_moves_them(self):
  with patch('tamtam_again.population_plans.now_ms',return_value=1000):r=prepare_plan(self.s,'request',self.policy,self.profile)
  plan=json.loads(self.s.connection.execute('select plan_json from validation_plans').fetchone()[0])
  self.assertEqual(plan['embargo_ms'],1501)
  self.assertGreaterEqual(plan['comparison']['start_ms'],plan['exploration']['end_ms']+1501)
  self.assertEqual(len(r['attempts']),2)
  with patch('tamtam_again.population_plans.now_ms',return_value=90000):again=prepare_plan(self.s,'request',self.policy,self.profile)
  self.assertEqual(again['status'],'already_registered')
  self.assertEqual(json.loads(self.s.connection.execute('select plan_json from validation_plans').fetchone()[0]),plan)
  with self.assertRaises(ValueError):prepare_plan(self.s,'request',{**self.policy,'final_duration_ms':7000},self.profile)
 def test_downstream_incident_keeps_original_window_anchor(self):
  with patch('tamtam_again.population_plans.now_ms',return_value=1000),patch('tamtam_again.population_plans.create_plan',side_effect=RuntimeError):
   with self.assertRaises(RuntimeError):prepare_plan(self.s,'request',self.policy,self.profile)
  draft=self.s.connection.execute('select plan_json from population_plan_drafts').fetchone()[0]
  with patch('tamtam_again.population_plans.now_ms',return_value=2000):prepare_plan(self.s,'request',self.policy,self.profile)
  self.assertEqual(self.s.connection.execute('select plan_json from validation_plans').fetchone()[0],draft)
 def test_requirements_prevent_plan_and_invalid_budget_rejected(self):
  self.result['proposal']['hypothesis']['required_data']=['missing evidence']
  self.s.connection.execute('update population_research_jobs set result_json=?',(json.dumps(self.result),));self.s.connection.commit()
  r=prepare_plan(self.s,'request',self.policy,self.profile)
  self.assertEqual(r['status'],'needs_data')
  self.assertEqual(self.s.connection.execute('select count(*) from population_plan_drafts').fetchone()[0],0)

 def test_global_plan_budget_does_not_reset_for_another_request(self):
  prepare_plan(self.s,'request',self.policy,self.profile)
  result=prepare_plan(self.s,'second-request',self.policy,{**self.profile,'hypothesis_id':'second-request'})
  self.assertEqual(result['status'],'budget_exhausted')
  self.assertEqual(self.s.connection.execute('select count(*) from validation_plans').fetchone()[0],1)
 def test_insufficient_duration_budget_creates_no_draft(self):
  policy={**self.policy,'budget':{**self.policy['budget'],'max_duration_ms':1}}
  with self.assertRaises(ValueError):prepare_plan(self.s,'request',policy,self.profile)
  self.assertEqual(self.s.connection.execute('select count(*) from population_plan_drafts').fetchone()[0],0)

 def test_missing_measurement_proof_is_rejected_before_draft_reservation(self):
  axis=self.profile['axes'][0]
  axis.update(parameter='latency_ms',category='system_capacity',values=[1],measurement_status='measured_reference',
   measurement_ref='request',measurement_available_ms=20)
  with self.assertRaisesRegex(ValueError,'sealed measurement proof'):
   prepare_plan(self.s,'request',self.policy,self.profile)
  self.assertEqual(self.s.connection.execute('select count(*) from population_plan_drafts').fetchone()[0],0)
