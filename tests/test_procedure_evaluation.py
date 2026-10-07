import copy
import unittest
from tamtam_again.procedure_evaluation import evaluate_procedure


def fixture():
    outcome=lambda pnl:{'net_pnl':pnl,'available_ms':30,'flat_at_boundaries':True,
        'risk_budget_id':'fixture-risk','evidence_ref':'fixture:outcome','costs_included':True}
    return {'as_of_ms':30,'policy_version':'fixture-v1','fixed_variant_id':'fixed',
        'baseline_available_ms':0,'baseline_evidence_ref':'fixture:baseline','risk_budget_id':'fixture-risk',
        'steps':[{'decision_ms':1,'start_ms':10,'end_ms':20,'evidence_refs':['fixture:decision'],
            'knowledge_available_ms':[0],'selected_variant_id':'chosen',
            'considered_variant_ids':['chosen','failed'],'change_cost':'1',
            'research_attempts':[{'id':'failed','available_ms':1,'cost':'2'}],
            'outcomes':{'chosen':outcome('5'),'fixed':outcome('3')}}]}


class ProcedureTests(unittest.TestCase):
    def test_failed_attempt_and_change_cost_included(self):
        r=evaluate_procedure(fixture())
        self.assertEqual(r['adaptive_net_after_research_and_change_costs'],'2')
        self.assertEqual(r['fixed_net'],'3')

    def test_future_knowledge_or_baseline_rejected(self):
        for edit in ('knowledge','baseline'):
            f=fixture()
            if edit=='knowledge':f['steps'][0]['knowledge_available_ms']=[2]
            else:f['baseline_available_ms']=2
            with self.assertRaises(ValueError):evaluate_procedure(f)

    def test_wait_and_missing_cost_not_false_success(self):
        f=fixture();f['steps'][0]['selected_variant_id']=None;f['steps'][0]['change_cost']='0'
        self.assertEqual(evaluate_procedure(f)['wait_periods'],1)
        f['steps'][0]['research_attempts'][0]['cost']=None
        self.assertIsNone(evaluate_procedure(f)['adaptive_net_after_research_and_change_costs'])

    def test_open_positions_rejected(self):
        f=fixture();f['steps'][0]['outcomes']['chosen']['flat_at_boundaries']=False
        with self.assertRaises(ValueError):evaluate_procedure(f)

    def test_expense_settled_after_decision_can_be_known_at_evaluation(self):
        f=fixture();f['steps'][0]['research_attempts'][0]['cost_available_ms']=25
        self.assertEqual(evaluate_procedure(f)['adaptive_net_after_research_and_change_costs'],'2')
        f['steps'][0]['research_attempts'][0]['cost_available_ms']=31
        self.assertIsNone(evaluate_procedure(f)['adaptive_net_after_research_and_change_costs'])
        f['steps'][0]['research_attempts'][0]['cost_available_ms']=0
        with self.assertRaises(ValueError):evaluate_procedure(f)

    def capital_fixture(self):
        f=fixture();f['capital_contract']={'currency':'USDC','external_flows':'none','initial_capital':'100',
            'available_ms':0,'evidence_ref':'fixture:capital'}
        for v,closing in [('chosen','105'),('fixed','103')]:
            f['steps'][0]['outcomes'][v].update(opening_capital='100',closing_capital=closing,currency='USDC',external_flows='none')
        return f

    def test_capital_reconciliation_and_expenses_separate(self):
        r=evaluate_procedure(self.capital_fixture())
        self.assertEqual(r['trading_capital']['adaptive'],'105')
        self.assertEqual(r['procedure_wealth_after_external_research_and_change_costs'],'102')
        self.assertEqual(r['capital_continuity_status'],'verified_supplied_boundaries')

    def test_capital_reset_at_replacement_rejected(self):
        f=self.capital_fixture();f['as_of_ms']=40
        second=copy.deepcopy(f['steps'][0]);second.update(decision_ms=20,start_ms=20,end_ms=30,research_attempts=[],change_cost='0')
        for value in second['outcomes'].values():value['available_ms']=40
        f['steps'].append(second)
        with self.assertRaisesRegex(ValueError,'Capital reset'):evaluate_procedure(f)

    def test_missing_capital_boundary_unknown(self):
        f=self.capital_fixture();del f['steps'][0]['outcomes']['chosen']['opening_capital']
        r=evaluate_procedure(f);self.assertIsNone(r['procedure_wealth_after_external_research_and_change_costs'])
        self.assertEqual(r['capital_continuity_status'],'unknown')

    def test_capital_future_or_flow_rejected(self):
        for kind in ('future','flow'):
            f=self.capital_fixture()
            if kind=='future':f['capital_contract']['available_ms']=2
            else:f['steps'][0]['outcomes']['chosen']['external_flows']='deposit'
            with self.assertRaises(ValueError):evaluate_procedure(f)

    def test_wrong_period_outcome_rejected(self):
        f=fixture();f['steps'][0]['outcomes']['chosen']['start_ms']=11
        with self.assertRaisesRegex(ValueError,'different period'):evaluate_procedure(f)
