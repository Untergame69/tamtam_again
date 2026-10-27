import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tamtam_again.continuous_research_resolution import resolve_result, poll_waits, _assessment, _typed_wait
from tamtam_again.engine import canonical, fingerprint
from tamtam_again.population_research import initialize as initialize_population
from tamtam_again.population_routing import route
from tamtam_again.research_work_queue import enqueue, initialize as initialize_queue
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

    def add_job(self, status, result, packet=None, identity=None):
        packet = packet or {'available_ms': 1000, 'observations': {}}
        packet.setdefault('fingerprint', fingerprint(packet))
        identity = identity or self.request_id
        self.store.connection.execute(
            'insert into population_research_jobs '
            '(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,result_json,updated_ms) '
            'values(?,?,?,?,?,?,?, ?,?,?)',
            (identity, 'fixture', 'fixture-account', fingerprint({'input': identity}),
             canonical(packet), '{}', 100, status, canonical(result), 100))
        self.store.connection.commit()

    def test_needs_data_text_becomes_durable_technical_task_without_acquisition(self):
        self.add_job('needs_data', {'critique': {'decision': 'needs_data',
            'diagnostic': 'Please fetch whatever might help.'}})
        result = resolve_result(self.store, 'population', self.request_id, clock_ms=500)
        self.assertEqual(result['state'], 'technical')
        self.assertEqual(result['queue_status'], 'technical_required')
        self.assertFalse(result['collection_started'])
        self.assertEqual(result['assessment']['wake'].get('kind'), 'structured_request_required')
        self.assertTrue(result['next_candidate'])
        self.assertEqual(result['assessment']['disposition'],'needs_data_contract_required')
        self.assertFalse(self.store.connection.execute(
            "select 1 from sqlite_master where type='table' and name='research_observation_plans'").fetchone())

    def test_structured_top_level_needs_data_is_registered_and_pollable(self):
        request = {'required_data_index': 0, 'source': 'public_rest_history',
            'endpoint': 'userFunding', 'start_ms': 100, 'end_ms': 800,
            'proof': 'pagination_coverage', 'decision_use': 'check archived funding'}
        result_body = {'proposal': {'decision': 'needs_data', 'diagnostic': 'Funding interval could change this descriptive conclusion.',
            'wake': {}, 'required_data': ['funding over selected interval'], 'observation_requests': [request]},
            'promotion_authorized': False, 'profitability_proven': False}
        self.add_job('needs_data', result_body)
        result = resolve_result(self.store, 'population', self.request_id, clock_ms=500)
        self.assertEqual(result['state'], 'waiting')
        self.assertEqual(result['queue_status'], 'waiting_deadline')
        self.assertEqual(result['assessment']['wake']['plan']['entries'][0]['state'], 'await_window_end')
        self.assertEqual(self.store.connection.execute(
            'select count(*) from research_observation_plans').fetchone()[0], 1)

    def test_structured_needs_data_from_critique_is_registered_without_hypothesis_promotion(self):
        request = {'required_data_index': 0, 'source': 'public_rest_history',
            'endpoint': 'userNonFundingLedgerUpdates', 'start_ms': 100, 'end_ms': 800,
            'proof': 'pagination_coverage', 'decision_use': 'check ledger events'}
        result_body = {'proposal': {'decision': 'hypothesis', 'hypothesis': {
            'mechanism': 'descriptive test', 'required_data': ['ledger coverage'], 'markets': ['ETH']}},
            'critique': {'decision': 'needs_data', 'diagnostic': 'Ledger data may resolve coverage.',
                'wake': {}, 'required_data': ['ledger coverage'], 'observation_requests': [request]},
            'promotion_authorized': False, 'profitability_proven': False}
        self.add_job('needs_data', result_body)
        result = resolve_result(self.store, 'population', self.request_id, clock_ms=500)
        self.assertEqual(result['state'], 'waiting')
        self.assertEqual(result['assessment']['wake']['plan']['entries'][0]['request'], request)
        self.assertEqual(self.store.connection.execute(
            "select status from population_research_jobs where request_id=?", (self.request_id,)).fetchone()[0], 'needs_data')

    def test_new_unstructured_result_closes_prior_wait_without_blocking_queue(self):
        request = {'required_data_index': 0, 'source': 'public_rest_history',
            'endpoint': 'userFunding', 'start_ms': 100, 'end_ms': 800,
            'proof': 'pagination_coverage', 'decision_use': 'check funding coverage'}
        self.add_job('needs_data', {'proposal': {'decision': 'needs_data',
            'diagnostic': 'Funding could matter.', 'wake': {}, 'required_data': ['funding'],
            'observation_requests': [request]}, 'promotion_authorized': False,
            'profitability_proven': False})
        first = resolve_result(self.store, 'population', self.request_id, clock_ms=500)
        self.assertEqual(first['queue_status'], 'waiting_deadline')
        self.store.connection.execute('update population_research_jobs set result_json=? where request_id=?',
            (canonical({'proposal': {'decision': 'needs_data', 'diagnostic': 'fetch relevant context', 'wake': {}},
                'promotion_authorized': False, 'profitability_proven': False}), self.request_id))
        self.store.connection.commit()
        second = resolve_result(self.store, 'population', self.request_id, clock_ms=600)
        self.assertEqual(second['queue_status'], 'technical_required')
        self.assertTrue(second['next_candidate'])
        self.assertEqual(self.store.connection.execute(
            'select status from research_work_queue where work_id=?', (first['work_id'],)).fetchone()[0], 'completed')

    def test_runtime_accepts_only_complete_typed_needs_data_requests(self):
        from tamtam_again.population_runtime import validate_response
        from tamtam_again.research import CallContractError
        request = {'required_data_index': 0, 'source': 'public_rest_history',
            'endpoint': 'userFunding', 'start_ms': 100, 'end_ms': 200,
            'proof': 'pagination_coverage', 'decision_use': 'inspect funding'}
        response = {'decision': 'needs_data', 'diagnostic': 'Funding may matter.',
            'wake': {}, 'required_data': ['funding interval'], 'observation_requests': [request]}
        self.assertIsNone(validate_response(response, {}))
        with self.assertRaises(CallContractError):
            validate_response({**response, 'observation_requests': []}, {})

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

    def seed_wait(self, *, end_ms=1000):
        initialize_queue(self.store)
        request = {'required_data_index': 0, 'source': 'public_rest_history',
            'endpoint': 'userFunding', 'start_ms': 10, 'end_ms': end_ms,
            'proof': 'pagination_coverage', 'decision_use': 'verify funding history'}
        plan = {'request_id': self.request_id, 'network': 'fixture', 'address': 'fixture-account',
            'research_origin': 'population', 'required_data': ['funding'],
            'entries': [{'request': request, 'missing_observation': 'funding'}]}
        self.store.connection.execute('create table research_observation_plans '
            '(plan_id text primary key,request_id text,created_ms integer,plan_json text)')
        plan_id = fingerprint({'plan': self.request_id})
        self.store.connection.execute('insert into research_observation_plans values(?,?,?,?)',
            (plan_id, self.request_id, 1, canonical(plan)))
        self.store.connection.execute('create table research_need_collection_states '
            '(need_id text primary key,plan_id text,attempts integer,state text,updated_ms integer,evidence_json text,lease_token text)')
        work, _ = enqueue(self.store, 'population_resolution', self.request_id,
            {'source': self.request_id}, status='waiting_data', clock_ms=100)
        return plan, plan_id, request, work

    def test_verified_collection_wake_creates_one_changed_evidence_followup(self):
        plan, _, _, original = self.seed_wait()
        self.store.connection.execute('create table research_observation_wakes '
            '(request_id text primary key,available_ms integer,evidence_fingerprint text,evidence_json text)')
        wake_fp = fingerprint({'proofs': ['verified-fixture']})
        self.store.connection.execute('insert into research_observation_wakes values(?,?,?,?)',
            (self.request_id, 500, wake_fp, canonical({'proofs': ['verified-fixture']})))
        self.store.connection.commit()
        exported = [{'request_id': self.request_id, 'evidence_fingerprint': wake_fp,
            'available_ms': 500, 'pages': []}]
        with patch('tamtam_again.research_need_collection.export_wakes', return_value=exported):
            first = poll_waits(self.store, clock_ms=600)
            second = poll_waits(self.store, clock_ms=700)
        self.assertEqual(first['candidate_followups'][0]['state'], 'evidence_changed')
        self.assertTrue(first['candidate_followups'][0]['next_packet_required'])
        self.assertEqual(second['advanced'], [])
        self.assertEqual(self.store.connection.execute(
            "select count(*) from research_work_queue where source_kind='population_wake'").fetchone()[0], 1)
        self.assertEqual(self.store.connection.execute(
            'select status from research_work_queue where work_id=?', (original['work_id'],)).fetchone()[0], 'completed')

    def test_exhausted_collection_is_terminal_insufficient_and_never_retried_here(self):
        _, plan_id, request, work = self.seed_wait()
        need_id = fingerprint({'plan_id': plan_id, 'request': request})
        self.store.connection.execute('insert into research_need_collection_states values(?,?,?,?,?,?,?)',
            (need_id, plan_id, 2, 'collection_failed', 500, '{}', 'lease'))
        self.store.connection.commit()
        policy = {'version': 'research-need-collection-v1', 'policy_id': 'fixture',
            'justification': 'fixture', 'max_needs_per_job': 1, 'max_pages_per_need': 1,
            'max_attempts_per_need': 2}
        result = poll_waits(self.store, clock_ms=1200, collection_policy=policy)
        self.assertEqual(result['advanced'][0]['state'], 'insufficient_data_terminal')
        self.assertEqual(self.store.connection.execute(
            'select status from research_work_queue where work_id=?', (work['work_id'],)).fetchone()[0], 'completed')

    def test_poll_waits_rotates_across_more_work_than_one_limit(self):
        initialize_queue(self.store)
        ids = []
        for index in range(10):
            work, _ = enqueue(self.store, 'population_resolution', f'request-{index}',
                {'request_id': f'request-{index}'}, status='waiting_data', clock_ms=100+index)
            ids.append(work['work_id'])
        first = poll_waits(self.store, clock_ms=500, limit=3)
        first_cursor = self.store.connection.execute(
            'select last_work_id from continuous_research_wait_poll_cursor').fetchone()[0]
        second = poll_waits(self.store, clock_ms=600, limit=3)
        second_cursor = self.store.connection.execute(
            'select last_work_id from continuous_research_wait_poll_cursor').fetchone()[0]
        self.assertEqual(len(first['advanced']), 0)
        self.assertEqual(len(second['advanced']), 0)
        self.assertNotEqual(first_cursor, second_cursor)
        self.assertEqual(second_cursor, sorted(ids)[5])

    def test_reviewed_hypothesis_is_remembered_even_when_waiting_for_specification(self):
        result = {'proposal': {'hypothesis': {'mechanism': 'descriptive association',
            'markets': ['ETH'], 'required_data': [], 'rejection_criteria': 'no association',
            'execution_constraints': 'no execution', 'risk': 'exploratory'}},
            'critique': {'decision': 'consistent'}, 'promotion_authorized': False,
            'profitability_proven': False}
        self.add_job('hypothesis_recorded', result)
        resolved = resolve_result(self.store, 'population', self.request_id, clock_ms=500)
        self.assertEqual(resolved['state'], 'technical')
        self.assertTrue(resolved['memory'])
        self.assertEqual(self.store.connection.execute('select count(*) from research_knowledge').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
