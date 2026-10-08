import unittest
from tamtam_again.account_acquisitions import group_acquisitions

def item(n,endpoint,payload,dex=''):
 return ({'endpoint':endpoint,'observation_id':n,'requested_at':'1970-01-01T00:00:01+00:00',
  'observed_at':'1970-01-01T00:00:02+00:00'},payload,
  {'acquisition_id':'batch','dex':dex,'expected_dexes':['','xyz'],'inventory_evidence_ref':'raw_observations:inventory'})
def fixture():
 return [item(1,'userAbstraction','unifiedAccount'),item(2,'spotClearinghouseState',{'balances':[]}),
         item(3,'clearinghouseState',{'time':1200}),item(4,'clearinghouseState',{'time':1300},'xyz')]
class AccountAcquisitionTests(unittest.TestCase):
 def test_linked_calls_are_not_atomic_or_priced(self):
  r=group_acquisitions(fixture())['groups'][0]
  self.assertEqual(r['status'],'linked_inventory')
  self.assertFalse(r['economic_components_aligned']);self.assertIsNone(r['equity'])
  self.assertFalse(r['economic_qualification'])
 def test_missing_duplicate_or_conflicting_scope(self):
  for records in [fixture()[:-1],fixture()+[fixture()[-1]]]:
   self.assertEqual(group_acquisitions(records)['groups'][0]['status'],'incomplete_linked_inventory')
  rows=fixture();rows[-1][2]['expected_dexes']=['']
  self.assertEqual(group_acquisitions(rows)['groups'][0]['status'],'incomplete_linked_inventory')
 def test_legacy_batches_never_inferred(self):
  rows=fixture()
  for r,p,q in rows:del q['acquisition_id']
  result=group_acquisitions(rows)
  self.assertEqual(result['groups'],[]);self.assertEqual(len(result['unlinked_legacy_evidence_refs']),4)
 def test_aligned_components_do_not_prove_valuation(self):
  rows=fixture()
  for r,p,q in rows:
   if isinstance(p,dict):p['time']=1500
  result=group_acquisitions(rows)['groups'][0]
  self.assertTrue(result['economic_components_aligned']);self.assertEqual(result['economic_event_ms'],1500)
  self.assertIsNone(result['equity'])
  rows[1][1]['time']=2500
  self.assertFalse(group_acquisitions(rows)['groups'][0]['economic_components_aligned'])
 def test_distinct_acquisitions_are_never_merged(self):
  rows=fixture();rows[-1][2]['acquisition_id']='different'
  groups=group_acquisitions(rows)['groups']
  self.assertEqual(len(groups),2)
  self.assertTrue(all(r['status']=='incomplete_linked_inventory' for r in groups))
