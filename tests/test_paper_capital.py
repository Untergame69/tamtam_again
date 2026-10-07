import json,tempfile,unittest
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.engine import initial_state,metrics
from tamtam_again.paper_evidence import initialize,record
from tamtam_again.paper_handover import carry_flat_cash
from tamtam_again.recipe import synthetic_spec

class CapitalTests(unittest.TestCase):
 def test_cash_evidence_and_new_session_pnl(self):
  with tempfile.TemporaryDirectory() as tmp:
   with Store(Path(tmp)/'db') as s:
    initialize(s);spec=synthetic_spec();state=initial_state(spec)
    state['cash']='123';state['last_ms']=10
    session={'session_id':'old','state_json':json.dumps(state)}
    with self.assertRaises(ValueError):carry_flat_cash(s,session,20)
    record(s,'old',10,1,state,metrics(state,spec,1))
    cash,proof=carry_flat_cash(s,session,20);self.assertEqual(cash,'123');self.assertTrue(proof)
    with self.assertRaises(ValueError):carry_flat_cash(s,session,9)
    new=initial_state(spec);new.update(cash=cash,peak_equity=cash,session_starting_capital_usdc=cash)
    self.assertEqual(metrics(new,spec,1)['net_pnl'],'0')
    new['equity_curve']=[[20,'125']];new['cash']='125'
    self.assertEqual(metrics(new,spec,1)['net_pnl'],'2')
    state['cash']='124';session['state_json']=json.dumps(state)
    with self.assertRaises(ValueError):carry_flat_cash(s,session,20)
