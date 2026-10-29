"""Bounded frozen sensitivity fixtures; never a physical cost or promotion proof."""
from decimal import Decimal
import json
import unittest
from unittest.mock import patch

from tests import test_funding_witnesses as witness_fixtures
from tamtam_again.funding_sensitivity import build_scenario, validate_scenario, apply_through, HOUR
from tamtam_again.engine import initial_state, _fill, reduce_event, replay, fingerprint, validate_spec
from tamtam_again.recipe import synthetic_spec, synthetic_plan, synthetic_events
from tamtam_again.validation import create_plan, evaluate, classify_evaluation_failures
from tamtam_again.population_experiments import register_experiment
from tamtam_again.research_evaluation import poll
from tamtam_again.pipeline import synthetic_tick
from tamtam_again.experiments import select_final
from tamtam_again.paper import start_paper


def scenario_spec(contract):
    spec=synthetic_spec();spec.update(engine='single_perp_v3',market='BTC')
    spec['execution'].update(max_quote_age_ms=1000,paper_tick_target_ms=5000,
        funding_observation_interval_ms=HOUR,
        funding_settlement_clock='reported_hour_with_inventory_invariance_v1',
        funding_sensitivity_scenario=contract,
        market_rules={'version':1,'instrument':'BTC','currency':'USDC','available_ms':0,
            'evidence_refs':['raw_observations:1','raw_observations:2'],'sz_decimals':4,
            'minimum_order_usdc':'10','max_leverage':'40'})
    return spec


class CalibrationFixture(unittest.TestCase):
    def setUp(self):
        self.f=witness_fixtures.FundingWitnessTests();self.f.setUp()
        self.f.save('userFundings',self.f.funding(usdc='-0.2',szi='2'))
        self.f.save('userFundings',self.f.funding(usdc='0.6',szi='2'),stamp=2200)
    def tearDown(self):self.f.tearDown()
    def build(self,**kwargs):
        return build_scenario(self.f.store,self.f.contract,network=self.f.network,address=self.f.source,
            market='BTC',cutoff_ms=kwargs.pop('cutoff_ms',5000),**kwargs)


class FundingCalibrationTests(CalibrationFixture):
    def test_exact_signed_sample_adverse_symmetric_debit_and_replay_provenance(self):
        self.f.store.connection.execute('pragma query_only=on')
        result=self.build();contract=result['contract']
        self.assertEqual(contract['debit_usdc_per_base_unit'],'0.3')
        self.assertEqual(contract['calibration']['minimum_signed_coefficient'],'-0.1')
        self.assertEqual(contract['calibration']['maximum_signed_coefficient'],'0.3')
        self.assertTrue(contract['calibration']['coefficient_disputes'])
        self.assertEqual(contract['rule'],'adverse_symmetric_sample_envelope')
        self.assertFalse(contract['promotion_authorized'])
        self.assertEqual(result,self.build())
        sample=contract['calibration']['maximum_producing_sample']
        self.assertEqual(sample['row_index'],0);self.assertTrue(sample['response_sha256'])
        self.assertTrue(all(ref.split(':')[1].isdigit() for ref in result['evidence_refs']))
        self.assertTrue(result['source_periods'])

    def test_old_snapshot_rows_and_future_event_rows_do_not_calibrate(self):
        cutoff=86_400_000+5000
        value=self.f.funding(stamp=1000,usdc='-999999')
        value['data']['fundings'].append({'coin':'BTC','time':cutoff+1,'usdc':'999999','szi':'1'})
        self.f.save('userFundings',value,stamp=cutoff-100)
        recent=self.f.funding(stamp=cutoff-2000,usdc='-0.4',szi='2')
        self.f.save('userFundings',recent,stamp=cutoff-1000)
        contract=self.build(cutoff_ms=cutoff)['contract']
        self.assertEqual(contract['debit_usdc_per_base_unit'],'0.2')
        self.assertEqual(contract['calibration']['matching_coefficients'],1)

    def test_reserved_corrupt_witness_is_never_payload_selected(self):
        from tamtam_again.validation import initialize
        initialize(self.f.store)
        self.f.store.connection.execute('insert into validation_plans values(?,?,?,?,?,?,?)',
            ('reserved',self.f.network,self.f.witness,'BTC','{}',0,0))
        self.f.store.connection.execute("update raw_observations set response_json='corrupt' where endpoint='userFundings'")
        self.f.store.connection.commit();queries=[]
        self.f.store.connection.set_trace_callback(queries.append)
        self.assertIsNone(self.build()['contract'])
        self.f.store.connection.set_trace_callback(None)
        self.assertFalse(any(q.lower().startswith('select * from raw_observations where observation_id=3') for q in queries))

    def test_hash_byte_record_policy_and_contract_mutations_fail_explicitly(self):
        with self.assertRaisesRegex(ValueError,'record bound'):self.build(policy={'max_records':1})
        with self.assertRaisesRegex(ValueError,'decoded'):self.build(policy={'max_decoded_bytes':1})
        with self.assertRaisesRegex(ValueError,'bounds'):self.build(policy={'max_envelopes':65})
        contract=self.build()['contract'];contract['debit_usdc_per_base_unit']='0.0000001'
        with self.assertRaisesRegex(ValueError,'Verified'):validate_scenario(contract)
        self.f.store.connection.execute("update raw_observations set response_sha256='bad' where observation_id=3");self.f.store.connection.commit()
        with self.assertRaisesRegex(ValueError,'hash mismatch'):self.build()

    def test_payload_causal_metadata_change_is_refused_before_decode(self):
        original=self.f.store.connection
        class ChangedMetadata:
            changed=False
            def execute(proxy,sql,params=()):
                if not proxy.changed and sql.startswith('select * from raw_observations') and "entity_type='account'" in sql:
                    proxy.changed=True
                    original.execute('update raw_observations set observed_at=? where observation_id=?',
                        ('1970-01-01T00:00:06.000+00:00',params[0]))
                return original.execute(sql,params)
            def __getattr__(proxy,name):return getattr(original,name)
        self.f.store.connection=ChangedMetadata()
        try:
            with self.assertRaisesRegex(ValueError,'identity changed'):self.build()
        finally:self.f.store.connection=original

    def test_sql_interruption_is_typed_preparation_refusal(self):
        import sqlite3
        original=self.f.store.connection;clock=[0]
        class InterruptedMetadata:
            def execute(proxy,sql,params=()):
                if sql.startswith('select observation_id,entity_id'):
                    clock[0]=1
                    raise sqlite3.OperationalError('interrupted')
                return original.execute(sql,params)
            def __getattr__(proxy,name):return getattr(original,name)
        self.f.store.connection=InterruptedMetadata()
        try:
            with patch('tamtam_again.funding_sensitivity.monotonic',side_effect=lambda:clock[0]):
                with self.assertRaisesRegex(ValueError,'time bound'):
                    self.build(policy={'max_duration_ms':1})
        finally:self.f.store.connection=original


class FundingSensitivityAccountingTests(CalibrationFixture):
    def test_model_debits_both_directions_without_duplicate_observed_cash(self):
        contract=self.build()['contract'];spec=scenario_spec(contract)
        for direction in (1,-1):
            with self.subTest(direction=direction):
                state=initial_state(spec);state['funding_sensitivity_window']={'start_ms':0,'end_ms':HOUR+1000}
                _fill(state,Decimal(direction*2),Decimal(100),Decimal(0),100)
                cash=Decimal(state['cash'])
                # Observed coefficients can disagree; neither is booked into model cash.
                for identity,coefficient in [('a','-0.1'),('b','-0.100001')]:
                    reduce_event(state,spec,{'id':identity,'kind':'funding','event_ms':HOUR+75,
                        'received_ms':HOUR+200,'unit_funding_usdc':coefficient})
                self.assertEqual(Decimal(state['funding']),Decimal('-0.6'))
                self.assertEqual(Decimal(state['cash']),cash-Decimal('0.6'))
                self.assertTrue(state['funding_source_diagnostics'])
                self.assertFalse(state['diagnostics'])
                self.assertEqual(state['funding_settlements'][str(HOUR+75)]['observed_payment_component'],str(Decimal(direction*2)*Decimal('-0.1')))
                apply_through(state,spec,HOUR+999,Decimal(1))
                self.assertEqual(Decimal(state['funding']),Decimal('-0.6'))
        state=initial_state(spec);state['funding_sensitivity_window']={'start_ms':0,'end_ms':HOUR+1}
        _fill(state,Decimal(2),Decimal(100),Decimal(0),100)
        apply_through(state,spec,HOUR,Decimal(2));self.assertEqual(Decimal(state['funding']),Decimal('-1.2'))

    def test_nominal_pre_boundary_inventory_and_no_phantom_execution_or_close(self):
        spec=scenario_spec(self.build()['contract']);state=initial_state(spec)
        state['funding_sensitivity_window']={'start_ms':0,'end_ms':HOUR+1}
        _fill(state,Decimal(1),Decimal(100),Decimal(0),HOUR)
        state['pending']=[{'target':'0','due_ms':HOUR,'expires_ms':HOUR+100}]
        apply_through(state,spec,HOUR,Decimal(1))
        self.assertEqual(Decimal(state['funding']),Decimal(0))
        self.assertEqual(state['position'],'1');self.assertEqual(len(state['pending']),1)
        self.assertEqual(state['funding_events'],0)

    def test_observed_unknown_is_separate_from_complete_chosen_model(self):
        spec=scenario_spec(self.build()['contract'])
        result=replay(spec,synthetic_events(10000),block_ms=1000,
            observation_window={'start_ms':10000,'end_ms':16000})
        self.assertEqual(result['metrics']['funding_coverage']['classification'],'chosen_model_cost_complete_not_observed_venue_cost')
        self.assertTrue(result['metrics']['funding_coverage']['model_only'])
        self.assertIn('observed_funding_coverage',result['metrics'])
        self.assertTrue(result['metrics']['observed_funding_not_booked_into_scenario_cash'])
        spec['execution']['funding_exposure_policy']='flat_at_settlement_v1'
        with self.assertRaisesRegex(ValueError,'excludes flat'):validate_spec(spec)


class FundingSensitivityIntegrationTests(CalibrationFixture):
    def family(self,values=(500,)):
        store=self.f.store;contract=self.build()['contract'];spec=scenario_spec(contract)
        plan=synthetic_plan();plan['coin']='BTC';plan['criteria']['require_funding']=True
        planid=create_plan(store,plan)['plan_id']
        store.connection.execute('create table population_research_jobs(request_id text,network text,address text,status text,result_json text,updated_ms integer,packet_json text)')
        proposal={'proposal':{'hypothesis':{'required_data':[],'executable_spec':spec,'markets':['BTC'],'type':'follower'}},
            'critique':{'decision':'consistent','diagnostic':'fixture','wake':{}},'promotion_authorized':False,'profitability_proven':False}
        store.connection.execute('insert into population_research_jobs values(?,?,?,?,?,?,?)',
            ('request','synthetic','fixture-only','hypothesis_recorded',json.dumps(proposal),5000,
             json.dumps({'available_ms':5000,'evidence_refs':['request',*contract['evidence_refs']]})))
        store.connection.commit()
        profile={'schema_version':1,'hypothesis_id':'request','justification':'fixture only','max_variants':len(values),
            'selection_rule':'comparison_then_one_final','axes':[{'parameter':'horizon_ms','values':list(values),
            'category':'hypothesis','justification':'fixture','evidence_refs':['request'],'measurement_status':'simulated'}]}
        family=register_experiment(store,'request',planid,profile)
        return family,family['attempts'][0]['variant_id']

    def test_passed_criteria_remain_exploratory_and_two_pipeline_ticks_never_read_final(self):
        family,variant=self.family();store=self.f.store
        class StageInputs(dict):
            def get(self,key,*args):
                if key=='final':raise AssertionError('Scenario must never read final inputs')
                return super().get(key,*args)
        fixtures={variant:StageInputs(comparison=synthetic_events(10000))}
        synthetic_tick(store,fixtures);synthetic_tick(store,fixtures)
        result=json.loads(store.connection.execute('select result_json from validation_evaluations').fetchone()[0])
        self.assertTrue(result['criteria_passed'])
        self.assertEqual(result['criteria_failures'],[])
        self.assertEqual(result['failures'],['scenario_only_not_promotable'])
        self.assertEqual(result['status'],'failed');self.assertFalse(result['promotable'])
        self.assertEqual(result['scenario_decision'],'criteria_passed_under_chosen_scenario')
        self.assertEqual(store.connection.execute("select count(*) from validation_evaluations where stage='final'").fetchone()[0],0)
        self.assertEqual(store.connection.execute('select count(*) from consumed_holdouts').fetchone()[0],0)
        self.assertEqual(store.connection.execute('select count(*) from paper_sessions').fetchone()[0],0)
        selected=select_final(store,family['family_id'])
        self.assertEqual(selected['status'],'exploratory_complete');self.assertIsNone(selected['variant_id'])
        decision=poll(store)['decisions'][0]
        self.assertEqual(decision['state'],'descriptive')
        self.assertEqual(decision['next_plan']['kind'],'next_candidate')
        self.assertFalse(decision['evidence']['actual_economic_validation'])
        self.assertTrue(store.connection.execute('select count(*) from validation_evaluation_source_periods').fetchone()[0])
        with self.assertRaisesRegex(ValueError,'comparison-only'):evaluate(store,variant,'final',synthetic_events(20000),provenance='synthetic')
        for kwargs in ({'synthetic_recipe':True},{'experimental_hypothesis':{'fixture':True}}):
            with self.assertRaisesRegex(ValueError,'cannot authorize any paper'):start_paper(store,variant,**kwargs)

    def test_model_economic_failure_is_scenario_specific_not_actual_rejection(self):
        _,variant=self.family();events=synthetic_events(10000)
        for event in events:
            if event['kind']=='bbo':event.update(bid='100',ask='100.1')
        result=evaluate(self.f.store,variant,'comparison',events,provenance='synthetic')
        self.assertFalse(result['criteria_passed'])
        self.assertEqual(result['scenario_decision'],'rejected_under_chosen_scenario')
        self.assertEqual(result['failure_classification']['state'],'inconclusive')
        self.assertFalse(result['actual_economic_validation'])
        self.assertEqual(poll(self.f.store)['decisions'][0]['state'],'descriptive')

    def test_mixed_success_and_execution_error_is_not_a_scientific_family_conclusion(self):
        family,first=self.family(values=(500,600));store=self.f.store
        evaluate(store,first,'comparison',synthetic_events(10000),provenance='synthetic')
        second=family['attempts'][1]['variant_id']
        with patch('tamtam_again.validation.replay',side_effect=ValueError('fixture interruption')):
            with self.assertRaises(ValueError):evaluate(store,second,'comparison',synthetic_events(10000),provenance='synthetic')
        self.assertEqual(poll(store)['decisions'][0]['state'],'technical_required')
        with self.assertRaisesRegex(ValueError,'execution error'):select_final(store,family['family_id'])

    def test_errors_and_coverage_gaps_remain_technical_not_scientific_rejection(self):
        _,variant=self.family();store=self.f.store
        with patch('tamtam_again.validation.replay',side_effect=ValueError('fixture engine interruption')):
            with self.assertRaises(ValueError):evaluate(store,variant,'comparison',synthetic_events(10000),provenance='synthetic')
        self.assertEqual(poll(store)['decisions'][0]['state'],'technical_required')
        missing={'status':'failed','evaluation_mode':'nonpromoting_funding_sensitivity',
            'criteria_failures':['flat_boundaries'],'scenario_decision':'inconclusive_under_chosen_scenario'}
        classification=classify_evaluation_failures(missing)
        self.assertEqual(classification['state'],'technical_required')
        self.assertIn('flat_boundaries',classification['evidence_failures'])


if __name__=='__main__':unittest.main()
