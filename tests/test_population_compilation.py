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

 def test_measured_reference_requires_actual_available_execution_proof(self):
  h=self.hypothesis();axis=h['experiment_profile']['axes'][0]
  axis.update(parameter='latency_ms',category='system_capacity',values=[1,2],
   measurement_status='measured_reference',measurement_available_ms=20,measurement_ref='measurement',evidence_refs=['measurement'])
  h['experiment_profile']['max_variants']=2
  with self.assertRaises(ValueError):validate_compilation(h,{'measurement'},as_of_ms=20)
  proof={'kind':'execution_delay_reference','parameter':'latency_ms','available_ms':20,'value_ms':1}
  r=validate_compilation(h,{'measurement'},measurements={'measurement':proof},as_of_ms=20)
  self.assertEqual(r['state'],'executable')
  with self.assertRaises(ValueError):validate_compilation(h,{'measurement'},measurements={'measurement':proof},as_of_ms=19)
  with self.assertRaises(ValueError):validate_compilation(h,{'measurement'},measurements={'measurement':{**proof,'kind':'rest_response_time'}},as_of_ms=20)
  axis['measurement_available_ms']=10
  with self.assertRaises(ValueError):validate_compilation(h,{'measurement'},measurements={'measurement':proof},as_of_ms=20)
