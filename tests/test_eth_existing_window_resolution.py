import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from tamtam_again.engine import canonical, fingerprint
from tamtam_again.eth_existing_window_resolution import (
    ADDRESS, END_MS, NETWORK, PROTOCOL_ID, REQUEST_ID, START_MS, VERSION,
    _classify, _join_contexts,
)
from tamtam_again.eth_report_projection import project, semantic_fingerprint
from tamtam_again.population_research import initialize as initialize_population
from tamtam_again.research_work_queue import enqueue, eth_report_work_payload, initialize as initialize_queue, set_status
from tamtam_again.storage import Store


ROOT = Path(__file__).resolve().parents[1]


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec='milliseconds')


def fixture_data():
    fills = []
    report_fills = []
    quote_events = []
    for index, (side, pre, size, crossed, order_id) in enumerate((
            ('B', '0', '1', True, 101), ('A', '1', '0.5', True, 101),
            ('A', '0.5', '1', False, 102), ('B', '-0.5', '0.5', False, 103))):
        stamp = START_MS + 100_000 + index * 100_000
        tid = f'fill-{index}'
        received = iso(stamp + 3_000)
        requested = iso(stamp + 1_000)
        archived = iso(stamp + 4_000)
        raw = {'coin': 'ETH', 'tid': tid, 'oid': order_id, 'time': stamp, 'side': side,
            'crossed': crossed, 'startPosition': pre, 'sz': size, 'px': str(2500 + index),
            'fee': '-0.001' if not crossed else '0.002', 'feeToken': 'USDC',
            'fill_page_observation_id': 100 + index, 'fill_page_sha256': f'{index+1:064x}',
            'fill_page_requested_at': requested, 'fill_page_received_at': received,
            'fill_page_archived_at': archived, 'poll_id': f'poll-{index}'}
        fills.append(raw)
        effect, close, opened, _ = _classify(raw)
        report_fills.append({'tid': tid, 'event_ms': stamp, 'side': side, 'crossed': crossed,
            'start_position': pre, 'size': size, 'price': raw['px'], 'fee': raw['fee'],
            'fee_token': 'USDC', 'action': effect, 'close_quantity': float(close),
            'open_quantity': float(opened), 'fill_page_observation_id': 100 + index,
            'fill_page_sha256': raw['fill_page_sha256'], 'fill_page_received_at': received,
            'fill_page_archived_at': archived, 'event_to_fill_page_receipt_ms': 3_000,
            'prefill_quote': None, 'future_quote': None,
            'event_time_markout_60s_bps': float(index - 1),
            'post_receipt_markout_60s_bps': float(1 - index),
            'receipt_baseline_quote': None, 'receipt_future_quote': None,
            'receipt_baseline_quote_ref': None, 'receipt_future_quote_ref': None})
        for channel in ('bbo', 'l2Book'):
            for quote_stamp in (stamp - 30_000, stamp - 1_000):
                event_index = len(quote_events)
                quote_events.append({'channel': channel, 'event_ms': quote_stamp,
                    'received_ms': quote_stamp + 100, 'event_received_ms': quote_stamp + 100,
                    'event_received_source': 'frame.received_at', 'archived_ms': quote_stamp + 200,
                    'connection_id': 'connection-1', 'observation_id': 700 + event_index,
                    'event_index': event_index, 'sha256': f'{event_index+1:064x}',
                    'bid': '2499', 'bid_size': '2', 'ask': '2501', 'ask_size': '3'})
        if index == 0:
            for channel in ('bbo', 'l2Book'):
                event_index = len(quote_events)
                quote_events.append({'channel': channel, 'event_ms': stamp,
                    'received_ms': stamp + 100, 'event_received_ms': stamp + 100,
                    'event_received_source': 'frame.received_at', 'archived_ms': stamp + 200,
                    'connection_id': 'connection-1', 'observation_id': 700 + event_index,
                    'event_index': event_index, 'sha256': f'{event_index+1:064x}',
                    'bid': '2499', 'bid_size': '2', 'ask': '2501', 'ask_size': '3'})
    fill_coverage = {'pages': [], 'page_count': 4, 'complete_page_count': 4,
        'incomplete_page_count': 0, 'unique_eth_fills': 4, 'duplicate_fill_instances': 0,
        'conflicting_fill_ids': [], 'source_fingerprint': 'fill-source-fingerprint'}
    by_channel = {channel: {'event_count': sum(q['channel'] == channel for q in quote_events),
        'max_received_gap_ms': 30_000} for channel in ('bbo', 'l2Book')}
    quote_refs = [{'observation_id': 700, 'endpoint': 'bbo', 'sha256': 'a'*64},
        {'observation_id': 701, 'endpoint': 'l2Book', 'sha256': 'b'*64}]
    quote_coverage = {'quotes': by_channel, 'rejected_events': {}, 'source_refs': quote_refs,
        'source_fingerprint': 'quote-source-fingerprint'}
    report = {'protocol_id': PROTOCOL_ID, 'protocol_fingerprint': 'protocol-fp',
        'stage': 'final_24h', 'input_fingerprint': 'final-report-input-fp',
        'decision': 'signal_exploratory_favorable', 'summary': {'all_fills': 4},
        'coverage': {'fills': {'page_count': 4, 'complete_page_count': 4,
            'incomplete_page_count': 0, 'unique_eth_fills': 4},
            'market': {'quotes': by_channel, 'source_fingerprint': 'quote-source-fingerprint',
                'source_refs': quote_refs, 'rejected_events': {}}},
        'fills': report_fills, 'quote_latency_ms': {}, 'stream_health': [],
        'limits': ['exploratory only'], 'generated_at_ms': END_MS + 4_000}
    return fills, report_fills, quote_events, fill_coverage, quote_coverage, report


class EthExistingWindowResolutionTests(unittest.TestCase):
    def test_strict_predecessor_excludes_same_time_and_preserves_local_clocks(self):
        fills, report_fills, quotes, _, _, _ = fixture_data()
        row = report_fills[0]
        joined = _join_contexts([row], fills, quotes)[0]
        bbo = joined['market_context']['bbo']
        self.assertEqual(bbo['strict_event_time_predecessor']['event_ms'], row['event_ms'] - 1_000)
        self.assertEqual(bbo['fill_timestamp_quote_count_relative_order_unknown'], 1)
        self.assertTrue(bbo['predecessor_available_by_rest_request_local_clock'])
        self.assertNotIn('available_at_execution', bbo)
        self.assertEqual(joined['event_time_markout_60s_bps'], row['event_time_markout_60s_bps'])
        self.assertEqual(joined['action'], 'opens')
        self.assertEqual(joined['market_context']['l2Book']['best_level_depth']['total_best_level_size'], '5')

    def test_inversion_splits_close_and_open_without_changing_fill_size(self):
        action, close, opened, post = _classify({'startPosition': '2', 'sz': '3', 'side': 'A'})
        self.assertEqual(action, 'inverts')
        self.assertEqual(close, 2)
        self.assertEqual(opened, 1)
        self.assertEqual(post, -1)

    def test_scheduler_executes_persists_and_replays_without_recalculation(self):
        from tamtam_again.population_scheduler import tick
        fills, report_fills, quote_events, fill_coverage, quote_coverage, report = fixture_data()
        semantic = semantic_fingerprint(report)
        projection = project(report)
        item = {'candidate': '67f7', 'rank': 1, 'research_interest': 'descriptive',
            'observability': 'archive-backed', 'paper_engine_compatibility': 'undetermined',
            'question': 'Use the exact existing ETH observation only.'}
        packet = {'schema_version': 'population-descriptive-pilot-adapter-v1',
            'network': NETWORK, 'address': ADDRESS, 'available_ms': START_MS - 1,
            'evidence_refs': [projection['source']['full_report_ref']], 'observations': {
                'markets': ['ETH'], 'prospective_eth_observation_v1': projection},
            'pilot_research': item, 'research_input_fingerprint': 'sealed-research-input',
            'limits': [], 'qualification': {}, 'research_contract': {}}
        packet['fingerprint'] = fingerprint(packet)
        request_text = f'Existing window {START_MS} through {END_MS} ms: join each fill and order.'
        result = {'proposal': {'decision': 'hypothesis', 'hypothesis': {
                'mechanism': 'Inventory-conditioned execution association', 'markets': ['ETH'],
                'signal': 'Descriptive fill state', 'required_data': [request_text, 'Join strict-prior market context from the existing archive.'],
                'rejection_criteria': 'No robust conditional association',
                'execution_constraints': 'No execution', 'risk': 'Exploratory only'}},
            'critique': {'decision': 'consistent', 'diagnostic': {'fidelity': 'descriptive'}, 'wake': {}},
            'promotion_authorized': False, 'profitability_proven': False}
        protocol = {'protocol_id': PROTOCOL_ID, 'network': NETWORK, 'address': ADDRESS,
            'market': 'ETH', 'start_ms': START_MS, 'end_ms': END_MS, 'version': 'eth-public-observation-v1'}
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / 'eth.sqlite3')
            try:
                initialize_population(store)
                store.connection.execute('insert into population_research_jobs '
                    '(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,result_json,updated_ms) '
                    'values(?,?,?,?,?,?,?,\'hypothesis_recorded\',?,?)',
                    (REQUEST_ID, NETWORK, ADDRESS, 'sealed-research-input', canonical(packet), '{}', START_MS,
                        canonical(result), START_MS))
                store.connection.execute('create table eth_observation_runs '
                    '(protocol_id text,status text,protocol_json text,finalised_ms integer)')
                store.connection.execute('insert into eth_observation_runs values(?,?,?,?)',
                    (PROTOCOL_ID, 'finalised', canonical(protocol), END_MS + 5_000))
                store.connection.execute('create table eth_observation_reports '
                    '(protocol_id text,stage text,input_fingerprint text,report_json text,created_ms integer,primary key(protocol_id,stage))')
                store.connection.execute('insert into eth_observation_reports values(?,?,?,?,?)',
                    (PROTOCOL_ID, 'final_24h', report['input_fingerprint'], canonical(report), END_MS + 5_000))
                initialize_queue(store)
                queue_payload = eth_report_work_payload(PROTOCOL_ID, 'final_24h', report)
                queue_row, _ = enqueue(store, 'eth_observation_report', PROTOCOL_ID, queue_payload,
                    status='completed', reason='superseded by final report', clock_ms=END_MS + 6_000)
                unrelated, _ = enqueue(store, 'eth_observation_report', 'unrelated-final-report',
                    {'protocol_id': 'unrelated-final-report', 'stage': 'final_24h'},
                    status='ready', reason='independent ready work', clock_ms=END_MS + 6_001)
                store.connection.commit()
                policy = json.loads((ROOT / 'config/population-research-policy.json').read_text())
                with patch('tamtam_again.eth_prospective_observation._fills', return_value=(fills, fill_coverage)) as fills_mock, \
                        patch('tamtam_again.eth_prospective_observation._quotes', return_value=(quote_events, quote_coverage)) as quotes_mock, \
                        patch('tamtam_again.eth_existing_window_resolution._write_artifact_file', return_value=Path(temp) / 'artifact.gz'):
                    first = tick(store, NETWORK, policy, dispatch=False, max_jobs=1)
                    self.assertEqual(first['local_resolutions'][0]['status'], 'prepared')
                    self.assertTrue(first['local_resolutions'][0]['recalculated'])
                    self.assertEqual(first['processed'], [])
                    self.assertEqual(first['sealed'], [])
                    self.assertEqual(first['local_resolutions'][0]['model_calls'], 0)
                    self.assertFalse(first['local_resolutions'][0]['collection_started'])
                    route = next(r for r in first['routes'] if r['request_id'] == REQUEST_ID)
                    self.assertEqual(route['state'], 'local_archive_analysis_complete')
                    self.assertEqual(route['followup_task']['kind'], 'eth_existing_window_analysis')
                    self.assertEqual(fills_mock.call_count, 1)
                    self.assertEqual(quotes_mock.call_count, 1)

                saved = store.connection.execute('select artifact_fingerprint,artifact_json from population_eth_existing_window_resolutions '
                    'where request_id=? and analysis_version=?', (REQUEST_ID, VERSION)).fetchone()
                artifact = json.loads(saved['artifact_json'])
                self.assertEqual(artifact['reconciliation']['fills_used_for_calculations'], 4)
                self.assertEqual(artifact['reconciliation']['statistics_exclude_packet_examples'], True)
                saved_job = store.connection.execute('select status,result_json from population_research_jobs where request_id=?',
                    (REQUEST_ID,)).fetchone()
                saved_result = json.loads(saved_job['result_json'])
                self.assertEqual(saved_job['status'], 'hypothesis_recorded')
                self.assertEqual(saved_result['proposal'], result['proposal'])
                self.assertEqual(saved_result['critique'], result['critique'])
                self.assertEqual(saved_result['local_eth_existing_window_resolution']['artifact_fingerprint'], saved['artifact_fingerprint'])
                queue_state = store.connection.execute('select status,reason from research_work_queue where work_id=?',
                    (queue_row['work_id'],)).fetchone()
                self.assertEqual(queue_state['status'], 'completed')
                self.assertEqual(queue_state['reason'], 'final report local analysis completed')
                unrelated_state = store.connection.execute('select status,reason from research_work_queue where work_id=?',
                    (unrelated['work_id'],)).fetchone()
                self.assertEqual(unrelated_state['status'], 'waiting_data')
                self.assertEqual(unrelated_state['reason'], 'final report is not durably persisted')

                with patch('tamtam_again.eth_prospective_observation._fills', side_effect=AssertionError('recalculated')), \
                        patch('tamtam_again.eth_prospective_observation._quotes', side_effect=AssertionError('recalculated')), \
                        patch('tamtam_again.eth_existing_window_resolution._write_artifact_file', return_value=Path(temp) / 'artifact.gz'):
                    replay = tick(store, NETWORK, policy, dispatch=False, max_jobs=1)
                self.assertEqual(replay['local_resolutions'][0]['status'], 'unchanged')
                self.assertFalse(replay['local_resolutions'][0]['recalculated'])
                self.assertEqual(store.connection.execute('select count(*) from population_eth_existing_window_resolutions '
                    'where request_id=?', (REQUEST_ID,)).fetchone()[0], 1)
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
