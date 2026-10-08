import unittest
from tamtam_again.spot_inventory import inventory
from tamtam_again.adaptation import population_descriptor
from tamtam_again.engine import fingerprint

class SpotInventoryTests(unittest.TestCase):
 def payload(self):return {'balances':[{'token':0,'coin':'USDC','total':'-100','hold':'-100','borrowed':'570','ltv':'0'},{'token':150,'coin':'HYPE','total':'10','hold':'10','supplied':'10'}],'portfolioMarginEnabled':True,'portfolioMarginRatio':'0.5'}
 def test_negative_balance_and_debt_preserved_without_double_sum(self):
  r=inventory(self.payload())
  self.assertEqual(r['balances'][0]['total'],'-100')
  self.assertEqual(r['balances'][0]['borrowed'],'570')
  self.assertEqual(r['reported_portfolio_margin_ratio'],'0.5')
  self.assertIsNone(r['equity']);self.assertFalse(r['economic_qualification'])
 def test_financial_content_stable_across_order_and_decimal_format(self):
  p=self.payload();first=inventory(p)
  p['balances'].reverse();p['balances'][1]['total']='-100.00'
  second=inventory(p)
  self.assertEqual(fingerprint(population_descriptor({'spot_inventory':first})),fingerprint(population_descriptor({'spot_inventory':second})))
  p['balances'][1]['borrowed']='571'
  self.assertNotEqual(first,inventory(p))
 def test_invalid_duplicate_nan_and_missing_arrays(self):
  p=self.payload();p['balances']*=2
  self.assertEqual(inventory(p)['status'],'unknown')
  p=self.payload();p['balances'][0]['borrowed']='NaN'
  self.assertEqual(inventory(p)['status'],'unknown')
  self.assertEqual(inventory({})['status'],'unknown')
