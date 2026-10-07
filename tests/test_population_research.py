import json
import tempfile
import unittest
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.population_research import seal


class RegistryTests(unittest.TestCase):
    def test_unchanged_content_cooldown_and_global_budget(self):
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)/'db') as s:
            s.connection.execute('create table account_scope_reports(report_id text,network text,address text,available_ms integer,payload_json text)')
            policy={'version':'population-research-v1','max_requests':2,'max_packet_chars':10000,
                'minimum_interval_ms':10,'timeout_seconds':1,'max_output_tokens':100,'max_request_age_ms':1000,
                'model':'fixture','call_reservation_usd':'1'}
            report={'markets':['BTC','ETH'],'activity':{'observed_unique_fills':1,
                'observed_fill_content_fingerprint':'one'}}
            def add(identity,stamp,payload):
                s.connection.execute('insert into account_scope_reports values(?,?,?,?,?)',
                    (identity,'test','account',stamp,json.dumps(payload)));s.connection.commit()
            add('one',20,report)
            first=seal(s,'test','account',policy,clock_ms=100)
            self.assertEqual(first['status'],'sealed');self.assertEqual(first['model_calls'],0)
            add('same',101,report)
            self.assertEqual(seal(s,'test','account',policy,clock_ms=101)['request_id'],first['request_id'])
            report['activity']['observed_fill_content_fingerprint']='two';add('two',102,report)
            self.assertEqual(seal(s,'test','account',policy,clock_ms=102),{'status':'waiting','wake_ms':110})
            self.assertEqual(seal(s,'test','account',policy,clock_ms=110)['status'],'sealed')
            report['activity']['observed_fill_content_fingerprint']='three';add('three',120,report)
            self.assertEqual(seal(s,'test','account',policy,clock_ms=120)['status'],'budget_exhausted')
            old=s.connection.execute('select packet_json from population_research_jobs where request_id=?',(first['request_id'],)).fetchone()[0]
            self.assertEqual(json.loads(old)['evidence_refs'],['account_scope_reports:one'])
            self.assertEqual(s.connection.execute('select count(*) from population_research_jobs').fetchone()[0],2)
