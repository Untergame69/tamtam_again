import copy
import json
from pathlib import Path
import tempfile
import unittest
from tamtam_again.storage import Store
from tamtam_again.population_research import initialize as initialize_jobs
from tamtam_again.continuous_research_policy import (authorize_task, reserve_call, initialize,
    report, finish_task, mark_call_state, candidates_for_admission, DAY_MS)

POLICY = json.loads((Path(__file__).resolve().parents[1] / 'config/continuous-research-policy.json').read_text())


class ContinuousAllowanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'db.sqlite')
        initialize_jobs(self.store)
        self.policy = copy.deepcopy(POLICY)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def task(self, name, stamp=1, semantic=None):
        self.store.connection.execute('insert into population_research_jobs '
            '(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,updated_ms) '
            'values(?,?,?,?,?,?,?,\'sealed\',?)', (name, self.policy['network'], '0xabc', name,
            json.dumps({'fingerprint': name}), json.dumps(self.policy['task_policy']), stamp, stamp))
        self.store.connection.commit()
        return authorize_task(self.store, self.policy, request_id=name, candidate='abc:BTC', address='0xabc',
            market='BTC', packet_fingerprint_value=name, semantic_fingerprint_value=semantic or name, authorized_ms=stamp)

    def test_renewal_does_not_refund_failures_or_repeat_evidence(self):
        self.task('one')
        reserve_call(self.store, 'one', 1, self.policy, clock_ms=2)
        mark_call_state(self.store, 'one', 1, 'interrupted')
        finish_task(self.store, 'one', 'suspended')
        self.assertEqual(report(self.store, self.policy, clock_ms=3)['calls_reserved'], 1)
        with self.assertRaisesRegex(ValueError, 'semantic evidence'):
            self.task('repeat', DAY_MS + 1, 'one')
        self.task('fresh', DAY_MS + 1)
        reserve_call(self.store, 'fresh', 1, self.policy, clock_ms=DAY_MS + 2)
        self.assertEqual(report(self.store, self.policy, clock_ms=DAY_MS + 3)['calls_reserved'], 1)
        self.assertEqual(report(self.store, self.policy, clock_ms=3)['calls_reserved'], 1)

    def test_every_dimension_is_checked_before_dispatch(self):
        for key, limit in [('max_calls', 1), ('max_input_tokens', 80000), ('max_output_tokens', 5000), ('max_duration_ms', 120000)]:
            with self.subTest(key=key):
                self.policy = copy.deepcopy(POLICY)
                self.policy['policy_id'] = key
                self.policy['period_limits'][key] = limit
                self.task(key)
                reserve_call(self.store, key, 1, self.policy, clock_ms=2)
                mark_call_state(self.store, key, 1, 'result_validated')
                with self.assertRaisesRegex(ValueError, 'reservation exhausted'):
                    reserve_call(self.store, key, 2, self.policy, clock_ms=3)

    def test_task_ceiling_immutable_policy_expiry_and_no_retry(self):
        self.policy['period_limits']['max_tasks'] = 1
        self.task('first')
        with self.assertRaisesRegex(ValueError, 'task allowance exhausted'):
            self.task('second')
        reserve_call(self.store, 'first', 1, self.policy, clock_ms=2)
        with self.assertRaisesRegex(ValueError, 'already consumed'):
            reserve_call(self.store, 'first', 1, self.policy, clock_ms=3)
        with self.assertRaisesRegex(ValueError, 'expired'):
            reserve_call(self.store, 'first', 2, self.policy, clock_ms=DAY_MS + 1)
        changed = copy.deepcopy(self.policy); changed['period_limits']['max_tasks'] = 2
        with self.assertRaisesRegex(ValueError, 'immutable policy'):
            initialize(self.store, changed)

    def test_all_markets_and_multi_market_proof(self):
        rows = []
        for i in range(5):
            rows.append({'candidate_id': '0x'+str(i), 'candidate_alias': str(i),
                'disposition': 'admissible_descriptive', 'research_question': 'Describe.', 'source_ref': 'decision:'+str(i),
                'scope': {'markets': ['xyz:ABC'], 'market_count': 1, 'period_start_ms': 0, 'cutoff_ms': 100}})
        multi = copy.deepcopy(rows[0]); multi.update(candidate_id='0xmulti', candidate_alias='multi', disposition='needs_more_evidence')
        multi['scope'].update(markets=['BTC', 'ETH'], market_count=2)
        rows.append(multi)
        admission = {'candidate_evaluations': rows, 'priority_queue': rows[:3]}
        self.assertEqual(len(candidates_for_admission(admission)), 5)
        proof = {'period_start_ms': 0, 'cutoff_ms': 100, 'fills': 10, 'active_days': 2,
            'coverage': {'pagination': 'incomplete_lower_bound'}, 'evidence_ref': 'verified:1'}
        selected = candidates_for_admission(admission, market_evidence={('0xmulti', 'ETH'): proof})
        self.assertEqual(len(selected), 6)
        self.assertEqual(selected[-1]['descriptive_markets'], ['ETH'])
        proof['cutoff_ms'] = 101
        self.assertEqual(len(candidates_for_admission(admission, market_evidence={('0xmulti', 'ETH'): proof})), 5)

    def test_existing_runtime_uses_continuous_allowance_before_provider(self):
        from unittest.mock import patch
        from tamtam_again.population_runtime import execute_job
        self.task('runtime')
        proposal = {'decision': 'needs_data', 'diagnostic': 'Need prospective quote coverage.',
            'wake': {'condition': 'new authorized observations'}}
        usage = {'cost_usd': 0, 'cost_status': 'included', 'input_tokens': 1200,
            'output_tokens': 80, 'duration_ms': 40, 'model': self.policy['task_policy']['model']}
        def provider(*args, **kwargs):
            count = self.store.connection.execute('select count(*) from continuous_research_calls').fetchone()[0]
            self.assertEqual(count, 1)
            return json.dumps(proposal), usage
        row = self.store.connection.execute('select * from population_research_jobs where request_id=?', ('runtime',)).fetchone()
        with patch('tamtam_again.population_runtime.now_ms', return_value=2), patch(
                'tamtam_again.population_runtime.verify'), patch(
                'tamtam_again.population_runtime.call', side_effect=provider) as call:
            outcome = execute_job(self.store, 'runtime', row)
        self.assertEqual(outcome['status'], 'needs_data')
        call.assert_called_once()
        self.assertEqual(report(self.store, self.policy, clock_ms=3)['calls_reserved'], 1)
        self.assertEqual(self.store.connection.execute('select state from continuous_research_tasks').fetchone()[0], 'needs_data')
