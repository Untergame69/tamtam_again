import copy,tempfile,unittest
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.recipe import synthetic_plan,synthetic_spec
from tamtam_again.experiment_allocation import bind_policy,plan_policy

class AllocationTests(unittest.TestCase):
    def setUp(self):
        self.policy={'version':'experiment-allocation-v1','policy_id':'fixture-v1',
            'justification':'synthetic test only','max_profile_variants':2,
            'plan_template':{'version':'population-plan-v1','justification':'fixture',
                'max_plans':1,'comparison_delay_ms':100,'comparison_duration_ms':1000,
                'selection_gap_ms':100,'final_duration_ms':1000,'isolation':'unavailable',
                'criteria':synthetic_plan()['criteria'],'budget':synthetic_plan()['budget']}}
        self.profile={'schema_version':1,'hypothesis_id':'fixture','justification':'fixture',
            'max_variants':2,'selection_rule':'comparison_then_one_final','axes':[
                {'parameter':'horizon_ms','values':[500,2500],'category':'hypothesis',
                 'justification':'fixture only','evidence_refs':['fixture:source'],'measurement_status':'simulated'}]}
    def test_external_policy_is_immutable_and_does_not_reset_plan_budget(self):
        with tempfile.TemporaryDirectory() as d,Store(Path(d)/'db') as s:
            first=bind_policy(s,self.policy)
            self.assertEqual(first,bind_policy(s,self.policy))
            changed=copy.deepcopy(self.policy);changed['plan_template']['criteria']['min_net_pnl']='-100'
            with self.assertRaisesRegex(ValueError,'immutable'):bind_policy(s,changed)
            self.assertEqual(s.connection.execute('select count(*) from experiment_allocation_policies').fetchone()[0],1)
    def test_windows_cover_submitted_footprint_without_raising_budgets(self):
        before=copy.deepcopy(self.policy)
        p=plan_policy(self.policy,self.profile,synthetic_spec())
        self.assertEqual(p['criteria']['block_ms'],2501)
        self.assertEqual(p['comparison_duration_ms'],2501*4)
        self.assertEqual(p['final_duration_ms'],2501*4)
        self.assertEqual(p['budget'],before['plan_template']['budget'])
        self.assertEqual(p['criteria']['min_net_pnl'],before['plan_template']['criteria']['min_net_pnl'])
        self.assertEqual(self.policy,before)
    def test_profile_cannot_enlarge_external_trial_cap(self):
        profile={**self.profile,'max_variants':3}
        with self.assertRaisesRegex(ValueError,'variant cap'):plan_policy(self.policy,profile,synthetic_spec())
