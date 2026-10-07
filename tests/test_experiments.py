import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from tamtam_again.storage import Store
from tamtam_again.recipe import synthetic_plan,synthetic_spec,synthetic_events
from tamtam_again.validation import create_plan,evaluate
from tamtam_again.experiments import compile_family,register_family,select_final,require_final_selection

def profile():
 return {'schema_version':1,'hypothesis_id':'fixture','justification':'synthetic parameter coverage only',
   'max_variants':4,'selection_rule':'comparison_then_one_final','axes':[
     {'parameter':'horizon_ms','values':[500,1500],'category':'hypothesis','justification':'test embargo failures',
      'evidence_refs':['fixture'],'measurement_status':'simulated'},
     {'parameter':'scale','values':['0.5','1'],'category':'risk_budget','justification':'chosen sizing sensitivity',
      'evidence_refs':['fixture'],'measurement_status':'simulated'}]}

class ExperimentTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db')
  self.plan=create_plan(self.s,synthetic_plan())['plan_id']
 def tearDown(self):self.s.close();self.tmp.cleanup()
 def test_cartesian_budget_and_base_immutable(self):
  base=synthetic_spec();old=json.dumps(base,sort_keys=True)
  self.assertEqual(len(compile_family(profile(),base)),4);self.assertEqual(json.dumps(base,sort_keys=True),old)
  p=profile();p['max_variants']=3
  with self.assertRaises(ValueError):compile_family(p,base)
 def test_failures_preserved_and_identical_family_idempotent(self):
  r=register_family(self.s,self.plan,profile(),synthetic_spec())
  self.assertEqual([a['status'] for a in r['attempts']].count('invalid_specification'),2)
  self.assertEqual(len(r['attempts']),4)
  self.assertEqual(register_family(self.s,self.plan,profile(),synthetic_spec())['family_id'],r['family_id'])
  self.assertEqual(self.s.connection.execute('select count(*) from experiment_attempts').fetchone()[0],4)
 def test_final_gate_no_selection(self):
  r=register_family(self.s,self.plan,profile(),synthetic_spec())
  variant=next(a['variant_id'] for a in r['attempts'] if a['variant_id'])
  with self.assertRaises(ValueError):require_final_selection(self.s,variant)
  with self.assertRaises(ValueError):select_final(self.s,r['family_id'])
  self.assertEqual(self.s.connection.execute('select count(*) from consumed_holdouts').fetchone()[0],0)
 def test_atomic_rollback_on_unexpected_failure(self):
  with patch('tamtam_again.experiments.register_variant',side_effect=RuntimeError('fixture failure')):
   with self.assertRaises(RuntimeError):register_family(self.s,self.plan,profile(),synthetic_spec())
  self.assertEqual(self.s.connection.execute('select count(*) from experiment_families').fetchone()[0],0)
  self.assertEqual(self.s.connection.execute('select count(*) from strategy_variants').fetchone()[0],0)
 def test_selection_stressed_pnl_and_loser_forbidden(self):
  r=register_family(self.s,self.plan,profile(),synthetic_spec())
  variants=[a['variant_id'] for a in r['attempts'] if a['variant_id']]
  for i,v in enumerate(variants):
   result={'stress_metrics':{'net_pnl':str(i)}}
   self.s.connection.execute('insert into validation_evaluations values (?,?,?,?,?,?,?,?)',(str(i),v,self.plan,'comparison','passed','fixture',json.dumps(result),'fixture'))
  self.s.connection.commit()
  selected=select_final(self.s,r['family_id']);self.assertEqual(selected['variant_id'],variants[1])
  require_final_selection(self.s,variants[1])
  with self.assertRaises(ValueError):require_final_selection(self.s,variants[0])
  with self.assertRaises(ValueError):evaluate(self.s,variants[0],'final',synthetic_events(20000),provenance='synthetic')
  self.assertEqual(self.s.connection.execute('select count(*) from consumed_holdouts').fetchone()[0],0)
  self.assertEqual(select_final(self.s,r['family_id']),selected)
 def test_existing_frozen_plan_not_extended(self):
  from tamtam_again.validation import register_variant
  register_variant(self.s,self.plan,synthetic_spec())
  with self.assertRaises(ValueError):register_family(self.s,self.plan,profile(),synthetic_spec())
 def test_delay_measured_vs_simulated_and_evidence(self):
  p=profile();p['axes'][0]['evidence_refs']=[]
  with self.assertRaises(ValueError):compile_family(p,synthetic_spec())
 def test_unsupported_signal_kept_without_economic_rejection(self):
  spec=synthetic_spec();spec['signal']['kind']='new_unknown_mechanism'
  r=register_family(self.s,self.plan,profile(),spec)
  self.assertTrue(all(a['status']=='unsupported_mechanism' for a in r['attempts']))
