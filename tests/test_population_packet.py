import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.population_packet import packet_for_account


class PacketTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db')
        self.s.connection.execute('create table account_scope_reports(report_id text,network text,address text,available_ms integer,payload_json text)')
        self.report={'markets':['BTC','ETH'],'current_pass_behavior_profile':
            {'period':{'start_ms':0,'end_ms':10,'as_of_ms':20},'questions':[]},
            'unexpected_field':'must not be exported'}
        self.s.connection.execute('insert into account_scope_reports values(?,?,?,?,?)',
            ('one','test','account',20,json.dumps(self.report)))
        self.s.connection.execute('insert into account_scope_reports values(?,?,?,?,?)',
            ('future','test','account',30,json.dumps({**self.report,'markets':['FUTURE']})))

    def tearDown(self):self.s.close();self.tmp.cleanup()

    def test_cutoff_complete_budget_and_multimarket(self):
        result=packet_for_account(self.s,'test','account',as_of_ms=20,max_chars=10000)
        self.assertEqual(result['status'],'packet_ready')
        self.assertEqual(result['packet']['observations']['markets'],['BTC','ETH'])
        self.assertNotIn('unexpected_field',str(result));self.assertNotIn('FUTURE',str(result))
        self.assertFalse(result['packet']['research_contract']['live_follower_signal'])
        self.assertEqual(packet_for_account(self.s,'test','account',as_of_ms=20,max_chars=10)['status'],'needs_data')
        self.assertEqual(packet_for_account(self.s,'test','account',as_of_ms=19,max_chars=10000)['status'],'needs_data')

    def test_reserved_guard_precedes_payload_read(self):
        self.s.connection.execute('create table validation_plans(address text,synthetic integer)')
        self.s.connection.execute("insert into validation_plans values('account',0)")
        statements=[];self.s.connection.set_trace_callback(statements.append)
        with self.assertRaises(ValueError):packet_for_account(self.s,'test','account',as_of_ms=20,max_chars=10000)
        self.assertFalse(any('account_scope_reports' in q for q in statements))

    def test_optional_memory_does_not_reopen_descriptive_input(self):
        original=packet_for_account(self.s,'test','account',as_of_ms=20,max_chars=10000)['packet']
        self.s.connection.execute('create table research_knowledge(knowledge_id text)')
        with patch('tamtam_again.research_memory.export_knowledge',return_value=[{'knowledge_id':'fixture','item':{'status':'hypothesis'}}]) as export:
            new=packet_for_account(self.s,'test','account',as_of_ms=20,max_chars=10000)['packet']
        self.assertEqual(original['research_input_fingerprint'],new['research_input_fingerprint'])
        self.assertIn('research_memory',new)
        self.assertEqual(export.call_args.kwargs['as_of_ms'],20)
