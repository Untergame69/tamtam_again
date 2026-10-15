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
        report={'input_fingerprint':'fp','decision':'data_insufficient','coverage':{'fills':4},'summary':{'ok':True},
            'route':{'next_action':'human review'}}
        self.store.connection.execute('create table eth_observation_reports(protocol_id text,stage text,input_fingerprint text,report_json text,created_ms integer,primary key(protocol_id,stage))')
        self.store.connection.execute('insert into eth_observation_reports values(?,?,?,?,?)',('eth-v1','final_24h','fp',json.dumps(report),1));self.store.connection.commit()
        row,_=enqueue(self.store,'eth_observation_report','eth-v1',{'protocol_id':'eth-v1','stage':'final_24h'},clock_ms=1)
        out=tick(self.store,clock_ms=2,max_jobs=1)
        self.assertEqual(out['advanced'][0]['status'],'analysis_skipped')
        self.assertEqual(self.store.connection.execute('select status from research_work_queue where work_id=?',(row['work_id'],)).fetchone()[0],'analysis_skipped')
        outcome=json.loads(self.store.connection.execute('select outcome_json from research_work_queue where work_id=?',(row['work_id'],)).fetchone()[0])
        self.assertIn('do not call IA',outcome['next_action'])
        self.store.close();self.store=Store(Path(self.tmp.name)/'queue.sqlite3')
        self.assertIsNotNone(self.store.connection.execute('select outcome_json from research_work_queue where work_id=?',(row['work_id'],)).fetchone()[0])
        self.assertEqual(tick(self.store,clock_ms=3)['advanced'],[])

    def test_expired_deadline_becomes_ready(self):
        row,_=enqueue(self.store,'eth_observation_report','x',{'protocol_id':'x','stage':'final_24h'},status='waiting_deadline',wake_at_ms=5,clock_ms=1)
        tick(self.store,clock_ms=5)
        self.assertEqual(self.store.connection.execute('select status from research_work_queue where work_id=?',(row['work_id'],)).fetchone()[0],'waiting_data')

    def test_new_report_evidence_seals_once_and_records_lifecycle(self):
        from unittest.mock import patch
        from tamtam_again.research_work_queue import eth_report_semantic_fingerprint
        self.store.connection.execute('create table eth_observation_reports(protocol_id text,stage text,input_fingerprint text,report_json text,created_ms integer,primary key(protocol_id,stage))')
        report={'protocol_id':'eth-v1','protocol_fingerprint':'protocol-fp','stage':'final_24h','input_fingerprint':'source-fp',
            'decision':'signal_exploratory_unfavorable','coverage':{'fills':5},'summary':{'reduce_n':3},'fills':[{'id':1}],
            'quote_latency_ms':{},'limits':[],'generated_at_ms':22,'route':{'next_action':'review'}}
        self.store.connection.execute('insert into eth_observation_reports values(?,?,?,?,?)',('eth-v1','final_24h','source-fp',json.dumps(report),22));self.store.connection.commit()
        semantic=eth_report_semantic_fingerprint(report)
        row,_=enqueue(self.store,'eth_observation_report','eth-v1',{'protocol_id':'eth-v1','stage':'final_24h','semantic_fingerprint':semantic},clock_ms=22)
        sealed={'status':'analysis_ready','request_id':'research-1','packet_fingerprint':'packet-fp','model_calls':0}
        with patch('tamtam_again.population_pilot.seal_final_eth_observation',return_value=sealed) as seal:
            out=tick(self.store,clock_ms=23,pilot_policy={'pilot_id':'v2'})
            self.assertEqual(tick(self.store,clock_ms=24,pilot_policy={'pilot_id':'v2'})['advanced'],[])
        self.assertEqual(out['advanced'][0]['status'],'analysis_ready');seal.assert_called_once()
        states=[r[0] for r in self.store.connection.execute('select status from research_work_queue_events where work_id=? order by created_ms,event_id',(row['work_id'],))]
        self.assertIn('packet_prepared',states);self.assertIn('analysis_ready',states)

    def test_v2_budget_exhaustion_is_persisted_without_call(self):
        from unittest.mock import patch
        from tamtam_again.research_work_queue import eth_report_semantic_fingerprint
        self.store.connection.execute('create table eth_observation_reports(protocol_id text,stage text,input_fingerprint text,report_json text,created_ms integer,primary key(protocol_id,stage))')
        report={'protocol_id':'eth-v1','protocol_fingerprint':'p','stage':'final_24h','input_fingerprint':'s',
            'decision':'indeterminate','coverage':{},'summary':{},'fills':[],'quote_latency_ms':{},'limits':[],'route':{}}
        self.store.connection.execute('insert into eth_observation_reports values(?,?,?,?,?)',('eth-v1','final_24h','s',json.dumps(report),1));self.store.connection.commit()
        sem=eth_report_semantic_fingerprint(report)
        row,_=enqueue(self.store,'eth_observation_report','eth-v1',{'protocol_id':'eth-v1','stage':'final_24h','semantic_fingerprint':sem},clock_ms=1)
        with patch('tamtam_again.population_pilot.seal_final_eth_observation',return_value={'status':'budget_exhausted','reason':'v2 task allowance exhausted'}) as seal:
            result=tick(self.store,clock_ms=2,pilot_policy={'pilot_id':'v2'})
        self.assertEqual(result['advanced'][0]['status'],'budget_exhausted');seal.assert_called_once()
        saved=self.store.connection.execute('select status,reason from research_work_queue where work_id=?',(row['work_id'],)).fetchone()
        self.assertEqual(tuple(saved),('budget_exhausted','v2 task allowance exhausted'))

    def test_report_row_fingerprint_must_match_persisted_payload(self):
        report={'protocol_id':'eth-v1','protocol_fingerprint':'p','stage':'final_24h','input_fingerprint':'payload-fp',
            'decision':'data_insufficient','coverage':{},'summary':{},'fills':[],'quote_latency_ms':{},'limits':[]}
        self.store.connection.execute('create table eth_observation_reports(protocol_id text,stage text,input_fingerprint text,report_json text,created_ms integer,primary key(protocol_id,stage))')
        self.store.connection.execute('insert into eth_observation_reports values(?,?,?,?,?)',
            ('eth-v1','final_24h','different-row-fp',json.dumps(report),1));self.store.connection.commit()
        row,_=enqueue(self.store,'eth_observation_report','eth-v1',
            {'protocol_id':'eth-v1','stage':'final_24h'},clock_ms=1)
        out=tick(self.store,clock_ms=2)
        self.assertEqual(out['advanced'][0]['status'],'technical_required')
        saved=self.store.connection.execute('select status,reason from research_work_queue where work_id=?',(row['work_id'],)).fetchone()
        self.assertEqual(saved['status'],'technical_required')
        self.assertIn('fingerprint',saved['reason'])

    def test_semantic_dedup_ignores_serialization_time_but_sees_new_context(self):
        from tamtam_again.research_work_queue import eth_report_semantic_fingerprint, eth_report_work_payload
        report={'protocol_id':'eth-v1','protocol_fingerprint':'p','stage':'final_24h','input_fingerprint':'same-source',
            'decision':'indeterminate','coverage':{'fills':8},'summary':{'spread_context':'narrow'},
            'fills':[{'tid':'same'}],'quote_latency_ms':{},'limits':[],'generated_at_ms':100}
        original=eth_report_semantic_fingerprint(report)
        serialized_again={**report,'generated_at_ms':200}
        self.assertEqual(eth_report_semantic_fingerprint(serialized_again),original)
        first,created=enqueue(self.store,'eth_observation_report','eth-v1',
            eth_report_work_payload('eth-v1','final_24h',report),clock_ms=1)
        replay,created_again=enqueue(self.store,'eth_observation_report','eth-v1',
            eth_report_work_payload('eth-v1','final_24h',serialized_again),clock_ms=2)
        self.assertTrue(created);self.assertFalse(created_again);self.assertEqual(first['work_id'],replay['work_id'])
        enriched={**serialized_again,'summary':{'spread_context':'measured-and-added'}}
        self.assertNotEqual(eth_report_semantic_fingerprint(enriched),original)
        changed,created_enriched=enqueue(self.store,'eth_observation_report','eth-v1',
            eth_report_work_payload('eth-v1','final_24h',enriched),clock_ms=3)
        self.assertTrue(created_enriched);self.assertNotEqual(changed['work_id'],first['work_id'])


if __name__=='__main__': unittest.main()
