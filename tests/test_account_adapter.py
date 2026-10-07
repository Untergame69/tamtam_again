import tempfile,unittest
from pathlib import Path
from tamtam_again.storage import Store,utc_now
from tamtam_again.account_adapter import report_account
class AdapterTests(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.s=Store(Path(self.t.name)/'test.sqlite3');self.addr='0x'+'1'*40
 def tearDown(self):self.s.close();self.t.cleanup()
 def test_pilot_refused_before_raw_query(self):
  self.s.connection.execute('create table validation_plans(address text,synthetic integer)');self.s.connection.execute('insert into validation_plans values (?,0)',(self.addr,));self.s.connection.commit()
  with self.assertRaises(ValueError):report_account(self.s,'test',self.addr,0,1000,as_of_ms=2000)
 def test_short_response_never_establishes_completeness(self):
  from datetime import datetime,timezone
  stamp='1970-01-01T00:00:01+00:00'
  self.s.save_observation(network='test',source='hyperliquid-population-rest-v1',entity_type='account',entity_id=self.addr,endpoint='userFillsByTime',payload=[{'coin':'BTC','time':500,'tid':1,'closedPnl':'10','fee':'1','feeToken':'USDC'}],requested_at=stamp,request_payload={'type':'userFillsByTime'},complete=False)
  self.s.connection.execute('update raw_observations set observed_at=?',(stamp,));self.s.connection.commit()
  r=report_account(self.s,'test',self.addr,0,1000,as_of_ms=2000)
  self.assertFalse(r['economic_validation']);self.assertIsNone(r['perp_scope_reports'][0]['metrics']['economic_pnl'])
  self.assertEqual(r['perp_scope_reports'][0]['observed']['realized_pnl'],'10')
 def test_other_sources_are_not_consumed(self):
  self.s.save_observation(network='test',source='hyperliquid-websocket-v1',entity_type='account',entity_id=self.addr,endpoint='userFills',payload={'secret_reserved_marker':'never_decode'})
  r=report_account(self.s,'test',self.addr,0,1000,as_of_ms=2000);self.assertEqual(r['evidence_refs'],[])
 def test_funding_and_ledger_scopes_separate_and_deduplicated(self):
  funding=[{'time':500,'hash':'h','delta':{'type':'funding','coin':'BTC','usdc':'-3'}}]
  ledger=[{'time':500,'hash':'d','delta':{'type':'deposit','usdc':'100'}}]
  for endpoint,payload in [('userFunding',funding),('userFunding',funding),('userNonFundingLedgerUpdates',ledger),('userNonFundingLedgerUpdates',ledger)]:
   self.s.save_observation(network='test',source='hyperliquid-population-rest-v1',entity_type='account',entity_id=self.addr,endpoint=endpoint,payload=payload,request_payload={'reception':self.s.connection.execute('select count(*) from raw_observations').fetchone()[0]},complete=False)
  self.s.connection.execute("update raw_observations set observed_at='1970-01-01T00:00:01+00:00'");self.s.connection.commit()
  r=report_account(self.s,'test',self.addr,0,1000,as_of_ms=2000)
  self.assertEqual(r['perp_scope_reports'][0]['observed']['funding'],'-3')
  self.assertEqual(r['perp_scope_reports'][0]['observed']['external_flows'],'0')
  self.assertEqual(len(r['ledger_scope']['normalized_events']),1)
  self.assertEqual(r['ledger_scope']['normalized_events'][0]['amount'],'100')
  self.assertFalse(r['economic_validation'])
 def test_future_catalog_not_used_to_denominate_hip_funding(self):
  import json
  catalog={'available_ms':600,'instruments':{'xyz:GOLD':{'currency':'USDH','status':'identified'}},'dexes':{'xyz':{'currency':'USDH','status':'identified'}}}
  self.s.connection.execute('create table collateral_catalogs (network text,available_ms integer,payload_json text)')
  self.s.connection.execute('insert into collateral_catalogs values (?,?,?)',('test',600,json.dumps(catalog)));self.s.connection.commit()
  payload=[{'time':500,'hash':'h','delta':{'type':'funding','coin':'xyz:GOLD','usdc':'-3'}}]
  self.s.save_observation(network='test',source='hyperliquid-population-rest-v1',entity_type='account',entity_id=self.addr,endpoint='userFunding',payload=payload,complete=False)
  self.s.connection.execute("update raw_observations set observed_at='1970-01-01T00:00:01+00:00'");self.s.connection.commit()
  r=report_account(self.s,'test',self.addr,0,1000,as_of_ms=2000)
  self.assertEqual(r['perp_scope_reports'][0]['scope']['currency'],'USDH')
  self.assertEqual(r['unsupported_events'][0]['status'],'currency_unverified')
  self.assertEqual(r['perp_scope_reports'][0]['observed']['funding'],'0')
  self.assertIn('funding denomination/amount unavailable',r['perp_scope_reports'][0]['unknown_reasons'])
