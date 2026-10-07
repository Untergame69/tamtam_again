import unittest
import tempfile,time,json
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.collateral import build_catalog,resolve_currency,refresh_catalog

def fixture(available=100):
 return build_catalog([{'universe':[{'name':'BTC','szDecimals':5}],'collateralToken':0},
                       [{'universe':[{'name':'xyz:GOLD'}],'collateralToken':7},[]]],
   [{'tokens':[{'index':7,'name':'USDH','tokenId':'h'},{'index':0,'name':'USDC','tokenId':'c'}]},[]],
   available_ms=available,evidence_refs=['fixture:meta','fixture:spot'])

class CollateralTests(unittest.TestCase):
 def test_token_indices_not_array_positions(self):
  c=fixture();self.assertEqual(c['instruments']['xyz:GOLD']['currency'],'USDH')
  self.assertEqual(c['dexes']['']['currency'],'USDC')
 def test_no_future_metadata_for_old_event(self):
  self.assertIsNone(resolve_currency([fixture()],event_ms=99,instrument='xyz:GOLD'))
  self.assertEqual(resolve_currency([fixture()],event_ms=100,instrument='xyz:GOLD')['currency'],'USDH')
 def test_newer_catalog_removal_does_not_fallback_old(self):
  empty={'available_ms':200,'instruments':{},'dexes':{}}
  self.assertIsNone(resolve_currency([fixture(),empty],event_ms=300,instrument='xyz:GOLD'))
 def test_empty_or_mixed_universe_not_positional_dex(self):
  c=build_catalog([{'universe':[],'collateralToken':0}], [{'tokens':[]}],available_ms=100,evidence_refs=['fixture'])
  self.assertEqual(c['dexes'],{});self.assertTrue(c['unknown'])
 def test_duplicate_token_index_refused(self):
  with self.assertRaises(ValueError):build_catalog([], [{'tokens':[{'index':0},{'index':0}]}],available_ms=100,evidence_refs=['fixture'])
 def test_missing_token_is_unknown(self):
  c=build_catalog([{'universe':[{'name':'x:ABC'}],'collateralToken':99}],[{'tokens':[]}],available_ms=100,evidence_refs=['fixture'])
  self.assertEqual(c['dexes']['x']['status'],'unknown')
 def test_cached_catalog_has_original_availability_and_no_network(self):
  with tempfile.TemporaryDirectory() as tmp,Store(Path(tmp)/'db') as store:
   store.connection.execute('create table collateral_catalogs (catalog_id integer primary key,network text,available_ms integer,payload_json text)')
   catalog=fixture(int(time.time()*1000))
   store.connection.execute('insert into collateral_catalogs values (1,?,?,?)',('test',catalog['available_ms'],json.dumps(catalog)));store.connection.commit()
   class Client:
    network='test'
    def post_info(self,q):raise AssertionError('cached metadata must not query network')
   self.assertEqual(refresh_catalog(store,Client()),catalog)
