import unittest,tempfile
from pathlib import Path
from unittest.mock import Mock,patch
from types import SimpleNamespace
from tamtam_again.account_lending import summarize,collect_snapshot
from tamtam_again.account_adapter import report_account
from tamtam_again.storage import Store

class LendingTests(unittest.TestCase):
 def payload(self):return {'tokenToState':[[0,{'borrow':{'basis':'10','value':'11'},'supply':{'basis':'20','value':'22'}}]],'health':'healthy'}
 def report(self,p):return summarize(p,available_ms=100,as_of_ms=100,evidence_ref='fixture')
 def test_token_components_not_equity_or_period_income(self):
  r=self.report(self.payload())
  self.assertEqual(r['tokens'][0]['borrow']['value_minus_basis'],'1')
  self.assertEqual(r['tokens'][0]['supply']['value_minus_basis'],'2')
  self.assertIsNone(r['equity']);self.assertIsNone(r['event_ms'])
  self.assertFalse(r['economic_qualification'])
 def test_duplicates_nonfinite_negative_and_future_cutoff(self):
  p=self.payload();p['tokenToState']*=2
  self.assertEqual(self.report(p)['status'],'unknown')
  for value in ('NaN','-1'):
   p=self.payload();p['tokenToState'][0][1]['borrow']['value']=value
   self.assertEqual(self.report(p)['status'],'unknown')
  with self.assertRaises(ValueError):summarize({},available_ms=101,as_of_ms=100,evidence_ref='fixture')
 def test_guard_before_provider(self):
  address='0x'+'1'*40;client=Mock()
  with patch('tamtam_again.discovery.protected_addresses',return_value={address}):
   with self.assertRaises(ValueError):collect_snapshot(None,client,'test',address)
  client.post_info.assert_not_called()
 def test_archive_to_account_adapter(self):
  address='0x'+'1'*40
  with tempfile.TemporaryDirectory() as d,Store(Path(d)/'db') as s:
   client=SimpleNamespace(network='test',post_info=Mock(return_value=self.payload()))
   collect_snapshot(s,client,'test',address)
   s.connection.execute("update raw_observations set observed_at='1970-01-01T00:00:00.100+00:00'");s.connection.commit()
   r=report_account(s,'test',address,0,50,as_of_ms=100)
   self.assertEqual(r['lending_observations'][0]['tokens'][0]['borrow']['reported_value'],'11')
   self.assertFalse(r['economic_validation'])
   self.assertEqual(report_account(s,'test',address,0,50,as_of_ms=99)['lending_observations'],[])
