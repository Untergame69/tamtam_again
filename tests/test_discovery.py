import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone
from tamtam_again.storage import Store
from tamtam_again.discovery import participants,record_window

def addr(n):return '0x'+format(n,'040x')
def event(n=1,stamp=1000):return {'channel':'trades','data':[{'coin':'BTC','time':stamp,'tid':n,'users':[addr(n),addr(99)]}]}
class DiscoveryTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db.sqlite3')
    def tearDown(self):self.s.close();self.tmp.cleanup()
    def test_more_than_ten_addresses_without_user_slots(self):
        events=[(datetime.fromtimestamp(2,timezone.utc).isoformat(),event(n)) for n in range(1,25)]
        reports=participants(self.s,'test','BTC',events)
        self.assertEqual(reports[0]['selected'],25)
        self.assertTrue(all(x['status']=='candidate' for x in self.s.candidates('test')))
        again=participants(self.s,'test','BTC',events)
        self.assertEqual(again[0]['new_candidates'],0)
        self.assertEqual(self.s.connection.execute('select count(*) from discovery_provenance').fetchone()[0],25)
    def test_repetition_does_not_weight_sample(self):
        receipt=datetime.fromtimestamp(2,timezone.utc).isoformat()
        events=[(receipt,event(n)) for n in range(1,25)]
        one=participants(self.s,'test','BTC',events,limit=3)
        two=participants(self.s,'test','BTC',events+[(receipt,event(1))]*100,limit=3)
        self.assertEqual(one[0]['window_id'],two[0]['window_id'])
    def test_future_data_and_reserved_accounts_excluded(self):
        self.s.connection.execute('create table validation_plans(address text,synthetic integer)')
        self.s.connection.execute('insert into validation_plans values (?,0)',(addr(1),));self.s.connection.commit()
        receipt=datetime.fromtimestamp(2,timezone.utc).isoformat()
        participants(self.s,'test','BTC',[(receipt,event(1)),(receipt,event(2,3000))])
        self.assertEqual([x['address'] for x in self.s.candidates('test')],[addr(99)])
    def test_multiple_sources_preserved(self):
        receipt=datetime.fromtimestamp(2,timezone.utc).isoformat()
        participants(self.s,'test','BTC',[(receipt,event(1))])
        record_window(self.s,network='test',source='leaderboard',market='*',start_ms=2000,end_ms=2000,available_ms=2000,version='ranking-v1',coverage={'status':'snapshot_only'},evidence={addr(1):{'rank':3}})
        self.assertEqual(self.s.connection.execute('select count(*) from discovery_provenance where address=?',(addr(1),)).fetchone()[0],2)
    def test_subscription_ranking_ignores_old_fills(self):
        from unittest.mock import patch
        from tamtam_again.websocket import _subscriptions
        from tamtam_again.storage import utc_now
        self.s.add_candidate('test',addr(1),'fixture')
        self.s.connection.execute("update candidates set status='tracked' where address=?",(addr(1),));self.s.connection.commit()
        now=200000
        self.s.save_observation(network='test',source='fixture',entity_type='account',entity_id=addr(1),endpoint='userFillsByTime',payload=[{'coin':'OLD','time':1,'px':'100000','sz':'1000','tid':1},{'coin':'RECENT','time':int(now*1000)-100,'px':'1','sz':'1','tid':2}],requested_at=utc_now())
        with patch('tamtam_again.websocket.time.time',return_value=now):
            accounts,markets,depth=_subscriptions(self.s,'test',30)
        self.assertEqual(markets,['RECENT'])

    def test_identical_window_replays_without_write_lock_and_repairs_missing_link(self):
        values=dict(network='test',source='ranking',market='*',start_ms=2000,end_ms=2000,
            available_ms=2000,version='ranking-v1',coverage={'status':'snapshot_only'},evidence={addr(1):{'rank':1}})
        first=record_window(self.s,**values)
        with Store(self.s.path) as writer:
            writer.connection.execute('begin immediate')
            self.s.connection.execute('pragma busy_timeout=1')
            replay=record_window(self.s,**values)
            self.assertEqual(replay['window_id'],first['window_id'])
            self.assertEqual(replay['new_candidates'],0)
            writer.connection.rollback()
        self.s.connection.execute('delete from discovery_provenance where window_id=?',(first['window_id'],))
        self.s.connection.commit()
        repaired=record_window(self.s,**values)
        self.assertEqual(repaired['window_id'],first['window_id'])
        self.assertEqual(self.s.connection.execute('select count(*) from discovery_provenance').fetchone()[0],1)

class LeaderboardProvenanceTests(unittest.TestCase):
    def test_rankings_preserved_without_financial_metrics(self):
        from tamtam_again.discovery import leaderboard_provenance
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)/'db') as store:
            rows=[{'address':addr(1),'window':'day','metric':'pnl','rank':1,'pnl':'999'},
                  {'address':addr(1),'window':'week','metric':'roi','rank':2,'roi':'99'}]
            result=leaderboard_provenance(store,'test','snapshot','2026-10-07T00:00:00+00:00',rows,10)
            self.assertEqual(result['selected'],1)
            proof=store.connection.execute('select evidence_json from discovery_provenance').fetchone()[0]
            self.assertNotIn('999',proof)
            self.assertIn('snapshot',proof)
            self.assertEqual(leaderboard_provenance(store,'test','snapshot','2026-10-07T00:00:00+00:00',rows,10)['new_candidates'],0)
