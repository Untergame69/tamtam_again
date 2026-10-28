"""Settlement coverage follows our inventory, not the source's funding count."""
from decimal import Decimal
import unittest

from tamtam_again.engine import funding_coverage, initial_state, reduce_event, replay, _fill
from tamtam_again.recipe import synthetic_spec, synthetic_plan
from tamtam_again.validation import promotion, classify_evaluation_failures


class FundingCompletenessTests(unittest.TestCase):
    def spec(self):
        spec=synthetic_spec()
        spec['execution']['funding_observation_interval_ms']=1000
        spec['horizon_ms']=10000
        return spec

    def funding(self, stamp, received=None, coefficient='-0.1', identity=None):
        return {'id':identity or 'funding:'+str(stamp),'kind':'funding',
                'event_ms':stamp,'received_ms':received if received is not None else stamp,
                'unit_funding_usdc':coefficient,'provenance':'fixture_settled_coefficient'}

    def state(self):
        spec=self.spec();return spec,initial_state(spec)

    def test_first_observed_then_missing_settlement_is_incomplete(self):
        spec,state=self.state()
        _fill(state,Decimal(1),Decimal(100),Decimal(0),100)
        reduce_event(state,spec,self.funding(1000))
        audit=funding_coverage(state,spec,{'start_ms':0,'end_ms':2500})
        self.assertEqual(state['funding_events'],1)
        self.assertEqual(audit['required_settlements'],[1000,2000])
        self.assertEqual(audit['missing_settlements'],[2000])
        self.assertEqual(audit['state'],'incomplete')

    def test_source_flat_does_not_prove_our_funding_is_zero(self):
        spec,state=self.state()
        # Source funding carries only its first settlement, then source is flat.
        # Our independent execution ledger retains an open position.
        _fill(state,Decimal(2),Decimal(100),Decimal(0),100)
        state['leader_target']='2'
        reduce_event(state,spec,self.funding(1000))
        reduce_event(state,spec,{'id':'source-flat','kind':'leader_fill',
            'event_ms':1500,'received_ms':1500,'is_snapshot':False,'delta':'-2'})
        self.assertEqual(state['position'],'2')
        self.assertEqual(state['leader_target'],'0')
        self.assertEqual(state['pending'][0]['target'],'0')
        audit=funding_coverage(state,spec,{'start_ms':0,'end_ms':2500})
        self.assertEqual(audit['missing_settlements'],[2000])

    def test_delayed_settlement_after_our_close_uses_historic_inventory(self):
        spec,state=self.state()
        _fill(state,Decimal(2),Decimal(100),Decimal(0),100)
        _fill(state,Decimal(-2),Decimal(100),Decimal(0),1200)
        reduce_event(state,spec,self.funding(1000,received=1500))
        self.assertEqual(state['position'],'0')
        self.assertEqual(Decimal(state['funding']),Decimal('-0.2'))
        self.assertEqual(state['funding_settlements']['1000']['inventory_at_settlement'],'2')
        self.assertEqual(funding_coverage(state,spec,{'start_ms':0,'end_ms':2500})['state'],'complete')

    def test_no_exposure_at_settlements_proves_zero_without_fake_event(self):
        spec,state=self.state()
        _fill(state,Decimal(1),Decimal(100),Decimal(0),100)
        _fill(state,Decimal(-1),Decimal(100),Decimal(0),900)
        audit=funding_coverage(state,spec,{'start_ms':0,'end_ms':2500})
        self.assertEqual(audit['state'],'complete')
        self.assertEqual(audit['required_settlements'],[])
        self.assertEqual(audit['zero_exposure_settlements'],3)
        self.assertEqual(state['funding_events'],0)
        self.assertEqual(state['funding'],'0')
        self.assertEqual(state['funding_settlements'],{})

    def test_zero_exposure_funding_gate_needs_no_fabricated_settlement(self):
        spec=self.spec()
        events=[{'id':'c','kind':'connection','event_ms':0,'received_ms':0,'session':'s','connected':True},
                {'id':'q','kind':'bbo','event_ms':10,'received_ms':10,'session':'s',
                 'bid':'100','ask':'100.1','bid_size':'100','ask_size':'100'}]
        metric=replay(spec,events,block_ms=1000,observation_window={'start_ms':0,'end_ms':2500})['metrics']
        criteria=synthetic_plan()['criteria'];criteria['require_funding']=True
        self.assertEqual(metric['funding_events'],0)
        self.assertEqual(metric['funding_coverage']['state'],'complete')
        self.assertNotIn('funding_observed',promotion(metric,metric,criteria,funding_completeness_required=True))

    def test_exact_ms_execution_is_unknown_not_invented_settlement_order(self):
        spec,state=self.state()
        _fill(state,Decimal(1),Decimal(100),Decimal(0),1000)
        reduce_event(state,spec,self.funding(1000,received=1100))
        audit=funding_coverage(state,spec,{'start_ms':0,'end_ms':1500})
        self.assertEqual(audit['ambiguous_settlements'],[1000])
        self.assertEqual(audit['state'],'incomplete')
        self.assertIsNone(state['funding_settlements']['1000']['inventory_at_settlement'])
        self.assertEqual(state['funding'],'0')

    def test_duplicate_coefficient_is_not_debited_twice_and_conflict_is_unknown(self):
        spec,state=self.state()
        _fill(state,Decimal(1),Decimal(100),Decimal(0),100)
        reduce_event(state,spec,self.funding(1000,received=1100))
        reduce_event(state,spec,self.funding(1000,received=1200,identity='same-settlement-new-id'))
        self.assertEqual(Decimal(state['funding']),Decimal('-0.1'))
        self.assertEqual(state['funding_events'],1)
        reduce_event(state,spec,self.funding(1000,received=1300,identity='conflict',coefficient='-0.2'))
        self.assertEqual(funding_coverage(state,spec,{'start_ms':0,'end_ms':1500})['state'],'incomplete')

    def test_legacy_interval_unknown_and_fixed_window_covers_time_after_last_receipt(self):
        spec,state=self.state()
        _fill(state,Decimal(1),Decimal(100),Decimal(0),100)
        reduce_event(state,spec,self.funding(1000))
        audit=funding_coverage(state,spec,{'start_ms':0,'end_ms':3500})
        self.assertEqual(audit['missing_settlements'],[2000,3000])
        del spec['execution']['funding_observation_interval_ms']
        self.assertEqual(funding_coverage(state,spec,{'start_ms':0,'end_ms':3500})['state'],'unknown')

    def test_replay_and_both_scenarios_gate_partial_funding_as_technical(self):
        spec=self.spec()
        events=[{'id':'c','kind':'connection','event_ms':0,'received_ms':0,'session':'s','connected':True},
                {'id':'q','kind':'bbo','event_ms':10,'received_ms':10,'session':'s',
                 'bid':'100','ask':'100.1','bid_size':'100','ask_size':'100'},
                {'id':'signal','kind':'leader_fill','event_ms':20,'received_ms':20,'is_snapshot':False,'delta':'1'},
                {'id':'execute','kind':'timer','event_ms':30,'received_ms':30},self.funding(1000),
                {'id':'q2','kind':'bbo','event_ms':2400,'received_ms':2400,'session':'s',
                 'bid':'100','ask':'100.1','bid_size':'100','ask_size':'100'}]
        result=replay(spec,events,block_ms=1000,observation_window={'start_ms':0,'end_ms':2500})
        metric=result['metrics']
        self.assertEqual(metric['funding_events'],1)
        self.assertEqual(metric['funding_coverage']['missing_settlements'],[2000])
        self.assertIsNone(metric['benchmark_matched_size_buy_hold_pnl'])
        criteria=synthetic_plan()['criteria'];criteria['require_funding']=True
        failures=promotion(metric,metric,criteria,funding_completeness_required=True)
        self.assertIn('funding_observed',failures)
        self.assertEqual(classify_evaluation_failures({'status':'failed','failures':failures,'metrics':metric})['state'], 'technical_required')
        complete={**metric,'funding_coverage':{'state':'complete'}}
        self.assertIn('funding_observed',promotion(complete,metric,criteria,funding_completeness_required=True))
        self.assertNotIn('funding_observed',promotion(complete,complete,criteria,funding_completeness_required=True))


class FundingEvaluationIntegrationTests(unittest.TestCase):
    def test_real_evaluation_legacy_unknown_and_fixed_interval_are_technical(self):
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        from tamtam_again.storage import Store
        from tamtam_again.recipe import synthetic_events
        from tamtam_again.validation import create_plan, register_variant, get_variant, evaluate
        for interval in (None,100):
            with self.subTest(interval=interval), tempfile.TemporaryDirectory() as directory:
                store=Store(Path(directory)/'fixture.sqlite3')
                plan=synthetic_plan();plan['criteria']['require_funding']=True
                plan_id=create_plan(store,plan)['plan_id']
                spec=synthetic_spec()
                if interval is not None:
                    spec['execution']['funding_observation_interval_ms']=interval
                variant=register_variant(store,plan_id,spec)['variant_id']
                row,spec,plan=get_variant(store,variant)
                events=synthetic_events(10000)
                events.append({'id':'one-settlement','kind':'funding','event_ms':10300,
                               'received_ms':10300,'unit_funding_usdc':'0.001'})
                # Temporary synthetic fixtures exercise the real dispatch branch;
                # no live archive, provider, or real validation data is touched.
                with patch('tamtam_again.validation.get_variant',return_value=({**dict(row),'synthetic':0},spec,plan)):
                    result=evaluate(store,variant,'comparison',events,provenance='local_archive')
                    self.assertEqual(result['failure_classification']['state'],'technical_required')
                    self.assertIn('funding_observed',result['failures'])
                    coverage=result['metrics']['funding_coverage']
                    if interval:
                        self.assertEqual(coverage['observation_window'],plan['comparison'])
                    self.assertEqual(coverage['state'],'incomplete' if interval else 'unknown')
                    archived=store.connection.execute('select result_json from validation_evaluations').fetchone()[0]
                    self.assertEqual(evaluate(store,variant,'comparison',events,provenance='local_archive'),result)
                    self.assertEqual(store.connection.execute('select result_json from validation_evaluations').fetchone()[0],archived)
                store.close()


if __name__=='__main__':unittest.main()
