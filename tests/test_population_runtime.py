import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tamtam_again.storage import Store
from tamtam_again.population_research import seal
from tamtam_again.population_runtime import run


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db')
        self.s.connection.execute('create table account_scope_reports(report_id text,network text,address text,available_ms integer,payload_json text)')
        report={'markets':['BTC','ETH'],'activity':{'observed_unique_fills':1,'observed_fill_content_fingerprint':'fixture'}}
        self.s.connection.execute('insert into account_scope_reports values(?,?,?,?,?)',('one','test','account',10,json.dumps(report)));self.s.connection.commit()
        policy={'version':'population-research-v1','max_requests':2,'max_packet_chars':10000,
            'minimum_interval_ms':10,'timeout_seconds':1,'max_output_tokens':100,
            'model':'fixture','call_reservation_usd':'1'}
        self.request=seal(self.s,'test','account',policy,clock_ms=20)['request_id']
        self.usage={'cost_usd':0,'cost_status':'included','duration_ms':1}

    def tearDown(self):self.s.close();self.tmp.cleanup()

    def test_open_hypothesis_and_review_never_promote(self):
        hypothesis={k:'fixture testable specification' for k in ('mechanism','signal','entry','exit','sizing','risk','horizon_justification','execution_constraints','rejection_criteria')}
        hypothesis.update(type='autonomous',markets=['BTC','ETH'],required_data=['causal price paths'],evidence_refs=['account_scope_reports:one'])
        proposal={'decision':'hypothesis','diagnostic':'fixture only','wake':{},'hypothesis':hypothesis}
        critique={'decision':'consistent','diagnostic':'testable fixture','wake':{}}
        with patch('tamtam_again.population_runtime.verify'),patch('tamtam_again.population_runtime.call',side_effect=[(json.dumps(proposal),self.usage),(json.dumps(critique),self.usage)]) as call:
            result=run(self.s,self.request)
            self.assertEqual(result['status'],'hypothesis_recorded');self.assertFalse(result['promotion_authorized'])
            self.assertEqual(run(self.s,self.request)['status'],'unchanged_no_inference');self.assertEqual(call.call_count,2)
        self.assertFalse(self.s.connection.execute("select 1 from sqlite_master where name='strategy_variants'").fetchone())

    def test_isolation_and_timeout_are_fail_closed(self):
        with patch('tamtam_again.population_runtime.verify',side_effect=RuntimeError),patch('tamtam_again.population_runtime.call') as call:
            with self.assertRaises(RuntimeError):run(self.s,self.request)
            call.assert_not_called()
        with patch('tamtam_again.population_runtime.verify'),patch('tamtam_again.population_runtime.call',side_effect=TimeoutError) as call:
            self.assertEqual(run(self.s,self.request)['status'],'suspended')
            self.assertEqual(run(self.s,self.request)['status'],'unchanged_no_inference');self.assertEqual(call.call_count,1)
        row=self.s.connection.execute('select reserved_cost_usd,actual_cost_usd from population_research_jobs').fetchone()
        self.assertEqual(row['reserved_cost_usd'],'2');self.assertIsNone(row['actual_cost_usd'])
