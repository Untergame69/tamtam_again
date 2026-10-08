import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from tamtam_again.account_batch import report_population


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(':memory:')
        self.store = SimpleNamespace(connection=self.connection)
        self.connection.execute('create table account_scope_reports(network text,address text,available_ms integer)')
        self.connection.executemany('insert into account_scope_reports values (?,?,?)',
            [('n','A',100),('n','a',200),('n','b',100),('n','c',1001),('other','d',100)])

    def tearDown(self):
        self.connection.close()

    def test_cutoff_network_dedup_and_protection_before_adapter(self):
        with patch('tamtam_again.account_batch.protected_addresses', return_value={'B'}), patch(
                'tamtam_again.account_batch.report_account', return_value={'economic_validation':False}) as adapter:
            out = report_population(self.store,'n',0,500,as_of_ms=1000)
        self.assertEqual(out['accounts_inventoried'],2)
        self.assertEqual(out['accounts_reported'],1)
        self.assertEqual(out['excluded_accounts'][0]['address'],'b')
        self.assertEqual(adapter.call_args.args[2],'a')
        self.assertEqual(out['economically_validated'],0)

    def test_failure_is_explicit_and_other_account_still_reported(self):
        with patch('tamtam_again.account_batch.protected_addresses', return_value=set()), patch(
                'tamtam_again.account_batch.report_account', side_effect=[ValueError('private payload'),{'economic_validation':True}]):
            out = report_population(self.store,'n',0,500,as_of_ms=1000)
        self.assertEqual(out['economically_validated'],1)
        self.assertEqual(out['failed_accounts'][0]['address'],'a')
        self.assertNotIn('private payload',str(out))

    def test_invalid_period_rejected_before_database_query(self):
        with self.assertRaises(ValueError):
            report_population(None,'n',0,1001,as_of_ms=1000)

    def test_observed_qualification_applies_to_all_accounts_without_financial_selection(self):
        from tamtam_again.account_batch import qualify_observed_population
        from unittest.mock import patch
        import json
        self.connection.row_factory=sqlite3.Row
        self.connection.execute('alter table account_scope_reports add column payload_json text')
        self.connection.execute("update account_scope_reports set payload_json=?",(json.dumps({'mode':'disabled'}),))
        p={'periods':[{'start_ms':100,'end_ms':500}]}
        with patch('tamtam_again.account_batch.protected_addresses',return_value={'b'}), patch(
            'tamtam_again.account_periods.observed_periods',return_value=p), patch(
            'tamtam_again.account_batch.report_account',return_value={'status':'public_scope_measured','economic_validation':False}) as adapter:
            result=qualify_observed_population(self.store,'n',as_of_ms=1000)
        self.assertEqual(result['accounts_considered'],2)
        self.assertEqual(adapter.call_count,2)
        self.assertEqual(result['public_scopes_measured'],2)
        self.assertEqual(result['economically_validated'],0)
