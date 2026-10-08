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


class DurationPeriodTests(unittest.TestCase):
    def policy(self):
        return {'version':'observed-period-policy-v1','policy_id':'fixture',
            'justification':'fixture only','target_duration_ms':600,
            'start_tolerance_ms':50,'max_end_age_ms':100}

    def observed(self,stamps,as_of=1000):
        return {'as_of_ms':as_of,'conflicting_timestamps':[],
            'valuation_boundaries':[{'event_ms':t,'available_ms':t+1,
                'evidence_ref':'raw:'+str(t)} for t in stamps]}

    def test_ties_choose_older_exact_boundary_and_do_not_fallback_to_adjacent(self):
        from tamtam_again.account_periods import select_observed_period
        out=select_observed_period(self.observed([350,450,900,1000]),self.policy())
        self.assertEqual(out['chosen_period']['start_ms'],350)
        self.assertEqual(out['chosen_period']['end_ms'],1000)
        self.assertEqual(out['chosen_period']['duration_ms'],650)
        self.assertFalse(out['interpolation_applied'])
        self.assertEqual(out['chosen_period']['coverage_status'],'unknown')

    def test_missing_start_or_stale_end_stays_waiting(self):
        from tamtam_again.account_periods import select_observed_period
        self.assertEqual(select_observed_period(self.observed([900,1000]),self.policy())['status'],'awaiting_duration_boundary')
        self.assertEqual(select_observed_period(self.observed([300,900],as_of=1001),self.policy())['status'],'awaiting_recent_valuation')
        self.assertEqual(select_observed_period(self.observed([1000]),self.policy())['status'],'awaiting_two_timestamped_valuations')

    def test_invalid_policy_before_any_selection(self):
        from tamtam_again.account_periods import validate_period_policy
        for changes in ({'target_duration_ms':True},{'start_tolerance_ms':600},{'max_end_age_ms':-1},{'extra':1}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                validate_period_policy({**self.policy(),**changes})

    def test_unavailable_and_conflicting_valuations_cannot_be_selected(self):
        from tamtam_again.account_periods import select_observed_period
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)/'db') as store:
            from unittest.mock import patch
            for stamp,equity,received in [(350,'10',900),(400,'10',900),(400,'20',900),(1000,'10',1100),(1050,'10',1200)]:
                with patch('tamtam_again.storage.utc_now',return_value='1970-01-01T00:00:'+format(received/1000,'06.3f')+'+00:00'):
                    store.save_observation(network='test',source='hyperliquid-population-rest-v1',
                        entity_type='account',entity_id='fixture',endpoint='clearinghouseState',
                        payload={'time':stamp,'assetPositions':[],'marginSummary':{'accountValue':equity}})
            observed=observed_periods(store,'test','fixture',as_of_ms=1100)
            self.assertEqual(observed['conflicting_timestamps'],[400])
            out=select_observed_period(observed,self.policy())
            self.assertEqual(out['chosen_period']['start_ms'],350)
            self.assertEqual(out['chosen_period']['end_ms'],1000)
            self.assertEqual(out['chosen_period']['available_ms'],1100)
