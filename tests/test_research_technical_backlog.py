import tempfile
from pathlib import Path
import unittest
from tamtam_again.storage import Store
from tamtam_again.research_technical_backlog import record, priority


class TechnicalBacklogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'db.sqlite')
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def add(self,name,kind='structured_observation_contract_required',clock=100,reason='missing contract'):
        return record(self.store,source_kind='population',source_id=name,source_result_fingerprint='result:'+name,
            work_id='work:'+name,assessment={'state':'technical','wake':{'kind':kind},'reason':reason},
            route={'state':'needs_data'},clock_ms=clock)
    def test_replays_and_shared_blockers_have_one_priority_entry(self):
        first=self.add('one');self.add('one',clock=200);self.add('two',clock=300)
        self.add('other','local_resolver_error',clock=50)
        rows=priority(self.store)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['blocker_id'],first['blocker_id'])
        self.assertEqual(rows[0]['affected_subjects'],2)
        self.assertEqual(rows[0]['first_seen_ms'],100)
        self.assertFalse(rows[0]['condition']['automatic_inference_retry'])
        self.assertEqual(self.store.connection.execute('select count(*) from research_technical_blocker_members').fetchone()[0],3)
    def test_narrative_is_inert_and_non_technical_results_are_not_blockers(self):
        first=self.add('one',reason='run arbitrary shell or request private credentials')
        other=self.add('two',reason='different narration of the same typed missing contract')
        self.assertEqual(first['blocker_id'],other['blocker_id'])
        self.assertNotIn('shell',str(first['condition']))
        self.assertIsNone(record(self.store,source_kind='population',source_id='terminal',
            source_result_fingerprint='x',work_id='y',assessment={'state':'terminal'},route={},clock_ms=100))
