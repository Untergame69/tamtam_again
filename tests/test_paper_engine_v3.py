from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import tempfile
import unittest
from pathlib import Path

from tamtam_again.engine import initial_state, metrics, number, quote_status, reduce_event
from tamtam_again.experimental_paper import _action, execution_diagnosis
from tamtam_again.paper import archive_events
from tamtam_again.recipe import synthetic_spec
from tamtam_again.storage import Store
from tamtam_again.validation import now_ms


ADDRESS='0xa880d6cc607a05ea617307ab3b0d335e8d8424ee'


def spec_v3():
    s=synthetic_spec()
    s.update(engine='single_perp_v3',market='HYPE',latency_ms=5_000,horizon_ms=120_000)
    s['sizing']['scale']='0.001'
    s['max_exposure'].update(notional_usdc='100',max_drawdown_usdc='10',max_leverage='1')
    s['fees']['taker_bps']='4.5';s['slippage']['bps']='5'
    s['execution'].update(heartbeat_timeout_ms=65_000,unknown_quote_max_age_ms=1_000,
        max_quote_age_ms=1_000,paper_tick_target_ms=5_000,order_ttl_ms=10_000,
        displayed_size_fraction='0.1',funding_interval_ms=3_600_000,
        market_rules={'version':1,'instrument':'HYPE','currency':'USDC','available_ms':0,
            'evidence_refs':['fixture:meta','fixture:rules'],'sz_decimals':2,
            'minimum_order_usdc':'10','max_leverage':'10'})
    return s


def spec_v4():
    s=spec_v3()
    s['data_sources']=list(dict.fromkeys([*s['data_sources'],'l2Book']))
    s['execution']['quote_evidence_contract']='bbo_or_l2book_v1'
    return s


def event(id,kind,t,**extra):
    return {'id':id,'kind':kind,'event_ms':t,'received_ms':t,**extra}


class PaperEngineV3Tests(unittest.TestCase):
    def test_v4_quote_requires_recent_receipt_prior_archive_availability_and_same_connection(self):
        s=spec_v4();state=initial_state(s)
        state.update(connected=True,session='s1',healthy_at_ms=2_500,
            quote={'received_ms':2_500,'source_received_ms':2_000,'available_ms':2_500,
                   'event_ms':2_000,'session':'s1','source':'l2Book','bid':'100','ask':'100.1',
                   'bid_size':'10','ask_size':'11'})
        self.assertEqual(quote_status(state,3_000,s['execution']),'continuous')
        self.assertEqual(quote_status(state,3_001,s['execution']),'stale')
        state['quote']['available_ms']=3_000
        self.assertEqual(quote_status(state,3_000,s['execution']),'unavailable')
        state['quote'].update(available_ms=2_500,session='other')
        self.assertNotEqual(quote_status(state,3_000,s['execution']),'continuous')

    def test_v4_mixed_bbo_l2_entry_exit_records_causal_opportunities(self):
        s=spec_v4();state=initial_state(s)
        events=[
            event('conn','connection',1_000,session='s1',connected=True),
            event('health','heartbeat',1_005,session='s1'),
            event('signal-in','leader_fill',1_020,session='s1',is_snapshot=False,delta='1000'),
            {**event('l2-entry','l2book',5_700,session='s1',source='l2Book',bid='100',ask='100.1',bid_size='500',ask_size='500'),'available_ms':5_700},
            event('entry-execution','timer',6_021),
            event('signal-out','leader_fill',6_100,session='s1',is_snapshot=False,delta='-1000'),
            {**event('bbo-exit','bbo',10_850,session='s1',source='bbo',bid='100.2',ask='100.3',bid_size='500',ask_size='500'),'available_ms':10_850},
            event('exit-execution','timer',11_101),
        ]
        for item in events:reduce_event(state,s,item)
        self.assertEqual(len(state['fills']),2)
        self.assertEqual(number(state['position']),0)
        self.assertEqual([x['quote_source'] for x in state['execution_opportunities']],['l2Book','bbo'])
        self.assertTrue(all(x['eligible'] for x in state['execution_opportunities']))
        self.assertEqual([x['outcome'] for x in state['execution_opportunities']],['executed','executed'])
        self.assertEqual([(x['position_before'],x['position_after']) for x in state['execution_opportunities']],
                         [('0','0.99'),('0.99','0.00')])

    def test_v4_stale_priority_exit_preserves_residual_and_records_miss(self):
        s=spec_v4();state=initial_state(s)
        state.update(session='s1',connected=True,healthy_at_ms=1_000,position='0.5',average_price='100',
            pending=[{'target':'0','due_ms':1_010,'expires_ms':1_020,'intent':'horizon_exit','priority':100,
                      'reduce_only':True,'decision_ms':1_000}],
            quote={'received_ms':1_000,'source_received_ms':1_000,'available_ms':1_000,'event_ms':1_000,
                   'session':'s1','source':'l2Book','bid':'100','ask':'100.1','bid_size':'500','ask_size':'500'})
        reduce_event(state,s,event('expired-close','timer',1_021))
        self.assertEqual(state['position'],'0.5')
        self.assertIn('priority_exit_unresolved_position',state['diagnostics'])
        self.assertEqual(state['execution_opportunities'][-1]['outcome'],'missed')
        self.assertEqual(state['execution_opportunities'][-1]['reason'],'order_ttl_expired')

    def test_opt_in_reduction_policy_closes_instead_of_leaving_subminimum_residual(self):
        s=spec_v3();s['execution']['small_residual_policy']='avoid_uncloseable_residual_v1'
        state=initial_state(s)
        state.update(connected=True,session='s1',healthy_at_ms=1_000,position='0.29',average_price='84',
            pending=[{'target':'0.05','due_ms':1_900,'expires_ms':5_000,'intent':'reduction',
                      'priority':50,'reduce_only':True,'decision_ms':1_800}],
            quote={'received_ms':1_800,'event_ms':1_800,'session':'s1','bid':'84','ask':'84.01',
                   'bid_size':'1000','ask_size':'1000'})
        reduce_event(state,s,event('reduce','timer',2_000))
        self.assertEqual(number(state['position']),0)
        self.assertEqual(state['fills'][0]['size'],'-0.29')
        self.assertEqual(state['pending'],[])

    def test_opt_in_policy_selects_full_close_before_partial_fill_and_preserves_actual_depth(self):
        s=spec_v3();s['execution']['small_residual_policy']='avoid_uncloseable_residual_v1'
        s['execution']['quote_evidence_contract']='bbo_or_l2book_v1';s['execution']['max_quote_age_ms']=1000
        s['data_sources']=list(set(s['data_sources'])|{'bbo','l2Book'})
        state=initial_state(s)
        state.update(connected=True,session='s1',healthy_at_ms=1_000,position='0.29',average_price='84',
            pending=[{'target':'0.05','due_ms':1_900,'expires_ms':5_000,'intent':'reduction',
                      'priority':50,'reduce_only':True,'decision_ms':1_800}],
            quote={'received_ms':1_800,'source_received_ms':1_800,'available_ms':1_800,'event_ms':1_800,'session':'s1','source':'l2Book','bid':'84','ask':'84.01',
                   'bid_size':'2','ask_size':'1000'})
        reduce_event(state,s,event('reduce','timer',2_000))
        # The policy selects a full-close instruction before the simulator sees
        # depth. Actual visible liquidity produces a real partial fill; no cap
        # is applied afterward to force a preferred residual.
        self.assertEqual(state['fills'][0]['size'],'-0.20')
        self.assertEqual(number(state['position']),Decimal('0.09'))
        self.assertEqual(len(state['pending']),1)
        self.assertEqual(state['pending'][0]['target'],'0.05')
        opportunity=state['execution_opportunities'][-1]
        self.assertEqual(opportunity['order_size'],'-0.29')
        self.assertEqual(opportunity['fill_size'],'-0.20')
        self.assertEqual(opportunity['outcome'],'partial')
        self.assertEqual(opportunity['order_selection'],'full_close_selected_to_avoid_subminimum_residual')

    def test_opt_in_reduction_policy_preserves_already_subminimum_position(self):
        s=spec_v3();s['execution']['small_residual_policy']='avoid_uncloseable_residual_v1'
        state=initial_state(s)
        state.update(connected=True,session='s1',healthy_at_ms=1_000,position='0.05',average_price='84',
            pending=[{'target':'0','due_ms':1_900,'expires_ms':5_000,'intent':'horizon_exit',
                      'priority':100,'reduce_only':True,'decision_ms':1_800}],
            quote={'received_ms':1_800,'event_ms':1_800,'session':'s1','bid':'84','ask':'84.01',
                   'bid_size':'1000','ask_size':'1000'})
        reduce_event(state,s,event('reduce','timer',2_000))
        self.assertEqual(number(state['position']),Decimal('0.05'))
        self.assertEqual(state['fills'],[])
        self.assertEqual(state['pending'][0]['last_wait_reason'],'priority_exit_below_venue_minimum')

    def test_opt_in_policy_does_not_select_nonadmissible_full_close(self):
        s=spec_v3();s['execution']['small_residual_policy']='avoid_uncloseable_residual_v1'
        state=initial_state(s)
        state.update(connected=True,session='s1',healthy_at_ms=1_000,position='0.09',average_price='84',
            pending=[{'target':'0.05','due_ms':1_900,'expires_ms':5_000,'intent':'reduction',
                      'priority':50,'reduce_only':True,'decision_ms':1_800}],
            quote={'received_ms':1_800,'event_ms':1_800,'session':'s1','bid':'84','ask':'84.01',
                   'bid_size':'1000','ask_size':'1000'})
        reduce_event(state,s,event('reduce','timer',2_000))
        self.assertEqual(state['fills'],[])
        self.assertEqual(number(state['position']),Decimal('0.09'))
        self.assertEqual(state['nonexecution_reasons']['reduce_only_adjustment_below_venue_minimum'],1)

    def test_small_residual_policy_is_opt_in_and_does_not_rewrite_legacy_specs(self):
        s=spec_v3();state=initial_state(s)
        state.update(connected=True,session='s1',healthy_at_ms=1_000,position='0.29',average_price='84',
            pending=[{'target':'0.05','due_ms':1_900,'expires_ms':5_000,'intent':'reduction',
                      'priority':50,'reduce_only':True,'decision_ms':1_800}],
            quote={'received_ms':1_800,'event_ms':1_800,'session':'s1','bid':'84','ask':'84.01',
                   'bid_size':'1000','ask_size':'1000'})
        reduce_event(state,s,event('reduce','timer',2_000))
        self.assertEqual(state['fills'][0]['size'],'-0.24')
        self.assertEqual(number(state['position']),Decimal('0.05'))

    def test_v4_zero_rounded_entry_is_counted_as_missed_with_reason(self):
        s=spec_v4();state=initial_state(s)
        state.update(session='s1',connected=True,healthy_at_ms=2_000,
            quote={'received_ms':2_000,'source_received_ms':2_000,'available_ms':2_000,
                   'event_ms':2_000,'session':'s1','source':'bbo','bid':'100','ask':'100.1',
                   'bid_size':'100','ask_size':'100'},
            pending=[{'target':'0.004','due_ms':2_010,'expires_ms':12_010,
                      'intent':'signal_target','priority':10,'reduce_only':False,'decision_ms':2_000}])
        reduce_event(state,s,event('rounded-zero','timer',2_011))
        self.assertEqual(state['missed_orders'],1)
        self.assertEqual(state['nonexecution_reasons']['zero_adjustment_after_rounding'],1)
        self.assertEqual(state['execution_opportunities'][-1]['outcome'],'missed')

    def test_archive_adapter_reads_l2_top_prices_sizes_and_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'l2.sqlite3');receipt=now_ms()
            stamp=datetime.fromtimestamp(receipt/1000,timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
            store.save_observation(network='hyperliquid-mainnet',source='hyperliquid-websocket-v1',
                entity_type='market',entity_id='HYPE',endpoint='l2Book',requested_at=stamp,
                payload={'events':[{'received_at':stamp,'message':{'channel':'l2Book',
                    '_stream':{'connection_id':'c1'},'data':{'coin':'HYPE','fast':True,'time':receipt,
                    'levels':[[{'px':'100','sz':'12'}],[{'px':'100.1','sz':'9'}]]}}}]})
            events,_=archive_events(store,'hyperliquid-mainnet',ADDRESS,'HYPE',receipt-1_000,receipt+2_000,
                                    include_l2book=True)
            l2=next(x for x in events if x['kind']=='l2book')
            self.assertEqual((l2['bid'],l2['ask'],l2['bid_size'],l2['ask_size']),('100','100.1','12','9'))
            self.assertEqual(l2['received_ms'],receipt)
            self.assertEqual(l2['session'],'c1')
            store.close()

    def test_actual_quote_receipt_age_is_not_rewritten_to_processing_time(self):
        s=spec_v3();state=initial_state(s)
        reduce_event(state,s,event('conn','connection',1_000,session='s1',connected=True))
        reduce_event(state,s,event('bbo','bbo',1_010,session='s1',bid='100',ask='100.1',bid_size='100',ask_size='100'),stress=number(1))
        # A delayed processing receipt can be causally later, but the quote stays
        # ten seconds old and cannot pass the declared one-second age bound.
        reduce_event(state,s,{**event('late-health','heartbeat',10_020,session='s1'),'available_ms':10_020})
        self.assertEqual(state['quote']['received_ms'],1_010)
        self.assertEqual(state['quote']['processed_ms'],1_010)
        self.assertEqual(quote_status(state,10_020,s['execution']),'stale')
        reduce_event(state,s,{**event('fresh-bbo','bbo',10_100,session='s1',bid='100',ask='100.1',bid_size='100',ask_size='100'),'available_ms':10_100})
        self.assertEqual(state['quote']['received_ms'],10_100)
        self.assertEqual(quote_status(state,10_600,s['execution']),'continuous')

    def test_frequent_signals_cannot_replace_priority_horizon_exit(self):
        s=spec_v3();state=initial_state(s)
        events=[
            event('conn','connection',1_000,session='s1',connected=True),
            event('bbo0','bbo',1_010,session='s1',bid='100',ask='100.1',bid_size='100',ask_size='100'),
            event('hb0','heartbeat',1_020,session='s1'),
            event('entry','leader_fill',1_030,session='s1',is_snapshot=False,delta='1000'),
            event('wait1','timer',6_031),
            event('bbo1','bbo',6_040,session='s1',bid='100',ask='100.1',bid_size='100',ask_size='100'),
            event('hb1','heartbeat',6_041,session='s1'),
            event('execute-fresh','timer',6_042),
        ]
        for e in events:reduce_event(state,s,e)
        self.assertEqual(number(state['position']),number('0.99'))
        self.assertEqual(len(state['fills']),1)
        # A subsequent leader increase then reduction then increase must leave
        # the stronger reduction intent intact while the position is open.
        reduce_event(state,s,event('add','leader_fill',7_000,session='s1',is_snapshot=False,delta='1000'))
        reduce_event(state,s,event('reduce','leader_fill',7_010,session='s1',is_snapshot=False,delta='-1500'))
        exit_order=state['pending'][0]
        self.assertTrue(exit_order['reduce_only'])
        self.assertEqual(exit_order['intent'],'reduction')
        target=exit_order['target']
        reduce_event(state,s,event('increase-again','leader_fill',7_020,session='s1',is_snapshot=False,delta='1000'))
        self.assertEqual(state['pending'][0]['target'],target)
        self.assertEqual(state['pending'][0]['intent'],'reduction')
        # Force an opened position past its declared horizon; an exit takes
        # priority over the frequent subsequent live fills.
        state['opened_ms']=1_000
        reduce_event(state,s,event('horizon','leader_fill',121_001,session='s1',is_snapshot=False,delta='1000'))
        self.assertEqual(state['pending'][0]['target'],'0')
        self.assertEqual(state['pending'][0]['intent'],'horizon_exit')
        self.assertTrue(state['pending'][0]['reduce_only'])
        self.assertEqual(number(state['position']),number('0.99'))

    def test_funding_gate_allows_reductions_and_rechecks_delayed_increases(self):
        s=spec_v3();state=initial_state(s)
        state.update(session='s1',connected=True,healthy_at_ms=3_599_800,position='1',
                     average_price='100',opened_ms=3_500_000,leader_target='1',
                     quote={'received_ms':3_599_800,'source_received_ms':3_599_800,
                            'processed_ms':3_599_800,'event_ms':3_599_800,'session':'s1',
                            'bid':'100','ask':'100.1','bid_size':'100','ask_size':'100'})
        reduce_event(state,s,event('close-signal','leader_fill',3_599_900,session='s1',is_snapshot=False,delta='-1000'))
        self.assertEqual(state['pending'][0]['intent'],'reduction')
        self.assertNotIn('position_horizon_overlaps_funding_boundary',state['nonexecution_reasons'])

        entry=initial_state(s)
        entry.update(session='s2',connected=True,healthy_at_ms=3_599_900,
                     quote={'received_ms':3_599_900,'source_received_ms':3_599_900,
                            'processed_ms':3_599_900,'event_ms':3_599_900,'session':'s2',
                            'bid':'100','ask':'100.1','bid_size':'100','ask_size':'100'},
                     pending=[{'target':'1','due_ms':3_599_950,'expires_ms':3_610_000,
                               'intent':'signal_target','priority':10,'reduce_only':False}])
        reduce_event(entry,s,event('late-execution','timer',3_599_999))
        self.assertEqual(entry['fills'],[])
        self.assertEqual(entry['nonexecution_reasons']['position_horizon_overlaps_funding_boundary_at_execution'],1)
        self.assertEqual(entry['position'],'0')

    def test_unfilled_exit_keeps_position_and_records_uncertainty(self):
        s=spec_v3();state=initial_state(s)
        state.update(position='1',average_price='100',opened_ms=1_000,risk_halted=False,
                     pending=[{'target':'0','due_ms':1_010,'expires_ms':1_020,
                               'intent':'horizon_exit','priority':100,'reduce_only':True}],
                     session='s1',connected=False)
        reduce_event(state,s,event('expire-exit','timer',1_021))
        self.assertEqual(state['position'],'1')
        self.assertEqual(state['pending'],[])
        self.assertTrue(state['risk_halted'])
        self.assertIn('priority_exit_unresolved_position',state['diagnostics'])
        self.assertEqual(state['exit_uncertainties'][0]['position'],'1')

    def test_actual_zero_after_lot_rounding_does_not_suspend_for_missed_close(self):
        s=spec_v3();state=initial_state(s)
        state.update(position='-0.31',average_price='85.007475',opened_ms=1_000,
                     pending=[{'target':'-0.30685','due_ms':1_010,'expires_ms':1_020,
                               'intent':'reduction','priority':50,'reduce_only':True}])
        reduce_event(state,s,event('expired-small-adjustment','timer',1_021))
        self.assertEqual(state['position'],'-0.31')
        self.assertEqual(state['pending'],[])
        self.assertFalse(state['risk_halted'])
        self.assertNotIn('priority_exit_unresolved_position',state['diagnostics'])
        self.assertEqual(state['nonexecution_reasons']['reduce_only_adjustment_rounded_to_zero'],1)
        self.assertEqual(state['exit_uncertainties'],[])

    def test_below_minimum_adjustment_releases_priority_slot(self):
        s=spec_v3();state=initial_state(s)
        state.update(position='1',average_price='100',session='s1',connected=True,
                     healthy_at_ms=1_000,
                     quote={'received_ms':1_010,'source_received_ms':1_010,'processed_ms':1_010,
                            'event_ms':1_010,'session':'s1','bid':'100','ask':'100.1',
                            'bid_size':'100','ask_size':'100'},
                     pending=[{'target':'0.95','due_ms':1_015,'expires_ms':3_000,
                               'intent':'reduction','priority':50,'reduce_only':True}])
        reduce_event(state,s,event('below-min-adjustment','timer',1_020))
        self.assertEqual(state['pending'],[])
        self.assertEqual(state['position'],'1')
        self.assertEqual(state['nonexecution_reasons']['reduce_only_adjustment_below_venue_minimum'],1)
        self.assertFalse(state['risk_halted'])

    def test_mandatory_exit_keeps_priority_and_unresolved_diagnostic(self):
        s=spec_v3();state=initial_state(s)
        state.update(position='-0.31',average_price='85',opened_ms=1_000,
                     pending=[{'target':'0','due_ms':1_010,'expires_ms':1_020,
                               'intent':'horizon_exit','priority':100,'reduce_only':True}],
                     session='s1',connected=False)
        reduce_event(state,s,event('expired-mandatory-exit','timer',1_021))
        self.assertEqual(state['position'],'-0.31')
        self.assertTrue(state['risk_halted'])
        self.assertIn('priority_exit_unresolved_position',state['diagnostics'])
        self.assertEqual(state['exit_uncertainties'][0]['position'],'-0.31')

    def test_bounded_synthetic_entry_exit_report_path(self):
        s=spec_v3();state=initial_state(s)
        events=[
            event('conn','connection',1_000,session='s1',connected=True),
            event('bbo0','bbo',1_010,session='s1',bid='100',ask='100.1',bid_size='100',ask_size='100'),
            event('hb0','heartbeat',1_020,session='s1'),
            event('entry-signal','leader_fill',1_030,session='s1',is_snapshot=False,delta='1000'),
            event('bbo-entry','bbo',6_040,session='s1',bid='100',ask='100.1',bid_size='100',ask_size='100'),
            event('hb-entry','heartbeat',6_041,session='s1'),
            event('entry-execution','timer',6_042),
            event('exit-signal','leader_fill',6_050,session='s1',is_snapshot=False,delta='-1000'),
            event('bbo-exit','bbo',11_000,session='s1',bid='100.2',ask='100.3',bid_size='100',ask_size='100'),
            event('hb-exit','heartbeat',11_001,session='s1'),
            event('exit-execution','timer',11_051),
        ]
        for item in events:reduce_event(state,s,item)
        report=metrics(state,s,1_000)
        self.assertEqual(len(state['fills']),2)
        self.assertEqual(number(state['position']),0)
        self.assertTrue(report['flat_end'])
        self.assertEqual(report['fills'],2)
        self.assertEqual(report['fees'],str(number(state['fees'])))

    def test_diagnosis_separates_no_opportunity_slow_processing_and_parameter_mismatch(self):
        s=spec_v3();state=initial_state(s)
        no_op=execution_diagnosis(state,s)
        self.assertEqual(no_op['category'],'no_admissible_opportunity')
        state.update(signals_received=4,missed_orders=3,
                     nonexecution_reasons={'order_ttl_expired':3},
                     paper_runtime={'target_interval_ms':5000,'max_interval_ms':23000,
                                    'max_processing_ms':22000,'max_receipt_lag_ms_since_start':20000,
                                    'interval_ms':23000,'processing_ms':22000,'max_receipt_lag_ms':20000})
        slow=execution_diagnosis(state,s)
        self.assertEqual(slow['category'],'processing_or_collection_delay')
        self.assertEqual(slow['recommended_action'],'collect_data')
        state['paper_runtime'].update(interval_ms=4000,processing_ms=3000,max_receipt_lag_ms=500)
        mismatch=execution_diagnosis(state,s)
        self.assertEqual(mismatch['category'],'execution_parameters_incompatible')
        self.assertEqual(mismatch['recommended_action'],'propose_new_version')
        state['fills']=[{'size':'1'}]
        progress=execution_diagnosis(state,s)
        self.assertEqual(progress['recommended_action'],'continue')
        state['fills']=[]
        self.assertEqual(execution_diagnosis(state,s)['category'],'execution_parameters_incompatible')
        state['diagnostics']=['priority_exit_unresolved_position']
        unresolved=execution_diagnosis(state,s)
        self.assertEqual(unresolved['category'],'priority_exit_unresolved_position')
        self.assertEqual(unresolved['recommended_action'],'stop_and_reconcile')
        action,detail,status=_action({'status':'suspended'},state,{'drawdown_usdc':'0'},
                                     {'loss_limit_usdc':'10'},1,unresolved)
        self.assertEqual((action,status),('abandon','abandoned'))
        self.assertIn('position is preserved',detail)

    def test_archive_uses_observation_id_cursor_and_records_scan_profile(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'archive.sqlite3')
            try:
                center=now_ms()
                def stamp(ms):return datetime.fromtimestamp(ms/1000,timezone.utc).isoformat(timespec='milliseconds')
                def bbo_payload(ms):
                    return {'events':[{'received_at':stamp(ms),'message':{'channel':'bbo','data':{
                        'coin':'HYPE','time':ms,'bbo':[{'px':'100','sz':'10'},{'px':'100.1','sz':'10'}]}}}]}
                store.save_observation(network='hyperliquid-mainnet',source='hyperliquid-websocket-v1',
                    entity_type='market',entity_id='HYPE',endpoint='bbo',payload=bbo_payload(center-1000),requested_at=stamp(center-1000))
                cursor=store.connection.execute('select max(observation_id) from raw_observations').fetchone()[0]
                store.save_observation(network='hyperliquid-mainnet',source='hyperliquid-websocket-v1',
                    entity_type='market',entity_id='PUMP',endpoint='bbo',payload=bbo_payload(center),requested_at=stamp(center))
                store.save_observation(network='hyperliquid-mainnet',source='hyperliquid-websocket-v1',
                    entity_type='market',entity_id='HYPE',endpoint='bbo',payload=bbo_payload(center),requested_at=stamp(center))
                profile={}
                events,highest=archive_events(store,'hyperliquid-mainnet',ADDRESS,'HYPE',center-5000,center+5000,
                    after_observation_id=cursor,query_metrics=profile)
                self.assertEqual(len(events),1)
                self.assertEqual(events[0]['received_ms'],center)
                self.assertEqual(profile['rows'],1)
                self.assertIn('query_ms',profile)
                plan=list(store.connection.execute("explain query plan select * from raw_observations not indexed where observation_id>?",(cursor,)))
                self.assertIn('INTEGER PRIMARY KEY',plan[0][3])
                self.assertGreater(highest,cursor)
            finally:store.close()


if __name__=='__main__':unittest.main()
