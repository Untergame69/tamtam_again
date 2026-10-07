import copy,unittest
from tamtam_again.accounting import reconcile_period

def fixture():
 return {'start_ms':0,'end_ms':1000,'as_of_ms':2000,'scope':{'id':'perp-main','currency':'USDC','account_mode':'default'},'coverage':{k:{'status':'complete','evidence_refs':['fixture-only:'+k]} for k in ('fills','funding','flows','other_income','valuation_scope')},'valuations':[{'event_ms':0,'available_ms':0,'scope_id':'perp-main','currency':'USDC','evidence_ref':'fixture:start','equity':'100','unrealized_pnl':'0','positions':[]},{'event_ms':1000,'available_ms':1000,'scope_id':'perp-main','currency':'USDC','evidence_ref':'fixture:end','equity':'160','unrealized_pnl':'5','positions':[{'coin':'BTC','size':'1'}]}],'events':[{'id':'trade1','kind':'fill','scope_id':'perp-main','event_ms':500,'available_ms':600,'closed_pnl':'8','pnl_currency':'USDC','fee':'1','fee_currency':'USDC','builderFee':'0.5'},{'id':'funding1','kind':'funding','scope_id':'perp-main','event_ms':750,'available_ms':800,'amount':'-2','currency':'USDC'},{'id':'deposit1','kind':'flow','scope_id':'perp-main','event_ms':1000,'available_ms':1100,'amount':'50','currency':'USDC','boundary_classification':'external','boundary_evidence_ref':'fixture:deposit'}]}
class AccountingTests(unittest.TestCase):
 def test_reconciliation_builder_fee_not_double_and_external_flow(self):
  r=reconcile_period(fixture());self.assertEqual(r['metrics']['economic_pnl'],'10');self.assertEqual(r['metrics']['component_pnl'],'10');self.assertEqual(r['metrics']['reconciliation_residual'],'0');self.assertEqual(r['metrics']['time_weighted_return'],'0.1');self.assertEqual(r['metrics']['modified_dietz_estimate'],'0.1')
 def test_same_event_is_not_counted_twice(self):
  f=fixture();f['events']+=copy.deepcopy(f['events']);r=reconcile_period(f);self.assertEqual(r['observed']['events'],3);self.assertEqual(r['metrics']['reconciliation_residual'],'0')
 def test_conflicting_duplicate_blocks_metrics(self):
  f=fixture();e=copy.deepcopy(f['events'][0]);e['fee']='2';f['events'].append(e);r=reconcile_period(f);self.assertEqual(r['status'],'unknown');self.assertIsNone(r['metrics']['economic_pnl'])
 def test_api_response_not_coverage_proof(self):
  f=fixture();f['coverage']['funding']={'status':'complete'};r=reconcile_period(f);self.assertIsNone(r['metrics']['economic_pnl']);self.assertIn('funding coverage not proven',r['unknown_reasons'])
 def test_shared_collateral_without_model_is_unknown(self):
  f=fixture();f['scope']['account_mode']='unifiedAccount';r=reconcile_period(f);self.assertIsNone(r['metrics']['economic_pnl']);self.assertIn('shared collateral valuation model not verified',r['unknown_reasons'])
 def test_rebate_is_negative_fee(self):
  f=fixture();f['events'][0]['fee']='-1';f['valuations'][-1]['equity']='162';r=reconcile_period(f);self.assertEqual(r['metrics']['component_pnl'],'12');self.assertEqual(r['metrics']['reconciliation_residual'],'0')
 def test_non_usdc_fee_requires_causal_fx(self):
  f=fixture();f['events'][0]['fee_currency']='HYPE';r=reconcile_period(f);self.assertIsNone(r['metrics']['economic_pnl'])
  f['events'][0]['fee_conversion']={'currency':'USDC','rate':'1','quote_ms':400,'evidence_ref':'fixture:fx'};self.assertEqual(reconcile_period(f)['metrics']['reconciliation_residual'],'0')
  f['events'][0]['fee_conversion']['quote_ms']=600;self.assertIsNone(reconcile_period(f)['metrics']['economic_pnl'])
 def test_transfer_inside_scope_is_not_return(self):
  f=fixture();f['events'][-1]['boundary_classification']='internal';f['valuations'][-1]['equity']='110';self.assertEqual(reconcile_period(f)['metrics']['economic_pnl'],'10')
 def test_flow_between_valuations_keeps_twr_unknown(self):
  f=fixture();f['events'][-1]['event_ms']=500;r=reconcile_period(f);self.assertIsNotNone(r['metrics']['modified_dietz_estimate']);self.assertIsNone(r['metrics']['time_weighted_return']);self.assertIsNone(r['metrics']['sampled_flow_adjusted_drawdown'])
 def test_unavailable_event_not_exposed_to_accounting(self):
  f=fixture();e=copy.deepcopy(f['events'][0]);e['id']='future';e['available_ms']=3000;f['events'].append(e);self.assertEqual(reconcile_period(f)['observed']['events'],3)
 def test_repeated_receipts_of_same_fill_do_not_conflict(self):
  f=fixture();e=copy.deepcopy(f['events'][0]);e['available_ms']=1500;e['evidence_ref']='fixture:later';f['events'].append(e)
  r=reconcile_period(f);self.assertEqual(r['observed']['events'],3);self.assertEqual(r['status'],'reconciled_inputs')
