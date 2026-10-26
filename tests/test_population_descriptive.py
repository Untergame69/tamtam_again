import hashlib
import json
import tempfile
import unittest
import zlib
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path

from tamtam_again.engine import canonical
from tamtam_again.population_descriptive import (prepare_candidate_market_detail,
    prepare_candidate_summary,prepare_inventory_execution_association,prepare_pilot_packet,
    _compact_repeated_reference_lists)
from tamtam_again.storage import Store
from scripts.prepare_43ad_local_resolution import _episode_table


class PopulationDescriptiveTests(unittest.TestCase):
    def test_reference_projection_reconstructs_full_evidence_without_changing_aggregates(self):
        from copy import deepcopy
        from tamtam_again.engine import fingerprint
        refs=['raw_observations:1#sha256:a','raw_observations:2#sha256:b','raw_observations:3#sha256:c']
        summary={'summary_fingerprint':'source-summary','evidence_refs':refs[:],
            'by_day':{'day1':{'fills':1000,'fee':'-5'},'day2':{'fills':2000,'fee':'2'}}}
        detail={'detail_fingerprint':'source-detail','evidence_refs':[refs[2],refs[0]],
            'fills':3000,'price_flow':'17.25'}
        packet={'evidence_refs':refs[:],'observations':{'descriptive_history_v1':deepcopy(summary),
            'market_execution_detail_v1':{'BTC':deepcopy(detail)}}}
        _compact_repeated_reference_lists(packet)
        for projected,original,field in [
                (packet['observations']['descriptive_history_v1'],summary,'summary_fingerprint'),
                (packet['observations']['market_execution_detail_v1']['BTC'],detail,'detail_fingerprint')]:
            recovered=[packet['evidence_refs'][i] for i in projected['evidence_ref_indices']]
            self.assertEqual(recovered,original['evidence_refs'])
            self.assertEqual(fingerprint(recovered),projected['reference_projection']['ordered_reference_fingerprint'])
            self.assertEqual(projected['source_'+field],original[field])
            for key,value in original.items():
                if key not in ('evidence_refs',field):self.assertEqual(projected[key],value)
        before=deepcopy(packet)
        _compact_repeated_reference_lists(packet)
        self.assertEqual(packet,before)
        self.assertEqual(packet['evidence_refs'],refs)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'summary.sqlite3')
        self.store.connection.execute('create table account_scope_reports '
            '(report_id text primary key,network text,address text,available_ms integer,payload_json text)')
        self.network='hyperliquid-mainnet';self.address='0x'+'1'*40;self.cutoff=200
        report={'address':self.address,'markets':['COIN'],'fills_requested_start_ms':90,
            'fills_requested_end_ms':180,'activity':{'observed_unique_fills':2,'window_seconds':90},
            'current_pass_behavior_profile':{'fills_observed':2,'evidence_refs':['population_attempts:test']}}
        self.store.connection.execute('insert into account_scope_reports values(?,?,?,?,?)',
            ('scope-test',self.network,self.address,190,json.dumps(report,sort_keys=True,separators=(',',':'))))
        self.store.connection.commit()

    def tearDown(self):
        self.store.close();self.tmp.cleanup()

    def _raw(self,observation_id,endpoint,payload,*,start=90,end=180,observed=190,complete=False,status='pagination_exhausted'):
        body=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        stamp=datetime.fromtimestamp(observed/1000,timezone.utc).isoformat(timespec='milliseconds')
        self.store.connection.execute('insert into raw_observations '
            '(observation_id,network,source,entity_type,entity_id,endpoint,request_json,requested_at,observed_at,'
            'window_start_ms,window_end_ms,record_count,complete,response_encoding,response_sha256,response_json,receipt_id) '
            'values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (observation_id,self.network,'hyperliquid-population-rest-v1','account',self.address,endpoint,
             json.dumps({'pagination_status':status},sort_keys=True),stamp,stamp,start,end,
             len(payload),int(complete),'zlib+json',hashlib.sha256(body.encode()).hexdigest(),
             zlib.compress(body.encode()),'receipt-'+str(observation_id)))
        self.store.connection.commit()

    def test_summary_and_enriched_packet_are_reproducible_and_keep_boundaries(self):
        fills=[
            {'coin':'COIN','tid':'open','time':100,'startPosition':'0','side':'B','sz':'1','px':'10','fee':'0.01','feeToken':'USDC','crossed':False},
            {'coin':'COIN','tid':'close','time':150,'startPosition':'1','side':'A','sz':'1','px':'12','fee':'-0.02','feeToken':'USDC','crossed':True},
            {'coin':'COIN','tid':'after','time':201,'startPosition':'0','side':'B','sz':'1','px':'9','fee':'0','feeToken':'USDC','crossed':False},
            {'coin':'COIN','tid':'conflict','time':120,'startPosition':'1','side':'A','sz':'0.1','px':'11','fee':'0','feeToken':'USDC','crossed':False},
        ]
        self._raw(1,'userFillsByTime',fills)
        self._raw(2,'userFillsByTime',[fills[0]])
        changed=dict(fills[3]);changed['px']='11.1'
        self._raw(3,'userFillsByTime',[changed])
        funding=[{'time':125,'hash':'fund-1','delta':{'coin':'COIN','usdc':'0.5','szi':'1'}}]
        self._raw(4,'userFunding',funding)

        summary=prepare_candidate_summary(self.store,self.network,self.address,cutoff_ms=self.cutoff,candidate='fixture')
        replay=prepare_candidate_summary(self.store,self.network,self.address,cutoff_ms=self.cutoff,candidate='fixture')
        self.assertEqual(summary['summary_fingerprint'],replay['summary_fingerprint'])
        self.assertEqual(summary['evidence_fingerprint'],replay['evidence_fingerprint'])
        self.assertEqual(summary['coverage']['fill_archive']['usable_unique_fill_count'],2)
        self.assertEqual(summary['coverage']['fill_archive']['duplicate_fill_instances'],2)
        self.assertEqual(summary['coverage']['fill_archive']['conflicting_fill_identity_count'],1)
        self.assertEqual(summary['coverage']['fill_archive']['records_after_cutoff_excluded'],1)
        market=summary['markets']['COIN']
        self.assertEqual(market['positions']['locally_reconstructible_flat_to_flat_episode_count'],1)
        self.assertEqual(market['price_result']['price_result_quote_units'],'2')
        self.assertEqual(market['signed_fees']['archive_fill_signed_fee_by_token']['USDC'],'-0.01')
        self.assertEqual(market['signed_fees']['bounded_episode_part_signed_fee_by_token']['USDC'],'-0.01')
        self.assertEqual(market['scope_membership'],'listed_by_available_scope_report')
        self.assertEqual(market['funding']['strictly_position_attributed_event_count'],1)
        self.assertEqual(market['funding']['strictly_position_attributed_amount_usdc'],'0.5')

        base={'schema_version':'fixture','network':self.network,'address':self.address,'available_ms':190,
            'research_input_fingerprint':'base','evidence_refs':['scope-test'],'observations':{}}
        item={'candidate':'fixture','rank':1,'research_interest':'fixture','observability':'partial',
            'paper_engine_compatibility':'unknown','question':'No inference in this test.',
            'descriptive_markets':['COIN']}
        packet=prepare_pilot_packet(self.store,base,candidate='fixture',item=item,pilot_id='p',
            policy_version='v',cutoff_ms=self.cutoff)
        packet2=prepare_pilot_packet(self.store,base,candidate='fixture',item=item,pilot_id='p',
            policy_version='v',cutoff_ms=self.cutoff)
        self.assertEqual(packet['fingerprint'],packet2['fingerprint'])
        self.assertEqual(base['evidence_refs'],['scope-test'])
        self.assertEqual(len(packet['evidence_refs']),len(set(packet['evidence_refs'])))
        self.assertTrue(any(ref.startswith('raw_observations:1#sha256:') for ref in packet['evidence_refs']))
        self.assertEqual(packet['observations']['market_execution_detail_v1']['COIN']['execution_activity']['fill_count'],2)
        self.assertTrue(packet['observations']['market_execution_detail_v1']['COIN']['detail_fingerprint'])

    def test_unreleased_reserved_window_is_rejected_before_observation_decode(self):
        self.store.connection.execute('create table validation_plans '
            '(plan_id text,network text,address text,plan_json text)')
        plan={'comparison':{'start_ms':150,'end_ms':250},'final':{'start_ms':300,'end_ms':400}}
        self.store.connection.execute('insert into validation_plans values(?,?,?,?)',
            ('reserved',self.network,self.address,json.dumps(plan)))
        self.store.connection.execute('insert into raw_observations '
            '(observation_id,network,source,entity_type,entity_id,endpoint,request_json,requested_at,observed_at,'
            'window_start_ms,window_end_ms,record_count,complete,response_encoding,response_sha256,response_json,receipt_id) '
            'values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (90,self.network,'hyperliquid-population-rest-v1','account',self.address,'userFillsByTime','{}',
             '1970-01-01T00:00:00Z','1970-01-01T00:00:00Z',90,180,1,0,'zlib+json','bad',b'not-zlib','r'))
        self.store.connection.commit()
        with self.assertRaisesRegex(PermissionError,'unreleased reserved period'):
            prepare_candidate_summary(self.store,self.network,self.address,cutoff_ms=self.cutoff)

    def test_market_detail_separates_execution_effect_and_bounded_results(self):
        fills=[
            {'coin':'COIN','tid':'open','time':100,'startPosition':'0','side':'B','sz':'1','px':'10','fee':'0.01','feeToken':'USDC','crossed':False},
            {'coin':'COIN','tid':'reduce','time':110,'startPosition':'1','side':'A','sz':'0.5','px':'12','fee':'-0.02','feeToken':'USDC','crossed':True},
            {'coin':'COIN','tid':'reverse','time':120,'startPosition':'0.5','side':'A','sz':'1','px':'12','fee':'-0.01','feeToken':'USDC','crossed':False},
            {'coin':'COIN','tid':'flat','time':130,'startPosition':'-0.5','side':'B','sz':'0.5','px':'13','fee':'0.02','feeToken':'USDC','crossed':True},
        ]
        self._raw(20,'userFillsByTime',fills)
        detail=prepare_candidate_market_detail(self.store,self.network,self.address,
            cutoff_ms=self.cutoff,market='COIN')
        replay=prepare_candidate_market_detail(self.store,self.network,self.address,
            cutoff_ms=self.cutoff,market='COIN')
        self.assertEqual(detail['detail_fingerprint'],replay['detail_fingerprint'])
        activity=detail['execution_activity']
        self.assertEqual(activity['position_increase_fill_count'],1)
        self.assertEqual(activity['position_reduction_fill_count'],2)
        self.assertEqual(activity['position_neutral_fill_count'],1)
        self.assertEqual(activity['reversal_fill_count'],1)
        self.assertEqual(activity['reversal_close_quantity'],'0.5')
        self.assertEqual(activity['reversal_open_quantity'],'0.5')
        self.assertEqual(activity['maker_fill_count'],2)
        self.assertEqual(activity['taker_fill_count'],2)
        self.assertEqual(activity['crossed_fee_groups']['maker_crossed_false']['fill_count'],2)
        self.assertEqual(activity['crossed_fee_groups']['maker_crossed_false']['signed_fees_by_token']['USDC'],'0.00')
        self.assertEqual(activity['crossed_fee_groups']['taker_crossed_true']['fill_count'],2)
        episode=detail['position_path']['segments']['1']['bounded_episode_examples_first_2'][0]
        self.assertEqual(episode['price_result_quote_units'],'2.0')
        self.assertEqual(detail['by_utc_day']['1970-01-01']['bounded_episode_results_by_segment']['1']['episode_count'],2)
        self.assertEqual(detail['fees_signed_by_token']['USDC'],'0.00')

    def test_inventory_execution_association_splits_reversals_at_zero(self):
        fills=[
            {'coin':'COIN','tid':'open','time':100,'startPosition':'0','side':'B','sz':'1','px':'10','fee':'0.01','feeToken':'USDC','crossed':False},
            {'coin':'COIN','tid':'reduce','time':110,'startPosition':'1','side':'A','sz':'0.5','px':'12','fee':'-0.02','feeToken':'USDC','crossed':True},
            {'coin':'COIN','tid':'reverse','time':120,'startPosition':'0.5','side':'A','sz':'1','px':'12','fee':'-0.01','feeToken':'USDC','crossed':False},
            {'coin':'COIN','tid':'flat','time':130,'startPosition':'-0.5','side':'B','sz':'0.5','px':'13','fee':'0.02','feeToken':'USDC','crossed':True},
        ]
        self._raw(21,'userFillsByTime',fills)
        result=prepare_inventory_execution_association(self.store,self.network,self.address,
            cutoff_ms=self.cutoff,market='COIN')
        row=next(r for r in result['by_position_side_inventory_bucket_and_crossed']
            if r['position_side']=='long' and r['crossed_group']=='maker_crossed_false')
        self.assertEqual(row['reversal_count'],1)
        self.assertEqual(row['reversal_close_quantity'],'0.5')
        self.assertEqual(row['reversal_open_quantity'],'0.5')
        taker=next(r for r in result['by_position_side_inventory_bucket_and_crossed']
            if r['position_side']=='long' and r['crossed_group']=='taker_crossed_true')
        self.assertEqual(taker['close_quantity'],'0.5')
        self.assertEqual(taker['open_quantity'],'0')

    def test_local_resolution_splits_reversal_part_notional_and_fee_between_episodes(self):
        fills=[
            {'coin':'BTC','tid':'open','time':100,'startPosition':'0','side':'B','sz':'1','px':'10','fee':'0.01','feeToken':'USDC','crossed':False},
            {'coin':'BTC','tid':'reduce','time':110,'startPosition':'1','side':'A','sz':'0.5','px':'12','fee':'-0.02','feeToken':'USDC','crossed':True},
            {'coin':'BTC','tid':'reverse','time':120,'startPosition':'0.5','side':'A','sz':'1','px':'12','fee':'-0.01','feeToken':'USDC','crossed':False},
            {'coin':'BTC','tid':'flat','time':130,'startPosition':'-0.5','side':'B','sz':'0.5','px':'13','fee':'0.02','feeToken':'USDC','crossed':True},
        ]
        events=[
            {'fill':fill,'pre_position':fill['startPosition'],
             'post_position':str(Decimal(fill['startPosition']) + (Decimal(fill['sz']) if fill['side']=='B' else -Decimal(fill['sz'])))}
            for fill in fills
        ]
        episodes, _ = _episode_table([(1,events)])
        self.assertEqual(len(episodes),2)
        prior, following = episodes
        self.assertEqual(prior['close_type'],'position_reversal')
        self.assertEqual(prior['price_result_quote_units'],'2.0')
        self.assertEqual(prior['signed_fees_by_token']['USDC'],'-0.015')
        self.assertEqual(prior['maker_quantity'],'1.5')
        self.assertEqual(prior['taker_quantity'],'0.5')
        self.assertEqual(prior['total_part_notional_quote_units'],'22.0')
        self.assertEqual(following['close_type'],'returned_to_zero')
        self.assertEqual(following['price_result_quote_units'],'-0.5')
        self.assertEqual(following['signed_fees_by_token']['USDC'],'0.015')
        self.assertEqual(following['maker_quantity'],'0.5')
        self.assertEqual(following['taker_quantity'],'0.5')
        self.assertEqual(following['total_part_notional_quote_units'],'12.5')

        inverse_fills=[
            {'coin':'BTC','tid':'short-open','time':200,'startPosition':'0','side':'A','sz':'1','px':'10','fee':'0.01','feeToken':'USDC','crossed':False},
            {'coin':'BTC','tid':'inverse-reverse','time':210,'startPosition':'-1','side':'B','sz':'1.5','px':'12','fee':'0.03','feeToken':'USDC','crossed':True},
            {'coin':'BTC','tid':'long-flat','time':220,'startPosition':'0.5','side':'A','sz':'0.5','px':'13','fee':'-0.02','feeToken':'USDC','crossed':False},
        ]
        inverse_events=[
            {'fill':fill,'pre_position':fill['startPosition'],
             'post_position':str(Decimal(fill['startPosition']) + (Decimal(fill['sz']) if fill['side']=='B' else -Decimal(fill['sz'])))}
            for fill in inverse_fills
        ]
        inverse, _ = _episode_table([(2,inverse_events)])
        self.assertEqual(len(inverse),2)
        closing, opening = inverse
        self.assertEqual(closing['price_result_quote_units'],'-2')
        self.assertEqual(closing['signed_fees_by_token']['USDC'],'0.03')
        self.assertEqual(closing['buy_quantity'],'1')
        self.assertEqual(closing['sell_quantity'],'1')
        self.assertEqual(opening['price_result_quote_units'],'0.5')
        self.assertEqual(opening['signed_fees_by_token']['USDC'],'-0.01')
        self.assertEqual(opening['buy_quantity'],'0.5')
        self.assertEqual(opening['sell_quantity'],'0.5')


if __name__=='__main__':unittest.main()
