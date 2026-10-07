import unittest
from decimal import Decimal
from tamtam_again.market_rules import valid_price,round_size,validate_execution_rules,mechanism_profile
from tamtam_again.recipe import synthetic_spec,synthetic_events
from tamtam_again.engine import initial_state,reduce_event,validate_spec

class MarketRuleTests(unittest.TestCase):
 def rules(self,**changes):
  return {'version':1,'instrument':'SYNTH','currency':'USDC','available_ms':1000,
          'sz_decimals':2,'minimum_order_usdc':'10','max_leverage':'2','evidence_refs':['fixture'],**changes}
 def run_order(self,delta,rules=None):
  spec=synthetic_spec();spec['execution']['market_rules']=self.rules() if rules is None else rules
  validate_spec(spec);state=initial_state(spec)
  for e in synthetic_events(1000)[:2]:reduce_event(state,spec,e)
  reduce_event(state,spec,{'id':'leader','kind':'leader_fill','event_ms':1020,'received_ms':1020,'is_snapshot':False,'delta':delta})
  reduce_event(state,spec,{'id':'timer','kind':'timer','event_ms':1021,'received_ms':1021})
  return state
 def test_official_price_examples_and_integer_exception(self):
  self.assertTrue(valid_price('123456',2));self.assertTrue(valid_price('1234.5',2))
  self.assertFalse(valid_price('1234.56',2));self.assertTrue(valid_price('0.001234',0))
  self.assertFalse(valid_price('0.0012345',0));self.assertFalse(valid_price('0.012345',1))
 def test_zero_and_nonfinite_prices(self):
  self.assertFalse(valid_price('NaN',2));self.assertFalse(valid_price('0',2))
 def test_signed_sizes_rounded_toward_zero(self):
  self.assertEqual(round_size('-1.239',2),Decimal('-1.23'))
  self.assertEqual(round_size('1.239',2),Decimal('1.23'))
 def test_engine_rounds_size_without_increasing_exposure(self):
  state=self.run_order('1.239')
  self.assertEqual(Decimal(state['fills'][0]['size']),Decimal('1.23'))
 def test_order_below_documented_minimum_not_filled(self):
  state=self.run_order('0.01');self.assertEqual(state['fills'],[])
  self.assertEqual(state['missed_orders'],1)
 def test_future_metadata_does_not_authorize_execution(self):
  state=self.run_order('1',self.rules(available_ms=2000))
  self.assertEqual(state['fills'],[])
 def test_non_usdc_mechanism_not_economic_rejection(self):
  with self.assertRaisesRegex(ValueError,'Unsupported mechanism'):
   validate_execution_rules(self.rules(currency='USDH'),'SYNTH')
 def test_profile_unknown_instrument(self):
  self.assertEqual(mechanism_profile({'instruments':{}},'NO')['status'],'unknown')
