import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tamtam_again.bounded_market_context import ContextBoundError, load_result, prepare_market_context
from tamtam_again.population_local_join import _event_iso
from tamtam_again.storage import Store


NETWORK = 'hyperliquid-mainnet'
ADDRESS = '0x' + 'a' * 40
BASE = 1_790_000_000_000


class BoundedMarketContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'context.sqlite3')

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def save(self, payload, *, endpoint, stamp, account=False, window=None, address=ADDRESS, market='ETH'):
        self.store.save_observation(network=NETWORK,
            source='hyperliquid-population-rest-v1' if account else 'hyperliquid-websocket-v1',
            entity_type='account' if account else 'market', entity_id=address if account else market,
            endpoint=endpoint, payload=payload, requested_at=_event_iso(stamp),
            window_start_ms=window[0] if window else stamp,
            window_end_ms=window[1] if window else stamp, record_count=len(payload) if isinstance(payload,list) else 1)
        row = self.store.connection.execute('select max(observation_id) from raw_observations').fetchone()[0]
        self.store.connection.execute('update raw_observations set observed_at=? where observation_id=?',
            (_event_iso(stamp+1), row))
        self.store.connection.commit()
        return row

    def fills(self, market='ETH', address=ADDRESS):
        return self.save([
            {'tid': 1, 'coin': market, 'time': BASE+1000, 'side': 'A', 'px': '101',
             'sz': '2', 'startPosition': '1', 'crossed': True},
            {'tid': 2, 'coin': market, 'time': BASE+2000, 'side': 'B', 'px': '100',
             'sz': '1', 'startPosition': '-1', 'crossed': False}],
            endpoint='userFillsByTime', stamp=BASE+3000, account=True,
            window=(BASE, BASE+2500), address=address)

    def quote(self, stamp, *, bid='99', ask='101', market='ETH', feed='bbo', receipt=None, batch=True):
        data = {'coin': market, 'time': stamp}
        top = [{'px': bid, 'sz': '10'}, {'px': ask, 'sz': '20'}]
        data['bbo' if feed=='bbo' else 'levels'] = top if feed=='bbo' else [[top[0]], [top[1]]]
        message = {'channel': feed, 'data': data}
        when = receipt if receipt is not None else stamp+10
        payload = {'events': [{'received_at': _event_iso(when), 'message': message}]} if batch else message
        return self.save(payload, endpoint=feed, stamp=when, window=(stamp,stamp), market=market)

    def run_context(self, **kwargs):
        return prepare_market_context(self.store, network=NETWORK, address=kwargs.pop('address',ADDRESS),
            market=kwargs.pop('market','ETH'), cutoff_ms=kwargs.pop('cutoff_ms',BASE+10_000), **kwargs)

    def test_strict_prefill_separate_clocks_roles_and_lossless_proof(self):
        self.fills()
        self.quote(BASE+500, receipt=BASE+1500)
        simultaneous = self.quote(BASE+1000, bid='100', ask='102')
        self.quote(BASE+1900, feed='l2Book', batch=False)
        result = self.run_context()
        proof = load_result(self.store, result['result_fingerprint'])
        first, second = proof['feeds']['bbo']['rows']
        self.assertEqual(first['strict_prefill_quote']['event_ms'], BASE+500)
        self.assertFalse(first['strict_prefill_quote']['received_before_fill_event'])
        self.assertEqual(first['same_millisecond_event_count'], 1)
        self.assertEqual(first['position_effect'], 'reversal')
        self.assertEqual(first['closing_quantity'], '1')
        self.assertEqual(first['opening_quantity'], '1')
        self.assertEqual(second['strict_prefill_quote']['source_ref'], 'raw_observations:'+str(simultaneous))
        self.assertEqual(second['role'], 'maker')
        self.assertEqual(second['position_effect'], 'closing')
        self.assertEqual(second['rest_page_request_started_ms'], BASE+3000)
        self.assertIsNone(second['rest_page_received_ms'])
        self.assertEqual(second['rest_page_available_upper_bound_ms'],BASE+3001)
        self.assertIsNone(proof['feeds']['l2Book']['rows'][0]['strict_prefill_quote'])
        self.assertEqual(proof['feeds']['l2Book']['rows'][1]['strict_prefill_quote']['event_ms'],BASE+1900)
        self.assertGreaterEqual(proof['feeds']['bbo']['coverage']['event_gap_ms_including_window_edges']['p50'],0)

    def test_cache_skips_decoding_after_reopen_and_ignores_postfill_quotes_and_cutoff_clock(self):
        self.fills()
        self.quote(BASE+500)
        first = self.run_context()
        self.quote(BASE+2500)  # Entire lot is later than every studied fill.
        self.store.close()
        self.store = Store(Path(self.temp.name) / 'context.sqlite3')
        with patch('tamtam_again.bounded_market_context._decode_verified', side_effect=AssertionError('decoded unchanged proof')), \
                patch('tamtam_again.bounded_market_context._load_fills', side_effect=AssertionError('loaded unchanged fills')):
            second = self.run_context(cutoff_ms=BASE+20_000)
        self.assertEqual(first['semantic_fingerprint'],second['semantic_fingerprint'])
        self.assertEqual(first['result_fingerprint'],second['result_fingerprint'])
        self.assertEqual(second['cache'],'unchanged')
        self.assertEqual(self.store.connection.execute('select count(*) from bounded_market_context_results').fetchone()[0],1)

    def test_new_prefill_quote_changes_context_and_other_account_market_are_excluded(self):
        self.fills()
        self.quote(BASE+400)
        first = self.run_context()
        self.quote(BASE+800, bid='100',ask='102')
        self.fills(market='BTC',address='0x'+'b'*40)
        self.quote(BASE+900,market='BTC')
        second = self.run_context()
        self.assertNotEqual(first['semantic_fingerprint'], second['semantic_fingerprint'])
        proof = load_result(self.store,second['result_fingerprint'])
        self.assertEqual(proof['feeds']['bbo']['rows'][0]['strict_prefill_quote']['event_ms'],BASE+800)
        self.assertEqual(proof['scope']['included_market_fills'],2)
        third=self.run_context(market='BTC',address='0x'+'b'*40)
        self.assertEqual(third['market'],'BTC')
        self.assertNotEqual(third['evidence_ref'],second['evidence_ref'])

    def test_new_other_market_fill_does_not_change_selected_market_semantic_facts(self):
        self.fills()
        self.quote(BASE+500)
        first=self.run_context()
        self.save([{'tid':99,'coin':'BTC','time':BASE+1500,'side':'B','px':'1000','sz':'1',
            'startPosition':'0','crossed':True}],endpoint='userFillsByTime',stamp=BASE+3500,
            account=True,window=(BASE,BASE+2500))
        second=self.run_context()
        self.assertEqual(first['semantic_fingerprint'],second['semantic_fingerprint'])
        self.assertEqual(second['scope']['other_market_fills'],1)

    def test_same_millisecond_at_last_fill_is_flagged_and_not_used(self):
        self.fills()
        self.quote(BASE+2000)
        result=self.run_context()
        proof=load_result(self.store,result['result_fingerprint'])
        last=proof['feeds']['bbo']['rows'][-1]
        self.assertEqual(last['same_millisecond_event_count'],1)
        self.assertIsNone(last['strict_prefill_quote'])

    def test_duplicate_quote_receipt_is_not_new_semantic_market_evidence(self):
        self.fills()
        self.quote(BASE+500,receipt=BASE+600)
        first=self.run_context()
        self.quote(BASE+500,receipt=BASE+700)
        second=self.run_context()
        self.assertEqual(first['semantic_fingerprint'],second['semantic_fingerprint'])
        proof=load_result(self.store,second['result_fingerprint'])
        self.assertEqual(proof['feeds']['bbo']['decoding']['rejected_or_excluded']['identical_source_quote_duplicates'],1)

    def test_request_time_is_not_receipt_and_single_message_uses_archive_upper_bound(self):
        self.fills()
        lot=self.quote(BASE+500,feed='l2Book',batch=False,receipt=BASE+700)
        # A long request began before the quote; the observation was archived
        # after both fills. There is no exact receive timestamp in this format.
        self.store.connection.execute('update raw_observations set requested_at=?,observed_at=? '
            'where observation_id=?',(_event_iso(BASE-10_000),_event_iso(BASE+4000),lot))
        self.store.connection.commit()
        result=self.run_context()
        proof=load_result(self.store,result['result_fingerprint'])
        quote=proof['feeds']['l2Book']['rows'][0]['strict_prefill_quote']
        self.assertEqual(quote['event_received_ms'],BASE+4000)
        self.assertFalse(quote['local_receipt_exact'])
        self.assertIsNone(quote['received_before_fill_event'])
        self.assertFalse(quote['archived_before_fill_event'])
        self.assertEqual(result['feeds']['l2Book']['coverage']['quote_locally_received_before_fill_event'],0)

    def test_unchanged_page_future_fill_becomes_eligible_when_cutoff_advances(self):
        self.save([
            {'tid':1,'coin':'ETH','time':BASE+1000,'side':'B','px':'100','sz':'1',
             'startPosition':'0','crossed':True},
            {'tid':2,'coin':'ETH','time':BASE+5000,'side':'A','px':'101','sz':'1',
             'startPosition':'1','crossed':False}],endpoint='userFillsByTime',
            stamp=BASE+1500,account=True,window=(BASE,BASE+1500))
        first=self.run_context(cutoff_ms=BASE+2000)
        self.assertEqual(first['scope']['included_market_fills'],1)
        second=self.run_context(cutoff_ms=BASE+6000)
        self.assertEqual(second['scope']['included_market_fills'],2)
        self.assertNotEqual(first['semantic_fingerprint'],second['semantic_fingerprint'])
        proof=load_result(self.store,second['result_fingerprint'])
        self.assertEqual(proof['feeds']['bbo']['rows'][1]['rest_page_request_started_ms'],BASE+1500)

    def test_receipts_follow_exact_nonconflicting_fill_not_arbitrary_tid(self):
        self.fills()
        self.save([{'tid':1,'coin':'BTC','time':BASE+500,'side':'B','px':'100','sz':'1',
            'startPosition':'0','crossed':False}],endpoint='userFillsByTime',
            stamp=BASE+2000,account=True,window=(BASE,BASE+1000))
        result=self.run_context()
        proof=load_result(self.store,result['result_fingerprint'])
        rows=proof['feeds']['bbo']['rows']
        self.assertEqual([r['tid'] for r in rows],['2'])
        self.assertEqual(rows[0]['rest_page_request_started_ms'],BASE+3000)

    def test_monotonic_timeout_refuses_before_partial_result_is_published(self):
        self.fills()
        self.quote(BASE+500)
        calls=[0]
        def clock():
            calls[0]+=1
            return 0 if calls[0]<9 else 61
        with patch('tamtam_again.bounded_market_context.time.monotonic',side_effect=clock):
            with self.assertRaisesRegex(ContextBoundError,'time limit'):
                self.run_context()
        exists=self.store.connection.execute("select 1 from sqlite_master where name='bounded_market_context_results'").fetchone()
        if exists:
            self.assertEqual(self.store.connection.execute('select count(*) from bounded_market_context_results').fetchone()[0],0)

    def test_old_movement_anchor_is_visible_and_excluded_from_near_60s_summary(self):
        self.fills()
        self.quote(BASE-7_200_000,bid='89',ask='91')
        self.quote(BASE+500,bid='99',ask='101')
        result=self.run_context()
        proof=load_result(self.store,result['result_fingerprint'])
        row=proof['feeds']['bbo']['rows'][0]['strict_prefill_quote']
        self.assertEqual(row['prior_move_anchor_age_ms'],7_200_500)
        group=result['feeds']['bbo']['groups'][0]
        self.assertGreater(group['prior_move_anchor_age_ms']['p50'],7_000_000)
        self.assertGreater(group['at_least_60s_move_bps']['count'],0)
        self.assertEqual(group['near_60s_move_bps']['count'],0)
        self.assertEqual(group['near_60s_move_coverage']['matched'],0)
        self.assertNotIn('prior_60s_move_bps',group)
        self.assertTrue(any('much longer' in note for note in result['limitations']))

    def test_near_60s_anchor_is_reported_in_distinct_summary(self):
        self.fills()
        self.quote(BASE-60_000,bid='89',ask='91')
        self.quote(BASE+500,bid='99',ask='101')
        result=self.run_context()
        group=result['feeds']['bbo']['groups'][0]
        self.assertEqual(group['near_60s_anchor_age_ms']['p50'],60_500)
        self.assertGreater(group['near_60s_move_bps']['count'],0)

    def test_load_result_checks_scope_and_reserve_before_decompressing_proof(self):
        self.fills()
        self.quote(BASE+500)
        result=self.run_context()
        with patch('tamtam_again.bounded_market_context.authorized_account_history',return_value=False), \
                patch('tamtam_again.bounded_market_context.zlib.decompress',side_effect=AssertionError('decoded reserved proof')):
            with self.assertRaises(PermissionError):load_result(self.store,result['result_fingerprint'])
        self.store.connection.execute('delete from bounded_market_context_scopes')
        self.store.connection.commit()
        with patch('tamtam_again.bounded_market_context.zlib.decompress',side_effect=AssertionError('decoded unscoped proof')):
            with self.assertRaises(PermissionError):load_result(self.store,result['result_fingerprint'])

    def test_indexed_event_overlap_keeps_straddling_lots_and_unknown_source_bounds(self):
        self.fills()
        quote_start=BASE+2000-86_400_000-300_000
        events=[]
        for stamp in (quote_start-1000,BASE+500):
            events.append({'received_at':_event_iso(BASE+600),
                'message':{'channel':'bbo','data':{'coin':'ETH','time':stamp,
                    'bbo':[{'px':'99','sz':'10'},{'px':'101','sz':'10'}]}}})
        self.save({'events':events},endpoint='bbo',stamp=BASE+600,
            window=(quote_start-1000,BASE+500))
        unknown=self.quote(BASE+1500,feed='l2Book')
        self.store.connection.execute('update raw_observations set window_start_ms=null,window_end_ms=null '
            'where observation_id=?',(unknown,))
        self.store.connection.commit()
        result=self.run_context()
        proof=load_result(self.store,result['result_fingerprint'])
        self.assertEqual(proof['feeds']['bbo']['rows'][0]['strict_prefill_quote']['event_ms'],BASE+500)
        self.assertEqual(proof['feeds']['l2Book']['rows'][-1]['strict_prefill_quote']['event_ms'],BASE+1500)
        self.assertEqual(proof['feeds']['bbo']['decoding']['rejected_or_excluded']['outside_declared_context_window'],1)

    def test_cutoff_and_latest_fill_window_exclusions_are_explicit(self):
        self.fills()
        self.save([{'tid':3,'coin':'ETH','time':BASE-90_000_000,'side':'B','px':'99','sz':'1',
            'startPosition':'0','crossed':True}],endpoint='userFillsByTime',stamp=BASE+3500,
            account=True,window=(BASE-90_000_000,BASE-89_000_000))
        self.quote(BASE+500,receipt=BASE+20_000)
        result=self.run_context()
        self.assertEqual(result['scope']['outside_window_market_fills'],1)
        self.assertEqual(result['feeds']['bbo']['coverage']['unmatched'],2)

    def test_bounds_and_corruption_never_publish_partial_statistics(self):
        self.fills()
        q1=self.quote(BASE+500)
        self.quote(BASE+600)
        for limits in ({'max_quote_lots_per_feed':1},{'max_quote_events_per_feed':1},
                       {'max_quote_decoded_bytes_per_feed':1},{'max_fill_records':1}):
            with self.subTest(limits=limits), self.assertRaises(ContextBoundError):
                self.run_context(limits=limits)
            self.assertEqual(self.store.connection.execute('select count(*) from bounded_market_context_results').fetchone()[0],0)
        self.store.connection.execute("update raw_observations set response_sha256='wrong' where observation_id=?",(q1,))
        self.store.connection.commit()
        with self.assertRaisesRegex(ValueError,'hash mismatch'):
            self.run_context()
        self.assertEqual(self.store.connection.execute('select count(*) from bounded_market_context_results').fetchone()[0],0)

    def ws_fills(self, *, stamp=BASE+3000, fills=None, snapshot=False):
        fill = {'tid': 50, 'coin': 'ETH', 'time': BASE+1000, 'side': 'B',
            'px': '100', 'sz': '1', 'startPosition': '0', 'crossed': True,
            'closedPnl': '0', 'fee': '0.01', 'feeToken': 'USDC'}
        message = {'channel': 'userFills', 'data': {'user': ADDRESS,
            'isSnapshot': snapshot, 'fills': [fill] if fills is None else fills}}
        lot = self.save({'events': [{'received_at': _event_iso(stamp), 'message': message}]},
            endpoint='userFills', stamp=stamp, account=True)
        self.store.connection.execute('update raw_observations set source=? where observation_id=?',
            ('hyperliquid-websocket-v1', lot))
        self.store.connection.commit()
        return lot, fill

    def test_ws_only_fills_join_strict_quotes_and_snapshots_remain_descriptive(self):
        lot, _ = self.ws_fills(snapshot=True)
        self.quote(BASE+500)
        self.assertEqual(self.run_context()['status'], 'data_absent')
        result = self.run_context(include_ws=True, ws_start_ms=BASE)
        proof = load_result(self.store, result['result_fingerprint'])
        row = proof['feeds']['bbo']['rows'][0]
        self.assertEqual(row['strict_prefill_quote']['event_ms'], BASE+500)
        receipt = row['fill_evidence_receipts'][0]
        self.assertEqual(receipt['observation_id'], lot)
        self.assertEqual(receipt['frame_received_ms'], BASE+3000)
        self.assertTrue(receipt['is_snapshot'])
        self.assertFalse(receipt['live_follower_signal'])
        self.assertFalse(proof['descriptive_fill_policy']['live_follower_signal'])
        self.assertEqual(len(proof['fill_source_manifest']['sources']['ws']), 1)

    def test_ws_context_cache_reuses_typed_evidence_and_duplicate_has_no_semantic_retry(self):
        self.ws_fills()
        self.quote(BASE+500)
        first = self.run_context(include_ws=True, ws_start_ms=BASE)
        with patch('tamtam_again.population_descriptive.load_research_fill_evidence',
                side_effect=AssertionError('decoded unchanged typed evidence')), patch(
                'tamtam_again.bounded_market_context._decode_verified',
                side_effect=AssertionError('decoded unchanged quotes')):
            cached = self.run_context(include_ws=True, ws_start_ms=BASE)
        self.assertEqual(cached['cache'], 'unchanged')
        self.ws_fills(stamp=BASE+4000)
        second = self.run_context(include_ws=True, ws_start_ms=BASE)
        self.assertEqual(first['semantic_fingerprint'], second['semantic_fingerprint'])
        proof = load_result(self.store, second['result_fingerprint'])
        self.assertEqual(len(proof['feeds']['bbo']['rows'][0]['fill_evidence_receipts']), 2)

    def test_ws_actual_new_fill_invalidates_cache_and_rest_history_is_preserved(self):
        self.fills()
        self.ws_fills()
        self.quote(BASE+500)
        first = self.run_context(include_ws=True, ws_start_ms=BASE)
        _, fill = self.ws_fills(stamp=BASE+4000, fills=[])
        self.ws_fills(stamp=BASE+5000, fills=[{**fill, 'tid': 51, 'time': BASE+4500}])
        second = self.run_context(include_ws=True, ws_start_ms=BASE)
        self.assertEqual(first['scope']['included_market_fills'], 3)
        self.assertEqual(second['scope']['included_market_fills'], 4)
        self.assertNotEqual(first['semantic_fingerprint'], second['semantic_fingerprint'])

    def test_ws_future_and_pre_window_exclusions_and_explicit_window(self):
        _, fill = self.ws_fills()
        self.ws_fills(stamp=BASE+4000, fills=[{**fill, 'tid': 51, 'time': BASE+20_000},
            {**fill, 'tid': 52, 'time': BASE-1}])
        result = self.run_context(include_ws=True, ws_start_ms=BASE)
        proof = load_result(self.store, result['result_fingerprint'])
        self.assertEqual([r['tid'] for r in proof['feeds']['bbo']['rows']], ['50'])
        with self.assertRaisesRegex(ValueError, 'explicit'):
            self.run_context(include_ws=True)
        with patch('tamtam_again.bounded_market_context.authorized_account_history', return_value=False), \
                patch('tamtam_again.population_descriptive.research_fill_source_manifest',
                    side_effect=AssertionError('scanned reserved WS evidence')):
            with self.assertRaises(PermissionError):
                self.run_context(include_ws=True, ws_start_ms=BASE)

    def test_reserved_account_refused_before_decoding_or_cache_access(self):
        with patch('tamtam_again.bounded_market_context.authorized_account_history',return_value=False), \
                patch('tamtam_again.bounded_market_context._decode_verified',side_effect=AssertionError('decoded reserve')):
            with self.assertRaises(PermissionError):self.run_context()
        self.assertFalse(self.store.connection.execute("select 1 from sqlite_master where name='bounded_market_context_results'").fetchone())


if __name__ == '__main__':
    unittest.main()
