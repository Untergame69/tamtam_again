import tempfile,unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from tamtam_again.storage import Store
from tamtam_again.population import enroll,claim,finish,cadence,collect_overview

def address(n):return '0x'+format(n,'040x')
P={'version':'test','max_rest_accounts':24,'max_jobs_per_tick':1,'default_poll_seconds':3600,'min_poll_seconds':300,'max_poll_seconds':21600,'retention_fraction':.5,'retention_fills':10000,'lease_seconds':600,'retry_seconds':300,'initial_lookback_seconds':86400,'sampling_seed':'test'}
class PopulationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db.sqlite3';self.s=Store(self.path)
  for n in range(1,41):self.s.add_candidate('test',address(n),'fixture')
 def tearDown(self):self.s.close();self.tmp.cleanup()
 def test_more_than_ten_and_no_direct_change(self):
  r=enroll(self.s,'test',P,now_ms=1000);self.assertEqual(r['rest_accounts'],24)
  self.assertTrue(all(x['status']=='candidate' for x in self.s.candidates('test')))
  self.assertEqual(enroll(self.s,'test',P,now_ms=2000)['enrolled'],[])
 def test_concurrent_claims_unique(self):
  enroll(self.s,'test',P,now_ms=1000)
  def run(_):
   with Store(self.path) as s:return claim(s,'test',now_ms=1000)['address']
  with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(run,range(4)))
  self.assertEqual(len(set(rows)),4)
 def test_expired_lease_preserves_attempt_and_blocks_old_finish(self):
  single={**P,'max_rest_accounts':1};enroll(self.s,'test',single,now_ms=1000)
  old=claim(self.s,'test',now_ms=1000);new=claim(self.s,'test',now_ms=700000)
  self.assertNotEqual(old['lease_token'],new['lease_token'])
  with self.assertRaises(ValueError):finish(self.s,old,{},300,now_ms=700001)
  self.assertEqual(self.s.connection.execute('select status from population_attempts where attempt_id=?',(old['attempt_id'],)).fetchone()[0],'interrupted')
 def test_retention_risk_changes_cadence(self):
  fills=[{'coin':'BTC','time':1000,'tid':n} for n in range(10000)]
  interval,activity=cadence(P,fills,0,10000)
  self.assertEqual(interval,300);self.assertTrue(activity['needs_faster_than_minimum'])
 def test_scope_includes_all_dexes_without_summing_collateral(self):
  enroll(self.s,'test',{**P,'max_rest_accounts':1},now_ms=1000);job=claim(self.s,'test',now_ms=1000)
  class Client:
   def post_info(self,q):
    kind=q['type']
    if kind=='userAbstraction':return 'unifiedAccount'
    if kind=='userRole':return {'role':'user'}
    if kind=='perpDexs':return [None,{'name':'xyz'}]
    if kind=='clearinghouseState':return {'marginSummary':{'accountValue':'100'},'assetPositions':[{'position':{'coin':'xyz:GOLD' if q.get('dex') else 'BTC','szi':'1'}}]}
    if kind=='spotClearinghouseState':return {'balances':[]}
    return []
  report=collect_overview(self.s,Client(),job,now_ms=2000)
  self.assertEqual(set(report['markets']),{'BTC','xyz:GOLD'})
  self.assertEqual(report['mode'],'unifiedAccount');self.assertTrue(report['capital_aggregation'].startswith('unknown'))
  self.assertEqual(self.s.connection.execute('select count(*) from account_scope_reports').fetchone()[0],1)
  raw=self.s.connection.execute("select complete,request_json from raw_observations where endpoint='userFillsByTime'").fetchone()
  self.assertFalse(raw['complete']);self.assertIn('pagination_only_retention_unknown',raw['request_json'])
  self.assertEqual(set(report['histories']),{'userFillsByTime','userFunding','userNonFundingLedgerUpdates'})
 def test_cursor_ends_at_request_not_later_processing(self):
  enroll(self.s,'test',{**P,'max_rest_accounts':1},now_ms=1000);job=claim(self.s,'test',now_ms=1000)
  finish(self.s,job,{'fills_requested_end_ms':2000},300,now_ms=8000)
  row=self.s.connection.execute('select last_success_ms,next_due_ms from population_accounts').fetchone()
  self.assertEqual(row['last_success_ms'],2000);self.assertEqual(row['next_due_ms'],308000)
 def test_history_cutoff_after_inventory_calls(self):
  from unittest.mock import patch
  enroll(self.s,'test',{**P,'max_rest_accounts':1},now_ms=1000);job=claim(self.s,'test',now_ms=1000)
  clock=[2.0]
  class Client:
   def post_info(self,q):
    if q['type']=='perpDexs':return [None]
    if q['type']=='clearinghouseState':
     clock[0]=5.0
     return {'time':4000,'marginSummary':{'accountValue':'100'},'assetPositions':[]}
    return []
  with patch('tamtam_again.population.time.time',side_effect=lambda:clock[0]):
   report=collect_overview(self.s,Client(),job)
  self.assertEqual(report['fills_requested_end_ms'],5000)
  self.assertTrue(all(h['end_ms']==5000 for h in report['histories'].values()))
