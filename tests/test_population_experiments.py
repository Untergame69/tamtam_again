import json,tempfile,unittest
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.recipe import synthetic_plan,synthetic_spec
from tamtam_again.validation import create_plan
from tamtam_again.population_experiments import register_experiment

class PopulationExperimentTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db')
  self.plan=create_plan(self.s,synthetic_plan())['plan_id']
  self.s.connection.execute('create table population_research_jobs(request_id text,network text,address text,status text,result_json text,updated_ms integer,packet_json text)')
  self.result={'proposal':{'hypothesis':{'required_data':[],'executable_spec':synthetic_spec(),'markets':['SYNTH'],'type':'follower'}},
   'critique':{'decision':'consistent','diagnostic':'fixture','wake':{}},'promotion_authorized':False,'profitability_proven':False}
  self.s.connection.execute('insert into population_research_jobs values(?,?,?,?,?,?,?)',('request','synthetic','fixture-only','hypothesis_recorded',json.dumps(self.result),100,json.dumps({'available_ms':50,'evidence_refs':['request']})));self.s.connection.commit()
  self.profile={'schema_version':1,'hypothesis_id':'request','justification':'fixture only', 'max_variants':1,'selection_rule':'comparison_then_one_final',
   'axes':[{'parameter':'horizon_ms','values':[500],'category':'hypothesis','justification':'fixture','evidence_refs':['request'],'measurement_status':'simulated'}]}
 def tearDown(self):self.s.close();self.tmp.cleanup()
 def test_registration_idempotent_and_no_promotion(self):
  r=register_experiment(self.s,'request',self.plan,self.profile)
  self.assertEqual(r['status'],'registered');self.assertFalse(r['promotion_authorized'])
  self.assertEqual(register_experiment(self.s,'request',self.plan,self.profile)['status'],'already_registered')
  self.assertEqual(self.s.connection.execute('select count(*) from strategy_variants').fetchone()[0],1)
  self.assertEqual(self.s.connection.execute('select count(*) from validation_evaluations').fetchone()[0],0)
  changed={**self.profile,'justification':'new specification'}
  with self.assertRaises(ValueError):register_experiment(self.s,'request',self.plan,changed)
 def test_missing_data_blocks_registration(self):
  self.result['proposal']['hypothesis']['required_data']=['unavailable path']
  self.s.connection.execute('update population_research_jobs set result_json=?',(json.dumps(self.result),));self.s.connection.commit()
  with self.assertRaises(ValueError):register_experiment(self.s,'request',self.plan,self.profile)
  self.assertEqual(self.s.connection.execute('select count(*) from strategy_variants').fetchone()[0],0)
 def test_scope_mismatch_and_existing_pilot_preserved(self):
  from tamtam_again.validation import register_variant
  variant=register_variant(self.s,self.plan,synthetic_spec())
  with self.assertRaises(ValueError):register_experiment(self.s,'request',self.plan,self.profile)
  self.assertEqual(self.s.connection.execute('select variant_id from strategy_variants').fetchone()[0],variant['variant_id'])

 def test_registered_family_uses_comparison_final_and_synthetic_paper_gates(self):
  from tamtam_again.recipe import synthetic_events
  from tamtam_again.validation import evaluate
  from tamtam_again.experiments import select_final
  from tamtam_again.paper import start_paper
  r=register_experiment(self.s,'request',self.plan,self.profile)
  variant=r['attempts'][0]['variant_id']
  comparison=evaluate(self.s,variant,'comparison',synthetic_events(10000),provenance='synthetic')
  self.assertEqual(comparison['status'],'passed')
  selected=select_final(self.s,r['family_id'])
  self.assertEqual(selected['variant_id'],variant)
  final=evaluate(self.s,variant,'final',synthetic_events(20000),provenance='synthetic')
  self.assertEqual(final['status'],'passed');self.assertFalse(final['promotable'])
  with self.assertRaises(ValueError):start_paper(self.s,variant)
  session=start_paper(self.s,variant,synthetic_recipe=True)
  self.assertTrue(session['synthetic'])

 def test_interrupted_link_registration_recovers_same_family(self):
  from unittest.mock import patch
  from tamtam_again.experiments import register_family
  with patch('tamtam_again.population_experiments.register_family',side_effect=RuntimeError('fixture interruption')):
   with self.assertRaises(RuntimeError):register_experiment(self.s,'request',self.plan,self.profile)
  # Simulate the family committing before the process dies before its link.
  register_family(self.s,self.plan,self.profile,synthetic_spec())
  r=register_experiment(self.s,'request',self.plan,self.profile)
  self.assertEqual(r['status'],'registered')
  self.assertEqual(self.s.connection.execute('select count(*) from experiment_families').fetchone()[0],1)
  self.assertEqual(self.s.connection.execute('select count(*) from strategy_variants').fetchone()[0],1)

 def test_real_comparison_must_still_be_future(self):
  from unittest.mock import patch
  self.s.connection.execute('update validation_plans set synthetic=0 where plan_id=?',(self.plan,));self.s.connection.commit()
  with patch('tamtam_again.population_experiments.now_ms',return_value=10000):
   with self.assertRaisesRegex(ValueError,'before future comparison'):
    register_experiment(self.s,'request',self.plan,self.profile)
  self.assertEqual(self.s.connection.execute('select count(*) from strategy_variants').fetchone()[0],0)

 def test_direct_registration_cannot_bypass_measurement_evidence(self):
  axis=self.profile['axes'][0]
  axis.update(parameter='latency_ms',category='system_capacity',values=[1],measurement_status='measured_reference',
   measurement_ref='request',measurement_available_ms=20)
  with self.assertRaisesRegex(ValueError,'sealed measurement proof'):
   register_experiment(self.s,'request',self.plan,self.profile)
  self.assertEqual(self.s.connection.execute('select count(*) from strategy_variants').fetchone()[0],0)
