"""End-to-end research-cycle verification on an isolated SQLite fixture.

The fixture stores only raw archive rows and authorization metadata. The
production observer builds the report; the queue and pilot build/seal the
packet and contract; provider replies alone are simulated.
"""
import json
import gzip
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from tamtam_again.engine import canonical, fingerprint
from tamtam_again.eth_prospective_observation import SOURCE as ETH_SOURCE, VERSION as ETH_VERSION, init as init_observer, tick as observer_tick
from tamtam_again.population_pilot import tick_locked as pilot_tick
from tamtam_again.population_research import initialize as init_research, seal
from tamtam_again.population_scheduler import historical_research_gate, tick as scheduler_tick
from tamtam_again.research_work_queue import enqueue, eth_report_work_payload, initialize as init_queue, tick as queue_tick
from tamtam_again.storage import Store
from tamtam_again.validation import now_ms


ROOT = Path(__file__).resolve().parents[1]
PILOT_POLICY = json.loads((ROOT / 'config/research-loop-pilot-v2.json').read_text())
RESEARCH_POLICY = json.loads((ROOT / 'config/population-research-policy.json').read_text())
ADDRESS = '0x67f7aa8fb95c47e6ea9c517b623e0701cbf9d9ba'
PROTOCOL_ID = '67f7-eth-public-observation-24h-20261014-v1'
NETWORK = 'hyperliquid-mainnet'


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec='milliseconds')


class ResearchCycleIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'cycle.sqlite3'
        self.store = Store(self.path)
        self.artifact_dir = Path(self.tmp.name) / 'artifacts'
        self.written_artifacts = []
        init_research(self.store)
        self.store.connection.execute('''create table account_scope_reports (
            report_id text, network text, address text, available_ms integer, payload_json text)''')
        self.store.connection.execute('''create table population_historical_decisions (
            decision_id text, network text, address text, as_of_ms integer, status text, decision_json text)''')
        self.cutoff = PILOT_POLICY['admission']['cutoff_ms']
        scope = {'address': ADDRESS, 'markets': ['ETH'],
            'activity': {'observed_unique_fills': 2,
                'observed_fill_content_fingerprint': 'fixture-historical-fills'}}
        self.store.connection.execute('insert into account_scope_reports values(?,?,?,?,?)',
            ('scope-at-pilot-cutoff', NETWORK, ADDRESS, self.cutoff - 10, canonical(scope)))
        decision = {'economic_validation': False,
            'economic_research_readiness': {'status': 'not_approved', 'eligible_for_ai_research': False,
                'evidence_refs': ['fixture historical prescreen']}}
        self.store.connection.execute('insert into population_historical_decisions values(?,?,?,?,?,?)',
            ('historical-pilot-prescreen', NETWORK, ADDRESS, self.cutoff - 20,
                'credible_deep_dive_candidate', canonical(decision)))
        self.store.connection.commit()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _write_test_artifact(self, _repo_path, artifact):
        """Keep resolver output inside this test's disposable fixture."""
        path = self.artifact_dir / Path(_repo_path).name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(canonical(artifact).encode('utf-8'), mtime=0))
        self.written_artifacts.append(path)

    def _add_admitted_pilot_candidate(self, candidate, *, available_ms):
        item = next(row for row in PILOT_POLICY['selection'] if row['candidate'] == candidate)
        scope = {'address': item['address'], 'markets': item.get('descriptive_markets', ['ETH']),
            'activity': {'observed_unique_fills': 2,
                'observed_fill_content_fingerprint': 'fixture-' + candidate}}
        self.store.connection.execute('insert into account_scope_reports values(?,?,?,?,?)',
            ('scope-' + candidate, NETWORK, item['address'], available_ms, canonical(scope)))
        decision = {'economic_validation': False,
            'economic_research_readiness': {'status': 'not_approved',
                'eligible_for_ai_research': False, 'evidence_refs': ['test fixture']}}
        self.store.connection.execute('insert into population_historical_decisions values(?,?,?,?,?,?)',
            ('decision-' + candidate, NETWORK, item['address'], available_ms - 1,
                'credible_deep_dive_candidate', canonical(decision)))
        self.store.connection.commit()

    def _create_report_from_raw_archive(self):
        """Publish a report through the production observer over raw fixture rows."""
        end = now_ms() - 2_000
        start = end - 86_400_000
        protocol = {'protocol_id': PROTOCOL_ID, 'version': ETH_VERSION, 'network': NETWORK,
            'address': ADDRESS, 'market': 'ETH', 'start_ms': start,
            'checkpoint_ms': start + 21_600_000, 'end_ms': end,
            'poll_interval_ms': 300_000, 'horizon_ms': 60_000,
            'prefill_age_ms': 1_000, 'target_overshoot_ms': 5_000}
        init_observer(self.store, protocol)
        self.store.connection.execute("update eth_observation_runs set status='finalised',finalised_ms=? where protocol_id=?",
            (end, PROTOCOL_ID))

        fills = [
            {'coin': 'ETH', 'tid': 'open-1', 'oid': 1, 'time': start + 100_000, 'side': 'B',
                'crossed': True, 'startPosition': '0', 'sz': '1', 'px': '100', 'fee': '0.01', 'feeToken': 'USDC'},
            {'coin': 'ETH', 'tid': 'reduce-1', 'oid': 2, 'time': start + 300_000, 'side': 'B',
                'crossed': True, 'startPosition': '-1', 'sz': '0.5', 'px': '100', 'fee': '0.01', 'feeToken': 'USDC'},
        ]
        poll_id = 'fixture-final-fill-page'
        received_ms = start + 310_000
        request = {'type': 'userFillsByTime', 'user': ADDRESS, 'startTime': start,
            'endTime': end, 'observation_id': PROTOCOL_ID, 'poll_id': poll_id,
            'collection_kind': 'bounded_prospective_rest_page', 'live_user_websocket': False}
        self.store.connection.execute('''insert into eth_observation_polls
            (poll_id,protocol_id,start_ms,end_ms,status,requested_at,response_received_at,
             record_count,complete,updated_ms) values(?,?,?,?,?,?,?,?,?,?)''',
            (poll_id, PROTOCOL_ID, start, end, 'complete', iso(start + 1_000),
                iso(received_ms), len(fills), 1, received_ms))
        self.store.save_observation(network=NETWORK, source=ETH_SOURCE, entity_type='account',
            entity_id=ADDRESS, endpoint='userFillsByTime', payload=fills, request_payload=request,
            requested_at=iso(start + 1_000), window_start_ms=start, window_end_ms=end,
            record_count=len(fills), complete=True)
        self.store.connection.execute('update raw_observations set observed_at=? where endpoint=? and source=? and entity_id=?',
            (iso(received_ms + 100), 'userFillsByTime', ETH_SOURCE, ADDRESS))

        frames = []
        for stamp, mid in ((start + 99_000, 100), (start + 160_000, 99),
                (start + 299_000, 100), (start + 360_000, 101)):
            frames.append({'message': {'channel': 'bbo', 'data': {'coin': 'ETH', 'time': stamp,
                'bbo': [{'px': str(mid - 0.5), 'sz': '2'}, {'px': str(mid + 0.5), 'sz': '3'}]}},
                'received_at': iso(stamp + 50)})
        self.store.save_observation(network=NETWORK, source='hyperliquid-websocket-v1',
            entity_type='market', entity_id='ETH', endpoint='bbo', payload={'events': frames},
            requested_at=iso(start), record_count=len(frames), complete=True)
        self.store.connection.execute('update raw_observations set observed_at=? where endpoint=? and source=? and entity_id=?',
            (iso(start + 360_100), 'bbo', 'hyperliquid-websocket-v1', 'ETH'))
        self.store.connection.commit()
        published = observer_tick(self.store, protocol, now=end + 1)
        self.assertEqual(published['status'], 'finalised')
        self.assertEqual(published['report_status'], 'prepared')
        row = self.store.connection.execute('select input_fingerprint,report_json from eth_observation_reports '
            'where protocol_id=? and stage=?', (PROTOCOL_ID, 'final_24h')).fetchone()
        report = json.loads(row['report_json'])
        self.assertEqual(report['decision'], 'signal_exploratory_favorable')
        return report

    def test_raw_report_to_sealed_runtime_local_resolution_memory_route_and_next_admissible_packet(self):
        report = self._create_report_from_raw_archive()
        init_queue(self.store)
        work, created = enqueue(self.store, 'eth_observation_report', PROTOCOL_ID,
            eth_report_work_payload(PROTOCOL_ID, 'final_24h', report), status='ready',
            reason='fixture report published by observer', clock_ms=now_ms())
        self.assertTrue(created)

        prepared = queue_tick(self.store, clock_ms=now_ms(), pilot_policy=PILOT_POLICY)
        self.assertEqual(prepared['advanced'][0]['status'], 'analysis_ready')
        queue_payload = json.loads(self.store.connection.execute(
            'select payload_json from research_work_queue where work_id=?', (work['work_id'],)).fetchone()[0])
        request_id = queue_payload['request_id']
        job = self.store.connection.execute('select packet_json,status from population_research_jobs where request_id=?',
            (request_id,)).fetchone()
        packet_json = job['packet_json']
        packet = json.loads(packet_json)
        self.assertEqual(job['status'], 'sealed')
        self.assertIn('local_analysis_contract_v1', packet)
        self.assertEqual(packet['local_analysis_contract_v1']['source']['semantic_fingerprint'],
            queue_payload['semantic_fingerprint'])

        proposal = {'decision': 'hypothesis', 'diagnostic': 'A local archive join can resolve the request.',
            'wake': {}, 'hypothesis': {'mechanism': 'Descriptive association by inventory effect.',
                'type': 'autonomous', 'markets': ['ETH'], 'signal': 'Recorded inventory effect on archived fills.',
                'entry': 'Observe only.', 'exit': 'Measure the recorded 60 second outcome.',
                'sizing': 'Not applicable to an observational description.',
                'risk': 'No execution or profitability inference.',
                'horizon_justification': 'The report records a 60 second outcome.',
                'required_data': ['Join the report fills to the exact archived quote observations.'],
                'execution_constraints': 'No paper or orders.',
                'rejection_criteria': 'Reject if the referenced local archive cannot support the comparison.',
                'evidence_refs': [packet['local_analysis_contract_v1']['source']['report_ref']]}}
        critique = {'decision': 'consistent', 'diagnostic': 'The request is bounded to the sealed archive.', 'wake': {}}
        usage = {'cost_usd': 0, 'cost_status': 'included', 'input_tokens': 900,
            'output_tokens': 80, 'duration_ms': 12, 'model': PILOT_POLICY['task_policy']['model']}
        with patch('tamtam_again.population_runtime.verify'), patch(
                'tamtam_again.population_runtime.call', side_effect=[
                    (json.dumps(proposal), usage), (json.dumps(critique), usage)]) as provider:
            runtime = pilot_tick(self.store, PILOT_POLICY, dispatch=True, clock_ms=now_ms())
            self.assertEqual(provider.call_count, 2)
        self.assertEqual(runtime['route']['state'], 'local_archive_analysis_required')
        post_runtime = self.store.connection.execute('select packet_json,status from population_research_jobs where request_id=?',
            (request_id,)).fetchone()
        self.assertEqual(post_runtime['status'], 'hypothesis_recorded')
        self.assertEqual(post_runtime['packet_json'], packet_json)

        # Retain an older route row to verify that the current view selects the new decision only.
        old_route, _ = enqueue(self.store, 'population_route', request_id,
            {'request_id': request_id, 'state': 'needs_data', 'required_data': ['old waiting route']},
            status='waiting_data', reason='pre-resolution route', clock_ms=now_ms())
        with patch('tamtam_again.population_local_archive_resolution._write_artifact',
                side_effect=self._write_test_artifact) as artifact_writer:
            scheduled = scheduler_tick(self.store, NETWORK, RESEARCH_POLICY,
                dispatch=False, max_jobs=1)
        self.assertEqual(artifact_writer.call_count, 1)
        self.assertEqual(len(self.written_artifacts), 1)
        artifact_path = self.written_artifacts[0]
        self.assertTrue(artifact_path.is_file())
        artifact = json.loads(gzip.decompress(artifact_path.read_bytes()))
        self.assertEqual(artifact['analysis_fingerprint'], scheduled['local_resolutions'][0]['artifact_fingerprint'])
        persisted_artifact = self.store.connection.execute(
            'select artifact_json from population_local_archive_resolutions where request_id=?',
            (request_id,)).fetchone()
        self.assertEqual(artifact, json.loads(persisted_artifact['artifact_json']))
        self.assertEqual(scheduled['local_resolutions'][0]['status'], 'prepared')
        self.assertEqual(scheduled['local_resolutions'][0]['model_calls'], 0)
        self.assertEqual(scheduled['processed'], [])
        self.assertEqual(scheduled['memory'][0]['status'], 'recorded')
        current_route = next(r for r in scheduled['routes'] if r['request_id'] == request_id)
        self.assertEqual(current_route['state'], 'local_archive_analysis_complete')
        self.assertFalse(current_route['promotion_authorized'])
        self.assertFalse(current_route.get('paper_authorized', False))
        self.assertEqual(self.store.connection.execute(
            'select status from research_work_queue where work_id=?', (old_route['work_id'],)).fetchone()[0],
            'waiting_data')
        current_rows = self.store.connection.execute(
            "select work_id,status from research_work_queue_current where source_kind='population_route' and source_id=?",
            (request_id,)).fetchall()
        self.assertEqual(len(current_rows), 1)
        self.assertNotEqual(current_rows[0]['work_id'], old_route['work_id'])
        self.assertEqual(current_rows[0]['status'], 'completed')

        memory_id = scheduled['memory'][0]['knowledge_id']
        memory_item = json.loads(self.store.connection.execute(
            'select item_json from research_knowledge where knowledge_id=?', (memory_id,)).fetchone()[0])
        self.assertEqual(memory_item['status'], 'observed_descriptor')
        self.assertIn('population_resolution', [ref['kind'] for ref in memory_item['evidence_refs']])

        # An explicitly admitted general task with newer, authorized fixture evidence consumes that memory.
        # Advance the temporary database beyond the production 24 hour cooldown;
        # the test's explicit future cutoff is scoped to this disposable fixture.
        task_time = now_ms() + RESEARCH_POLICY['minimum_interval_ms'] + 1_000
        previous_request_ms = self.store.connection.execute(
            'select max(created_ms) from population_research_jobs where network=? and address=?',
            (NETWORK, ADDRESS)).fetchone()[0]
        self.assertLess(previous_request_ms, task_time)
        next_scope = {'address': ADDRESS, 'markets': ['ETH'],
            'activity': {'observed_unique_fills': 3,
                'observed_fill_content_fingerprint': 'fixture-newer-fills'}}
        self.store.connection.execute('insert into account_scope_reports values(?,?,?,?,?)',
            ('scope-for-next-admissible-task', NETWORK, ADDRESS, task_time - 100, canonical(next_scope)))
        approved = {'economic_validation': True,
            'economic_research_readiness': {'status': 'approved_for_re',
                'eligible_for_ai_research': True, 'evidence_refs': ['test-only explicit admission fixture']}}
        self.store.connection.execute('insert into population_historical_decisions values(?,?,?,?,?,?)',
            ('admission-for-next-fixture-task', NETWORK, ADDRESS, task_time - 10,
                'credible_deep_dive_candidate', canonical(approved)))
        self.store.save_observation(network=NETWORK, source='hyperliquid-population-rest-v1',
            entity_type='account', entity_id=ADDRESS, endpoint='userFillsByTime',
            payload=[{'coin': 'ETH', 'tid': 'newer-fill', 'time': task_time - 3_000}],
            requested_at=iso(task_time - 3), window_start_ms=task_time - 5,
            window_end_ms=task_time - 2, record_count=1, complete=True)
        self.store.connection.execute('update raw_observations set observed_at=? where endpoint=? and source=? and entity_id=?',
            (iso(task_time - 20), 'userFillsByTime', 'hyperliquid-population-rest-v1', ADDRESS))
        self.store.connection.commit()
        gate = historical_research_gate(self.store, NETWORK, ADDRESS,
            as_of_ms=task_time, max_requests=RESEARCH_POLICY['max_requests'])
        self.assertTrue(gate['allowed'], (gate, task_time, previous_request_ms,
            [dict(r) for r in self.store.connection.execute("select source,endpoint,observed_at,window_end_ms "
                "from raw_observations where network=? and entity_type='account' and entity_id=?",
                (NETWORK, ADDRESS))],
            [dict(r) for r in self.store.connection.execute("select request_id,created_ms,status "
                "from population_research_jobs where network=? and address=?", (NETWORK, ADDRESS))]))
        with patch('tamtam_again.research_memory.clock', return_value=task_time):
            next_job = seal(self.store, NETWORK, ADDRESS, RESEARCH_POLICY, clock_ms=task_time)
        self.assertEqual(next_job['status'], 'sealed')
        next_packet = json.loads(self.store.connection.execute(
            'select packet_json from population_research_jobs where request_id=?',
            (next_job['request_id'],)).fetchone()[0])
        self.assertEqual(next_packet['research_memory'][0]['knowledge_id'], memory_id)
        self.assertIn('knowledge:' + memory_id, next_packet['evidence_refs'])
        self.assertTrue(any(ref.startswith('population_resolution:') for ref in next_packet['evidence_refs']))

        counts_before = self.store.connection.execute('select count(*) from research_knowledge').fetchone()[0]
        artifact_table = self.store.connection.execute('select count(*) from population_local_archive_resolutions').fetchone()[0]
        with patch('tamtam_again.population_local_archive_resolution._write_artifact',
                side_effect=self._write_test_artifact) as replay_artifact_writer, \
                patch('tamtam_again.population_runtime.call', side_effect=AssertionError('replay must not call provider')), \
                patch('tamtam_again.population_local_archive_resolution._fills', side_effect=AssertionError('replay must not reload fills')), \
                patch('tamtam_again.population_local_archive_resolution._quotes', side_effect=AssertionError('replay must not reload quotes')):
            replay = scheduler_tick(self.store, NETWORK, RESEARCH_POLICY,
                dispatch=False, max_jobs=1, resume_local_resolution=request_id)
        self.assertEqual(replay_artifact_writer.call_count, 1)
        self.assertEqual(len(self.written_artifacts), 2)
        self.assertTrue(all(path.parent == self.artifact_dir for path in self.written_artifacts))
        self.assertEqual(self.written_artifacts[0], self.written_artifacts[1])
        self.assertEqual(json.loads(gzip.decompress(self.written_artifacts[1].read_bytes())), artifact)
        self.assertEqual(replay['local_resolutions'][0]['status'], 'unchanged')
        self.assertFalse(replay['local_resolutions'][0]['recalculated'])
        self.assertEqual(self.store.connection.execute('select count(*) from research_knowledge').fetchone()[0], counts_before)
        self.assertEqual(self.store.connection.execute('select count(*) from population_local_archive_resolutions').fetchone()[0], artifact_table)
        self.assertEqual(self.store.connection.execute('select packet_json from population_research_jobs where request_id=?',
            (request_id,)).fetchone()[0], packet_json)

    def test_rejected_candidate_does_not_block_next_candidate(self):
        from tamtam_again.population_pilot import initialize as init_pilot

        clock = now_ms()
        self._add_admitted_pilot_candidate('67f7', available_ms=self.cutoff - 100)
        self._add_admitted_pilot_candidate('be504', available_ms=self.cutoff - 100)
        init_pilot(self.store, PILOT_POLICY)
        rejected = {'decision': 'reject', 'diagnostic': 'The simulated evidence does not support this candidate.',
            'wake': {}}
        usage = {'cost_usd': 0, 'cost_status': 'included', 'input_tokens': 500,
            'output_tokens': 40, 'duration_ms': 10, 'model': PILOT_POLICY['task_policy']['model']}
        with patch('tamtam_again.population_runtime.verify'), patch(
                'tamtam_again.population_runtime.call',
                return_value=(json.dumps(rejected), usage)) as provider:
            first = pilot_tick(self.store, PILOT_POLICY, dispatch=True, clock_ms=clock)
            self.assertEqual(provider.call_count, 1)
        self.assertEqual(first['candidate'], '67f7')
        self.assertEqual(first['status'], 'reject')
        next_result = pilot_tick(self.store, PILOT_POLICY, dispatch=False, clock_ms=clock + 1)
        self.assertEqual(next_result['candidate'], 'be504')
        self.assertEqual(next_result['status'], 'sealed')
        terminal = next(row for row in next_result['prior_candidates'] if row['candidate'] == '67f7')
        self.assertEqual(terminal['status'], 'terminal_route')


if __name__ == '__main__':
    unittest.main()
