import unittest
from tamtam_again.population_compilation import validate_compilation
from tamtam_again.recipe import synthetic_spec

class CompilationTests(unittest.TestCase):
 def hypothesis(self):
  return {'markets':['SYNTH'],'type':'follower','executable_spec':synthetic_spec(),
   'experiment_profile':{'schema_version':1,'hypothesis_id':'request','justification':'fixture only','max_variants':1,'selection_rule':'comparison_then_one_final',
   'axes':[{'parameter':'horizon_ms','values':[500],'category':'hypothesis','justification':'fixture','evidence_refs':['report'],'measurement_status':'simulated'}]}}
 def test_valid_rule_profile_and_source_are_required(self):
  h=self.hypothesis();self.assertEqual(validate_compilation(h,{'report'},request_id='request')['state'],'executable')
  h['experiment_profile']['axes'][0]['evidence_refs']=['invented']
  with self.assertRaises(ValueError):validate_compilation(h,{'report'},request_id='request')
 def test_unknown_mechanism_not_rewritten_or_economically_rejected(self):
  h=self.hypothesis();h['executable_spec']['signal']['kind']='unknown_inventory_controller'
  r=validate_compilation(h,{'report'},request_id='request')
  self.assertEqual(r['state'],'unsupported_mechanism');self.assertFalse(r['economic_rejection'])
  self.assertEqual(h['executable_spec']['signal']['kind'],'unknown_inventory_controller')
 def test_partial_output_wrong_origin_and_wrong_scope_rejected(self):
  h=self.hypothesis();del h['experiment_profile']
  with self.assertRaises(ValueError):validate_compilation(h,{'report'})
  h=self.hypothesis()
  with self.assertRaises(ValueError):validate_compilation(h,{'report'},request_id='different')
  h['markets']=['OTHER']
  with self.assertRaises(ValueError):validate_compilation(h,{'report'})
