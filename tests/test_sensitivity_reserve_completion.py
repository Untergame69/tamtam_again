"""A preregistered comparison-only study cancels, never evaluates, its final."""
from unittest.mock import patch

from tests.test_funding_sensitivity import CalibrationFixture, scenario_spec
from tamtam_again.engine import canonical
from tamtam_again.recipe import synthetic_plan, synthetic_events
from tamtam_again.validation import create_plan, register_variant, evaluate
from tamtam_again.reserve_cycle import tick
from tamtam_again.research_memory import authorized_account_history
from tamtam_again.research_evaluation import _persist, export_memory

POLICY={'version':'reserve-cycle-v1','policy_id':'scenario-fixture',
    'justification':'Temporary fixture only; keep existing release grace',
    'grace_ms':100,'abandon_unfinished_after_ms':1000,'max_plans_per_tick':2}


class SensitivityReserveCompletionTests(CalibrationFixture):
    def setUp(self):
        super().setUp();self.store=self.f.store
        contract=self.build()['contract'];self.spec=scenario_spec(contract)
        plan=synthetic_plan();plan.update(network=self.f.network,address=self.f.source,coin='BTC')
        plan['population_origin']={'request_id':'scenario-request'}
        self.plan=create_plan(self.store,plan)['plan_id']
        self.variant=register_variant(self.store,self.plan,self.spec)['variant_id']
        self.result=evaluate(self.store,self.variant,'comparison',synthetic_events(10000),provenance='synthetic')
        self.assertEqual(self.result['evaluation_mode'],'nonpromoting_funding_sensitivity')
        self.store.connection.execute('update strategy_variants set frozen_ms=5000 where variant_id=?',(self.variant,))
        self.store.connection.execute('update validation_plans set synthetic=0 where plan_id=?',(self.plan,))
        self.store.connection.execute('create table population_experiment_links(request_id text,plan_id text)')
        self.store.connection.execute('insert into population_experiment_links values(?,?)',('scenario-request',self.plan))
        self.store.connection.commit()

    def test_declared_terminal_comparison_releases_after_grace_and_never_reads_final(self):
        self.assertFalse(authorized_account_history(self.store,self.f.network,self.f.source,16100))
        self.assertEqual(tick(self.store,POLICY,clock_ms=16099)['released'],[])
        released=tick(self.store,POLICY,clock_ms=16100)['released']
        self.assertEqual(released[0]['closure_basis'],'frozen_nonpromoting_comparison_contract')
        self.assertEqual(released[0]['final_kind'],'abandoned_for_development')
        self.assertTrue(authorized_account_history(self.store,self.f.network,self.f.source,16100))
        self.assertFalse(authorized_account_history(self.store,self.f.network,self.f.source,16099))
        self.assertEqual(self.store.connection.execute('select start_ms,end_ms from consumed_holdouts').fetchone()[:],(20000,26000))
        self.assertEqual(self.store.connection.execute("select count(*) from validation_evaluations where stage='final'").fetchone()[0],0)
        self.assertEqual(tick(self.store,POLICY,clock_ms=17000)['released'],[])

    def test_error_or_technical_comparison_cannot_trigger_early_release(self):
        self.store.connection.execute("update validation_evaluations set status='error' where plan_id=?",(self.plan,))
        self.store.connection.commit()
        self.assertEqual(tick(self.store,POLICY,clock_ms=16100)['released'],[])
        self.assertEqual(self.store.connection.execute('select count(*) from consumed_holdouts').fetchone()[0],0)

    def test_mixed_strict_variant_keeps_ordinary_final_deadline(self):
        strict=dict(self.spec);strict['execution']=dict(strict['execution']);strict['execution'].pop('funding_sensitivity_scenario')
        self.store.connection.execute('insert into strategy_variants values(?,?,?,?,?,?,?)',
            ('fixture-mixed',self.plan,canonical(strict),'{}',5000,None,'fixture'))
        self.store.connection.commit()
        result=tick(self.store,POLICY,clock_ms=16100)
        self.assertEqual(result['released'],[])
        self.assertEqual(result['waiting'][0]['wake_ms'],26100)

    def test_release_makes_comparison_feedback_exportable_without_future_payloads(self):
        self.store.connection.execute('create table population_research_jobs '
            '(request_id text primary key,network text,address text,packet_json text)')
        packet={'available_ms':5000,'funding_witness_source_periods':self.build()['source_periods']}
        self.store.connection.execute('insert into population_research_jobs values(?,?,?,?)',
            ('scenario-request',self.f.network,self.f.source,canonical(packet)))
        self.store.connection.commit()
        with patch('tamtam_again.research_evaluation.now_ms',return_value=16100):
            event=_persist(self.store,'scenario-request','population','descriptive',
                evidence={'evaluations':[{'evaluation_id':self.result['evaluation_id'],
                    'status':'failed','source_periods':self.result['source_periods']}]})
        self.assertEqual(export_memory(self.store,self.f.network,self.f.source,16100),[])
        tick(self.store,POLICY,clock_ms=16100)
        queries=[];self.store.connection.set_trace_callback(queries.append)
        feedback=export_memory(self.store,self.f.network,self.f.source,16100)
        self.store.connection.set_trace_callback(None)
        self.assertEqual(len(feedback),1)
        self.assertEqual(feedback[0]['event_id'],event['event_id'])
        self.assertEqual(feedback[0]['item']['next_plan']['kind'],'next_candidate')
        self.assertFalse(any('from raw_observations' in q.lower() for q in queries))
