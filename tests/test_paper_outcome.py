import tempfile
import unittest
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.paper_evidence import initialize,record
from tamtam_again.paper_outcome import period_outcome


class OutcomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db')
        self.s.connection.executescript('''create table paper_sessions(session_id text,variant_id text);
            create table strategy_variants(variant_id text,plan_id text,spec_json text);
            create table validation_plans(plan_id text,synthetic integer);
            insert into paper_sessions values('session','variant');
            insert into strategy_variants values('variant','plan','{"starting_capital_usdc":"100","max_exposure":{"notional_usdc":"20"}}');
            insert into validation_plans values('plan',1);''')
        initialize(self.s)
        self.a={'net_pnl':'1','fees':'0.1','funding':'-0.2','flat_end':True,'pending_end':0,'diagnostics':[]}
        self.b={**self.a,'net_pnl':'3'}
        record(self.s,'session',10,1,{'last_ms':10},self.a)
        record(self.s,'session',20,2,{'last_ms':20},self.b)

    def tearDown(self):self.s.close();self.tmp.cleanup()

    def test_net_difference_and_exact_boundaries(self):
        outcome=period_outcome(self.s,'session',start_ms=10,end_ms=20,as_of_ms=20)
        self.assertEqual(outcome['net_pnl'],'2');self.assertTrue(outcome['synthetic'])
        from tamtam_again.procedure_evaluation import evaluate_procedure
        trace={'as_of_ms':20,'policy_version':'fixture','baseline_evidence_ref':'fixture predeclared',
            'baseline_available_ms':0,'fixed_variant_id':'variant','risk_budget_id':outcome['risk_budget_id'],
            'steps':[{'start_ms':10,'end_ms':20,'decision_ms':10,'evidence_refs':['fixture choice'],
                'knowledge_available_ms':[0],'selected_variant_id':'variant','considered_variant_ids':['variant'],
                'research_attempts':[],'change_cost':'0','outcomes':{'variant':outcome}}]}
        self.assertEqual(evaluate_procedure(trace)['adaptive_net_after_research_and_change_costs'],'2')
        trace['steps'][0]['outcomes']['variant']=period_outcome(self.s,'session',start_ms=11,end_ms=20,as_of_ms=20)
        self.assertIsNone(evaluate_procedure(trace)['adaptive_net_after_research_and_change_costs'])
        for start,end,cutoff in ((11,20,20),(10,21,21),(10,20,19)):
            self.assertIsNone(period_outcome(self.s,'session',start_ms=start,end_ms=end,as_of_ms=cutoff)['net_pnl'])

    def test_open_position_and_diagnostics_are_unknown(self):
        record(self.s,'session',30,3,{'last_ms':30},{**self.b,'flat_end':False})
        self.assertIsNone(period_outcome(self.s,'session',start_ms=10,end_ms=30,as_of_ms=30)['net_pnl'])
        record(self.s,'session',40,4,{'last_ms':40},{**self.b,'diagnostics':['gap']})
        record(self.s,'session',50,5,{'last_ms':50},self.b)
        self.assertIsNone(period_outcome(self.s,'session',start_ms=10,end_ms=50,as_of_ms=50)['net_pnl'])
