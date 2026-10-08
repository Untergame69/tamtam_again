import unittest
from tamtam_again.account_cashflows import summarize

def fill(identity,dex,currency):return {'kind':'fill','id':identity,'scope_id':'perp:'+dex,'event_ms':500,
 'available_ms':900,'evidence_ref':'fixture:'+identity,'closed_pnl':'10','fee':'1',
 'fee_currency':currency,'pnl_currency':currency}
def report(events,ledger):return summarize(events,ledger,address='a',start_ms=100,end_ms=800,as_of_ms=1000,account_mode='unifiedAccount')
class AccountCashflowsTests(unittest.TestCase):
 def test_shared_address_flow_once_multiple_dexes_and_duplicate_pages(self):
  a,b=fill('a','','USDC'),fill('b','xyz','USDC')
  flow={'kind':'flow','id':'deposit','scope_id':'hypercore:a','event_ms':500,
        'available_ms':900,'evidence_ref':'fixture:deposit','amount':'100','currency':'USDC','boundary_classification':'external'}
  r=report([a,a,b],[flow,flow]);observed=r['currency_reports'][0]['observed']
  self.assertEqual(observed['external_flows'],'100');self.assertEqual(observed['realized_pnl'],'20')
  self.assertEqual(observed['fees_converted_observed'],'2')
  self.assertIsNone(r['economic_pnl']);self.assertIsNone(r['capital'])
 def test_currencies_not_added_and_unknown_not_zero(self):
  r=report([fill('a','','USDC'),fill('b','xyz','USDH'),fill('c','unknown','UNVERIFIED_DEX_CURRENCY')],[])
  self.assertEqual(len(r['currency_reports']),2);self.assertEqual(len(r['unassigned_events']),1)
  self.assertFalse(r['economic_qualification'])
 def test_foreign_fee_not_assumed_at_parity(self):
  f=fill('a','','USDC');f['fee_currency']='USDH'
  r=report([f],[])['currency_reports'][0]
  self.assertEqual(r['observed']['fees_by_currency'],{'USDH':'1'})
  self.assertEqual(r['status'],'unknown');self.assertIsNone(r['metrics']['economic_pnl'])
 def test_conflicting_duplicate_not_selected_for_nicer_pnl(self):
  a=fill('a','','USDC');b={**a,'closed_pnl':'100'}
  r=report([a,b],[])['currency_reports'][0]
  self.assertTrue(r['conflicting_duplicates']);self.assertEqual(r['status'],'unknown')
 def test_unavailable_and_outside_events_ignored(self):
  a=fill('a','','USDC');b={**a,'available_ms':1001};c={**a,'event_ms':100}
  self.assertEqual(report([b,c],[])['currency_reports'],[])
