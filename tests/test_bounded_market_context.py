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
        self.assertEqual(second['earliest_rest_page_received_ms'], BASE+3000)
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

    def test_reserved_account_refused_before_decoding_or_cache_access(self):
        with patch('tamtam_again.bounded_market_context.authorized_account_history',return_value=False), \
                patch('tamtam_again.bounded_market_context._decode_verified',side_effect=AssertionError('decoded reserve')):
            with self.assertRaises(PermissionError):self.run_context()
        self.assertFalse(self.store.connection.execute("select 1 from sqlite_master where name='bounded_market_context_results'").fetchone())


if __name__ == '__main__':
    unittest.main()
