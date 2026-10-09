import unittest
from tamtam_again.account_events import normalize_event

A='0x'+'1'*40;B='0x'+'2'*40
def normalize(kind,**fields):
 endpoint='userFunding' if kind=='funding' else 'userNonFundingLedgerUpdates'
 return normalize_event(endpoint,{'time':100,'hash':'fixture-hash','delta':{'type':kind,**fields}},address=A,available_ms=200,evidence_ref='fixture:1')

class AccountEventTests(unittest.TestCase):
 def test_funding_signed_and_hip_currency_unverified(self):
  r=normalize('funding',coin='BTC',usdc=' -3.2 ')
  self.assertEqual(r['event']['amount'],'-3.2');self.assertEqual(r['event']['currency'],'USDC')
  r=normalize('funding',coin='xyz:GOLD',usdc='4')
  self.assertEqual(r['status'],'currency_unverified')
  self.assertEqual(r['event']['scope_id'],'perp:xyz')
 def test_deposit_single_address_boundary(self):
  e=normalize('deposit',usdc='100')['event']
  self.assertEqual(e['scope_id'],'hypercore:'+A);self.assertEqual(e['boundary_classification'],'external')
 def test_named_internal_transfer_external_for_single_address(self):
  e=normalize('internalTransfer',usdc='100',user=A,destination=B,fee=0)['event']
  self.assertEqual(e['amount'],'-100');self.assertEqual(e['boundary_classification'],'external')
  e=normalize('internalTransfer',usdc='100',user=B,destination=A,fee=0)['event']
  self.assertEqual(e['amount'],'100')
 def test_subaccount_not_automatically_consolidated(self):
  e=normalize('subAccountTransfer',usdc='10',user=A,destination=B)['event']
  self.assertEqual(e['boundary_classification'],'external')
 def test_spot_perp_internal_not_income(self):
  e=normalize('accountClassTransfer',usdc='100',toPerp=True)['event']
  self.assertEqual(e['amount'],'0');self.assertEqual(e['boundary_classification'],'internal')
 def test_fee_semantics_and_unknown_mechanism_not_guessed(self):
  for r in [normalize('withdraw',usdc='10',fee='1'),
            normalize('internalTransfer',usdc='10',user=A,destination=B,fee='1'),
            normalize('vaultDeposit',usdc='10',vault=B),normalize('rewardsClaim',amount='10')]:
   self.assertEqual(r['status'],'unknown');self.assertNotIn('event',r)
 def test_wrong_direction_and_nonfinite_not_accepted(self):
  for r in [normalize('deposit',usdc='NaN'),normalize('deposit',usdc=True),
            normalize('deposit',usdc='-1'),normalize('internalTransfer',usdc='10',user=B,destination=B,fee=0)]:
   self.assertEqual(r['status'],'unknown')
 def test_nonzero_send_fee_preserves_diagnostic_without_booking(self):
  for source,destination in ((A,B),(B,A),(A,A)):
   for fee,native in (('1','0'),('0','0.0001142'),('1','0.0001142')):
    r=normalize('send',amount='2500000',token='USDC',user=source,
     destination=destination,sourceDex='',destinationDex='spot',fee=fee,
     feeToken='',nativeTokenFee=native)
    self.assertEqual(r['status'],'unknown');self.assertNotIn('event',r)
    self.assertEqual(r['reported_transfer']['principal'],'2500000')
    self.assertEqual(r['reported_transfer']['native_token_fee'],native)
    self.assertEqual(r['reported_transfer']['fee_token'],'')
    self.assertEqual(len(r['missing_semantics']),2)
 def test_future_availability_guard(self):
  r=normalize_event('userFunding',{'time':300,'hash':'h','delta':{'type':'funding','coin':'BTC','usdc':'10'}},address=A,available_ms=200,evidence_ref='fixture')
  self.assertEqual(r['status'],'unknown');self.assertNotIn('event',r)
 def test_identity_independent_of_financial_values(self):
  self.assertEqual(normalize('funding',coin='BTC',usdc='1')['event']['id'],normalize('funding',coin='BTC',usdc='2')['event']['id'])
  self.assertNotEqual(normalize('funding',coin='BTC',usdc='1')['event']['id'],normalize('funding',coin='ETH',usdc='1')['event']['id'])
