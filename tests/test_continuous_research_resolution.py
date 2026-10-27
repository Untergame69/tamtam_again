import json
import tempfile
import unittest
from pathlib import Path

from tamtam_again.continuous_research_resolution import resolve_result, _assessment, _typed_wait
from tamtam_again.engine import canonical, fingerprint
from tamtam_again.population_research import initialize as initialize_population
from tamtam_again.population_routing import route
from tamtam_again.storage import Store


class ContinuousResearchResolutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'research.sqlite3')
        initialize_population(self.store)
        self.request_id = 'fixture-request'

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def add_job(self, status, result, packet=None):
        packet = packet or {'available_ms': 1000, 'observations': {}}
        packet.setdefault('fingerprint', fingerprint(packet))
        self.store.connection.execute(
            'insert into population_research_jobs '
            '(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,result_json,updated_ms) '
            'values(?,?,?,?,?,?,?, ?,?,?)',
            (self.request_id, 'fixture', 'fixture-account', fingerprint({'input': 1}),
             canonical(packet), '{}', 100, status, canonical(result), 100))
        self.store.connection.commit()

    def test_needs_data_text_stays_waiting_and_does_not_create_acquisition(self):
        self.add_job('needs_data', {'critique': {'decision': 'needs_data',
            'diagnostic': 'Please fetch whatever might help.'}})
        result = resolve_result(self.store, 'population', self.request_id, clock_ms=500)
        self.assertEqual(result['state'], 'waiting')
        self.assertEqual(result['queue_status'], 'waiting_data')
        self.assertFalse(result['collection_started'])
        self.assertEqual(result['assessment']['wake'].get('kind'), 'structured_request_required')

    def test_terminal_result_is_idempotent_and_does_not_block_next_candidate(self):
        self.add_job('non_identifiable', {'critique': {'decision': 'non_identifiable',
            'diagnostic': {'reason': 'required mechanism is unobservable'}}})
        first = resolve_result(self.store, 'population', self.request_id, clock_ms=500)
        second = resolve_result(self.store, 'population', self.request_id, clock_ms=600)
        self.assertEqual(first['state'], 'terminal')
        self.assertTrue(first['next_candidate'])
        self.assertEqual(first['work_id'], second['work_id'])
        self.assertFalse(second['created'])
        self.assertEqual(self.store.connection.execute(
            'select count(*) from research_work_queue').fetchone()[0], 1)

    def test_only_typed_routes_create_actions(self):
        self.assertEqual(_assessment({}, {'state': 'local_archive_analysis_required'})['action'],
            'run_sealed_local_calculation')
        self.assertEqual(_assessment({}, {'state': 'technical_task_required'})['state'], 'technical')
        self.assertEqual(_assessment({}, {'state': 'reject'})['state'], 'terminal')
        self.assertEqual(_assessment({}, {'state': 'some_model_phrase'})['state'], 'no_new_question')

    def test_local_source_wait_has_a_poll_key_bound_to_sealed_source_and_deadline(self):
        packet = {'local_analysis_contract_v1': {'source': {'protocol_id': 'fixture-protocol',
            'stage': 'final_24h', 'input_fingerprint': 'source-fp'},
            'scope': {'start_ms': 1000, 'end_ms': 2000}}}
        row = {'request_id': self.request_id, 'packet_json': canonical(packet)}
        route_value = {'state': 'local_archive_data_required',
            'validation_diagnostic': {'code': 'source_not_finalised'}}
        wait = _typed_wait(self.store, row, {}, route_value, 1500)
        self.assertTrue(wait['pollable'])
        self.assertEqual(wait['deadline_ms'], 2000)
        self.assertEqual(wait['required_source']['input_fingerprint'], 'source-fp')


if __name__ == '__main__':
    unittest.main()
