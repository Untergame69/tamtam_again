import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tamtam_again.storage import Store
from tamtam_again.recipe import synthetic_plan,synthetic_spec,synthetic_events
from tamtam_again.validation import create_plan,register_variant,evaluate
from tamtam_again.research_memory import migrate,authorized_period
from tamtam_again.discovery import protected_addresses
from tamtam_again.reserve_cycle import tick

POLICY={'version':'reserve-cycle-v1','policy_id':'fixture-v1','justification':'synthetic lifecycle test',
 'grace_ms':100,'abandon_unfinished_after_ms':1000,'max_plans_per_tick':2}
class ReserveCycleTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db')
  migrate(self.s)
  self.s.connection.execute('create table population_experiment_links(request_id text,plan_id text)')
  p=synthetic_plan();p['population_origin']={'request_id':'fixture-request'}
  self.plan=create_plan(self.s,p)['plan_id'];self.variant=register_variant(self.s,self.plan,synthetic_spec())['variant_id']
  self.s.connection.execute('insert into population_experiment_links values(?,?)',('fixture-request',self.plan))
  # Only the metadata guard is exercised as real, inside a temporary fixture DB.
  self.s.connection.execute('update validation_plans set synthetic=0')
  self.s.connection.commit()
  self.period={'network':'synthetic','address':'fixture-only','market':'*','start_ms':0,'end_ms':30000}
 def tearDown(self):self.s.close();self.tmp.cleanup()
 def test_abandoned_final_is_spent_and_new_future_reserve_reprotects_address(self):
  self.assertIn('fixture-only',protected_addresses(self.s))
  self.assertFalse(authorized_period(self.s,self.period,30000))
  r=tick(self.s,POLICY,clock_ms=27000)
  self.assertEqual(r['released'][0]['final_kind'],'abandoned_for_development')
  self.assertFalse(authorized_period(self.s,self.period,26999))
  self.assertTrue(authorized_period(self.s,self.period,30000))
  self.assertNotIn('fixture-only',protected_addresses(self.s))
  self.assertEqual(self.s.connection.execute('select count(*) from validation_evaluations').fetchone()[0],0)
  self.assertEqual(self.s.connection.execute('select start_ms,end_ms from consumed_holdouts').fetchone()[:],(20000,26000))
  self.assertEqual(tick(self.s,POLICY,clock_ms=40000)['released'],[])
  future=synthetic_plan();future['final']={'start_ms':50000,'end_ms':56000}
  future['population_origin']={'request_id':'future-request'}
  new_plan=create_plan(self.s,future)['plan_id']
  self.s.connection.execute('update validation_plans set synthetic=0 where plan_id=?',(new_plan,));self.s.connection.commit()
  self.assertIn('fixture-only',protected_addresses(self.s))
  self.assertFalse(authorized_period(self.s,{**self.period,'start_ms':50000,'end_ms':55000},60000))
 def test_grace_and_abandonment_deadlines_and_running_evaluation(self):
  r=tick(self.s,POLICY,clock_ms=26099)
  self.assertEqual(r['waiting'][0]['wake_ms'],26100)
  r=tick(self.s,POLICY,clock_ms=26100)
  self.assertEqual(r['waiting'][0]['wake_ms'],27000)
  self.s.connection.execute('insert into validation_evaluations values(?,?,?,?,?,?,?,?)',
   ('fixture-evaluation',self.variant,self.plan,'comparison','running','fixture','reserved-marker-never-read','fixture'))
  self.s.connection.commit()
  self.assertEqual(tick(self.s,POLICY,clock_ms=30000)['released'],[])
  self.assertEqual(self.s.connection.execute('select count(*) from consumed_holdouts').fetchone()[0],0)
 def test_terminal_original_retained_and_burn_required(self):
  self.s.connection.execute('insert into validation_evaluations values(?,?,?,?,?,?,?,?)',
   ('fixture-evaluation',self.variant,self.plan,'final','failed','fixture','reserved-marker-never-read','fixture'))
  self.s.connection.commit()
  self.assertEqual(tick(self.s,POLICY,clock_ms=30000)['released'],[])
  self.s.connection.execute('insert into consumed_holdouts values(?,?,?,?,?,?,?)',
   ('fixture-evaluation','synthetic','fixture-only','SYNTH',20000,26000,'fixture'))
  self.s.connection.commit()
  r=tick(self.s,POLICY,clock_ms=30000)
  self.assertEqual(r['released'][0]['final_kind'],'evaluated')
  self.assertEqual(self.s.connection.execute('select status,result_json from validation_evaluations').fetchone()[:],
   ('failed','reserved-marker-never-read'))
  self.assertEqual(self.s.connection.execute('select count(*) from consumed_holdouts').fetchone()[0],1)
 def test_legacy_pilot_on_same_address_remains_protected(self):
  tick(self.s,POLICY,clock_ms=30000)
  legacy=synthetic_plan();legacy['comparison']={'start_ms':100000,'end_ms':106000};legacy['final']={'start_ms':110000,'end_ms':116000}
  plan=create_plan(self.s,legacy)['plan_id']
  self.s.connection.execute('update validation_plans set synthetic=0 where plan_id=?',(plan,));self.s.connection.commit()
  tick(self.s,POLICY,clock_ms=200000)
  self.assertIn('fixture-only',protected_addresses(self.s))
  self.assertEqual(self.s.connection.execute('select count(*) from research_window_releases where plan_id=?',(plan,)).fetchone()[0],0)
 def test_policy_immutable_and_release_atomic_after_incident(self):
  tick(self.s,POLICY,clock_ms=20000)
  with self.assertRaisesRegex(ValueError,'immutable'):tick(self.s,{**POLICY,'grace_ms':0},clock_ms=30000)
  self.s.connection.execute("create trigger fixture_fail_release before insert on research_window_releases when new.stage='final' begin select raise(abort,'fixture incident'); end")
  self.s.connection.commit()
  with self.assertRaises(Exception):tick(self.s,POLICY,clock_ms=30000)
  self.assertEqual(self.s.connection.execute('select count(*) from consumed_holdouts').fetchone()[0],0)
  self.assertEqual(self.s.connection.execute('select count(*) from research_window_releases').fetchone()[0],0)
  self.s.connection.execute('drop trigger fixture_fail_release');self.s.connection.commit()
  self.assertEqual(len(tick(self.s,POLICY,clock_ms=30000)['released']),1)

 def test_abandoned_development_window_cannot_be_final_of_new_plan(self):
  tick(self.s,POLICY,clock_ms=30000)
  second=synthetic_plan();second['criteria']['min_net_pnl']='1'
  new_plan=create_plan(self.s,second)['plan_id']
  variant=register_variant(self.s,new_plan,synthetic_spec())['variant_id']
  self.assertEqual(evaluate(self.s,variant,'comparison',synthetic_events(10000),provenance='synthetic')['status'],'passed')
  with self.assertRaisesRegex(ValueError,'consumed'):
   evaluate(self.s,variant,'final',synthetic_events(20000),provenance='synthetic')

 def test_current_release_never_authorizes_a_historical_export_at_reserve_boundary(self):
  from tamtam_again.research_memory import authorized_account_history
  from tamtam_again.account_adapter import report_account
  from tamtam_again.account_periods import observed_periods
  from tamtam_again.population_packet import packet_for_account
  tick(self.s,POLICY,clock_ms=30000)
  self.assertNotIn('fixture-only',protected_addresses(self.s))
  self.assertTrue(authorized_account_history(self.s,'synthetic','fixture-only',9999))
  self.assertFalse(authorized_account_history(self.s,'synthetic','fixture-only',10000))
  self.assertTrue(authorized_account_history(self.s,'synthetic','fixture-only',30000))
  queries=[];self.s.connection.set_trace_callback(queries.append)
  for operation in (
   lambda:report_account(self.s,'synthetic','fixture-only',1000,9000,as_of_ms=10000),
   lambda:observed_periods(self.s,'synthetic','fixture-only',as_of_ms=10000),
   lambda:packet_for_account(self.s,'synthetic','fixture-only',as_of_ms=10000,max_chars=10000)):
   with self.assertRaisesRegex(ValueError,'reserved'):operation()
  self.assertFalse(any('from raw_observations' in q.lower() for q in queries))

 def test_packet_availability_includes_release_without_inventing_market_receipt(self):
  from tamtam_again.population_packet import packet_for_account
  tick(self.s,POLICY,clock_ms=30000)
  self.s.connection.execute('create table account_scope_reports(report_id text,network text,address text,available_ms integer,payload_json text)')
  self.s.connection.execute('insert into account_scope_reports values(?,?,?,?,?)',
   ('fixture-scope','synthetic','fixture-only',20000,json.dumps({'markets':['SYNTH']})))
  self.s.connection.commit()
  p=packet_for_account(self.s,'synthetic','fixture-only',as_of_ms=30000,max_chars=10000)['packet']
  self.assertEqual(p['available_ms'],30000)
  self.assertEqual(len(p['access_provenance']['released_windows']),2)
  self.assertEqual(self.s.connection.execute('select available_ms from account_scope_reports').fetchone()[0],20000)
  self.assertNotIn('result_json',str(p))

 def test_production_pipeline_does_not_reevaluate_abandoned_plan(self):
  from tamtam_again.pipeline import tick as pipeline_tick
  tick(self.s,POLICY,clock_ms=30000)
  with patch('tamtam_again.pipeline.archive_events') as archive,patch('tamtam_again.pipeline.evaluate') as evaluator:
   result=pipeline_tick(self.s)
  archive.assert_not_called();evaluator.assert_not_called()
  self.assertTrue(any(r.get('status')=='abandoned_for_development' for r in result['processed']))
