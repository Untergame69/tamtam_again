from __future__ import annotations

from datetime import datetime, timezone
import tempfile
import unittest
from pathlib import Path

from tamtam_again.engine import initial_state, number, quote_status, reduce_event
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


def event(id,kind,t,**extra):
    return {'id':id,'kind':kind,'event_ms':t,'received_ms':t,**extra}


class PaperEngineV3Tests(unittest.TestCase):
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
