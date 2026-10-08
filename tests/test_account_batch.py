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
