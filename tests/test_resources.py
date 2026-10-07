import unittest
from tamtam_again.resources import resource_change


class ResourceTests(unittest.TestCase):
    def sample(self,t,pid=1):
        return {'sampled_at':t,'database_identity':[1,2],'logical_live_page_bytes':t*10,
                'process':{'pid':pid,'start_ticks':3,'cpu_seconds':t*.5}}

    def test_growth_and_cpu_rate(self):
        r=resource_change(self.sample(1),self.sample(3))
        self.assertEqual(r['logical_live_growth_bytes_per_second'],10)
        self.assertEqual(r['process_cpu_cores_used'],.5)

    def test_restarted_process_and_replaced_database_unknown(self):
        before=self.sample(1);after=self.sample(3,2);after['database_identity']=[2,2]
        r=resource_change(before,after)
        self.assertIsNone(r['process_cpu_cores_used'])
        self.assertIsNone(r['logical_live_growth_bytes_per_second'])
