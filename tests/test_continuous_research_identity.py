import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tamtam_again.storage import Store
from tamtam_again.population_research import initialize
from tamtam_again.continuous_research_identity import semantic_identity, prior_equivalent


def packet():
    return {'network': 'net', 'address': '0xabc', 'observations': {
        'activity': {'observed_fill_content_fingerprint': 'whole-account'},
        'market_execution_detail_v1': {'BTC': {'market': 'BTC', 'cutoff_ms': 10,
            'observed_fill_content_fingerprint': 'exact-BTC-fill-ids-and-values',
            'execution_activity': {'fill_count': 10}, 'position_path': {'segments': {}},
            'by_utc_day': {'2026-10-01': {'fill_count': 10}}, 'fees_signed_by_token': {'USDC': '1'},
            'coverage': {'fill_archive': {'raw_observation_count': 1, 'last_observed_at': 'old'}},
            'reference_projection': {'ordered_reference_fingerprint': 'old', 'reference_count': 1}}}}}


class IdentityTests(unittest.TestCase):
    def test_equivalent_receipts_and_other_market_changes_do_not_reopen(self):
        original = packet(); changed = copy.deepcopy(original)
        detail = changed['observations']['market_execution_detail_v1']['BTC']
        detail['cutoff_ms'] = 20
        detail['coverage']['fill_archive'].update(raw_observation_count=2, last_observed_at='new', duplicate_fill_instances=10)
        detail['reference_projection'].update(ordered_reference_fingerprint='new', reference_count=2)
        changed['observations']['activity']['observed_fill_content_fingerprint'] = 'new-ETH-only-fill'
        changed['observations']['market_execution_detail_v1']['ETH'] = {'anything': 'new'}
        self.assertEqual(semantic_identity(original, 'BTC'), semantic_identity(changed, 'BTC'))

    def test_changed_fill_identity_changes_semantics_even_at_equal_aggregates(self):
        original = packet(); changed = copy.deepcopy(original)
        changed['observations']['market_execution_detail_v1']['BTC']['observed_fill_content_fingerprint'] = 'same-values-different-fill-ids'
        self.assertNotEqual(semantic_identity(original, 'BTC'), semantic_identity(changed, 'BTC'))

    def test_historical_attempt_is_deduplicated_and_fresh_ids_are_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'db.sqlite')
            try:
                initialize(store)
                old = packet()
                del old['observations']['market_execution_detail_v1']['BTC']['observed_fill_content_fingerprint']
                store.connection.execute('insert into population_research_jobs '
                    '(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,updated_ms) '
                    'values(?,?,?,?,?,?,?,?,?)', ('historical-failed', 'net', '0xabc', 'old-policy-input', json.dumps(old), '{}', 1, 'suspended', 1))
                store.connection.commit()
                with patch('tamtam_again.continuous_research_identity._legacy_fill_identity', return_value='exact-BTC-fill-ids-and-values'):
                    same = prior_equivalent(store, 'net', '0xabc', 'BTC', packet())
                    self.assertEqual(same['request_id'], 'historical-failed')
                    self.assertEqual(same['source_status'], 'suspended')
                with patch('tamtam_again.continuous_research_identity._legacy_fill_identity', return_value='older-distinct-fill-ids'):
                    self.assertIsNone(prior_equivalent(store, 'net', '0xabc', 'BTC', packet()))
                with patch('tamtam_again.continuous_research_identity._legacy_fill_identity', return_value=None):
                    self.assertTrue(prior_equivalent(store, 'net', '0xabc', 'BTC', packet())['legacy_aggregate_fallback'])
            finally:
                store.close()

    def test_legacy_hash_reads_exact_sealed_pages_and_deduplicates(self):
        from datetime import datetime, timezone
        import hashlib
        import zlib
        from tamtam_again.engine import canonical, fingerprint
        from tamtam_again.continuous_research_identity import _legacy_fill_identity
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'db.sqlite')
            try:
                fill = {'tid': 'actual-id', 'coin': 'BTC', 'time': 1, 'px': '10', 'sz': '1'}
                body = canonical([fill, fill]); digest = hashlib.sha256(body.encode()).hexdigest()
                stamp = datetime.fromtimestamp(.002, timezone.utc).isoformat(timespec='milliseconds')
                store.connection.execute('insert into raw_observations '
                    '(observation_id,network,source,entity_type,entity_id,endpoint,request_json,requested_at,observed_at,'
                    'window_start_ms,window_end_ms,record_count,complete,response_encoding,response_sha256,response_json,receipt_id) '
                    'values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (1, 'net', 'hyperliquid-population-rest-v1', 'account', '0xabc', 'userFillsByTime', '{}', stamp, stamp,
                     0, 2, 2, 0, 'zlib+json', digest, zlib.compress(body.encode()), 'receipt'))
                store.connection.commit()
                old = packet(); detail = old['observations']['market_execution_detail_v1']['BTC']
                detail['evidence_refs'] = ['raw_observations:1#sha256:' + digest]
                self.assertEqual(_legacy_fill_identity(store, old, 'BTC'), fingerprint([fill]))
                detail['cutoff_ms'] = 1
                self.assertIsNone(_legacy_fill_identity(store, old, 'BTC'))
            finally:
                store.close()

    def test_verified_new_requested_proof_reopens_same_fills_only_once(self):
        from tamtam_again.engine import fingerprint
        def with_wake(original, identity):
            result = copy.deepcopy(original)
            ref = 'raw_observations:' + identity
            evidence = {'proofs': [{'source_request': {'source': 'public_rest_history',
                'endpoint': 'userFunding', 'proof': 'pagination_coverage', 'start_ms': 1, 'end_ms': 2},
                'pagination_status': 'covered', 'evidence_refs': [ref]}],
                'promotion_authorized': False, 'economic_completeness_proven': False}
            result['observations']['completed_observation_requests'] = [{'request_id': identity,
                'available_ms': 3, 'evidence': evidence, 'evidence_fingerprint': fingerprint(evidence),
                'pages': [{'evidence_ref': ref, 'endpoint': 'userFunding', 'values': []}]}]
            result['evidence_refs'] = ['research_observation_wakes:' + identity, ref]
            return result
        base = packet(); first = with_wake(base, '1'); second = with_wake(base, '2')
        self.assertNotEqual(semantic_identity(base, 'BTC'), semantic_identity(first, 'BTC'))
        same = copy.deepcopy(first)
        same['observations']['completed_observation_requests'][0]['available_ms'] = 4
        self.assertEqual(semantic_identity(first, 'BTC'), semantic_identity(same, 'BTC'))
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'db.sqlite')
            try:
                initialize(store)
                store.connection.execute('insert into population_research_jobs '
                    '(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,updated_ms) '
                    'values(?,?,?,?,?,?,?,?,?)', ('wake1', 'net', '0xabc', 'wake1', json.dumps(first), '{}', 1, 'needs_data', 1))
                store.connection.commit()
                self.assertEqual(prior_equivalent(store, 'net', '0xabc', 'BTC', same)['request_id'], 'wake1')
                self.assertIsNone(prior_equivalent(store, 'net', '0xabc', 'BTC', second))
            finally:
                store.close()
        forged = copy.deepcopy(first); forged['evidence_refs'] = []
        with self.assertRaisesRegex(ValueError, 'provenance'):
            semantic_identity(forged, 'BTC')
        forged = copy.deepcopy(first)
        forged['observations']['completed_observation_requests'][0]['evidence']['proofs'][0]['pagination_status'] = 'incomplete'
        with self.assertRaisesRegex(ValueError, 'proof'):
            semantic_identity(forged, 'BTC')

    def test_continuous_history_uses_permanent_index_without_reparsing_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'db.sqlite')
            try:
                initialize(store)
                store.connection.execute('create table continuous_research_tasks '
                    '(request_id text primary key,network text,address text,market text,semantic_fingerprint text,'
                    'unique(network,address,market,semantic_fingerprint))')
                current = packet(); semantic = semantic_identity(current, 'BTC')
                store.connection.execute('insert into population_research_jobs '
                    '(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,updated_ms) '
                    'values(?,?,?,?,?,?,?,?,?)', ('continuous', 'net', '0xabc', 'input', json.dumps(current), '{}', 1, 'suspended', 1))
                store.connection.execute('insert into continuous_research_tasks values(?,?,?,?,?)',
                    ('continuous', 'net', '0xabc', 'BTC', semantic))
                store.connection.commit()
                with patch('tamtam_again.continuous_research_identity.json.loads', side_effect=AssertionError('must use persisted semantic index')):
                    self.assertEqual(prior_equivalent(store, 'net', '0xabc', 'BTC', current)['request_id'], 'continuous')
                    changed = copy.deepcopy(current)
                    changed['observations']['market_execution_detail_v1']['BTC']['observed_fill_content_fingerprint'] = 'fresh'
                    self.assertIsNone(prior_equivalent(store, 'net', '0xabc', 'BTC', changed))
            finally:
                store.close()

    def test_terminal_evaluation_facts_wake_unchanged_fills_without_metadata_retries(self):
        def with_feedback(original, outcomes, event='event-1', available=10):
            result = copy.deepcopy(original)
            result['research_evaluation_memory'] = [{'event_id': event, 'available_ms': available,
                'periods': [], 'evidence_refs': [{'kind': 'research_evaluation', 'id': event}],
                'item': {'version': 'research-evaluation-memory-v1', 'evaluation_event_id': event,
                    'profitability_proven': False, 'state': 'rejected', 'evidence': {'evaluations': outcomes}}}]
            return result
        base = packet()
        technical = with_feedback(base, [])
        self.assertEqual(semantic_identity(base, 'BTC'), semantic_identity(technical, 'BTC'))
        pending = with_feedback(base, [{'evaluation_id': 'eval-1', 'status': 'running'}])
        self.assertEqual(semantic_identity(base, 'BTC'), semantic_identity(pending, 'BTC'))
        first = with_feedback(base, [{'evaluation_id': 'eval-1', 'status': 'failed'}])
        self.assertNotEqual(semantic_identity(base, 'BTC'), semantic_identity(first, 'BTC'))
        republished = with_feedback(base, [{'evaluation_id': 'eval-1', 'status': 'failed', 'diagnostic': 'new metadata'},
            {'evaluation_id': 'eval-1', 'status': 'failed'}], event='republished-event', available=999)
        self.assertEqual(semantic_identity(first, 'BTC'), semantic_identity(republished, 'BTC'))
        second = with_feedback(base, [{'evaluation_id': 'eval-1', 'status': 'failed'}, {'evaluation_id': 'eval-2', 'status': 'passed'}])
        self.assertNotEqual(semantic_identity(first, 'BTC'), semantic_identity(second, 'BTC'))
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'db.sqlite')
            try:
                initialize(store)
                def save(name, body):
                    store.connection.execute('insert into population_research_jobs '
                        '(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,updated_ms) '
                        'values(?,?,?,?,?,?,?,?,?)', (name, 'net', '0xabc', name, json.dumps(body), '{}', 1, 'suspended', 1))
                    store.connection.commit()
                save('legacy-without-evaluation', base)
                self.assertIsNone(prior_equivalent(store, 'net', '0xabc', 'BTC', first))
                save('previous-evaluation', first)
                self.assertEqual(prior_equivalent(store, 'net', '0xabc', 'BTC', republished)['request_id'], 'previous-evaluation')
                self.assertIsNone(prior_equivalent(store, 'net', '0xabc', 'BTC', second))
            finally:
                store.close()

    def test_inactive_paper_economic_feedback_changes_identity_without_receipt_churn(self):
        original = packet()
        session = {'session_id': 'paper-1', 'status': 'stopped', 'position': '1',
            'pending': False, 'pending_count': 0, 'complete_flat_state': False,
            'diagnostics': ['incomplete exposure'], 'net_pnl': '-5', 'fees': '1', 'funding': '0',
            'source_period': {'start_ms': 1, 'end_ms': 10}}
        original['research_evaluation_memory'] = [{'event_id': 'event', 'available_ms': 10,
            'evidence_refs': [{'kind': 'research_evaluation', 'id': 'event'}],
            'item': {'version': 'research-evaluation-memory-v1', 'evaluation_event_id': 'event',
                'profitability_proven': False, 'evidence': {'sessions': [session]}}}]
        republished = copy.deepcopy(original)
        republished['research_evaluation_memory'][0]['available_ms'] = 99
        republished['research_evaluation_memory'][0]['item']['evidence']['sessions'][0]['source_period']['end_ms'] = 99
        self.assertEqual(semantic_identity(original, 'BTC'), semantic_identity(republished, 'BTC'))
        for field, value in [('position', '0'), ('net_pnl', '-6'), ('diagnostics', ['new terminal ledger diagnostic'])]:
            changed = copy.deepcopy(original)
            changed['research_evaluation_memory'][0]['item']['evidence']['sessions'][0][field] = value
            self.assertNotEqual(semantic_identity(original, 'BTC'), semantic_identity(changed, 'BTC'))
        active = copy.deepcopy(original)
        active['research_evaluation_memory'][0]['item']['evidence']['sessions'][0]['status'] = 'active'
        self.assertEqual(semantic_identity(packet(), 'BTC'), semantic_identity(active, 'BTC'))
        self.assertNotEqual(semantic_identity(packet(), 'BTC'), semantic_identity(original, 'BTC'))
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'db.sqlite')
            try:
                initialize(store)
                store.connection.execute('insert into population_research_jobs '
                    '(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,updated_ms) '
                    'values(?,?,?,?,?,?,?,?,?)', ('paper-feedback', 'net', '0xabc', 'input', json.dumps(original), '{}', 1, 'suspended', 1))
                store.connection.commit()
                self.assertEqual(prior_equivalent(store, 'net', '0xabc', 'BTC', republished)['request_id'], 'paper-feedback')
                self.assertIsNone(prior_equivalent(store, 'net', '0xabc', 'BTC', changed))
            finally:
                store.close()
