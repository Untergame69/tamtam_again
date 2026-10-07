import tempfile
import unittest
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.qualification import qualify


class QualificationTests(unittest.TestCase):
    def test_shared_capital_ratio_not_reported_as_leverage(self):
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)/'db') as store:
            store.save_observation(network='test',source='fixture',entity_type='account',
                entity_id='fixture',endpoint='clearinghouseState',payload={
                    'marginSummary':{'accountValue':'10','totalNtlPos':'1000'},
                    'assetPositions':[]})
            observed=qualify(store,'test','fixture')['performance']['observed']
            self.assertEqual(observed['account_value'],'10')
            self.assertIsNone(observed['leverage'])

    def test_hip3_and_spot_not_summed_into_standard_dex(self):
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)/'db') as store:
            store.save_observation(network='test',source='fixture',entity_type='account',
                entity_id='fixture',endpoint='userFillsByTime',payload=[
                    {'coin':coin,'time':1,'tid':i,'closedPnl':'5','fee':'1','feeToken':'USDC'}
                    for i,coin in enumerate(['BTC','cash:BTC','@1','HYPE/USDC'])])
            store.save_observation(network='test',source='fixture',entity_type='account',
                entity_id='fixture',endpoint='clearinghouseState',
                request_payload={'dex':'cash'},payload={
                    'marginSummary':{'accountValue':'999','totalNtlPos':'1000'},
                    'assetPositions':[]})
            report=qualify(store,'test','fixture')
            self.assertEqual(report['performance']['observed']['realized_pnl'],'5')
            self.assertEqual(report['observability']['fills'],1)
            self.assertIsNone(report['performance']['observed']['account_value'])
