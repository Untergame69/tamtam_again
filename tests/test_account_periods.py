import tempfile
import unittest
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.account_periods import observed_periods


class PeriodTests(unittest.TestCase):
    def test_adjacent_periods_and_conflicting_boundary(self):
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)/'db') as store:
            for stamp,equity in [(100,'10'),(200,'10'),(300,'10'),(200,'20')]:
                store.save_observation(network='test',source='hyperliquid-population-rest-v1',
                    entity_type='account',entity_id='fixture',endpoint='clearinghouseState',
                    payload={'time':stamp,'assetPositions':[],
                             'marginSummary':{'accountValue':equity}})
            store.connection.execute("update raw_observations set observed_at='1970-01-01T00:00:01+00:00'")
            result=observed_periods(store,'test','fixture',as_of_ms=2000)
            self.assertEqual(result['conflicting_timestamps'],[200])
            self.assertEqual([(p['start_ms'],p['end_ms']) for p in result['periods']],[(100,300)])
            self.assertEqual(result['periods'][0]['coverage_status'],'unknown')
            self.assertEqual(observed_periods(store,'test','fixture',as_of_ms=999)['periods'],[])

    def test_reserved_account_refused(self):
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)/'db') as store:
            store.connection.execute('create table validation_plans(address text,synthetic integer)')
            store.connection.execute("insert into validation_plans values('fixture',0)")
            with self.assertRaises(ValueError):
                observed_periods(store,'test','fixture',as_of_ms=2000)
