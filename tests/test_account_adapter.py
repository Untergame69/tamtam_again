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
