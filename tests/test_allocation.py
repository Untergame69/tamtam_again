import tempfile,unittest,json,time
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.population import enroll,claim,finish
from tamtam_again.allocation import choose
from test_population import P,address

A={'version':'fixture-v1','seed':'fixture','justification':'bounded prospective experiment',
 'epoch_ms':1000,'max_deepen_epochs':2,'leaderboard_window':'day',
 'slots':{'explore':2,'deepen':2,'control_uniform':1,'control_leaderboard':1}}
def rows():return [{'address':address(n),'observed_scope':n<6,'leaderboard_rank':n,'performance':'unknown'} for n in range(1,21)]

class AllocationTests(unittest.TestCase):
 def test_groups_disjoint_bounded_deterministic(self):
  r=choose(rows(),A,epoch=1);members=[a for g in r['groups'].values() for a in g]
  self.assertEqual(len(members),6);self.assertEqual(len(set(members)),6)
  self.assertEqual(r,choose(list(reversed(rows())),A,epoch=1))
 def test_unknown_not_adverse_and_blocked_not_selected(self):
  source=rows();source[0]['hard_blockers']=['fixture'];source[1]['adverse_results']=['observed loss']
  r=choose(source,A,epoch=1)
  self.assertFalse(r['decisions'][0]['selected']);self.assertEqual(r['decisions'][1]['performance'],'unknown')
  self.assertEqual(r['decisions'][1]['adverse_results'],['observed loss'])
 def test_old_coverage_no_permanent_deepening(self):
  source=rows()
  for r in source:r['consecutive_deepen_epochs']=2
  self.assertEqual(choose(source,A,epoch=1)['groups']['deepen'],[])
 def test_unavailable_controls_remain_unfilled(self):
  source=rows()
  for r in source:r['leaderboard_rank']=None
  self.assertEqual(choose(source,A,epoch=1)['unfilled_slots']['control_leaderboard'],1)
 def test_live_rotation_preserves_running_and_budget_and_archive(self):
  with tempfile.TemporaryDirectory() as tmp,Store(Path(tmp)/'db') as store:
   for n in range(1,30):store.add_candidate('test',address(n),'fixture')
   old={**P,'max_rest_accounts':6};clock=int(time.time()*1000)
   enroll(store,'test',old,now_ms=clock);job=claim(store,'test',now_ms=clock)
   policy={**old,'allocation':A}
   r=enroll(store,'test',policy,now_ms=clock+1)
   self.assertLessEqual(store.connection.execute("select count(*) from population_accounts where status!='retired'").fetchone()[0],6)
   self.assertEqual(store.connection.execute('select lease_token from population_accounts where address=?',(job['address'],)).fetchone()[0],job['lease_token'])
   first=store.connection.execute('select snapshot_json from population_cohorts where cohort_id=?',(r['cohort_id'],)).fetchone()[0]
   repeated=enroll(store,'test',policy,now_ms=clock+1)
   self.assertEqual(repeated['cohort_id'],r['cohort_id'])
   finish(store,job,{'fills_requested_end_ms':clock},300,now_ms=clock+2)
   enroll(store,'test',policy,now_ms=clock+3)
   self.assertEqual(store.connection.execute('select snapshot_json from population_cohorts where cohort_id=?',(r['cohort_id'],)).fetchone()[0],first)
   self.assertEqual(store.connection.execute('select status from population_attempts where attempt_id=?',(job['attempt_id'],)).fetchone()[0],'complete')
 def test_duplicate_addresses_rejected(self):
  with self.assertRaises(ValueError):choose(rows()+rows()[:1],A,epoch=1)
 def test_history_prioritizes_deepening_without_using_dollar_gains(self):
  source=rows()
  for r in source:r['consecutive_deepen_epochs']=2
  source[3]['consecutive_deepen_epochs']=0;source[3]['historical_priority']=True
  source[3]['historical_concentration']=0.3;source[3]['historical_positive_months']=5
  source[4]['consecutive_deepen_epochs']=0;source[4]['historical_priority']=True
  source[4]['historical_concentration']=0.5;source[4]['historical_positive_months']=4
  policy={**A,'slots':{'explore':0,'deepen':2,'control_uniform':0,'control_leaderboard':0}}
  result=choose(source,policy,epoch=1)
  self.assertEqual(result['groups']['deepen'],[source[3]['address'],source[4]['address']])
  self.assertEqual(result['groups']['explore'],[])
  self.assertIn('historical positive curve',next(x['reason'] for x in result['decisions'] if x['address']==source[3]['address']))
