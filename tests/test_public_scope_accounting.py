import unittest
from tamtam_again.public_scope_accounting import assess
from tamtam_again.account_events import normalize_event

A='0x'+'1'*40;B='0x'+'2'*40
class PublicScopeTests(unittest.TestCase):
    def run_report(self,**changes):
        data={'address':A,'scope':'perp:','mode':'disabled','mode_changed':False,
            'start_ms':100,'end_ms':900,'valuations':[
                {'event_ms':100,'equity':'100','unrealized_pnl':'0','positions':[],
                 'currency':'USDC','scope_id':'perp:','evidence_ref':'fixture:start'},
                {'event_ms':900,'equity':'120','unrealized_pnl':'5','positions':[],
                 'currency':'USDC','scope_id':'perp:','evidence_ref':'fixture:end'}],
            'component_report':{'observed':{'realized_pnl':'10','unrealized_change':'5',
                'fees_converted_observed':'1','funding':'2','other_income':'0'}},
            'ledger_events':[],'unsupported':[],
            'history_coverage':{e:{'pagination_status':'covered','evidence_refs':['fixture:'+e],
                'retention_proven':False,'status':'unknown'} for e in
                ('userFillsByTime','userFunding','userNonFundingLedgerUpdates')}}
        data.update(changes);return assess(**data)
    def send(self,source=A,destination=B,source_dex='',destination_dex='',amount='4',fee='0'):
        r=normalize_event('userNonFundingLedgerUpdates',{'time':500,'hash':'h',
            'delta':{'type':'send','user':source,'destination':destination,'sourceDex':source_dex,
                'destinationDex':destination_dex,'amount':amount,'token':'USDC','fee':fee,'nativeTokenFee':'0'}},
            address=A,available_ms=1000,evidence_ref='fixture:send')
        return r
    def test_measured_capital_change_is_distinct_from_attribution_and_validation(self):
        r=self.run_report();self.assertEqual(r['status'],'measured_public_scope')
        self.assertEqual(r['metrics']['net_capital_change'],'20')
        self.assertEqual(r['metrics']['observed_attribution_residual'],'4')
        self.assertFalse(r['attribution_complete']);self.assertFalse(r['account_economic_qualification'])
        self.assertFalse(r['coverage']['userFillsByTime']['retention_proven'])
    def test_send_flows_correct_scope_not_repeated_per_dex(self):
        e=self.send()['event'];self.assertEqual(e['amount'],'-4')
        r=self.run_report(ledger_events=[e]);self.assertEqual(r['metrics']['net_capital_change'],'24')
        e=self.send(source=B,destination=A)['event']
        self.assertEqual(self.run_report(ledger_events=[e])['metrics']['net_capital_change'],'16')
        e=self.send(source=A,destination=A,destination_dex='xyz')['event']
        self.assertEqual(e['amount'],'0')
        self.assertEqual(self.run_report(ledger_events=[e])['metrics']['net_capital_change'],'24')
        e=self.send(source_dex='xyz',destination_dex='spot')['event']
        self.assertEqual(self.run_report(ledger_events=[e])['metrics']['net_capital_change'],'20')
    def test_fee_scope_and_shared_mode_guards(self):
        self.assertEqual(self.send(fee='1')['status'],'unknown')
        for mode in ('unifiedAccount','portfolioMargin','unknown','dexAbstraction'):
            self.assertIsNone(self.run_report(mode=mode)['metrics']['net_capital_change'])
        self.assertIsNone(self.run_report(scope='perp:xyz')['metrics']['net_capital_change'])
        self.assertIsNone(self.run_report(mode_changed=True)['metrics']['net_capital_change'])
    def test_unclassified_ledger_and_missing_boundary_do_not_become_zero(self):
        r=self.run_report(unsupported=[{'endpoint':'userNonFundingLedgerUpdates','reason':'withdraw'}])
        self.assertIsNone(r['metrics']['external_flows'])
        self.assertIsNone(self.run_report(valuations=[])['metrics']['net_capital_change'])
        e={'event_ms':500,'amount':'100','evidence_ref':'fixture:deposit','kind':'flow'}
        self.assertIsNone(self.run_report(ledger_events=[e])['metrics']['net_capital_change'])
