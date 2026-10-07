import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tamtam_again.storage import Store
from tamtam_again.recipe import synthetic_plan,synthetic_spec,synthetic_events
from tamtam_again.population_plans import prepare_plan
from tamtam_again.pipeline import synthetic_tick,tick

class PopulationPipelineTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db')
  self.s.connection.execute('create table population_research_jobs(request_id text,network text,address text,status text,result_json text,updated_ms integer,packet_json text)')
  result={'proposal':{'hypothesis':{'required_data':[],'executable_spec':synthetic_spec(),'markets':['SYNTH'],'type':'follower'}},
   'critique':{'decision':'consistent','diagnostic':'fixture','wake':{}},'promotion_authorized':False,'profitability_proven':False}
  self.s.connection.execute('insert into population_research_jobs values(?,?,?,?,?,?,?)',('request','synthetic','fixture-only','hypothesis_recorded',json.dumps(result),100,json.dumps({'available_ms':50,'evidence_refs':['request']})));self.s.connection.commit()
  profile={'schema_version':1,'hypothesis_id':'request','justification':'fixture only','max_variants':1,'selection_rule':'comparison_then_one_final',
   'axes':[{'parameter':'horizon_ms','values':[500],'category':'hypothesis','justification':'fixture','evidence_refs':['request'],'measurement_status':'simulated'}]}
  policy={'version':'population-plan-v1','justification':'fixture only','max_plans':1,'comparison_delay_ms':100,
   'comparison_duration_ms':6000,'selection_gap_ms':2000,'final_duration_ms':6000,'criteria':synthetic_plan()['criteria'],
   'budget':synthetic_plan()['budget'],'isolation':'unavailable'}
  r=prepare_plan(self.s,'request',policy,profile);self.variant=r['attempts'][0]['variant_id']
  plan=json.loads(self.s.connection.execute('select plan_json from validation_plans').fetchone()[0])
  self.fixtures={self.variant:{stage:synthetic_events(plan[stage]['start_ms']) for stage in ('comparison','final')}}
  self.fixtures[self.variant]['paper']=synthetic_events(plan['final']['end_ms']+1000)
 def tearDown(self):self.s.close();self.tmp.cleanup()
 def test_scheduler_comparison_selection_final_paper_and_replay(self):
  with patch('tamtam_again.pipeline.archive_events') as archive:
   first=synthetic_tick(self.s,self.fixtures)
   self.assertEqual(self.s.connection.execute('select count(*) from paper_sessions').fetchone()[0],0)
   second=synthetic_tick(self.s,self.fixtures)
   self.assertTrue(second['synthetic_recipe']);self.assertFalse(second['real_strategy_validated'])
   session=self.s.connection.execute('select * from paper_sessions').fetchone()
   self.assertIsNotNone(session)
   state=session['state_json']
   third=synthetic_tick(self.s,self.fixtures)
   self.assertEqual(self.s.connection.execute('select count(*) from paper_sessions').fetchone()[0],1)
   self.assertEqual(self.s.connection.execute('select state_json from paper_sessions').fetchone()[0],state)
   self.assertEqual(self.s.connection.execute('select count(*) from validation_evaluations').fetchone()[0],2)
   archive.assert_not_called()
  for row in self.s.connection.execute('select result_json from validation_evaluations'):
   self.assertTrue(json.loads(row[0])['synthetic']);self.assertFalse(json.loads(row[0])['promotable'])
 def test_fixture_scheduler_rejects_database_with_any_real_plan_before_archive(self):
  self.s.connection.execute('update validation_plans set synthetic=0');self.s.connection.commit()
  with patch('tamtam_again.pipeline.archive_events') as archive:
   with self.assertRaises(ValueError):synthetic_tick(self.s,self.fixtures)
   archive.assert_not_called()
 def test_normal_pipeline_does_not_activate_synthetic_variants(self):
  tick(self.s)
  self.assertEqual(self.s.connection.execute('select count(*) from paper_sessions').fetchone()[0],0)

 def test_failed_comparison_never_starts_paper(self):
  for event in self.fixtures[self.variant]['comparison']:
   if event['kind']=='bbo' and event['bid']=='102':event.update(bid='98',ask='98.1')
  synthetic_tick(self.s,self.fixtures);synthetic_tick(self.s,self.fixtures)
  self.assertEqual(self.s.connection.execute('select status from validation_evaluations').fetchone()[0],'failed')
  self.assertEqual(self.s.connection.execute('select count(*) from paper_sessions').fetchone()[0],0)

 def test_complete_recipe_has_explicit_synthetic_provenance(self):
  from tamtam_again.population_recipe import run_recipe
  with tempfile.TemporaryDirectory() as output:result=run_recipe(Path(output))
  self.assertFalse(result['real_strategy_validated']);self.assertEqual(result['real_model_calls'],0)
  self.assertEqual(result['counts']['paper_sessions'],1)
  self.assertTrue(result['restart_and_duplicate_verified'])
