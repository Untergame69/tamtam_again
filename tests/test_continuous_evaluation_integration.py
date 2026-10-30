"""Temporary database; actual orchestrator/reducer, provider and archive admission fixtures."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tamtam_again.engine import canonical, fingerprint
from tamtam_again.storage import Store
from tamtam_again.recipe import synthetic_plan, synthetic_spec, synthetic_events
from tamtam_again.validation import create_plan, evaluate
from tamtam_again.population_experiments import register_experiment


class ContinuousEvaluationIntegrationTests(unittest.TestCase):
 def test_recent_oversized_account_does_not_starve_other_instrumented_accounts(self):
  from tamtam_again import continuous_research
  from tamtam_again.population import migrate
  policy=json.loads((Path(continuous_research.__file__).resolve().parents[2]/'config/continuous-research-policy.json').read_text())
  policy['network']='synthetic'
  inventory={'candidate_evaluations':[{'candidate_id':name,'candidate_alias':name,
    'disposition':'admissible_descriptive','research_question':'fixture',
    'source_ref':'fixture:'+name,'priority':'P3','scope':{'markets':['SYNTH'],'market_count':1,
    'period_start_ms':0,'cutoff_ms':100}} for name in ('oversized','other')]}
  with tempfile.TemporaryDirectory() as directory, Store(Path(directory)/'fixture.sqlite') as store:
   migrate(store);continuous_research.initialize(store)
   store.connection.execute('insert into continuous_research_candidates values(?,?,?,?,?,?,?)',
    ('synthetic','oversized','SYNTH','old','packet_too_large','{}',10));store.connection.commit()
   with patch('tamtam_again.continuous_research.admission_inventory',return_value=inventory),patch(
      'tamtam_again.continuous_research.market_proofs',return_value={
       ('oversized','SYNTH'):{'last_fill_event_ms':999},('other','SYNTH'):{'last_fill_event_ms':100}}),patch(
      'tamtam_again.continuous_research.tracked_accounts',return_value={'oversized','other'}),patch(
      'tamtam_again.continuous_research.prepare_packet',return_value={'status':'packet_too_large'}) as preparation:
    outcome=continuous_research.tick(store,policy,dispatch=False,clock_ms=1000,max_candidates=1)
   self.assertEqual(outcome['candidates'][0]['candidate'],'other:SYNTH')
   self.assertEqual(preparation.call_count,1)
   self.assertEqual(outcome['dispatched'],[])

 def test_malformed_provider_wake_does_not_block_the_next_candidate(self):
  from tamtam_again import continuous_research
  from tamtam_again.population import migrate
  policy=json.loads((Path(continuous_research.__file__).resolve().parents[2]/'config/continuous-research-policy.json').read_text())
  policy['network']='synthetic'
  inventory={'candidate_evaluations':[{'candidate_id':name,'candidate_alias':name,
    'disposition':'admissible_descriptive','research_question':'Describe observations.',
    'source_ref':'fixture:'+name,'priority':'P3','scope':{'markets':['SYNTH'],'market_count':1,
    'period_start_ms':0,'cutoff_ms':100}} for name in ('first','second')]}
  def preparation(store,policy,item):
   packet={'network':'synthetic','address':item['address'],'available_ms':100,
    'observations':{'markets':['SYNTH'],'market_execution_detail_v1':{'SYNTH':{'market':'SYNTH',
    'execution_activity':{'fills':10},'position_path':{},'by_utc_day':{},'fees_signed_by_token':{},
    'observed_fill_content_fingerprint':item['address']}}}}
   packet['fingerprint']=fingerprint(packet)
   from tamtam_again.continuous_research_identity import semantic_identity
   return {'status':'packet_ready','packet':packet,'semantic_fingerprint':semantic_identity(packet,'SYNTH')}
  responses=[{'decision':'unsupported_mechanism','diagnostic':'Passive queue is unsupported.',
    'wake':{'kind':{'malformed':True},'diagnostic_code':['invalid']}},
   {'decision':'non_identifiable','diagnostic':'No pre-decision signal identified.','wake':{}}]
  usage={'cost_usd':0,'cost_status':'included','input_tokens':100,'output_tokens':50,
    'duration_ms':5,'model':policy['task_policy']['model']}
  with tempfile.TemporaryDirectory() as directory, Store(Path(directory)/'fixture.sqlite') as store:
   migrate(store)
   with patch('tamtam_again.continuous_research.admission_inventory',return_value=inventory),patch(
      'tamtam_again.continuous_research.prepare_packet',side_effect=preparation),patch(
      'tamtam_again.population_runtime.verify'),patch('tamtam_again.population_runtime.now_ms',return_value=1002),patch(
      'tamtam_again.population_runtime.call',side_effect=[(json.dumps(r),usage) for r in responses]) as provider:
    first=continuous_research.tick(store,policy,clock_ms=1000)
    second=continuous_research.tick(store,policy,clock_ms=1001)
   self.assertEqual(first['dispatched'][0]['status'],'unsupported_mechanism')
   self.assertEqual(second['dispatched'][0]['status'],'non_identifiable')
   self.assertEqual(second['candidates'][0]['candidate'],'second:SYNTH')
   self.assertEqual(provider.call_count,2)
   self.assertEqual(store.connection.execute('select count(*) from continuous_research_calls').fetchone()[0],2)
   self.assertTrue(first['technical_priorities'])

 def test_exhausted_admission_skips_archive_preparation_but_polls_existing_work(self):
  from tamtam_again import continuous_research
  from tamtam_again.continuous_research_policy import authorize_task, finish_task
  from tamtam_again.population_research import initialize
  policy=json.loads((Path(continuous_research.__file__).resolve().parents[2]/'config/continuous-research-policy.json').read_text())
  policy['network']='synthetic'
  with tempfile.TemporaryDirectory() as directory, Store(Path(directory)/'fixture.sqlite') as store:
   initialize(store)
   for request in ('one','two','three'):
    packet={'available_ms':50,'fingerprint':request}
    store.connection.execute('insert into population_research_jobs '
     '(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,updated_ms) '
     'values(?,?,?,?,?,?,?,?,?)',(request,'synthetic',request,request,canonical(packet),canonical(policy['task_policy']),100,'sealed',100))
    store.connection.commit()
    authorize_task(store,policy,request_id=request,candidate=request+':SYNTH',address=request,market='SYNTH',
     packet_fingerprint_value=request,semantic_fingerprint_value=request,authorized_ms=100)
    store.connection.execute("update population_research_jobs set status='non_identifiable' where request_id=?",(request,));store.connection.commit()
    finish_task(store,request,'non_identifiable')
   with patch('tamtam_again.continuous_research.admission_inventory') as inventory,patch(
      'tamtam_again.continuous_research.prepare_packet') as preparation,patch(
      'tamtam_again.research_evaluation.poll',return_value={'decisions':[]}) as evaluations,patch(
      'tamtam_again.continuous_research_resolution.poll_waits',return_value={'advanced':[]}) as waits:
    outcome=continuous_research.tick(store,policy,clock_ms=1000)
   self.assertEqual(outcome['admission']['status'],'waiting_allowance')
   self.assertEqual(outcome['dispatched'],[])
   inventory.assert_not_called();preparation.assert_not_called()
   evaluations.assert_called_once();waits.assert_called_once()

 def test_rejection_feedback_and_another_market_continue_in_same_tick(self):
  from tamtam_again import continuous_research
  from tamtam_again.continuous_research_policy import authorize_task, finish_task
  policy=json.loads((Path(continuous_research.__file__).resolve().parents[2]/'config/continuous-research-policy.json').read_text())
  policy['network']='synthetic'
  with tempfile.TemporaryDirectory() as directory, Store(Path(directory)/'fixture.sqlite') as store:
   from tamtam_again.population import migrate
   migrate(store)
   continuous_research.initialize(store)
   plan=create_plan(store,synthetic_plan())['plan_id']
   profile={'schema_version':1,'hypothesis_id':'old','justification':'synthetic example',
    'max_variants':1,'selection_rule':'comparison_then_one_final','axes':[{'parameter':'horizon_ms','values':[500],
    'category':'hypothesis','justification':'fixture','evidence_refs':['old'],'measurement_status':'simulated'}]}
   result={'proposal':{'hypothesis':{'required_data':[],'executable_spec':synthetic_spec(),
    'markets':['SYNTH'],'type':'follower','experiment_profile':profile}},
    'critique':{'decision':'consistent','diagnostic':'fixture','wake':{}},
    'promotion_authorized':False,'profitability_proven':False}
   packet={'available_ms':50,'evidence_refs':['old'],'fingerprint':'old'}
   store.connection.execute('insert into population_research_jobs '
    '(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,result_json,updated_ms) '
    'values(?,?,?,?,?,?,?,?,?,?)',('old','synthetic','fixture-only','old',canonical(packet),canonical(policy['task_policy']),100,'sealed',canonical(result),100))
   store.connection.commit()
   authorize_task(store,policy,request_id='old',candidate='old:SYNTH',address='fixture-only',market='SYNTH',
    packet_fingerprint_value='old',semantic_fingerprint_value='old',authorized_ms=100)
   store.connection.execute("update population_research_jobs set status='hypothesis_recorded' where request_id='old'")
   store.connection.commit()
   finish_task(store,'old','hypothesis_recorded')
   family=register_experiment(store,'old',plan,profile)
   events=synthetic_events(10000)
   for event in events:
    if event['kind']=='bbo':event.update(bid='100',ask='100.1')
   from tamtam_again.pipeline import synthetic_tick
   variant=family['attempts'][0]['variant_id']
   pipeline=synthetic_tick(store,{variant:{'comparison':events}})
   evaluated=[entry for entry in pipeline['processed'] if entry.get('stage')=='comparison'][0]
   self.assertEqual(evaluated['status'],'failed')
   inventory={'candidate_evaluations':[{'candidate_id':'other-account','candidate_alias':'other',
    'disposition':'admissible_descriptive','research_question':'Describe causal observations.',
    'source_ref':'fixture:other','priority':'P3','scope':{'markets':['OTHER'],
    'market_count':1,'period_start_ms':0,'cutoff_ms':30000}}]}
   packet2={'available_ms':29000,'fingerprint':'next','network':'synthetic','address':'other-account',
    'observations':{'market_execution_detail_v1':{'OTHER':{'market':'OTHER',
    'execution_activity':{'fills':10},'position_path':[],'by_utc_day':[],
    'fees_signed_by_token':{},'observed_fill_content_fingerprint':'other-market-only'}}}}
   prepared={'status':'packet_ready','semantic_fingerprint':'different-economic-observations','packet':packet2}
   response={'decision':'needs_data','diagnostic':'Prospective observations missing.',
    'wake':{'condition':'new authorized observations'}}
   usage={'cost_usd':0,'cost_status':'included','input_tokens':100,'output_tokens':50,
    'duration_ms':5,'model':policy['task_policy']['model']}
   with patch('tamtam_again.continuous_research.admission_inventory',return_value=inventory), patch(
    'tamtam_again.continuous_research.prepare_packet',return_value=prepared), patch(
    'tamtam_again.population_runtime.verify'), patch('tamtam_again.population_runtime.now_ms',return_value=30000), patch(
    'tamtam_again.population_runtime.call',return_value=(json.dumps(response),usage)) as provider:
    outcome=continuous_research.tick(store,policy,clock_ms=30000)
   feedback=[entry for entry in outcome['evaluations']['decisions'] if entry['request_id']=='old'][0]
   self.assertEqual(feedback['state'],'rejected')
   self.assertEqual(feedback['next_plan']['kind'],'next_candidate')
   self.assertEqual(len(outcome['dispatched']),1,outcome)
   self.assertEqual(outcome['dispatched'][0]['status'],'needs_data')
   self.assertEqual(outcome['candidates'][0]['market'],'OTHER')
   provider.assert_called_once()
   self.assertEqual(store.connection.execute('select count(*) from paper_sessions').fetchone()[0],0)
   self.assertFalse(outcome['real_orders_authorized'])
