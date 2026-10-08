import json
import tempfile
import unittest
from pathlib import Path
from tamtam_again.storage import Store, decode_observation_payload
from tamtam_again.population import enroll, claim, collect_overview
from tamtam_again.account_acquisitions import group_acquisitions

POLICY={'version':'review','max_rest_accounts':2,'max_jobs_per_tick':1,'default_poll_seconds':3600,'min_poll_seconds':300,'max_poll_seconds':21600,'retention_fraction':.5,'retention_fills':10000,'lease_seconds':600,'retry_seconds':300,'initial_lookback_seconds':1,'sampling_seed':'review','history_max_pages_per_endpoint':2}
class Client:
    def post_info(self,q):
        if q['type']=='userAbstraction':return 'standard'
        if q['type']=='userRole':return {'role':'user'}
        if q['type']=='perpDexs':return [None,{'name':'xyz'}]
        if q['type']=='spotClearinghouseState':return {'balances':[]}
        if q['type']=='clearinghouseState':return {'time':1900,'marginSummary':{'accountValue':'100'},'assetPositions':[]}
        return []
class ReceiptTests(unittest.TestCase):
    def test_repeated_acquisitions_shared_inventory_and_identical_dex_content(self):
        with tempfile.TemporaryDirectory() as d, Store(Path(d)/'db') as s:
            for digit in ('1','2'):s.add_candidate('test','0x'+digit*40,'fixture')
            enroll(s,'test',POLICY,now_ms=1000)
            for pass_number in range(3):
                clock=1000 if pass_number<2 else s.connection.execute('select min(next_due_ms) from population_accounts').fetchone()[0]
                job=claim(s,'test',now_ms=clock)
                result=collect_overview(s,Client(),job,now_ms=2000)
                self.assertIsNotNone(result['dex_inventory_evidence_ref'])
                rows=s.connection.execute("select * from raw_observations where entity_id=? and entity_type='account'",(job['address'],)).fetchall()
                groups=group_acquisitions([(r,decode_observation_payload(r),json.loads(r['request_json'])) for r in rows])['groups']
                self.assertTrue(all(g['status']=='linked_inventory' for g in groups))
                self.assertTrue(all(g['dexes_observed']==['','xyz'] for g in groups))
            receipts=s.connection.execute("select receipt_id,requested_at,observed_at from raw_observations where endpoint='perpDexs'").fetchall()
            self.assertEqual(len(receipts),3)
            self.assertEqual(len({r['receipt_id'] for r in receipts}),3)
            self.assertTrue(all(r['requested_at']<=r['observed_at'] for r in receipts))
    def test_legacy_migration_does_not_create_receipts(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db'
            with Store(path) as s:
                s.save_observation(network='test',source='fixture',entity_type='account',entity_id='a',endpoint='x',payload={})
                before=dict(s.connection.execute('select * from raw_observations').fetchone())
                s.connection.execute('drop index uq_raw_receipt')
                s.connection.execute('alter table raw_observations drop column receipt_id')
                s.connection.execute('create unique index uq_raw_observation on raw_observations(response_sha256)')
                s.connection.commit()
            with Store(path) as s:
                after=dict(s.connection.execute('select * from raw_observations').fetchone())
                self.assertEqual(after,before)
