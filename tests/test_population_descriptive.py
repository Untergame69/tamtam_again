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
    def _ws_raw(self,observation_id,fills,*,observed=195,received=190,snapshot=True,
            batched=True,user=None):
        message={'channel':'userFills','data':{'user':user or self.address,
            'isSnapshot':snapshot,'fills':fills}}
        payload={'events':[{'received_at':datetime.fromtimestamp(received/1000,timezone.utc).isoformat(),
            'message':message}]} if batched else message
        self._raw(observation_id,'userFills',payload,observed=observed,start=None,end=None)
        self.store.connection.execute("update raw_observations set source='hyperliquid-websocket-v1' where observation_id=?",(observation_id,))
        self.store.connection.commit()

    def _execution(self,tid='one',time=150,**changes):
        return {'coin':'COIN','tid':tid,'time':time,'startPosition':'0','side':'B',
            'sz':'1','px':'10','closedPnl':'0','fee':'0.01','feeToken':'USDC',
            'crossed':False,**changes}

    def test_ws_merge_normalizes_economics_and_keeps_transport_in_raw_provenance(self):
        from tamtam_again.population_descriptive import load_research_fill_evidence
        rest=self._execution(oid=123,hash='trade-hash',transport='rest')
        ws=self._execution(px=10.0,sz='1.000',fee='0.0100',oid='123',transport='ws',extra='only-ws')
        self._raw(1,'userFillsByTime',[rest])
        self._ws_raw(2,[ws])
        fills,coverage,refs,proofs=load_research_fill_evidence(self.store,self.network,self.address,
            self.cutoff,ws_start_ms=100)
        self.assertEqual(len(fills),1)
        self.assertNotIn('transport',fills[0])
        self.assertNotIn('extra',fills[0])
        self.assertEqual(coverage['duplicate_fill_instances'],1)
        self.assertEqual(coverage['conflicting_fill_identity_count'],0)
        self.assertEqual({p['source'] for p in proofs['one']},{'rest','ws'})
        self.assertEqual({r['id'] for r in refs},{'1','2'})
        ws_proof=next(p for p in proofs['one'] if p['source']=='ws')
        self.assertTrue(ws_proof['is_snapshot'])
        self.assertEqual(ws_proof['frame_received_ms'],190)
        self.assertFalse(ws_proof['live_follower_signal'])

    def test_ws_actual_economic_conflict_excludes_identity(self):
        from tamtam_again.population_descriptive import load_research_fill_evidence
        self._raw(1,'userFillsByTime',[self._execution()])
        self._ws_raw(2,[self._execution(px='10.1')])
        fills,coverage,_,proofs=load_research_fill_evidence(self.store,self.network,self.address,
            self.cutoff,ws_start_ms=100)
        self.assertEqual(fills,[])
        self.assertEqual(proofs,{})
        self.assertEqual(coverage['conflicting_fill_id_examples'],['one'])

    def test_ws_cutoffs_scope_snapshots_and_legacy_default(self):
        from tamtam_again.population_descriptive import load_research_fill_evidence,_load_fills
        self._raw(1,'userFillsByTime',[self._execution('old-rest',time=50)])
        self._ws_raw(2,[self._execution('snapshot'),self._execution('old-ws',time=99),
            self._execution('future-event',time=201)])
        self._ws_raw(3,[self._execution('future-frame')],received=201)
        self._ws_raw(4,[self._execution('future-archive')],observed=201)
        self._ws_raw(5,[self._execution('other-user')],user='0x'+'2'*40)
        self._ws_raw(6,[self._execution('unbatched',time=160)],batched=False,snapshot=False)
        fills,coverage,refs,proofs=load_research_fill_evidence(self.store,self.network,self.address,
            self.cutoff,ws_start_ms=100)
        self.assertEqual({f['tid'] for f in fills},{'old-rest','snapshot','unbatched'})
        self.assertEqual({f['tid'] for f in _load_fills(self.store,self.network,self.address,self.cutoff)[0]}, {'old-rest'})
        self.assertNotIn('4',{r['id'] for r in refs})
        self.assertEqual(coverage['records_after_cutoff_excluded'],1)
        self.assertEqual(coverage['source_counts']['ws_events_before_declared_window'],1)
        self.assertEqual(proofs['unbatched'][0]['frame_receipt_status'],'unknown; archive availability only')
        self.assertFalse(coverage['continuity_proven'])

    def test_ws_only_activity_passes_through_summary_detail_and_packet(self):
        self._ws_raw(1,[self._execution()])
        options={'cutoff_ms':self.cutoff,'include_ws':True,'ws_start_ms':100}
        summary=prepare_candidate_summary(self.store,self.network,self.address,**options)
        self.assertEqual(summary['coverage']['fill_archive']['usable_unique_fill_count'],1)
        detail=prepare_candidate_market_detail(self.store,self.network,self.address,market='COIN',**options)
        self.assertEqual(detail['execution_activity']['fill_count'],1)
        base={'network':self.network,'address':self.address,'available_ms':190,
            'research_input_fingerprint':'base','evidence_refs':[],'observations':{}}
        packet=prepare_pilot_packet(self.store,base,candidate='test',
            item={'descriptive_markets':['COIN']},pilot_id=None,policy_version='v',**options)
        self.assertEqual(packet['observations']['market_execution_detail_v1']['COIN']['execution_activity']['fill_count'],1)
        self.assertEqual(prepare_candidate_summary(self.store,self.network,self.address,
            cutoff_ms=self.cutoff)['coverage']['fill_archive']['usable_unique_fill_count'],0)

    def test_ws_resource_bounds_fail_without_partial_summary(self):
        from tamtam_again.population_descriptive import load_research_fill_evidence
        self._ws_raw(1,[self._execution(),self._execution('two')])
        self._ws_raw(2,[self._execution('three')])
        for limits,pattern in [({'max_ws_lots':1},'lot limit'),
                ({'max_ws_records':1},'record limit'),
                ({'max_decoded_bytes_per_lot':20},'byte bound'),
                ({'max_decoded_bytes_per_source':20},'decoded-byte limit')]:
            with self.subTest(limits=limits),self.assertRaisesRegex(ValueError,pattern):
                load_research_fill_evidence(self.store,self.network,self.address,
                    self.cutoff,ws_start_ms=100,limits=limits)
        for start,limits in [(None,None),(201,None),(100,{'unlimited':1}),(100,{'max_ws_records':0})]:
            with self.assertRaises(ValueError):
                load_research_fill_evidence(self.store,self.network,self.address,self.cutoff,
                    ws_start_ms=start,limits=limits)

    def test_ws_merge_rest_bounds_hash_and_exact_decimal_identity(self):
        from tamtam_again.population_descriptive import load_research_fill_evidence
        large='123456789012345678901234567890.123456789'
        self._raw(1,'userFillsByTime',[self._execution(px=large),self._execution('two')])
        self._raw(2,'userFillsByTime',[self._execution('three')])
        self._ws_raw(3,[self._execution(px=large+'0')])
        fills,coverage,_,_=load_research_fill_evidence(self.store,self.network,self.address,
            self.cutoff,ws_start_ms=100)
        self.assertEqual(len(fills),3)
        self.assertEqual(coverage['usable_fill_provenance']['both_sources_fill_count'],1)
        for limits,pattern in [({'max_rest_pages':1},'rest lot limit'),
                ({'max_rest_records':1},'rest record limit')]:
            with self.assertRaisesRegex(ValueError,pattern):
                load_research_fill_evidence(self.store,self.network,self.address,
                    self.cutoff,ws_start_ms=100,limits=limits)
        self.store.connection.execute("update raw_observations set response_sha256='bad' where observation_id=3")
        with self.assertRaisesRegex(ValueError,'hash mismatch'):
            load_research_fill_evidence(self.store,self.network,self.address,self.cutoff,ws_start_ms=100)

    def test_ws_reserved_guard_precedes_metadata_and_payload_reads(self):
        from tamtam_again.population_descriptive import load_research_fill_evidence,research_fill_source_manifest
        from unittest.mock import patch
        queries=[]
        self.store.connection.set_trace_callback(queries.append)
        with patch('tamtam_again.population_descriptive.authorized_account_history',return_value=False):
            for function in (load_research_fill_evidence,research_fill_source_manifest):
                with self.assertRaises(PermissionError):
                    function(self.store,self.network,self.address,self.cutoff,ws_start_ms=100)
        self.store.connection.set_trace_callback(None)
        self.assertFalse(any('raw_observations' in query for query in queries))

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
        self.assertEqual(closing['peak_abs_position'],'1')
        self.assertEqual(opening['peak_abs_position'],'0.5')


if __name__=='__main__':unittest.main()
