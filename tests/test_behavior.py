import unittest
from tamtam_again.behavior import profile_behavior

def observation(tid,time=100,coin='BTC',**fields):
 return {'fill':{'tid':tid,'time':time,'coin':coin,'sz':'1','px':'10',**fields},
         'available_ms':1000,'evidence_ref':'fixture:'+str(tid)}
def profile(rows,**options):
 return profile_behavior(rows,start_ms=0,end_ms=1000,as_of_ms=1000,**options)

class BehaviorTests(unittest.TestCase):
 def test_duplicate_reception_does_not_inflate_activity(self):
  a=observation(1,crossed=True,oid=1)
  p=profile([a,{**a,'evidence_ref':'fixture:other'}])
  self.assertEqual(p['fills_observed'],1);self.assertEqual(p['markets'][0]['taker_fills'],1)
 def test_conflicting_identity_excluded(self):
  p=profile([observation(1),observation(1,px='11')])
  self.assertEqual(p['fills_observed'],0);self.assertTrue(p['conflicting_fill_identities'])
 def test_future_observation_and_event_excluded(self):
  a=observation(1);a['available_ms']=1001
  b=observation(2);b['available_ms']=50
  self.assertEqual(profile([a,b])['fills_observed'],0)
 def test_maker_and_unknown_not_conflated(self):
  p=profile([observation(1,crossed=False),observation(2,crossed='false')])
  m=p['markets'][0];self.assertEqual(m['maker_fills'],1);self.assertEqual(m['aggression_unknown'],1)
 def test_multi_asset_groups_are_questions_not_arbitrage_claim(self):
  p=profile([observation(1),observation(2,coin='ETH')])
  self.assertEqual(p['market_count'],2);self.assertEqual(len(p['multi_market_time_groups']),1)
  self.assertEqual(p['questions'][0]['status'],'question_only')
 def test_invalid_sizes_and_order_partial_fills(self):
  p=profile([observation(1,sz='NaN',oid=3),observation(2,oid=3)])
  m=p['markets'][0];self.assertEqual(m['invalid_size_rows'],1)
  self.assertEqual(m['orders_with_multiple_fills'],1)
 def test_inventory_excursion_not_whole_account_profit(self):
  p=profile([observation(1,time=100,startPosition='2',side='B',dir='Open Long'),
             observation(2,time=200,startPosition='3',side='A',dir='Close Long')])
  m=p['markets'][0];self.assertEqual(len(m['candidate_episodes']),1)
  self.assertNotEqual(m['candidate_episodes'][0]['cycle_kind'],'flat_to_flat')
  self.assertFalse(m['candidate_episodes'][0]['exploitable'])
  self.assertEqual(p['performance_status'],'not_evaluated')
 def test_missing_initial_inventory_does_not_default_to_flat(self):
  p=profile([observation(1,side='B',dir='Open Long'),observation(2,time=200,side='A',dir='Close Long')])
  self.assertEqual(p['markets'][0]['candidate_episodes'],[])
