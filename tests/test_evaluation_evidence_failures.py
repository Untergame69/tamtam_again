"""Missing evidence remains distinct from a measured economic rejection."""
import json
from copy import deepcopy
import unittest
from tests import test_population_experiments as fixtures
from tamtam_again.recipe import synthetic_plan, synthetic_events
from tamtam_again.validation import create_plan, evaluate, classify_evaluation_failures
from tamtam_again.population_experiments import register_experiment
from tamtam_again.research_evaluation import poll
from tamtam_again.experiments import select_final


class EvidenceFailureTests(unittest.TestCase):
    setUp=fixtures.PopulationExperimentTests.setUp
    tearDown=fixtures.PopulationExperimentTests.tearDown

    def test_known_necessary_net_gate_can_reject_without_an_unpriced_benchmark(self):
        metrics={'funding_coverage':{'state':'complete','required_settlements':[],
            'settlement_clock':'reported_hour_with_inventory_invariance_v1'},
            'flat_end':True,'pending_end':0,'fills':4,'diagnostics':[],
            'net_pnl':'-1','benchmark_matched_size_buy_hold_pnl':None}
        result={'status':'failed','failures':['net_edge_after_costs','market_reference'],
            'metrics':metrics,'stress_metrics':deepcopy(metrics)}
        classified=classify_evaluation_failures(result)
        self.assertEqual(classified['state'],'rejected')
        self.assertEqual(classified['decision_basis'],'known_necessary_net_gate')
        self.assertEqual(classified['evidence_failures'],['market_reference'])
        self.assertEqual(result['status'],'failed')
        for failure in ('funding_observed','flat_boundaries','independent_block_volume','regime_coverage'):
            missing=deepcopy(result);missing['failures'].append(failure)
            self.assertNotEqual(classify_evaluation_failures(missing)['state'],'rejected')
        for change in ('exposed','incomplete','no_fills','unresolved_exit','old_clock'):
            missing=deepcopy(result)
            if change=='exposed':missing['metrics']['funding_coverage']['required_settlements']=[1000]
            elif change=='incomplete':missing['stress_metrics']['funding_coverage']['state']='incomplete'
            elif change=='no_fills':missing['metrics']['fills']=0
            elif change=='unresolved_exit':missing['metrics']['flat_end']=False
            else:missing['metrics']['funding_coverage']['settlement_clock']='exact_epoch_v1'
            self.assertEqual(classify_evaluation_failures(missing)['state'],'technical_required')

    def family(self, **criteria):
        plan=synthetic_plan()
        plan['criteria'].update(criteria)
        self.plan=create_plan(self.s,plan)['plan_id']
        family=register_experiment(self.s,'request',self.plan,self.profile)
        return family,family['attempts'][0]['variant_id']

    def test_missing_funding_keeps_gate_failed_without_economic_rejection(self):
        family,variant=self.family(require_funding=True)
        result=evaluate(self.s,variant,'comparison',synthetic_events(10000),provenance='synthetic')
        self.assertEqual(result['status'],'failed')
        self.assertIn('funding_observed',result['failures'])
        self.assertEqual(result['failure_classification']['state'],'technical_required')
        decision=poll(self.s)['decisions'][0]
        self.assertEqual(decision['state'],'technical_required')
        self.assertEqual(decision['next_plan']['kind'],'next_candidate')
        self.assertEqual(self.s.connection.execute('select state from pipeline_decisions order by decision_id desc limit 1').fetchone()[0],'needs_data')
        select_final(self.s,family['family_id'])
        self.assertEqual(poll(self.s)['decisions'][0]['state'],'technical_required')

    def test_insufficient_blocks_is_inconclusive_even_with_negative_observed_pnl(self):
        _,variant=self.family(min_blocks=8)
        events=synthetic_events(10000)
        for event in events:
            if event['kind']=='bbo':event.update(bid='100',ask='100.1')
        result=evaluate(self.s,variant,'comparison',events,provenance='synthetic')
        self.assertEqual(result['status'],'failed')
        self.assertIn('net_edge_after_costs',result['failures'])
        self.assertIn('independent_block_volume',result['failures'])
        self.assertEqual(result['failure_classification']['state'],'inconclusive')
        decision=poll(self.s)['decisions'][0]
        self.assertEqual(decision['state'],'descriptive')
        self.assertEqual(decision['evidence']['evaluation_disposition'],'inconclusive')
        self.assertEqual(decision['next_plan']['kind'],'next_candidate')
        self.assertEqual(self.s.connection.execute('select count(*) from paper_sessions').fetchone()[0],0)

    def test_missing_flat_boundary_or_continuity_never_becomes_economic_rejection(self):
        _,variant=self.family()
        events=synthetic_events(10000)
        events=[event for event in events if not (event['kind']=='leader_fill'
            and event['received_ms']==13120)]
        result=evaluate(self.s,variant,'comparison',events,provenance='synthetic')
        self.assertIn('flat_boundaries',result['failures'])
        self.assertEqual(poll(self.s)['decisions'][0]['state'],'technical_required')
        incomplete={'status':'failed','failures':['uninterrupted_observation','net_edge_after_costs'],
                    'metrics':{'diagnostics':['connection_interrupted']}}
        self.assertEqual(classify_evaluation_failures(incomplete)['state'],'technical_required')

    def test_legacy_result_is_interpreted_without_mutation_and_replay_is_idempotent(self):
        _,variant=self.family(require_funding=True)
        result=evaluate(self.s,variant,'comparison',synthetic_events(10000),provenance='synthetic')
        legacy={key:value for key,value in result.items() if key!='failure_classification'}
        archived=json.dumps(legacy)
        self.s.connection.execute('update validation_evaluations set result_json=? where evaluation_id=?',
                                  (archived,result['evaluation_id']))
        self.s.connection.commit()
        first=poll(self.s)['decisions'][0]
        self.assertEqual(first['state'],'technical_required')
        self.assertEqual(poll(self.s)['decisions'][0],first)
        self.assertEqual(self.s.connection.execute('select result_json from validation_evaluations where evaluation_id=?',
            (result['evaluation_id'],)).fetchone()[0],archived)

    def test_missing_funding_final_keeps_consumed_holdout_and_no_paper(self):
        family,variant=self.family(require_funding=True)
        events=synthetic_events(10000)
        events.append({'id':'fixture-funding','kind':'funding','event_ms':10300,
                       'received_ms':10300,'unit_funding_usdc':'-0.001'})
        comparison=evaluate(self.s,variant,'comparison',events,provenance='synthetic')
        self.assertEqual(comparison['status'],'passed')
        select_final(self.s,family['family_id'])
        result=evaluate(self.s,variant,'final',synthetic_events(20000),provenance='synthetic')
        self.assertFalse(result['promotable'])
        self.assertEqual(poll(self.s)['decisions'][0]['state'],'technical_required')
        self.assertEqual(self.s.connection.execute('select count(*) from consumed_holdouts').fetchone()[0],1)
        self.assertEqual(self.s.connection.execute('select count(*) from paper_sessions').fetchone()[0],0)

    def test_sample_and_risk_classification_does_not_hide_actual_failed_gates(self):
        result={'status':'failed','failures':['regime_coverage','uncertainty'],
                'metrics':{'block_mean_lower_95_descriptive':None}}
        self.assertEqual(classify_evaluation_failures(result)['state'],'inconclusive')
        risk={'status':'failed','failures':['drawdown_limit','uninterrupted_observation'],
              'metrics':{'diagnostics':['risk_drawdown_limit']}}
        self.assertEqual(classify_evaluation_failures(risk)['state'],'rejected')
        risk['failures'].append('flat_boundaries')
        self.assertEqual(classify_evaluation_failures(risk)['state'],'technical_required')


if __name__=='__main__':unittest.main()
