import tempfile
import unittest
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.adaptation import initialize,observe_population


class AdaptationTests(unittest.TestCase):
    def test_equal_volume_changed_content_is_new_information(self):
        from tamtam_again.population import cadence
        policy={'default_poll_seconds':60,'min_poll_seconds':1,'max_poll_seconds':60,
                'retention_fills':100,'retention_fraction':0.5}
        first={'coin':'BTC','time':10,'tid':1,'px':'100'}
        _,a=cadence(policy,[first,first],0,100)
        _,b=cadence(policy,[first],0,100)
        self.assertEqual(a,b)
        _,changed=cadence(policy,[{**first,'px':'101'}],0,100)
        self.assertEqual(a['observed_unique_fills'],changed['observed_unique_fills'])
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)/'db') as s:
            initialize(s)
            job={'network':'test','address':'fixture','attempt_id':'one'}
            self.assertEqual(observe_population(s,job,{'activity':a},100)['status'],'diagnostic_recorded')
            job['attempt_id']='two'
            self.assertEqual(observe_population(s,job,{'activity':b},101)['status'],'unchanged_no_reanalysis')
            self.assertEqual(observe_population(s,job,{'activity':changed},102)['status'],'diagnostic_recorded')

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
