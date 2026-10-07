import json,unittest
from copy import deepcopy
from decimal import Decimal
from tamtam_again.portfolio_engine import initial,reduce,metrics,replay
from tamtam_again.harness_extensions import capability

def spec(**changes):
 return {'schema_version':1,'engine':'portfolio_reference_v1','currency':'USDC',
  'legs':[{'market':'A','target_units':'1'},{'market':'B','target_units':'-1'}],
  'capital_usdc':'1000','max_gross_usdc':'100','max_loss_usdc':'100',
  'taker_fee_bps':'1','slippage_bps':'0','displayed_size_fraction':'1',
  'start_ms':2,'latency_ms':1,'horizon_ms':10,'leg_timeout_ms':2,'heartbeat_timeout_ms':100,
  'unhedged_policy':'flatten_on_timeout','evidence_refs':['synthetic:reference'],**changes}
def event(kind,time,market=None,**fields):
 return {'id':str((kind,time,market,fields)),'kind':kind,'event_ms':time,'received_ms':time,
         **({'market':market} if market else {}),**fields}
def setup(depth_b='10'):
 return [event('connection',0,m,session=m,connected=True) for m in ('A','B')]+[
  event('bbo',1,'A',session='A',bid='10',ask='10',bid_size='10',ask_size='10'),
  event('bbo',1,'B',session='B',bid='20',ask='20',bid_size=depth_b,ask_size='10'),event('timer',2),event('timer',3)]

class PortfolioTests(unittest.TestCase):
 def test_joint_positions_and_gross_not_netted(self):
  s=spec();r=replay(s,setup());m=r['metrics']
  self.assertEqual(m['positions'],{'A':'1','B':'-1'})
  self.assertEqual(Decimal(m['gross_exposure_usdc']),Decimal(30))
  self.assertEqual(Decimal(m['net_exposure_usdc']),Decimal(-10))
  self.assertEqual(Decimal(m['fees_usdc']),Decimal('.003'))
 def test_round_trip_accounting_and_funding_once(self):
  events=setup()+[event('funding',4,'A',payment_per_unit='-.01'),event('funding',4,'B',payment_per_unit='-.01'),event('timer',13),event('timer',14)]
  r=replay(spec(),events);m=r['metrics']
  self.assertEqual(m['positions'],{'A':'0','B':'0'})
  self.assertEqual(Decimal(m['fees_usdc']),Decimal('.006'))
  self.assertEqual(Decimal(m['funding_usdc']),Decimal(0))
  self.assertEqual(Decimal(m['cash_usdc']),Decimal('999.994'))
  self.assertFalse(r['real_strategy_validated'])
 def test_single_leg_failure_then_flatten_actual_inventory(self):
  r=replay(spec(),setup('0'));self.assertEqual(r['metrics']['phase'],'unhedged')
  self.assertEqual(r['metrics']['positions'],{'A':'1','B':'0'})
  r=replay(spec(),setup('0')+[event('timer',6),event('timer',7)])
  self.assertEqual(r['metrics']['positions'],{'A':'0','B':'0'})
  self.assertTrue(r['state']['risk_halted']);self.assertEqual(r['metrics']['phase'],'finished')
 def test_partial_leg_preserved(self):
  r=replay(spec(),setup('.25'))
  self.assertEqual(Decimal(r['metrics']['positions']['B']),Decimal('-.25'))
  self.assertTrue(any(d['kind']=='partial_execution' for d in r['state']['diagnostics']))
 def test_disconnected_market_not_filled_or_valued(self):
  events=setup()[:-1]+[event('connection',3,'B',session='B',connected=False)]
  r=replay(spec(),events);self.assertEqual(r['metrics']['positions']['B'],'0')
  events=setup()+[event('connection',4,'B',session='B',connected=False)]
  self.assertIsNone(replay(spec(),events)['metrics']['equity_usdc'])
 def test_same_receipt_quote_does_not_open(self):
  s=spec(start_ms=1);r=replay(s,setup()[:-2]);self.assertEqual(r['metrics']['phase'],'waiting')
 def test_reconnect_does_not_execute_old_session_quote(self):
  r=replay(spec(),setup()[:-1]+[event('connection',3,'B',session='new',connected=True)])
  self.assertEqual(r['metrics']['positions']['B'],'0')
 def test_future_event_no_mutation(self):
  s=spec();state=initial(s);before=deepcopy(state)
  bad=event('timer',2);bad['event_ms']=3
  with self.assertRaises(ValueError):reduce(state,s,bad)
  self.assertEqual(state,before)
 def test_late_funding_no_mutation(self):
  s=spec();state=replay(s,setup())['state'];before=deepcopy(state)
  e=event('funding',4,'A',payment_per_unit='1');e['available_ms']=5
  with self.assertRaises(ValueError):reduce(state,s,e)
  self.assertEqual(state,before)
 def test_restart_duplicate_idempotence_and_version_guard(self):
  s=spec();events=setup();state=replay(s,events)['state'];state=json.loads(json.dumps(state));before=deepcopy(state)
  for e in events:reduce(state,s,e)
  self.assertEqual(state,before)
  with self.assertRaises(ValueError):reduce(state,spec(horizon_ms=11),event('timer',4))
 def test_aggregate_limit_blocks_reference_without_offsetting_legs(self):
  r=replay(spec(max_gross_usdc='25'),setup());self.assertEqual(r['metrics']['positions'],{'A':'0','B':'0'})
  self.assertTrue(r['state']['risk_halted'])
 def test_non_usdc_classified_unsupported_without_economic_failure(self):
  r=capability(spec(currency='USDH'));self.assertEqual(r['state'],'unsupported_mechanism')
  self.assertFalse(r['economic_rejection'])
 def test_unknown_engine_classified_unsupported(self):
  self.assertEqual(capability({'engine':'unknown'})['state'],'unsupported_mechanism')
