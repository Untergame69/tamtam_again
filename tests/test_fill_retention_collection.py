import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from tamtam_again.storage import Store
from tamtam_again.fill_retention_collection import collect_witness

class CollectionTests(unittest.TestCase):
 def test_guard_precedes_provider_and_archive(self):
  address='0x'+'1'*40
  with patch('tamtam_again.fill_retention_collection.protected_addresses',return_value={address}):
   client=Mock()
   with self.assertRaises(ValueError):collect_witness(None,client,'test',address)
   client.post_info.assert_not_called()

 def test_one_unaggregated_request_archived_without_completeness_claim(self):
  address='0x'+'1'*40
  with tempfile.TemporaryDirectory() as d,Store(Path(d)/'db') as s:
   client=SimpleNamespace(network='test',post_info=Mock(return_value=[{'coin':'BTC','time':1,'tid':1}]))
   result=collect_witness(s,client,'test',address)
   self.assertEqual(result['fills_returned'],1)
   client.post_info.assert_called_once_with({'type':'userFills','user':address,'aggregateByTime':False})
   row=s.connection.execute('select endpoint,complete from raw_observations').fetchone()
   self.assertEqual(tuple(row),('userFills',0))
