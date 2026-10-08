import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tamtam_again.storage import Store
from tamtam_again.cohort_matching import match,register
from tamtam_again.allocation import SCHEMA
P={'version':'matched-collection-v1','seed':'fixture','justification':'fixture only',
   'max_age_ms':2000,'minimum_activity_window_seconds':300,'max_pairs':8,
   'maximum_window_ratio':2,'activity_rate_cuts':[.001,.01,.1]}
def row(address,group,markets=None):
 return {'address':address,'group':group,'available_ms':9000,'evidence_ref':'fixture:'+address,
  'payload':{'activity':{'fills_per_second':.002,'window_seconds':1000},
  'mode':'default','markets':markets or ['BTC'],'perp_dexes_observed':[''],
  'spot_observed':True,'poll_interval_seconds':3600,'fill_coverage':'unknown'}}
class MatchingTests(unittest.TestCase):
 def test_disjoint_deterministic_maximum_matching(self):
  rows=[row('a','deepen',['BTC','ETH']),row('b','explore',['BTC']),
        row('c','control_uniform',['BTC']),row('d','control_leaderboard',['ETH'])]
  result=match(rows,P,cutoff_ms=10000)
  self.assertEqual(len(result['pairs']),2)
  self.assertEqual(result,match(list(reversed(rows)),P,cutoff_ms=10000))
  self.assertEqual({p['control_address'] for p in result['pairs']},{'c','d'})
  self.assertFalse(result['economic_qualification'])
 def test_future_stale_missing_data_not_zero(self):
  rows=[row('a','deepen'),row('b','control_uniform'),row('c','explore')]
  rows[0]['available_ms']=10001;rows[1]['available_ms']=1
  del rows[2]['payload']['activity']['fills_per_second']
  r=match(rows,P,cutoff_ms=10000)
  self.assertEqual(len(r['excluded']),3);self.assertEqual(r['pairs'],[])
 def test_mismatch_not_silently_relaxed(self):
  for field,value in [('mode','unifiedAccount'),('poll_interval_seconds',60),
                      ('fill_coverage','complete'),('perp_dexes_observed',['xyz'])]:
   a,b=row('a','deepen'),row('b','control_uniform');b['payload'][field]=value
   self.assertEqual(match([a,b],P,cutoff_ms=10000)['pairs'],[])
  a,b=row('a','deepen'),row('b','control_uniform')
  b['payload']['activity']['window_seconds']=2100
  self.assertEqual(match([a,b],P,cutoff_ms=10000)['pairs'],[])
 def test_no_shared_market_and_budget(self):
  rows=[row('a','deepen',['BTC']),row('b','control_uniform',['ETH'])]
  self.assertEqual(match(rows,P,cutoff_ms=10000)['unmatched_selected'][0]['reason'],'no compatible control')
  rows=[row('a','deepen'),row('b','deepen'),row('c','control_uniform'),row('d','control_uniform')]
  self.assertEqual(len(match(rows,{**P,'max_pairs':1},cutoff_ms=10000)['pairs']),1)
 def test_register_future_immutable_replay_no_reserved_payload(self):
  with tempfile.TemporaryDirectory() as tmp,Store(Path(tmp)/'db') as s:
   s.connection.executescript(SCHEMA)
   s.connection.execute('create table account_scope_reports (report_id text,network text,address text,available_ms integer,payload_json text)')
   groups={'deepen':['a','protected'],'explore':[],'control_uniform':['b'],'control_leaderboard':[]}
   s.connection.execute('insert into population_cohorts values(?,?,?,?,?,?)',('cohort','test',1,8000,'{}',json.dumps({'groups':groups})))
   for address,group in [('a','deepen'),('b','control_uniform')]:
    s.connection.execute('insert into account_scope_reports values(?,?,?,?,?)',(address,'test',address,9000,json.dumps(row(address,group)['payload'])))
   # Invalid JSON proves protected payload is never decoded.
   s.connection.execute('insert into account_scope_reports values(?,?,?,?,?)',('secret','test','protected',9000,'invalid reserved payload'))
   s.connection.commit()
   with patch('tamtam_again.cohort_matching.time.time',return_value=10),patch('tamtam_again.cohort_matching.protected_addresses',return_value={'protected'}):
    out=register(s,'test','cohort',P,start_ms=11000,end_ms=12000)
    self.assertEqual(len(out['pairs']),1)
    with self.assertRaises(ValueError):register(s,'test','cohort',P,start_ms=9000,end_ms=12000)
   with patch('tamtam_again.cohort_matching.time.time',return_value=20):
    replay=register(s,'test','cohort',P,start_ms=11000,end_ms=12000)
   self.assertTrue(replay['replayed']);self.assertEqual(out['registered_ms'],replay['registered_ms'])
   self.assertEqual(out['pairs'],replay['pairs'])
 def test_invalid_policy_and_duplicates(self):
  with self.assertRaises(ValueError):match([row('a','deepen'),row('a','deepen')],P,cutoff_ms=10000)
  with self.assertRaises(ValueError):match([],{**P,'activity_rate_cuts':[.1,.01]},cutoff_ms=10000)
