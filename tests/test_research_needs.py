import json,tempfile,unittest
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.validation import create_plan
from tamtam_again.recipe import synthetic_plan
from tamtam_again.research_needs import validate_requests,classify,register

class ResearchNeedsTests(unittest.TestCase):
 def request(self,**changes):
  return {'required_data_index':0,'source':'public_rest_history','endpoint':'userFunding','start_ms':1000,
   'end_ms':2000,'proof':'pagination_coverage','decision_use':'determine whether funding settlements are archived',**changes}
 def test_complete_explicit_contract_and_unrecognized_capability(self):
  r=self.request();validate_requests(['funding pages'],[r]);self.assertEqual(classify(r)['state'],'acquisition_required')
  self.assertEqual(classify(self.request(source='external_hedge'))['state'],'unsupported_acquisition')
  self.assertEqual(classify(self.request(proof='economic_completeness'))['state'],'unsupported_proof')
 def test_no_partial_mapping_or_model_budget(self):
  for requests in ([],[self.request(),self.request()], [self.request(required_data_index=True)],
   [self.request(max_pages=999)],[self.request(end_ms=1000)]):
   with self.assertRaises(ValueError):validate_requests(['funding pages'],requests)
  with self.assertRaises(ValueError):validate_requests(['fills','funding'],[self.request()])
 def test_registration_legacy_and_reserved_metadata_guard(self):
  with tempfile.TemporaryDirectory() as directory,Store(Path(directory)/'db') as store:
   create_plan(store,synthetic_plan())
   store.connection.execute('create table population_research_jobs(request_id text,network text,address text,status text,updated_ms integer,result_json text)')
   def job(identity,requests=None):
    hypothesis={'required_data':['funding pages']}
    if requests is not None:hypothesis['observation_requests']=requests
    result={'proposal':{'hypothesis':hypothesis},'critique':{'decision':'consistent'},'promotion_authorized':False,'profitability_proven':False}
    store.connection.execute('insert into population_research_jobs values(?,?,?,?,?,?)',(identity,'synthetic','fixture-only','hypothesis_recorded',100,json.dumps(result)));store.connection.commit()
   job('legacy');legacy=register(store,'legacy',clock_ms=30000)
   self.assertEqual(legacy['state'],'structured_request_required')
   job('reserved',[self.request(start_ms=20000,end_ms=22000)])
   queries=[];store.connection.set_trace_callback(queries.append)
   plan=register(store,'reserved',clock_ms=30000)
   self.assertEqual(plan['entries'][0]['state'],'reserved_period')
   self.assertFalse(any('raw_observations' in q for q in queries))
   self.assertEqual(register(store,'reserved',clock_ms=40000),plan)
   job('future',[self.request(start_ms=40000,end_ms=50000)])
   self.assertEqual(register(store,'future',clock_ms=30000)['entries'][0]['state'],'await_window_end')
   self.assertFalse(plan['dispatch_authorized']);self.assertFalse(plan['economic_rejection'])
