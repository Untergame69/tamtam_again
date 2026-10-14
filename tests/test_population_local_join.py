import hashlib
import json
import tempfile
import unittest
import zlib
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from tamtam_again.engine import canonical, fingerprint
from tamtam_again.population_local_join import VERSION, _quote_values, execute_offline_archive_join
from tamtam_again.population_research import initialize
from tamtam_again.population_scheduler import tick
from tamtam_again.storage import Store, decode_observation_payload


class PopulationLocalJoinTests(unittest.TestCase):
    """Synthetic integration fixtures; these are not the operational scheduler run."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'join.sqlite3')
        initialize(self.store)
        self.network = 'hyperliquid-mainnet'
        self.address = '0x' + '7' * 40
        self.cutoff = 5000
        self.request_id = 'request-local-join-fixture'
        self._seed_sources()
        self._seed_job()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    @staticmethod
    def _stamp(ms):
        return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec='milliseconds')

    def _raw(self, observation_id, source, entity_type, entity_id, endpoint, payload,
             event_or_window=None, received=4500):
        raw = canonical(payload).encode()
        self.store.connection.execute(
            'insert into raw_observations (observation_id,network,source,entity_type,entity_id,endpoint,'
            'request_json,requested_at,observed_at,window_start_ms,window_end_ms,record_count,complete,'
            'response_encoding,response_sha256,response_json,receipt_id) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (observation_id, self.network, source, entity_type, entity_id, endpoint, '{}', self._stamp(received),
             self._stamp(received), None, event_or_window, 1, 0, 'zlib+json',
             hashlib.sha256(raw).hexdigest(), zlib.compress(raw), f'receipt-{observation_id}'))

    def _seed_sources(self):
        fills = [
            {'coin': 'ETH', 'tid': 'before-quotes', 'time': 800, 'startPosition': '0',
             'side': 'B', 'sz': '1', 'px': '10', 'crossed': False},
            {'coin': 'ETH', 'tid': 'matched', 'time': 1000, 'startPosition': '1',
             'side': 'B', 'sz': '1', 'px': '11', 'crossed': False},
            {'coin': 'ETH', 'tid': 'strict-predecessor', 'time': 3000, 'startPosition': '2',
             'side': 'B', 'sz': '1', 'px': '12', 'crossed': False},
        ]
        self._raw(1, 'hyperliquid-population-rest-v1', 'account', self.address,
                  'userFillsByTime', fills, event_or_window=self.cutoff, received=4500)
        bbo = lambda event, bid: {'channel':'bbo','data': {'coin':'ETH','time': event, 'bbo': [
            {'px': str(bid), 'sz': '2'}, {'px': str(bid + 1), 'sz': '3'}]}}
        l2 = lambda event, bid: {'channel':'l2Book','data': {'coin':'ETH','time': event, 'levels': [
            [{'px': str(bid), 'sz': '4'}], [{'px': str(bid + 1), 'sz': '5'}]]}}
        bbo_batch={'events':[{'received_at':self._stamp(4202),'message':bbo(900,9)},
            {'received_at':self._stamp(4202),'message':bbo(950,10)}]}
        l2_batch={'events':[{'received_at':self._stamp(4213),'message':l2(3100,30)}]}
        for oid, event, bid in ((2, 900, 9), (3, 3100, 30), (4, 6000, 60)):
            bbo_payload=bbo_batch if oid==2 else bbo(event,bid)
            l2_payload=l2(900,9) if oid==2 else l2_batch if oid==3 else l2(event,bid)
            self._raw(oid, 'hyperliquid-websocket-v1', 'market', 'ETH', 'bbo', bbo_payload, received=4200 + oid)
            self._raw(oid + 10, 'hyperliquid-websocket-v1', 'market', 'ETH', 'l2Book', l2_payload, received=4200 + oid)
        self._raw(30, 'hyperliquid-population-rest-v1', 'account', self.address,
                  'clearinghouseState', {'time': 700, 'assetPositions': []}, received=4300)
        self.store.connection.commit()

    def _seed_job(self):
        packet = {'schema_version': 'fixture', 'network': self.network, 'address': self.address,
            'available_ms': 4400, 'research_input_fingerprint': 'input-fixture',
            'pilot_research': {'candidate': '67f7', 'admission_cutoff_ms': self.cutoff},
            'observations': {'markets': ['ETH'], 'market_execution_detail_v1': {'ETH': {
                'cutoff_ms': self.cutoff, 'detail_fingerprint': 'sealed-detail'}}}}
        packet['fingerprint'] = fingerprint(packet)
        result = {'local_resolution': {'version': 'fixture', 'followup_task': {
            'kind': 'offline_archive_join', 'title': 'join fixture'}}}
        self.store.connection.execute('insert into population_research_jobs values(?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (self.request_id, self.network, self.address, 'input-fixture', canonical(packet), '{}',
             4400, 'needs_data', None, None, canonical(result), None, 4400))
        self.store.connection.commit()

    def _seed_completed_job(self, request_id, address, created_ms=4300):
        packet={'schema_version':'fixture','network':self.network,'address':address,
            'available_ms':created_ms,'research_input_fingerprint':'complete-'+request_id,
            'pilot_research':{'candidate':'67f7','admission_cutoff_ms':self.cutoff},
            'observations':{'markets':['ETH'],'market_execution_detail_v1':{'ETH':{
                'cutoff_ms':self.cutoff,'detail_fingerprint':'sealed-detail'}}}}
        packet['fingerprint']=fingerprint(packet)
        result={'local_resolution':{'version':'fixture','followup_task':{
                'kind':'offline_archive_join','title':'join fixture'}},
            'local_archive_join':{'version':VERSION,'state':'completed','artifact_fingerprint':'cached',
                'artifact_path':'cached.json.gz','source_fingerprint':'cached','model_calls':0,
                'collection_started':False,'matched_fills':0},
            'local_inventory_market_context':{'version':'population-inventory-market-context-v2','state':'completed',
                'analysis_fingerprint':'cached-context','base_join_fingerprint':'cached','artifact_path':'cached-context.json.gz',
                'model_calls':0,'collection_started':False}}
        self.store.connection.execute('insert into population_research_jobs values(?,?,?,?,?,?,?,?,?,?,?,?,?)',
            ('completed-'+request_id,self.network,address,'complete-'+request_id,canonical(packet),'{}',
             created_ms,'needs_data',None,None,canonical(result),None,created_ms))
        self.store.connection.commit()

    def test_event_predecessors_unmatched_rows_cutoff_and_idempotent_reopen(self):
        result = execute_offline_archive_join(self.store, self.request_id)
        self.assertEqual(result['status'], 'prepared')
        row = self.store.connection.execute('select artifact_json from population_local_archive_joins').fetchone()
        artifact = json.loads(row[0])
        self.assertEqual(artifact['schema_version'], VERSION)
        self.assertEqual(len(artifact['fills']), 3)
        by_id = {fill['fill_id']: fill for fill in artifact['fills']}
        self.assertIsNone(by_id['before-quotes']['bbo'])
        self.assertEqual(by_id['matched']['bbo']['event_ms'], 950)
        self.assertEqual(by_id['strict-predecessor']['bbo']['event_ms'], 950)
        self.assertEqual(by_id['matched']['bbo']['observation_ref']['event_index'],1)
        self.assertNotEqual(by_id['strict-predecessor']['bbo']['bid'], '30')
        # Receipt-clock context is a separate predecessor. Its venue event time
        # may be after the fill, so it cannot be silently used as historical state.
        self.assertEqual(by_id['matched']['bbo_by_local_receipt']['event_ms'], 3100)
        self.assertEqual(by_id['matched']['bbo_by_local_receipt']['local_receipt_age_ms'], 297)
        self.assertLess(by_id['matched']['bbo_by_local_receipt']['event_age_vs_fill_ms'], 0)
        self.assertEqual(by_id['strict-predecessor']['position_delta_snapshot_minus_startPosition'], '-2')
        self.assertEqual(artifact['market_snapshot_coverage']['event_time_after_cutoff_excluded'],
                         {'bbo': 1, 'l2book': 1})
        self.assertFalse(artifact['decision']['additional_collection_requested'])
        self.assertIn('whether the matched quote had arrived', artifact['comparisons_not_established'][0])
        self.assertEqual(artifact['market_snapshot_coverage']['by_segment_utc_day_gaps'][0]
                         ['event_clock_coverage']['observation_count'], 2)

        with patch('tamtam_again.population_local_join._decode_verified',
                   side_effect=AssertionError('idempotent replay must not decode source rows')):
            before_result=self.store.connection.execute(
                'select result_json from population_research_jobs where request_id=?',(self.request_id,)).fetchone()[0]
            before_routes=self.store.connection.execute(
                'select count(*) from population_hypothesis_route_history where request_id=?',(self.request_id,)).fetchone()[0]
            replay = execute_offline_archive_join(self.store, self.request_id)
            after_result=self.store.connection.execute(
                'select result_json from population_research_jobs where request_id=?',(self.request_id,)).fetchone()[0]
            after_routes=self.store.connection.execute(
                'select count(*) from population_hypothesis_route_history where request_id=?',(self.request_id,)).fetchone()[0]
        self.assertEqual(replay['status'], 'unchanged')
        self.assertEqual(replay['artifact_fingerprint'], result['artifact_fingerprint'])
        self.assertEqual(before_result,after_result)
        self.assertEqual(before_routes,after_routes)

        # A new connection observes both the artifact and the completed route payload.
        self.store.close()
        self.store = Store(Path(self.tmp.name) / 'join.sqlite3')
        saved = self.store.connection.execute('select artifact_fingerprint from population_local_archive_joins').fetchone()
        self.assertEqual(saved[0], result['artifact_fingerprint'])


    def test_inventory_market_context_strict_predecessor_ties_three_clocks_and_replay(self):
        from tamtam_again.population_inventory_market_context import VERSION as CONTEXT_VERSION
        bbo_equal={'channel':'bbo','data':{'coin':'ETH','time':1000,'bbo':[{'px':'10','sz':'3'},{'px':'11','sz':'4'}]}}
        l2_equal={'channel':'l2Book','data':{'coin':'ETH','time':1000,'levels':[[{'px':'10','sz':'7'}],[{'px':'11','sz':'8'}]]}}
        self._raw(40,'hyperliquid-websocket-v1','market','ETH','bbo',
            {'events':[{'received_at':self._stamp(4210),'message':bbo_equal}]},received=4210)
        self._raw(41,'hyperliquid-websocket-v1','market','ETH','l2Book',
            {'events':[{'received_at':self._stamp(4211),'message':l2_equal}]},received=4211)
        self.store.connection.commit()
        joined=execute_offline_archive_join(self.store,self.request_id)
        self.assertEqual(joined['inventory_market_context']['version'],CONTEXT_VERSION)
        row=self.store.connection.execute('select artifact_json,analysis_fingerprint from population_inventory_market_contexts').fetchone()
        artifact=json.loads(row['artifact_json']);by_id={x['fill_id']:x for x in artifact['fills']}
        matched=by_id['matched']
        self.assertEqual(matched['bbo']['event_ms'],950)
        self.assertEqual(matched['bbo_same_event_time']['count'],1)
        self.assertEqual(matched['bbo_same_event_time']['relative_order_to_fill'],'unknown')
        self.assertEqual(matched['l2book_same_event_time']['count'],1)
        self.assertEqual(matched['bbo']['age_to_fill_event_ms'],50)
        self.assertEqual(matched['bbo']['observation_ref']['event_index'],1)
        self.assertEqual(matched['bbo']['received_at_ms'],4202)
        self.assertEqual(matched['bbo']['lot_archived_at_ms'],4202)
        self.assertEqual(matched['fill_page_ref']['observation_id'],1)
        self.assertIn('received_at_minus_fill_page_received_ms',matched['bbo'])
        self.assertIn('lot_archived_minus_fill_page_received_ms',matched['bbo'])
        self.assertEqual(artifact['question_and_thresholds']['primary_age_ms'],30000)
        self.assertEqual(artifact['sensitivity_by_age']['1000']['all_fill_count'],3)
        self.assertTrue(any(x['position_side']=='long' and x['inventory_bucket'].startswith('inventory_')
            for x in artifact['coverage_by_day_segment_position']))
        self.assertEqual(artifact['primary_context_usable_count'],0)
        self.assertIsNone(matched['movement']['30s'])
        before=self.store.connection.execute('select count(*) from population_inventory_market_contexts').fetchone()[0]
        before_routes=self.store.connection.execute('select count(*) from population_hypothesis_route_history where request_id=?',(self.request_id,)).fetchone()[0]
        result_before=self.store.connection.execute('select result_json from population_research_jobs where request_id=?',(self.request_id,)).fetchone()[0]
        with patch('tamtam_again.population_local_join._decode_verified',side_effect=AssertionError('context replay must not decode archives')):
            replay=execute_offline_archive_join(self.store,self.request_id)
        after=self.store.connection.execute('select count(*) from population_inventory_market_contexts').fetchone()[0]
        result_after=self.store.connection.execute('select result_json from population_research_jobs where request_id=?',(self.request_id,)).fetchone()[0]
        after_routes=self.store.connection.execute('select count(*) from population_hypothesis_route_history where request_id=?',(self.request_id,)).fetchone()[0]
        self.assertEqual(replay['inventory_market_context']['status'],'unchanged')
        self.assertEqual(before,after)
        self.assertEqual(result_before,result_after)
        self.assertEqual(before_routes,after_routes)
        self.assertEqual(row['analysis_fingerprint'],replay['inventory_market_context']['analysis_fingerprint'])
        self.store.close()
        self.store=Store(Path(self.tmp.name)/'join.sqlite3')
        reopened=self.store.connection.execute('select analysis_fingerprint from population_inventory_market_contexts').fetchone()
        self.assertEqual(reopened[0],row['analysis_fingerprint'])

    def test_scheduler_executes_local_route_with_dispatch_disabled(self):
        policy = {'version': 'population-research-v1', 'max_requests': 1, 'max_packet_chars': 10000,
            'minimum_interval_ms': 1000, 'timeout_seconds': 30, 'max_output_tokens': 100,
            'max_request_age_ms': 10000, 'model': 'fixture', 'usage_mode': 'pay_as_you_go',
            'call_reservation_usd': '0.01'}
        result = tick(self.store, self.network, policy, dispatch=False, max_jobs=1)
        self.assertEqual(len(result['local_resolutions']), 1)
        self.assertEqual(result['local_resolutions'][0]['status'], 'prepared')
        self.assertEqual(result['local_resolutions'][0]['inventory_market_context']['status'],'prepared')
        contribution=result['local_resolutions'][0]['execution_contribution']
        self.assertEqual(contribution['status'],'prepared')
        self.assertEqual(contribution['version'],'population-eth-execution-contribution-v1')
        route = next(route for route in result['routes'] if route['request_id'] == self.request_id)
        self.assertEqual(route['state'], 'local_archive_analysis_complete')
        self.assertEqual(route['local_inventory_market_context']['version'],'population-inventory-market-context-v2')
        self.assertEqual(route['local_eth_execution_contribution']['analysis_fingerprint'],
            contribution['analysis_fingerprint'])
        self.assertEqual(result['processed'], [])
        replay=tick(self.store,self.network,policy,dispatch=False,max_jobs=1)
        replay_result=next(x for x in replay['local_resolutions'] if x['request_id']==self.request_id)
        self.assertEqual(replay_result['execution_contribution']['status'],'unchanged')
        self.assertEqual(replay_result['execution_contribution']['analysis_fingerprint'],
            contribution['analysis_fingerprint'])
        self.assertEqual(self.store.connection.execute(
            'select count(*) from population_eth_execution_contributions where request_id=?',
            (self.request_id,)).fetchone()[0],1)

    def test_completed_result_does_not_consume_slot_before_waiting_task(self):
        self._seed_completed_job('first','0x'+'8'*40,created_ms=4300)
        policy = {'version': 'population-research-v1', 'max_requests': 1, 'max_packet_chars': 10000,
            'minimum_interval_ms': 1000, 'timeout_seconds': 30, 'max_output_tokens': 100,
            'max_request_age_ms': 10000, 'model': 'fixture', 'usage_mode': 'pay_as_you_go',
            'call_reservation_usd': '0.01'}
        result=tick(self.store,self.network,policy,dispatch=False,max_jobs=1)
        statuses=[(r['request_id'],r['status']) for r in result['local_resolutions']]
        self.assertIn(('completed-first','unchanged'),statuses)
        self.assertIn((self.request_id,'prepared'),statuses)
        self.assertEqual(sum(status=='prepared' for _,status in statuses),1)
        self.assertEqual(result['processed'],[])

    def test_explicit_resume_rebuilds_stale_version_without_model_dispatch(self):
        # Complete v2-shaped output is eligible for the current v3 resolver.
        result_job=json.loads(self.store.connection.execute(
            'select result_json from population_research_jobs where request_id=?',(self.request_id,)).fetchone()[0])
        result_job['local_archive_join']={'version':'population-offline-archive-join-v2','state':'completed',
            'artifact_fingerprint':'old','artifact_path':'old.json.gz','source_fingerprint':'old',
            'model_calls':0,'collection_started':False,'matched_fills':3}
        self.store.connection.execute('update population_research_jobs set result_json=? where request_id=?',
            (canonical(result_job),self.request_id));self.store.connection.commit()
        policy={'version':'population-research-v1','max_requests':1,'max_packet_chars':10000,
            'minimum_interval_ms':1000,'timeout_seconds':30,'max_output_tokens':100,
            'max_request_age_ms':10000,'model':'fixture','usage_mode':'pay_as_you_go',
            'call_reservation_usd':'0.01'}
        result=tick(self.store,self.network,policy,dispatch=False,max_jobs=1,
            resume_local_resolution=self.request_id)
        self.assertEqual(result['processed'],[])
        self.assertEqual(result['local_resolutions'][0]['status'],'prepared')
        self.assertEqual(result['local_resolutions'][0]['resolver_version'],VERSION)
        self.assertEqual(next(r for r in result['routes'] if r['request_id']==self.request_id)['state'],
            'local_archive_analysis_complete')

    def test_decoded_event_cap_fails_without_persisting_partial_artifact(self):
        with patch('tamtam_again.population_local_join.MAX_MARKET_EVENTS_PER_STREAM',1):
            with self.assertRaisesRegex(ValueError,'decoded-event bound'):
                execute_offline_archive_join(self.store,self.request_id)
        self.assertEqual(self.store.connection.execute(
            'select count(*) from population_local_archive_joins').fetchone()[0],0)

    def test_fill_page_after_sealed_cutoff_is_not_included(self):
        # A new receipt after cutoff changes the source set only when its recorded
        # page window itself is within cutoff; page-level evidence stays bounded.
        self._raw(99, 'hyperliquid-population-rest-v1', 'account', self.address,
                  'userFillsByTime', [{'coin': 'ETH', 'tid': 'late', 'time': 1200,
                  'startPosition': '3', 'side': 'B', 'sz': '1', 'px': '13'}],
                  event_or_window=6000, received=7000)
        self.store.connection.commit()
        result = execute_offline_archive_join(self.store, self.request_id)
        artifact = json.loads(self.store.connection.execute(
            'select artifact_json from population_local_archive_joins where source_fingerprint=?',
            (result['source_fingerprint'],)).fetchone()[0])
        self.assertEqual([fill['fill_id'] for fill in artifact['fills']],
                         ['before-quotes', 'matched', 'strict-predecessor'])

    def test_quote_reader_supports_individual_and_batches_with_identity_and_cutoff_checks(self):
        single={'channel':'bbo','data':{'coin':'ETH','time':1000,'bbo':[
            {'px':'10','sz':'2'},{'px':'11','sz':'3'}]}}
        values,rejected,count,batched=_quote_values('bbo',single,'ETH',lot_received_ms=1100,cutoff_ms=1200)
        self.assertFalse(batched);self.assertEqual(count,1);self.assertEqual(len(values),1)
        self.assertEqual(values[0]['event_received_ms'],1100)
        self.assertEqual(values[0]['event_received_source'],'raw_observation.observed_at')

        batch={'events':[
            {'received_at':self._stamp(1005),'message':single},
            {'received_at':self._stamp(1006),'message':{**single,'data':{**single['data'],'time':1001}}},
            {'received_at':self._stamp(1007),'message':{**single,'data':{**single['data'],'coin':'BTC'}}},
            {'received_at':self._stamp(1300),'message':single},
            {'received_at':self._stamp(1008),'message':{**single,'data':{**single['data'],'time':1300}}},
        ]}
        values,rejected,count,batched=_quote_values('bbo',batch,'ETH',lot_received_ms=1150,cutoff_ms=1200)
        self.assertTrue(batched);self.assertEqual(count,5);self.assertEqual([v['event_index'] for v in values],[0,1])
        self.assertEqual(values[0]['event_received_ms'],1005)
        self.assertEqual(rejected,{'market_mismatch_or_missing':1,'event_receipt_after_cutoff':1,'event_time_after_cutoff':1})

        wrong_channel={**single,'channel':'l2Book'}
        _values,rejected,_count,_batched=_quote_values('bbo',wrong_channel,'ETH',lot_received_ms=1100,cutoff_ms=1200)
        self.assertEqual(rejected,{'channel_mismatch_or_missing':1})


if __name__ == '__main__':
    unittest.main()
