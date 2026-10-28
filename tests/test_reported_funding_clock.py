"""Explicit reported-hour clock; no timestamp tolerance or rate approximation."""
from decimal import Decimal
import unittest
from tamtam_again.engine import initial_state, _fill, reduce_event, funding_coverage, validate_spec, hold_benchmark
from tamtam_again.recipe import synthetic_spec

HOUR=3_600_000


class ReportedFundingClockTests(unittest.TestCase):
    def setup_state(self):
        spec=synthetic_spec();spec['execution'].update(funding_observation_interval_ms=HOUR,
            funding_settlement_clock='reported_hour_with_inventory_invariance_v1')
        return spec,initial_state(spec)

    def event(self,stamp,*,coefficient='-0.1',identity=None):
        return {'id':identity or str(stamp),'kind':'funding','event_ms':stamp,'received_ms':stamp+100,
                'unit_funding_usdc':coefficient}

    def audit(self,state,spec):return funding_coverage(state,spec,{'start_ms':HOUR,'end_ms':HOUR+1000})

    def test_reported_offset_is_retained_and_invariant_inventory_is_used(self):
        spec,state=self.setup_state();_fill(state,Decimal(2),Decimal(100),Decimal(0),HOUR-100)
        reduce_event(state,spec,self.event(HOUR+75))
        audit=self.audit(state,spec)
        self.assertEqual(audit['state'],'complete');self.assertEqual(audit['required_settlements'],[HOUR])
        self.assertEqual(audit['reported_settlements'],[{'scheduled_ms':HOUR,'reported_ms':HOUR+75,'offset_ms':75}])
        self.assertEqual(Decimal(state['funding']),Decimal('-0.2'))
        self.assertEqual(state['funding_settlements'][str(HOUR+75)]['reported_offset_ms'],75)

    def test_round_trip_anywhere_in_closed_clock_interval_remains_unknown(self):
        for opening,closing in ((HOUR,HOUR+40),(HOUR+20,HOUR+40),(HOUR+20,HOUR+75)):
            with self.subTest(opening=opening,closing=closing):
                spec,state=self.setup_state()
                _fill(state,Decimal(1),Decimal(100),Decimal(0),opening)
                _fill(state,Decimal(-1),Decimal(100),Decimal(0),closing)
                reduce_event(state,spec,self.event(HOUR+75))
                audit=self.audit(state,spec)
                self.assertEqual(audit['state'],'incomplete')
                self.assertEqual(audit['ambiguous_settlements'],[HOUR])
                self.assertEqual(state['funding'],'0')

    def test_two_reported_times_in_same_slot_cannot_charge_twice(self):
        spec,state=self.setup_state();_fill(state,Decimal(1),Decimal(100),Decimal(0),HOUR-100)
        reduce_event(state,spec,self.event(HOUR+75));reduce_event(state,spec,self.event(HOUR+86))
        audit=self.audit(state,spec)
        self.assertEqual(audit['state'],'incomplete')
        self.assertEqual(audit['multiple_reported_time_slots'],[HOUR])
        self.assertEqual(Decimal(state['funding']),Decimal('-0.1'))

    def test_missing_time_with_later_bucket_trade_cannot_invent_zero(self):
        spec,state=self.setup_state();_fill(state,Decimal(1),Decimal(100),Decimal(0),HOUR+300)
        _fill(state,Decimal(-1),Decimal(100),Decimal(0),HOUR+500)
        audit=self.audit(state,spec)
        self.assertEqual(audit['state'],'incomplete')
        self.assertEqual(audit['unresolved_report_time_slots'],[HOUR])
        empty=initial_state(spec)
        self.assertEqual(self.audit(empty,spec)['state'],'complete')
        self.assertEqual(empty['funding_events'],0)

    def test_mid_hour_window_does_not_drop_unresolved_first_bucket(self):
        spec,state=self.setup_state();_fill(state,Decimal(1),Decimal(100),Decimal(0),HOUR+300)
        audit=funding_coverage(state,spec,{'start_ms':HOUR+200,'end_ms':HOUR+1000})
        self.assertEqual(audit['unresolved_report_time_slots'],[HOUR])

    def test_coefficient_disagreement_is_still_exact_unknown(self):
        spec,state=self.setup_state();_fill(state,Decimal(1),Decimal(100),Decimal(0),HOUR-100)
        reduce_event(state,spec,self.event(HOUR+75))
        reduce_event(state,spec,self.event(HOUR+75,coefficient='-0.1000001',identity='different-print'))
        self.assertIn('conflicting_funding_settlement_coefficients',state['diagnostics'])
        self.assertEqual(self.audit(state,spec)['state'],'incomplete')

    def test_clock_is_opt_in_and_requires_hourly_contract(self):
        spec,state=self.setup_state();del spec['execution']['funding_settlement_clock']
        reduce_event(state,spec,self.event(HOUR+75))
        self.assertEqual(self.audit(state,spec)['off_boundary_settlements'],[HOUR+75])
        spec['execution']['funding_settlement_clock']='reported_hour_with_inventory_invariance_v1'
        spec['execution']['funding_observation_interval_ms']=1000
        with self.assertRaisesRegex(ValueError,'hourly'):validate_spec(spec)

    def test_benchmark_requires_same_reported_clock_and_invariant_boundaries(self):
        spec,_=self.setup_state()
        events=[self.event(75),self.event(HOUR+75),
            {'id':'first','kind':'bbo','event_ms':1000,'received_ms':1000,'bid':'100','ask':'100.1','ask_size':'100'},
            {'id':'signal','kind':'leader_fill','event_ms':1100,'received_ms':1100,'is_snapshot':False,'delta':'1'},
            {'id':'last','kind':'bbo','event_ms':HOUR+1000,'received_ms':HOUR+1000,'bid':'101','ask':'101.1','ask_size':'100'}]
        self.assertIsNotNone(hold_benchmark(spec,events,Decimal(1)))
        events[-1].update(event_ms=HOUR+40,received_ms=HOUR+40)
        self.assertIsNone(hold_benchmark(spec,events,Decimal(1)))


if __name__=='__main__':unittest.main()
