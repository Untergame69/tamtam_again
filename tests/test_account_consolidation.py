import copy
import unittest
from tamtam_again.account_consolidation import consolidate_equity


def value(scope,currency='USDC'):
    return {'scope_id':scope,'event_ms':100,'available_ms':110,
            'equity':'10','currency':currency,'capital_pool_id':scope,
            'capital_pool_evidence_ref':'fixture:pool','evidence_ref':'fixture:valuation'}


class ConsolidationTests(unittest.TestCase):
    def report(self,values):
        return consolidate_equity(values,event_ms=100,as_of_ms=200,currency='USDC',
            expected_scope_ids=['standard','spot'],perimeter_evidence_refs=['fixture:perimeter'])

    def test_independent_pools_and_shared_pool_refusal(self):
        values=[value('standard'),value('spot')]
        self.assertEqual(self.report(values)['equity'],'20')
        values[1]['capital_pool_id']='standard'
        self.assertIsNone(self.report(values)['equity'])

    def test_missing_scope_and_misaligned_time(self):
        self.assertIsNone(self.report([value('standard')])['equity'])
        v=value('spot');v['event_ms']=99
        self.assertIsNone(self.report([value('standard'),v])['equity'])

    def test_conversion_must_be_contemporaneous_and_available(self):
        v=value('spot','USDH')
        v['conversion']={'currency':'USDC','rate':'0.9','quote_ms':100,
                         'available_ms':120,'evidence_ref':'fixture:fx'}
        self.assertEqual(self.report([value('standard'),v])['equity'],'19.0')
        for changes in ({'available_ms':201},{'quote_ms':99},{'rate':'-1'}):
            changed=copy.deepcopy(v);changed['conversion'].update(changes)
            self.assertIsNone(self.report([value('standard'),changed])['equity'])

    def test_duplicate_scope_does_not_double_count(self):
        v=value('standard')
        self.assertIsNone(self.report([v,v,value('spot')])['equity'])
