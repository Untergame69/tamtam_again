import unittest
from tamtam_again.resource_series import summarize

def point(t,invocation='a',cpu=None):
 return {'services':{'sampled_at':t,'units':[{'unit':'fixture','InvocationID':invocation,
         'CPUUsageNSec':int(t*1e9) if cpu is None else cpu,'MemoryCurrent':200}]},
         'storage':{'sampled_at':t,'database_identity':[1,1],
          'logical_live_page_bytes':t*10,'process':None,'disk_free_bytes':1000}}
class ResourceSeriesTests(unittest.TestCase):
 def test_edges_are_not_filled_and_rate_uses_only_known_interval(self):
  r=summarize([point(10),point(70)],since=0,until=100)
  self.assertEqual(r['units']['fixture']['mean_cpu_cores_on_known_intervals'],1)
  self.assertEqual(r['units']['fixture']['known_fraction_of_requested_window'],.6)
  self.assertEqual(r['logical_live_growth_bytes_per_second_on_known_intervals'],10)
 def test_gap_and_restart_not_smoothed_into_full_window(self):
  r=summarize([point(0),point(60,'b'),point(300,'b')],since=0,until=300,maximum_gap_seconds=180)
  self.assertIsNone(r['units']['fixture']['mean_cpu_cores_on_known_intervals'])
  self.assertEqual(r['units']['fixture']['unknown_seconds'],300)
  self.assertEqual(len(r['excluded_gaps']),1)
  self.assertEqual(r['storage_known_seconds'],60)
 def test_no_data_or_one_sample_means_unknown_rate(self):
  for points in ([],[point(60)]):
   r=summarize(points,since=0,until=100)
   self.assertIsNone(r['logical_live_growth_bytes_per_second_on_known_intervals'])
 def test_db_replacement_and_counter_reversal(self):
  after=point(60,cpu=0);after['storage']['database_identity']=[2,2]
  r=summarize([point(0,cpu=1),after],since=0,until=100)
  self.assertEqual(r['storage_known_seconds'],0)
  self.assertEqual(r['units']['fixture']['unknown_seconds'],60)
 def test_duplicate_times_rejected(self):
  with self.assertRaises(ValueError):summarize([point(0),point(0)],since=0,until=100)
