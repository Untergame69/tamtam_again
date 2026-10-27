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
    def test_untyped_provider_wake_cannot_crash_or_fragment_the_backlog(self):
        for name,wake in [('object',{'kind':{'anything':1},'diagnostic_code':['unknown']}),
                          ('huge',{'kind':'x'*10000,'diagnostic_code':'x'*10000})]:
            result=record(self.store,source_kind='population',source_id=name,
                source_result_fingerprint=name,work_id=name,
                assessment={'state':'technical','wake':wake},route={'state':'unsupported_mechanism'},clock_ms=100)
            self.assertEqual(result['kind'],'unsupported_mechanism')
            self.assertIsNone(result['condition']['diagnostic_code'])
        self.assertEqual(len(priority(self.store)),1)
    def test_resolved_or_superseded_work_is_preserved_but_not_prioritized(self):
        from tamtam_again.research_work_queue import initialize
        initialize(self.store)
        self.add('one');self.add('two')
        self.store.connection.execute('insert into research_work_queue values(?,?,?,?,?,?,?,?,?,?,?)',
            ('work:one','population_resolution','one','one','technical_required','missing',None,'{}',None,100,100))
        self.store.connection.execute('insert into research_work_queue values(?,?,?,?,?,?,?,?,?,?,?)',
            ('work:two','population_resolution','two','two','technical_required','missing',None,'{}',None,100,100))
        self.store.connection.commit()
        self.assertEqual(priority(self.store)[0]['affected_subjects'],2)
        self.store.connection.execute('insert into research_work_queue values(?,?,?,?,?,?,?,?,?,?,?)',
            ('resolved:one','population_resolution','one','new','completed','verified local resolution',None,'{}','{}',200,200))
        self.store.connection.commit()
        current=priority(self.store)[0]
        self.assertEqual(current['affected_subjects'],1)
        self.assertEqual(current['historical_affected_subjects'],2)
        self.store.connection.execute("update research_work_queue set status='completed' where work_id='work:two'")
        self.store.connection.commit()
        self.assertEqual(priority(self.store),[])
        self.assertEqual(self.store.connection.execute('select count(*) from research_technical_blocker_members').fetchone()[0],2)
