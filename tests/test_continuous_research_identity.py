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
