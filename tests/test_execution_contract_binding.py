"""Compact provider notation resolves only immutable packet execution contracts."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from tamtam_again.engine import canonical, fingerprint
from tamtam_again.execution_research_context import attach_execution_context
from tamtam_again.population_compilation import bind_execution_contracts, validate_packet_compilation
from tamtam_again.population_runtime import run, validate_response
from tests import test_execution_research_context as context_fixtures
from tests import test_funding_sensitivity as funding_fixtures
from tests import test_population_runtime as runtime_fixtures


class ExecutionContractBindingTests(unittest.TestCase):
    def setUp(self):
        self.fixture=funding_fixtures.CalibrationFixture();self.fixture.setUp()
        self.contract=self.fixture.build()['contract']
        factory=context_fixtures.ExecutionResearchContextTests()
        self.packet=factory.packet();self.packet['available_ms']=5000
        context=attach_execution_context(self.packet,context_fixtures.ROOT)
        overrides=deepcopy(context['available_execution_profiles']['flat_at_settlement_v1']['execution_overrides'])
        del overrides['funding_exposure_policy']
        overrides['funding_sensitivity_scenario']=deepcopy(self.contract)
        context['available_execution_profiles']['funding_sensitivity_v1']={
            'engine':'single_perp_v3','execution_overrides':overrides}
        del context['fingerprint'];context['fingerprint']=fingerprint(context)
        self.hypothesis=deepcopy(factory.hypothesis(self.packet))
        spec=self.hypothesis['executable_spec'];spec['engine']='single_perp_v3'
        spec['execution'].update(deepcopy(overrides))
        spec['execution']['funding_sensitivity_scenario']='sealed:'+self.contract['fingerprint']
        self.response={'decision':'hypothesis','diagnostic':'fixture only','wake':{},'hypothesis':self.hypothesis}

    def tearDown(self):self.fixture.tearDown()

    def test_exact_binding_keeps_source_and_engine_contract_unchanged(self):
        original=deepcopy(self.hypothesis);packet=deepcopy(self.packet)
        bound,provenance=bind_execution_contracts(self.hypothesis,self.packet['execution_research_context'])
        self.assertEqual(bound['executable_spec']['execution']['funding_sensitivity_scenario'],self.contract)
        self.assertEqual(self.hypothesis,original);self.assertEqual(self.packet,packet)
        self.assertEqual(provenance[0]['contract_fingerprint'],self.contract['fingerprint'])
        self.assertEqual(provenance[0]['execution_context_fingerprint'],self.packet['execution_research_context']['fingerprint'])
        self.assertEqual(validate_packet_compilation(self.hypothesis,self.hypothesis['experiment_profile'],self.packet,'request')['state'],'executable')
        validate_response(self.response,self.packet,request_id='request')
        self.assertEqual(self.hypothesis,original)
        copied,no_bindings=bind_execution_contracts(bound,self.packet['execution_research_context'])
        self.assertEqual(copied,bound);self.assertEqual(no_bindings,[])
        copied['executable_spec']['execution']['funding_sensitivity_scenario']['evidence_refs'].append('mutation')
        self.assertNotEqual(copied,bound);self.assertEqual(self.packet,packet)

    def test_references_context_tampering_and_lower_guards_fail_closed(self):
        for reference in ['sealed:'+'0'*64,'sealed:unknown','invented',{'reference':'sealed:'+self.contract['fingerprint']}]:
            with self.subTest(reference=reference):
                response=deepcopy(self.response)
                response['hypothesis']['executable_spec']['execution']['funding_sensitivity_scenario']=reference
                with self.assertRaises(ValueError):validate_response(response,self.packet,request_id='request')
        with self.assertRaises(ValueError):bind_execution_contracts(self.hypothesis,None)
        missing_profile=deepcopy(self.packet['execution_research_context'])
        del missing_profile['available_execution_profiles']['funding_sensitivity_v1']
        del missing_profile['fingerprint'];missing_profile['fingerprint']=fingerprint(missing_profile)
        with self.assertRaises(ValueError):bind_execution_contracts(self.hypothesis,missing_profile)
        missing=deepcopy(self.packet);del missing['execution_research_context']
        with self.assertRaises(ValueError):validate_response(self.response,missing,request_id='request')
        tampered=deepcopy(self.packet)
        tampered['execution_research_context']['available_execution_profiles']['funding_sensitivity_v1']['execution_overrides']['funding_sensitivity_scenario']['debit_usdc_per_base_unit']='0.00001'
        with self.assertRaises(ValueError):validate_response(self.response,tampered,request_id='request')
        context=tampered['execution_research_context'];del context['fingerprint'];context['fingerprint']=fingerprint(context)
        with self.assertRaises(ValueError):validate_response(self.response,tampered,request_id='request')
        response=deepcopy(self.response);response['hypothesis']['executable_spec']['fees']['taker_bps']='0'
        with self.assertRaises(ValueError):validate_response(response,self.packet,request_id='request')

    def run_fixture(self,reference=None):
        runtime=runtime_fixtures.RuntimeTests();runtime.setUp();self.addCleanup(runtime.tearDown)
        response=deepcopy(self.response)
        response['hypothesis']['experiment_profile']['hypothesis_id']=runtime.request
        if reference is not None:response['hypothesis']['executable_spec']['execution']['funding_sensitivity_scenario']=reference
        runtime.s.connection.execute('update population_research_jobs set packet_json=?,policy_json=?',
            (canonical(self.packet),canonical({**runtime.policy,'max_prompt_chars':100000})))
        runtime.s.connection.commit()
        raw=canonical(response);critique={'decision':'consistent','diagnostic':'fixture review','wake':{}}
        with patch('tamtam_again.population_runtime.verify'),patch('tamtam_again.population_runtime.call',side_effect=[(raw,runtime.usage),(canonical(critique),runtime.usage)]) as caller:
            outcome=run(runtime.s,runtime.request)
            self.assertEqual(run(runtime.s,runtime.request)['status'],'unchanged_no_inference')
        row=runtime.s.connection.execute('select * from population_research_jobs').fetchone()
        return outcome,caller,json.loads(row['result_json']),json.loads(row['usage_json']),raw,response,row

    def test_runtime_critique_persistence_replay_and_usage(self):
        outcome,caller,artifacts,usage,raw,response,row=self.run_fixture()
        self.assertEqual(outcome['status'],'hypothesis_recorded');self.assertEqual(caller.call_count,2)
        self.assertEqual(artifacts['raw_proposal'],raw);self.assertEqual(artifacts['source_proposal'],response)
        stored=artifacts['proposal']['hypothesis']['executable_spec']['execution']['funding_sensitivity_scenario']
        self.assertEqual(stored,self.contract)
        self.assertEqual(artifacts['execution_contract_bindings'][0]['reference'],'sealed:'+self.contract['fingerprint'])
        critic_prompt=caller.call_args_list[1].args[1]
        self.assertEqual(json.loads(critic_prompt.split('\nProposal:\n')[1]),response)
        self.assertEqual(usage,[{'cost_usd':0,'cost_status':'included','duration_ms':1}]*2)
        self.assertEqual(row['reserved_cost_usd'],'2')
        self.assertEqual(artifacts['usage_accounting']['calls'],2)

    def test_full_object_provider_output_remains_compatible(self):
        outcome,caller,artifacts,usage,raw,response,row=self.run_fixture(deepcopy(self.contract))
        self.assertEqual(outcome['status'],'hypothesis_recorded');self.assertEqual(caller.call_count,2)
        self.assertEqual(artifacts['source_proposal'],response)
        self.assertEqual(artifacts['proposal'],response)
        self.assertEqual(artifacts['execution_contract_bindings'],[])

    def test_bad_binding_consumes_one_attempt_without_critique_or_retry(self):
        outcome,caller,artifacts,usage,raw,response,row=self.run_fixture('sealed:'+'0'*64)
        self.assertEqual(outcome['status'],'suspended');self.assertEqual(caller.call_count,1)
        self.assertEqual(artifacts['raw_proposal'],raw);self.assertEqual(artifacts['source_proposal'],response)
        self.assertNotIn('proposal',artifacts);self.assertNotIn('critique',artifacts)
        self.assertEqual(len(usage),1);self.assertEqual(row['reserved_cost_usd'],'2')
