"""Optional causal zero-funding exposure constraint, never a forced signal."""
from decimal import Decimal
import unittest
from tamtam_again.engine import initial_state, validate_spec, reduce_event, funding_coverage, _fill, _order, _execute
from tamtam_again.recipe import synthetic_spec

HOUR=3_600_000


class FlatAtSettlementTests(unittest.TestCase):
    def spec(self):
        spec=synthetic_spec();spec['engine']='single_perp_v3'
        spec['execution'].update(max_quote_age_ms=1000,paper_tick_target_ms=5000,
            funding_observation_interval_ms=HOUR,
            funding_settlement_clock='reported_hour_with_inventory_invariance_v1',
            funding_exposure_policy='flat_at_settlement_v1')
        return spec

    def funding(self,stamp=75,*,coefficient='-0.1',identity=None):
        return {'id':identity or str(stamp)+coefficient,'kind':'funding','event_ms':stamp,
            'received_ms':stamp+100,'unit_funding_usdc':coefficient}

    def clock(self,state,spec):reduce_event(state,spec,self.funding())

    def test_opt_in_requires_priority_hourly_engine_and_is_not_a_default(self):
        spec=self.spec();validate_spec(spec)
        spec.pop('engine')
        with self.assertRaisesRegex(ValueError,'priority'):validate_spec(spec)
        base=synthetic_spec();state=initial_state(base);_order(state,base,Decimal(1),1000)
        self.assertEqual(state['pending'][0]['target'],'1')

    def test_first_hour_without_observed_clock_blocks_opening_and_drops_stale_orders(self):
        spec=self.spec();state=initial_state(spec)
        _order(state,spec,Decimal(1),1000)
        self.assertEqual(state['pending'],[])
        self.assertIn('current_hour_reported_funding_clock_unavailable',state['nonexecution_reasons'])
        state['pending']=[{'target':'1','due_ms':1000,'expires_ms':3000}]
        _execute(state,spec,1100,Decimal(1));self.assertEqual(state['pending'],[])
        # A subsequent clock does not recreate the rejected intent.
        reduce_event(state,spec,self.funding(stamp=1075))
        self.assertEqual(state['pending'],[]);self.assertEqual(state['position'],'0')

    def test_causal_current_hour_clock_then_fresh_entry_can_be_considered(self):
        spec=self.spec();state=initial_state(spec);self.clock(state,spec)
        _order(state,spec,Decimal(1),175)
        self.assertEqual(state['pending'],[])  # same-ms availability is not prior evidence
        _order(state,spec,Decimal(1),1000)
        self.assertEqual(state['pending'][0]['target'],'1')
        # A new hour requires its own observed clock, not last hour's report.
        state['pending']=[];_order(state,spec,Decimal(1),HOUR+1000)
        self.assertEqual(state['pending'],[])

    def test_exit_buffer_blocks_new_exposure_but_reduction_has_priority(self):
        spec=self.spec();state=initial_state(spec);self.clock(state,spec)
        # horizon500 + entry/exit latency2 + TTL500 + quote buffer1000.
        _order(state,spec,Decimal(1),HOUR-2002)
        self.assertEqual(state['pending'],[])
        self.assertIn('entry_exit_buffer_overlaps_next_funding_hour',state['nonexecution_reasons'])
        _fill(state,Decimal(1),Decimal(100),Decimal(0),HOUR-3000)
        _order(state,spec,Decimal(0),HOUR-100,intent='horizon_exit')
        self.assertEqual(state['pending'][0]['target'],'0')
        self.assertTrue(state['pending'][0]['reduce_only'])

    def test_execution_rechecks_buffer_and_never_moves_expired_entry_into_next_hour(self):
        spec=self.spec();state=initial_state(spec);self.clock(state,spec)
        _order(state,spec,Decimal(1),HOUR-3000)
        self.assertEqual(len(state['pending']),1)
        _execute(state,spec,HOUR-1000,Decimal(1))
        self.assertEqual(state['pending'],[]);self.assertEqual(state['position'],'0')
        self.assertIn('entry_exit_buffer_overlaps_next_funding_hour',state['nonexecution_reasons'])

    def test_failed_exit_retains_position_and_missing_funding_remains_unknown(self):
        spec=self.spec();state=initial_state(spec);self.clock(state,spec)
        _fill(state,Decimal(1),Decimal(100),Decimal(0),HOUR-3000)
        _order(state,spec,Decimal(0),HOUR-2000,intent='horizon_exit')
        _execute(state,spec,HOUR+100,Decimal(1))
        self.assertEqual(state['position'],'1')
        self.assertIn('priority_exit_unresolved_position',state['diagnostics'])
        audit=funding_coverage(state,spec,{'start_ms':0,'end_ms':HOUR+1000})
        self.assertEqual(audit['state'],'incomplete');self.assertEqual(audit['missing_settlements'],[HOUR])

    def test_zero_inventory_conflicting_coefficients_and_clocks_are_only_source_uncertainty(self):
        spec=self.spec();state=initial_state(spec)
        reduce_event(state,spec,self.funding(coefficient='-0.1'))
        reduce_event(state,spec,self.funding(coefficient='-0.100001'))
        reduce_event(state,spec,self.funding(stamp=86))
        audit=funding_coverage(state,spec,{'start_ms':0,'end_ms':1000})
        self.assertEqual(audit['state'],'complete');self.assertEqual(state['funding'],'0.0')
        self.assertTrue(audit['source_data_diagnostics'])
        self.assertFalse(audit['diagnostics']);self.assertFalse(state['diagnostics'])
        _order(state,spec,Decimal(1),1000)
        self.assertEqual(state['pending'][0]['target'],'1')

    def test_intraday_flat_close_and_unrelated_source_conflict_do_not_poison_later_slot(self):
        spec=self.spec();state=initial_state(spec)
        reduce_event(state,spec,self.funding(coefficient='-0.1'))
        reduce_event(state,spec,self.funding(coefficient='-0.100001'))
        _fill(state,Decimal(1),Decimal(100),Decimal(0),1000)
        _fill(state,Decimal(-1),Decimal(100),Decimal(0),2000)
        reduce_event(state,spec,self.funding(stamp=HOUR+75,coefficient='-0.3'))
        reduce_event(state,spec,self.funding(stamp=HOUR+75,coefficient='-0.30001'))
        audit=funding_coverage(state,spec,{'start_ms':0,'end_ms':HOUR+1000})
        self.assertEqual(audit['state'],'complete')
        self.assertEqual(Decimal(state['funding']),Decimal(0))
        self.assertTrue(audit['source_data_diagnostics']);self.assertFalse(state['diagnostics'])

    def test_trade_between_two_reported_times_invalidates_zero_cost_even_if_flat_again(self):
        spec=self.spec();state=initial_state(spec)
        reduce_event(state,spec,self.funding())
        _fill(state,Decimal(1),Decimal(100),Decimal(0),80)
        _fill(state,Decimal(-1),Decimal(100),Decimal(0),82)
        reduce_event(state,spec,self.funding(stamp=86))
        audit=funding_coverage(state,spec,{'start_ms':0,'end_ms':1000})
        self.assertEqual(audit['state'],'incomplete')
        self.assertIn(0,audit['ambiguous_settlements'])

    def test_nonzero_inventory_conflict_is_strictly_unknown(self):
        spec=self.spec();state=initial_state(spec)
        _fill(state,Decimal(1),Decimal(100),Decimal(0),HOUR-1000)
        reduce_event(state,spec,self.funding(stamp=HOUR+75,coefficient='-0.1'))
        reduce_event(state,spec,self.funding(stamp=HOUR+75,coefficient='-0.100001'))
        audit=funding_coverage(state,spec,{'start_ms':HOUR,'end_ms':HOUR+1000})
        self.assertEqual(audit['state'],'incomplete')
        self.assertIn('conflicting_funding_settlement_coefficients',audit['diagnostics'])
        self.assertIn('conflicting_funding_settlement_coefficients',state['diagnostics'])

    def test_risk_stop_on_partial_ledger_is_labeled_funding_uncertainty(self):
        spec=self.spec();spec['max_exposure']['max_drawdown_usdc']='1'
        state=initial_state(spec);state['paper_funding_started_ms']=0
        _fill(state,Decimal(1),Decimal(100),Decimal(0),100)
        reduce_event(state,spec,{'id':'adverse','kind':'bbo','event_ms':1100,'received_ms':1100,
            'session':'s','bid':'80','ask':'80.1','bid_size':'100','ask_size':'100'})
        self.assertTrue(state['risk_halted'])
        self.assertIn('risk_drawdown_with_unknown_funding',state['diagnostics'])
        self.assertNotIn('risk_drawdown_limit',state['diagnostics'])
        self.assertEqual(state['position'],'1')

    def test_round_trip_in_clock_interval_cannot_claim_zero_cost(self):
        spec=self.spec();state=initial_state(spec)
        _fill(state,Decimal(1),Decimal(100),Decimal(0),20)
        _fill(state,Decimal(-1),Decimal(100),Decimal(0),40)
        reduce_event(state,spec,self.funding())
        audit=funding_coverage(state,spec,{'start_ms':0,'end_ms':1000})
        self.assertEqual(audit['state'],'incomplete')
        self.assertEqual(audit['ambiguous_settlements'],[0])


if __name__=='__main__':unittest.main()
