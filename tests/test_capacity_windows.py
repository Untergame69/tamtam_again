import unittest
from tamtam_again.capacity_windows import summarize_windows

def row(stamp,weight=900):
 return {'started_at':stamp,'task':'population-rest-incremental','reserved_weight':weight,
         'http_status':200,'wait_seconds':1,'response_bytes':20}
class CapacityWindowTests(unittest.TestCase):
 def test_complete_buckets_include_idle_and_exclude_partial(self):
  r=summarize_windows([row(1),row(3600,48000),row(10800)],since=1,until=10801)
  self.assertEqual(r['complete_bucket_count'],2)
  self.assertEqual(r['mean_reserved_weight_per_minute'],400)
  self.assertEqual(r['p95_reserved_weight_per_minute'],800)
  self.assertEqual(r['buckets_above_operational_budget'],1)
  self.assertEqual(r['complete_buckets'][1]['attempts'],0)
  self.assertEqual(r['excluded_partial_seconds'],3600)
 def test_no_complete_window_is_unknown(self):
  r=summarize_windows([row(100)],since=1,until=200)
  self.assertIsNone(r['mean_reserved_weight_per_minute'])
 def test_phase_and_rate_limit_retained(self):
  sample=row(3600);sample['http_status']=429
  r=summarize_windows([sample],since=3600,until=7200)
  self.assertEqual(r['complete_buckets'][0]['rate_limits'],1)
  self.assertEqual(r['complete_buckets'][0]['phases'],{'incremental_history':900})
 def test_invalid_bounds_and_values(self):
  for since,until in [(2,1),(float('nan'),2)]:
   with self.assertRaises(ValueError):summarize_windows([],since=since,until=until)
  with self.assertRaises(ValueError):summarize_windows([row(3600,-1)],since=3600,until=7200)
