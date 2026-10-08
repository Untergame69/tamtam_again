import unittest
from tamtam_again.portfolio_evidence import summarize

def report(payload):
 return summarize(payload,available_ms=1000,as_of_ms=2000,start_ms=100,end_ms=900,evidence_ref='fixture')
def payload():
 return [['day',{'accountValueHistory':[[100,'100'],[900,'130']],
                 'pnlHistory':[[100,'0'],[900,'5']]}]]
class PortfolioEvidenceTests(unittest.TestCase):
 def test_reported_value_change_is_not_flow_adjusted_profit(self):
  r=report(payload());self.assertFalse(r['economic_qualification'])
  self.assertEqual(r['windows'][0]['series']['accountValueHistory']['reported_change'],'30')
  self.assertEqual(r['windows'][0]['series']['pnlHistory']['reported_change'],'5')
 def test_missing_exact_bounds_never_interpolated(self):
  p=payload();p[0][1]['accountValueHistory'][0][0]=99
  self.assertIsNone(report(p)['windows'][0]['series']['accountValueHistory']['reported_change'])
 def test_future_conflicting_and_nan_samples_block_difference(self):
  for extra in ([900,'140'],[1001,'140'],[500,'NaN']):
   p=payload();p[0][1]['accountValueHistory'].append(extra)
   r=report(p)['windows'][0]
   self.assertEqual(r['status'],'sample_quality_unknown')
   self.assertIsNone(r['series']['accountValueHistory']['reported_change'])
 def test_duplicate_windows_and_different_scopes_not_merged(self):
  p=payload();p.append(['perpDay',{'accountValueHistory':[[100,'10'],[900,'15']],'pnlHistory':[]}])
  p.extend(payload());r=report(p)
  self.assertEqual(r['windows'][1]['series']['accountValueHistory']['reported_change'],'5')
  self.assertEqual(r['windows'][2]['status'],'duplicate_window')
  self.assertIsNone(r['windows'][0]['series']['accountValueHistory']['reported_change'])
 def test_bad_envelope_or_unavailable_archive(self):
  self.assertEqual(report({})['status'],'malformed_portfolio_response')
  self.assertEqual(report([[{},{}]])['windows'][0]['status'],'malformed_window')
  with self.assertRaises(ValueError):summarize([],available_ms=3000,as_of_ms=2000,start_ms=100,end_ms=900,evidence_ref='fixture')
