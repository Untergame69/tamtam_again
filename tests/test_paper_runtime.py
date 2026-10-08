import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tamtam_again.storage import Store
from tamtam_again.recipe import synthetic_plan,synthetic_spec
from tamtam_again.validation import create_plan,register_variant
from tamtam_again.research_memory import migrate
from tamtam_again.paper_research import seal,packet
from tamtam_again.paper_runtime import run
from tamtam_again.paper_scheduler import tick

class PaperRuntimeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db');migrate(self.s)
  self.plan=create_plan(self.s,synthetic_plan())['plan_id'];self.variant=register_variant(self.s,self.plan,synthetic_spec())['variant_id']
  self.s.connection.execute('update strategy_variants set frozen_ms=500 where variant_id=?',(self.variant,))
  self.s.connection.execute('insert into paper_sessions values(?,?,?,?,?,?,?,?,?,?)',
   ('fixture-session',self.variant,'synthetic','fixture-only','SYNTH',json.dumps({'fixture_preserved_positions':'never_mutate'}),'suspended',30000,0,'fixture'))
  self.s.connection.execute('create table paper_adaptation_requests(request_id text primary key,session_id text,created_ms integer,diagnostic_json text)')
  d={'request_id':'fixture-diagnostic','session_id':'fixture-session','created_ms':40000,
    'state':'research_budget_required','paper_snapshot_available_ms':39900,'evidence_refs':['paper_snapshots:fixture'],
    'observed_paper_metrics':{'net_pnl':'-5'}}
  self.s.connection.execute('insert into paper_adaptation_requests values(?,?,?,?)',('fixture-diagnostic','fixture-session',40000,json.dumps(d)));self.s.connection.commit()
  self.policy={'version':'paper-adaptation-research-v1','justification':'fixture only','max_requests':2,
   'max_packet_chars':20000,'minimum_interval_ms':1,'timeout_seconds':1,'max_output_tokens':100,
   'max_request_age_ms':10000,'model':'fixture','call_reservation_usd':'1'}
  self.allocation={'version':'experiment-allocation-v1','policy_id':'fixture-v1','justification':'fixture only',
   'max_profile_variants':1,'plan_template':{'version':'population-plan-v1','justification':'fixture',
    'max_plans':2,'comparison_delay_ms':100,'comparison_duration_ms':6000,'selection_gap_ms':1000,'final_duration_ms':6000,
    'criteria':synthetic_plan()['criteria'],'budget':synthetic_plan()['budget'],'isolation':'unavailable'}}
  self.clock=patch('tamtam_again.population_runtime.now_ms',return_value=40001);self.clock.start()
 def tearDown(self):self.clock.stop();self.s.close();self.tmp.cleanup()
 def responses(self,request):
  spec=synthetic_spec()
  profile={'schema_version':1,'hypothesis_id':request,'justification':'fixture paper hypothesis only',
   'max_variants':1,'selection_rule':'comparison_then_one_final','axes':[
    {'parameter':'horizon_ms','values':[500],'category':'hypothesis','justification':'fixture data simulator',
     'evidence_refs':['paper_adaptation_requests:fixture-diagnostic'],'measurement_status':'simulated'}]}
  hypothesis={k:'fixture unproven mechanism' for k in ('mechanism','signal','entry','exit','sizing','risk',
    'horizon_justification','execution_constraints','rejection_criteria')}
  hypothesis.update(type='follower',markets=['SYNTH'],required_data=[],
   evidence_refs=['paper_adaptation_requests:fixture-diagnostic'],executable_spec=spec,experiment_profile=profile)
  usage={'cost_usd':0,'cost_status':'included','duration_ms':1}
  return [(json.dumps({'decision':'hypothesis','diagnostic':'fixture only','wake':{},'hypothesis':hypothesis}),usage),
   (json.dumps({'decision':'consistent','diagnostic':'fixture causal consistency only','wake':{}}),usage)]
 def test_worker_and_scheduler_prepare_new_plan_without_manual_decision(self):
  before=self.s.connection.execute('select state_json,status from paper_sessions').fetchone()[:]
  request=seal(self.s,'fixture-diagnostic',self.policy,clock_ms=40000)['request_id']
  with patch('tamtam_again.population_runtime.verify'),patch('tamtam_again.population_runtime.call',side_effect=self.responses(request)) as caller:
   result=tick(self.s,self.policy,experiment_policy=self.allocation)
  self.assertEqual(caller.call_count,2)
  self.assertEqual(result['processed'][0]['status'],'hypothesis_recorded')
  self.assertEqual(result['plans'][0]['status'],'registered')
  self.assertEqual(result['memory'][0]['status'],'recorded')
  self.assertEqual(self.s.connection.execute('select count(*) from validation_plans').fetchone()[0],2)
  new=json.loads(self.s.connection.execute('select plan_json from validation_plans where plan_id!=?',(self.plan,)).fetchone()[0])
  self.assertGreater(new['comparison']['start_ms'],40000)
  self.assertEqual(new['population_origin']['parent_session_id'],'fixture-session')
  self.assertEqual(new['population_origin']['research_origin'],'paper')
  self.assertEqual(self.s.connection.execute('select state_json,status from paper_sessions').fetchone()[:],before)
  with patch('tamtam_again.population_runtime.call') as caller:
   again=tick(self.s,self.policy,experiment_policy=self.allocation)
  caller.assert_not_called();self.assertEqual(again['plans'],[])
 def test_reserved_guard_precedes_diagnosis_read_and_old_rule_remains_immutable(self):
  request=seal(self.s,'fixture-diagnostic',self.policy,clock_ms=40000)['request_id']
  original=json.loads(self.s.connection.execute('select plan_json from validation_plans').fetchone()[0])
  original['final']['end_ms']=40000
  self.s.connection.execute('update validation_plans set plan_json=?',(json.dumps(original),));self.s.connection.commit()
  queries=[];self.s.connection.set_trace_callback(queries.append)
  with patch('tamtam_again.population_runtime.call') as caller:
   with self.assertRaisesRegex(ValueError,'reserve'):run(self.s,request)
  caller.assert_not_called()
  self.assertFalse(any('select diagnostic_json' in q or 'select packet_json from paper_research_jobs' in q for q in queries))
 def test_shared_population_budget_is_not_an_extra_paper_tranche(self):
  self.s.connection.execute('create table population_research_jobs(request_id text)')
  self.s.connection.executemany('insert into population_research_jobs values(?)',[('spent1',),('spent2',)]);self.s.connection.commit()
  self.assertEqual(seal(self.s,'fixture-diagnostic',self.policy,clock_ms=40000)['status'],'budget_exhausted')
  self.assertEqual(self.s.connection.execute('select count(*) from paper_research_jobs').fetchone()[0],0)
 def test_expired_and_interrupted_requests_never_retry(self):
  request=seal(self.s,'fixture-diagnostic',self.policy,clock_ms=1+40000)['request_id']
  with patch('tamtam_again.population_runtime.now_ms',return_value=60000),patch('tamtam_again.population_runtime.verify') as verifier:
   self.assertEqual(run(self.s,request)['status'],'expired')
  verifier.assert_not_called()
  self.s.connection.execute("update paper_research_jobs set status='running',result_json=?",(json.dumps({'raw_proposal':'fixture interrupted checkpoint'}),));self.s.connection.commit()
  with patch('tamtam_again.population_runtime.call') as caller:
   result=tick(self.s,self.policy,experiment_policy=self.allocation)
  caller.assert_not_called();self.assertEqual(result['interrupted_without_retry'],[request])
  self.assertIn('fixture interrupted checkpoint',self.s.connection.execute('select result_json from paper_research_jobs').fetchone()[0])
 def test_changed_sealed_packet_is_rejected_before_model(self):
  request=seal(self.s,'fixture-diagnostic',self.policy,clock_ms=40000)['request_id']
  self.s.connection.execute('update paper_research_jobs set packet_json=?',(json.dumps({'tampered':True}),));self.s.connection.commit()
  with patch('tamtam_again.population_runtime.call') as caller:
   with self.assertRaisesRegex(ValueError,'provenance'):run(self.s,request)
  caller.assert_not_called()

 def test_pending_diagnoses_are_bounded_and_failed_older_one_does_not_starve_next(self):
  d=json.loads(self.s.connection.execute('select diagnostic_json from paper_adaptation_requests').fetchone()[0])
  for n in range(4):
   self.s.connection.execute('insert into paper_adaptation_requests values(?,?,?,?)',
    ('invalid-'+str(n),'missing-session',100+n,json.dumps(d)))
  self.s.connection.commit()
  with patch('tamtam_again.paper_scheduler.now_ms',return_value=40001):
   first=tick(self.s,{**self.policy,'max_diagnoses_per_tick':2},experiment_policy=self.allocation,dispatch=False)
   self.assertEqual(len(first['sealed']),2)
   same=tick(self.s,{**self.policy,'max_diagnoses_per_tick':2},experiment_policy=self.allocation,dispatch=False)
   self.assertEqual(len(same['sealed']),2)
   again=tick(self.s,{**self.policy,'max_diagnoses_per_tick':2},experiment_policy=self.allocation,dispatch=False)
   self.assertEqual(again['sealed'][0]['status'],'sealed')
  self.assertEqual(self.s.connection.execute('select count(*) from paper_research_jobs').fetchone()[0],1)
