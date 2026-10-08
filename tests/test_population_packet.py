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
        with patch('tamtam_again.research_memory.export_knowledge',return_value=[{'knowledge_id':'fixture','created_ms':22,'item':{'status':'hypothesis'}}]) as export:
            new=packet_for_account(self.s,'test','account',as_of_ms=25,max_chars=10000)['packet']
        self.assertEqual(original['research_input_fingerprint'],new['research_input_fingerprint'])
        self.assertIn('research_memory',new)
        self.assertEqual(export.call_args.kwargs['as_of_ms'],25)
        self.assertEqual(new['available_ms'],22)

    def test_order_evidence_is_causal_and_changes_input_only_for_content(self):
        original=packet_for_account(self.s,'test','account',as_of_ms=20,max_chars=10000)['packet']
        self.s.connection.execute('create table population_order_reports(report_id text,network text,address text,available_ms integer,payload_json text)')
        report={'network':'test','address':'account','available_ms':25,
            'descriptor':{'content_fingerprint':'new-orders','order_lifecycle_complete':False},'limits':['partial orders']}
        self.s.connection.execute('insert into population_order_reports values(?,?,?,?,?)',('orders','test','account',25,json.dumps(report)))
        early=packet_for_account(self.s,'test','account',as_of_ms=20,max_chars=10000)['packet']
        later=packet_for_account(self.s,'test','account',as_of_ms=25,max_chars=10000)['packet']
        self.assertEqual(early['research_input_fingerprint'],original['research_input_fingerprint'])
        self.assertNotEqual(later['research_input_fingerprint'],original['research_input_fingerprint'])
        self.assertEqual(later['available_ms'],25)
        self.assertFalse(later['observations']['public_orders']['order_lifecycle_complete'])

    def lending(self,value,available,source='hyperliquid-population-rest-v1'):
        from datetime import datetime,timezone
        stamp=datetime.fromtimestamp(available/1000,timezone.utc).isoformat()
        self.s.save_observation(network='test',source=source,entity_type='account',entity_id='account',
            endpoint='borrowLendUserState',payload={'tokenToState':[[0,{'borrow':{'basis':'10','value':value},'supply':{'basis':'0','value':'0'}}]],'health':'atRisk'},
            request_payload={'type':'borrowLendUserState','user':'account','receipt_marker':available},requested_at=stamp,complete=False)
        self.s.connection.execute('update raw_observations set observed_at=? where observation_id=(select max(observation_id) from raw_observations)',(stamp,))
        self.s.connection.commit()

    def test_lending_cutoff_and_content_change_not_receipt(self):
        original=packet_for_account(self.s,'test','account',as_of_ms=20,max_chars=20000)['packet']
        self.lending('11',25)
        early=packet_for_account(self.s,'test','account',as_of_ms=20,max_chars=20000)['packet']
        first=packet_for_account(self.s,'test','account',as_of_ms=25,max_chars=20000)['packet']
        self.assertEqual(original['research_input_fingerprint'],early['research_input_fingerprint'])
        self.assertNotEqual(original['research_input_fingerprint'],first['research_input_fingerprint'])
        self.assertEqual(first['observations']['public_lending']['tokens'][0]['borrow']['reported_value'],'11')
        self.assertEqual(first['available_ms'],25)
        self.lending('11.00',26)
        same=packet_for_account(self.s,'test','account',as_of_ms=26,max_chars=20000)['packet']
        self.assertEqual(first['research_input_fingerprint'],same['research_input_fingerprint'])
        self.lending('12',27)
        changed=packet_for_account(self.s,'test','account',as_of_ms=27,max_chars=20000)['packet']
        self.assertNotEqual(same['research_input_fingerprint'],changed['research_input_fingerprint'])
        self.assertIsNone(changed['observations']['public_lending']['equity'])
        self.assertFalse(changed['research_contract']['profitability_claim_authorized'])

    def test_lending_other_source_not_exported_and_full_budget_required(self):
        self.lending('11',25,source='other-source')
        packet=packet_for_account(self.s,'test','account',as_of_ms=25,max_chars=20000)['packet']
        self.assertNotIn('public_lending',packet['observations'])
        self.lending('12',26)
        result=packet_for_account(self.s,'test','account',as_of_ms=26,max_chars=1000)
        self.assertEqual(result['status'],'needs_data')
        self.assertIn('budget',result['reason'])
