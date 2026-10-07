import tempfile
import unittest
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.procedure_trace import registry_trace


class TraceTests(unittest.TestCase):
    def test_retirement_is_exported_at_its_own_time(self):
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)/'db') as s:
            s.connection.execute('create table paper_sessions(session_id text,variant_id text,started_ms integer)')
            s.connection.execute('create table paper_retirements(session_id text,retired_ms integer,reason text)')
            s.connection.execute("insert into paper_sessions values('old','variant',1000)")
            s.connection.execute("insert into paper_retirements values('old',3000,'operator free text')")
            early=registry_trace(s,as_of_ms=2000)
            self.assertEqual([e['kind'] for e in early['events']],['paper_session_started'])
            later=registry_trace(s,as_of_ms=3000)
            self.assertEqual([e['kind'] for e in later['events']],['paper_session_started','paper_session_retired'])
            self.assertEqual(later['events'][1]['available_ms'],3000)
            self.assertNotIn('operator free text',str(later))

    def test_latest_status_not_backdated(self):
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)/'db') as s:
            s.connection.execute('create table isolated_research_jobs(run_id text,plan_id text,input_fingerprint text,status text,reserved_cost_usd text,actual_cost_usd text,created_at text,updated_at text)')
            s.connection.execute("insert into isolated_research_jobs values('run','plan','input','failed','2','1','1970-01-01T00:00:01+00:00','1970-01-01T00:00:03+00:00')")
            early=registry_trace(s,as_of_ms=2000)
            self.assertEqual(len(early['events']),1)
            self.assertNotIn('failed',str(early))
            later=registry_trace(s,as_of_ms=3000)
            self.assertEqual(later['events'][1]['status'],'failed')
            self.assertIsNone(later['net_adaptation_result'])

    def test_future_freeze_not_exported(self):
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)/'db') as s:
            s.connection.execute('create table strategy_variants(variant_id text,plan_id text,frozen_ms integer)')
            s.connection.execute("insert into strategy_variants values('future','plan',3000)")
            self.assertEqual(registry_trace(s,as_of_ms=2000)['events'],[])
