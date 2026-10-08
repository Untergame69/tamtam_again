import copy,unittest
from tamtam_again.unified_risk import unified_ratio
class RiskTests(unittest.TestCase):
 def inputs(self):
  s={'event_ms':100,'available_ms':110,'evidence_ref':'fixture:spot','balances':[{'token':0,'total':'100','hold':'20'}]}
  state=lambda dex,cross,isolated:{'dex':dex,'event_ms':100,'available_ms':110,'evidence_ref':'fixture:'+dex,
   'crossMaintenanceMarginUsed':cross,'positions':[{'leverage':{'type':'isolated'},'marginUsed':isolated}]}
  c={'available_ms':90,'evidence_refs':['fixture:catalog'],'dexes':{d:{'collateral_token':0,'evidence_refs':['fixture:mapping']} for d in ('a','b')}}
  return dict(mode='unifiedAccount',spot=s,dex_states=[state('a','10','10'),state('b','5','15')],catalog=c,
   expected_dexes=['a','b'],event_ms=100,as_of_ms=200)
 def test_shared_balance_used_once_and_hold_not_added(self):
  r=unified_ratio(**self.inputs());self.assertEqual(r['ratio'],'0.2');self.assertEqual(len(r['collateral_pools']),1)
 def test_nonpositive_collateral_not_false_zero(self):
  x=self.inputs();x['spot']['balances'][0]['total']='20';self.assertIsNone(unified_ratio(**x)['ratio'])
 def test_missing_future_or_wrong_mode_unknown(self):
  for k in ('missing','future','mode','time'):
   x=self.inputs()
   if k=='missing':x['dex_states'].pop()
   if k=='future':x['catalog']['available_ms']=101
   if k=='mode':x['mode']='portfolioMargin'
   if k=='time':x['spot']['event_ms']=99
   self.assertIsNone(unified_ratio(**x)['ratio'])
