import tempfile
import unittest
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.adaptation import initialize,observe_population


class AdaptationTests(unittest.TestCase):
    def test_unchanged_and_replay_do_not_reopen_analysis(self):
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)/'db') as store:
            initialize(store)
            job={'network':'test','address':'fixture','attempt_id':'one'}
            report={'mode':'default','markets':['BTC'],'activity':{'observed_unique_fills':10}}
            self.assertEqual(observe_population(store,job,report,100)['status'],'diagnostic_recorded')
            self.assertEqual(observe_population(store,job,report,101)['status'],'already_recorded')
            job['attempt_id']='two'
            self.assertEqual(observe_population(store,job,report,102)['status'],'unchanged_no_reanalysis')
            report['markets'].append('ETH')
            self.assertEqual(observe_population(store,job,report,103)['status'],'diagnostic_recorded')
            payload=store.connection.execute('select payload_json from adaptation_events order by rowid desc limit 1').fetchone()[0]
            self.assertIn('"ai_call_authorized": false',payload)
            self.assertIn('"promotion_authorized": false',payload)
