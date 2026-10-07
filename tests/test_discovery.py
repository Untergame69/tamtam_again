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
