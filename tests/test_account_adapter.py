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
 def test_missing_valuation_time_is_not_receipt_time(self):
  self.s.save_observation(network='test',source='hyperliquid-population-rest-v1',entity_type='account',entity_id=self.addr,endpoint='clearinghouseState',payload={'marginSummary':{'accountValue':'100'},'assetPositions':[]})
  self.s.connection.execute("update raw_observations set observed_at='1970-01-01T00:00:01+00:00'");self.s.connection.commit()
  r=report_account(self.s,'test',self.addr,0,1000,as_of_ms=2000)
  self.assertEqual(r['boundary_diagnostics'][0]['status'],'valuation_event_time_unknown')
  self.assertEqual(r['perp_scope_reports'],[])
 def test_nearest_valuation_not_interpolated(self):
  for stamp in (100,900):
   self.s.save_observation(network='test',source='hyperliquid-population-rest-v1',entity_type='account',entity_id=self.addr,endpoint='clearinghouseState',payload={'time':stamp,'marginSummary':{'accountValue':'100'},'assetPositions':[]})
  self.s.connection.execute("update raw_observations set observed_at='1970-01-01T00:00:01+00:00'");self.s.connection.commit()
  r=report_account(self.s,'test',self.addr,0,1000,as_of_ms=2000)
  self.assertEqual(r['boundary_diagnostics'][0]['nearest_after']['distance_ms'],100)
  self.assertEqual(r['boundary_diagnostics'][1]['nearest_before']['distance_ms'],100)
  self.assertFalse(r['boundary_diagnostics'][1]['interpolation_applied'])
  self.assertIsNone(r['perp_scope_reports'][0]['metrics']['economic_pnl'])
 def test_unified_per_dex_capital_not_used_as_equity(self):
  for endpoint,payload in [('userAbstraction','unifiedAccount'),('clearinghouseState',{'time':500,'marginSummary':{'accountValue':'100'},'assetPositions':[]}),('spotClearinghouseState',{'balances':[{'coin':'USDC','token':0,'total':'200','hold':'0'}]})]:
   self.s.save_observation(network='test',source='hyperliquid-population-rest-v1',entity_type='account',entity_id=self.addr,endpoint=endpoint,payload=payload)
  self.s.connection.execute("update raw_observations set observed_at='1970-01-01T00:00:01+00:00'");self.s.connection.commit()
  r=report_account(self.s,'test',self.addr,0,1000,as_of_ms=2000)
  self.assertEqual(r['perp_scope_reports'],[])
  self.assertEqual(r['boundary_diagnostics'][0]['status'],'per_dex_capital_not_usable')
  self.assertEqual(r['capital_model']['balance_source'],'spotClearinghouseState')
  self.assertEqual(r['spot_balance_snapshots'][0]['balances'][0]['total'],'200')
  self.assertIsNone(r['unified_maintenance_ratio_observations'][0]['ratio'])
  self.assertEqual(r['unified_maintenance_ratio_observations'][0]['status'],'unknown')
  self.assertIn('spot response lacks an economic timestamp',r['unified_maintenance_ratio_observations'][0]['unknown_reasons'])
  self.assertTrue(r['unified_maintenance_ratio_observations'][0]['next_actions'])
  self.assertFalse(r['economic_validation'])

 def test_retention_witness_opens_fill_coverage_only(self):
  from datetime import datetime,timezone
  def stamp(t):return datetime.fromtimestamp(t/1000,timezone.utc).isoformat()
  self.s.save_observation(network='test',source='hyperliquid-population-rest-v1',entity_type='account',entity_id=self.addr,
   endpoint='userFillsByTime',payload=[],request_payload={'pagination_status':'pagination_exhausted'},
   window_start_ms=100,window_end_ms=900,requested_at=stamp(900),complete=False)
  self.s.save_observation(network='test',source='hyperliquid-population-rest-v1',entity_type='account',entity_id=self.addr,
   endpoint='userFills',payload=[{'coin':'BTC','time':50,'tid':1}],
   request_payload={'type':'userFills','user':self.addr,'aggregateByTime':False},requested_at=stamp(900),complete=False)
  self.s.connection.execute('update raw_observations set observed_at=?',(stamp(950),));self.s.connection.commit()
  r=report_account(self.s,'test',self.addr,100,900,as_of_ms=1000)
  self.assertEqual(r['history_coverage']['userFillsByTime']['status'],'complete')
  self.assertEqual(r['history_coverage']['userFunding']['status'],'unknown')
  self.assertFalse(r['economic_validation'])

 def test_public_scope_reconciliation_through_archived_sources(self):
  from datetime import datetime,timezone
  def stamp(t):return datetime.fromtimestamp(t/1000,timezone.utc).isoformat()
  def save(endpoint,payload,request=None,left=None,right=None,requested=900):
   self.s.save_observation(network='test',source='hyperliquid-population-rest-v1',
    entity_type='account',entity_id=self.addr,endpoint=endpoint,payload=payload,
    request_payload=request or {},window_start_ms=left,window_end_ms=right,
    requested_at=stamp(requested),complete=False)
   self.s.connection.execute('update raw_observations set observed_at=? where observation_id=(select max(observation_id) from raw_observations)',(stamp(950),));self.s.connection.commit()
  save('userAbstraction','disabled')
  save('clearinghouseState',{'time':100,'marginSummary':{'accountValue':'100'},'assetPositions':[]})
  save('clearinghouseState',{'time':900,'marginSummary':{'accountValue':'120'},'assetPositions':[{'position':{'coin':'BTC','szi':'1','unrealizedPnl':'1'}}]})
  fill={'time':400,'coin':'BTC','tid':1,'closedPnl':'8','fee':'1','feeToken':'USDC'}
  histories={
   'userFillsByTime':[fill],
   'userFunding':[{'time':600,'hash':'f','delta':{'type':'funding','coin':'BTC','usdc':'2'}}],
   'userNonFundingLedgerUpdates':[{'time':500,'hash':'s','delta':{'type':'send','user':'0x'+'2'*40,
    'destination':self.addr,'sourceDex':'','destinationDex':'','token':'USDC',
    'amount':'10','fee':'0','nativeTokenFee':'0'}}]}
  for endpoint,rows in histories.items():
   save(endpoint,rows,{'type':endpoint,'user':self.addr,'startTime':100,'endTime':900,
    'pagination_status':'pagination_exhausted'},100,900)
  save('userFills',[{'time':50,'coin':'BTC','tid':0},fill],{'type':'userFills','user':self.addr,'aggregateByTime':False})
  r=report_account(self.s,'test',self.addr,100,900,as_of_ms=1000)
  a=r['perp_scope_reports'][0]['public_scope_assessment'];c=a['contract_reconciliation']
  self.assertEqual(a['metrics']['external_flows'],'10')
  self.assertEqual(c['status'],'reconciled_inputs')
  self.assertEqual(c['metrics']['economic_pnl'],'10')
  self.assertEqual(c['metrics']['reconciliation_residual'],'0')
  self.assertFalse(r['economic_validation']);self.assertFalse(a['strategy_validation'])
  early=report_account(self.s,'test',self.addr,100,900,as_of_ms=949)
  self.assertEqual(early['evidence_refs'],[])
