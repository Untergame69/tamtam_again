import tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from tamtam_again.storage import Store
from tamtam_again.population_orders import collect_orders
from tamtam_again.providers.hyperliquid import _request_weight,response_weight_bound

class OrdersTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db')
  self.address='0x'+'1'*40;self.client=Mock(network='test')
 def tearDown(self):self.s.close();self.tmp.cleanup()
 def test_limits_and_provenance_without_completeness(self):
  self.client.post_info.side_effect=[[{'status':'canceled','statusTimestamp':10,'order':{'oid':1}}],[]]
  r=collect_orders(self.s,self.client,'test',self.address,dexes=[''])
  self.assertEqual(r['descriptor']['historical_status_counts'],{'canceled':1})
  self.assertFalse(r['descriptor']['order_lifecycle_complete'])
  self.assertEqual(r['descriptor']['queue_priority'],'unknown')
  self.assertEqual(len(r['evidence_refs']),2)
  self.assertEqual(self.s.connection.execute('select sum(complete) from raw_observations').fetchone()[0],0)
 def test_reserved_before_any_request(self):
  with patch('tamtam_again.population_orders.protected_addresses',return_value={self.address}):
   with self.assertRaises(ValueError):collect_orders(self.s,self.client,'test',self.address,dexes=[''])
  self.client.post_info.assert_not_called()
 def test_explicit_budget_and_historical_weight(self):
  with self.assertRaises(ValueError):collect_orders(self.s,self.client,'test',self.address,dexes=['a','b','c','d'])
  self.client.post_info.assert_not_called()
  self.assertEqual(_request_weight({'type':'historicalOrders'}),120)
  self.assertEqual(response_weight_bound({'type':'historicalOrders'},2000),120)
