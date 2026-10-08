import unittest
from tamtam_again.service_resources import parse_properties,service_changes
class ServiceResourceTests(unittest.TestCase):
 def test_unknown_accounting_never_zero(self):
  r=parse_properties('CPUUsageNSec=18446744073709551615\nMemoryCurrent=[not set]\nEnvironment=do not export\nInvocationID=a')
  self.assertIsNone(r['CPUUsageNSec']);self.assertIsNone(r['MemoryCurrent']);self.assertNotIn('Environment',r)
 def test_same_invocation_and_restarts(self):
  def sample(t,identity,cpu):return {'sampled_at':t,'units':[{'unit':'fixture','InvocationID':identity,'CPUUsageNSec':cpu}]}
  r=service_changes(sample(1,'a',1e9),sample(3,'a',2_000_000_000))
  # Counters are integer nanoseconds; floats are deliberately not accepted.
  self.assertIsNone(r['units'][0]['cpu_cores_used'])
  r=service_changes(sample(1,'a',1_000_000_000),sample(3,'a',2_000_000_000))
  self.assertEqual(r['units'][0]['cpu_cores_used'],.5)
  for identity,cpu in [('b',2_000_000_000),('a',0)]:
   self.assertIsNone(service_changes(sample(1,'a',1_000_000_000),sample(3,identity,cpu))['units'][0]['cpu_cores_used'])
