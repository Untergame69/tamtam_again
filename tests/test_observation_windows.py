import unittest
from tamtam_again.observation_windows import acquisition_window,acquisition_span
class WindowTests(unittest.TestCase):
 def w(self,a,b):return acquisition_window('1970-01-01T00:00:0'+str(a)+'+00:00','1970-01-01T00:00:0'+str(b)+'+00:00')
 def test_window_is_local_only(self):
  r=self.w(1,3);self.assertEqual(r['duration_ms'],2000);self.assertFalse(r['economic_time_inferred'])
 def test_invalid_clock_and_naive_missing_times(self):
  for a,b in [('bad','bad'),(None,None),('1970-01-01','1970-01-02')]:
   self.assertEqual(acquisition_window(a,b)['status'],'unknown')
  self.assertEqual(self.w(3,1)['status'],'unknown')
 def test_overlap_does_not_prove_alignment(self):
  r=acquisition_span([self.w(1,3),self.w(2,4)])
  self.assertTrue(r['requests_overlap']);self.assertFalse(r['economic_alignment_proven'])
  self.assertFalse(acquisition_span([self.w(1,2),self.w(3,4)])['requests_overlap'])
  self.assertEqual(acquisition_span([])['status'],'unknown')
