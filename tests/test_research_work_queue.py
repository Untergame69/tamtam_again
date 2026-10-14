import json
import tempfile
import unittest
from pathlib import Path

from tamtam_again.storage import Store
from tamtam_again.research_work_queue import enqueue, set_status, tick


class WorkQueueTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'queue.sqlite3')

    def tearDown(self):
        self.store.close(); self.tmp.cleanup()

    def test_waiting_work_does_not_block_ready_and_replay_is_idempotent(self):
        waiting,_=enqueue(self.store,'deadline','eth-v1',{'at':10},status='waiting_deadline',wake_at_ms=10,clock_ms=1)
        enqueue(self.store,'population_route','blocked-1',{'state':'technical_required'},status='technical_required',reason='terminal issue',clock_ms=1)
        ready,created=enqueue(self.store,'eth_observation_report','useful-1',{'protocol_id':'useful-1','stage':'final_24h'},clock_ms=2)
        self.assertTrue(created)
        result=tick(self.store,clock_ms=2,max_jobs=1)
        self.assertEqual(result['advanced'][0]['work_id'],ready['work_id'])
        self.assertEqual(result['advanced'][0]['status'],'waiting_data')
        self.assertEqual(self.store.connection.execute('select status from research_work_queue where work_id=?',(waiting['work_id'],)).fetchone()[0],'waiting_deadline')
        same,created=enqueue(self.store,'eth_observation_report','useful-1',{'protocol_id':'useful-1','stage':'final_24h'},clock_ms=3)
        self.assertFalse(created);self.assertEqual(same['work_id'],ready['work_id'])

    def test_budget_and_technical_states_do_not_block_ready_work(self):
        budget,_=enqueue(self.store,'population_route','budget-1',{'state':'budget_required'},status='budget_exhausted',clock_ms=1)
        waiting,_=enqueue(self.store,'population_route','data-1',{'state':'needs_data'},status='waiting_data',clock_ms=1)
        other,_=enqueue(self.store,'eth_observation_report','other',{'protocol_id':'other','stage':'final_24h'},clock_ms=1)
        self.store.connection.execute('create table eth_observation_reports(protocol_id text,stage text,input_fingerprint text,report_json text,created_ms integer,primary key(protocol_id,stage))')
        self.store.connection.execute('insert into eth_observation_reports values(?,?,?,?,?)',('other','final_24h','fp',json.dumps({'decision':'review'}),1)); self.store.connection.commit()
        self.assertEqual(tick(self.store,clock_ms=2,max_jobs=1)['advanced'][0]['work_id'],other['work_id'])
        states={r['work_id']:r['status'] for r in self.store.connection.execute('select work_id,status from research_work_queue')}
        self.assertEqual(states[budget['work_id']],'budget_exhausted');self.assertEqual(states[waiting['work_id']],'waiting_data')

    def test_deadline_and_report_packet_persist_across_reopen(self):
        report={'decision':{'state':'review'},'coverage':{'fills':4},'summary':{'ok':True},
            'route':{'next_action':'human review'}}
        self.store.connection.execute('create table eth_observation_reports(protocol_id text,stage text,input_fingerprint text,report_json text,created_ms integer,primary key(protocol_id,stage))')
        self.store.connection.execute('insert into eth_observation_reports values(?,?,?,?,?)',('eth-v1','final_24h','fp',json.dumps(report),1));self.store.connection.commit()
        row,_=enqueue(self.store,'eth_observation_report','eth-v1',{'protocol_id':'eth-v1','stage':'final_24h'},clock_ms=1)
        out=tick(self.store,clock_ms=2,max_jobs=1)
        self.assertEqual(out['advanced'][0]['status'],'completed')
        self.assertEqual(self.store.connection.execute('select status from research_work_queue where work_id=?',(row['work_id'],)).fetchone()[0],'completed')
        outcome=json.loads(self.store.connection.execute('select outcome_json from research_work_queue where work_id=?',(row['work_id'],)).fetchone()[0])
        self.assertEqual(outcome['next_action'],'human review')
        self.store.close();self.store=Store(Path(self.tmp.name)/'queue.sqlite3')
        self.assertIsNotNone(self.store.connection.execute('select outcome_json from research_work_queue where work_id=?',(row['work_id'],)).fetchone()[0])
        self.assertEqual(tick(self.store,clock_ms=3)['advanced'],[])

    def test_expired_deadline_becomes_ready(self):
        row,_=enqueue(self.store,'eth_observation_report','x',{'protocol_id':'x','stage':'final_24h'},status='waiting_deadline',wake_at_ms=5,clock_ms=1)
        tick(self.store,clock_ms=5)
        self.assertEqual(self.store.connection.execute('select status from research_work_queue where work_id=?',(row['work_id'],)).fetchone()[0],'waiting_data')


if __name__=='__main__': unittest.main()
