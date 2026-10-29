import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tamtam_again.execution_research_context import attach_execution_context
from tamtam_again.population_compilation import validate_packet_compilation
from tamtam_again.population_runtime import build_proposal_prompt, validate_response


ROOT = Path(__file__).resolve().parents[1]


class ExecutionResearchContextTests(unittest.TestCase):
    def test_optional_intraday_profile_compiles_without_changing_default_signal(self):
        from copy import deepcopy
        from tamtam_again.experiments import compile_family
        packet=self.packet();context=attach_execution_context(packet,ROOT)
        self.assertEqual(context['paper_cadence_reference']['configured_tick_ms'],500)
        self.assertEqual(context['paper_cadence_reference']['classification'],'configured_target_not_measured_lag')
        h=self.hypothesis(packet);base=deepcopy(h['executable_spec'])
        self.assertNotIn('funding_exposure_policy',base['execution'])
        optional=context['available_execution_profiles']['flat_at_settlement_v1']
        spec=h['executable_spec'];spec['engine']=optional['engine']
        spec['execution'].update(optional['execution_overrides'])
        self.assertEqual(validate_packet_compilation(h,h['experiment_profile'],packet,'request')['state'],'executable')
        compiled=compile_family(h['experiment_profile'],spec)
        self.assertEqual(compiled[0]['signal'],base['signal'])
        self.assertEqual(compiled[0]['horizon_ms'],base['horizon_ms'])
        self.assertEqual(compiled[0]['execution']['funding_exposure_policy'],'flat_at_settlement_v1')
        spec['execution']['paper_tick_target_ms']+=1
        with self.assertRaisesRegex(ValueError,'preserve'):
            validate_packet_compilation(h,h['experiment_profile'],packet,'request')

    def test_intraday_profile_requires_cadence_source_and_rejects_unlisted_policy(self):
        from tamtam_again.execution_research_context import _paper_cadence
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(_paper_cadence(directory))
            path=Path(directory)/'systemd/user/tamtam-again-paper.timer';path.parent.mkdir(parents=True)
            for value in ['0ms','garbage','1.5s']:
                path.write_text('[Timer]\nOnUnitActiveSec='+value+'\n')
                self.assertIsNone(_paper_cadence(directory))
        packet=self.packet();attach_execution_context(packet,ROOT)
        h=self.hypothesis(packet);h['executable_spec']['execution']['funding_exposure_policy']='invented'
        with self.assertRaisesRegex(ValueError,'explicitly supplied optional'):
            validate_packet_compilation(h,h['experiment_profile'],packet,'request')

    def test_frozen_existing_funding_pool_supports_autonomous_costs_without_account_signals(self):
        from tests.test_funding_witnesses import FundingWitnessTests
        from tamtam_again.collateral import build_catalog
        from tamtam_again.market_rules import mechanism_profile
        fixture=FundingWitnessTests();fixture.setUp()
        try:
            fixture.save('userFundings',fixture.funding(),entity=fixture.witness,stamp=2100)
            fixture.save('userFundings',fixture.funding(address=fixture.reserved),entity=fixture.reserved,stamp=2100)
            perps=[{'collateralToken':0,'universe':[{'name':'BTC','szDecimals':4,'maxLeverage':40}]}]
            spot=[{'tokens':[{'index':0,'name':'USDC','tokenId':'fixture-usdc'}]},[]]
            catalog=build_catalog(perps,spot,available_ms=100,evidence_refs=fixture.contract['evidence_refs'])
            packet={'network':fixture.network,'address':fixture.source,'available_ms':3000,
                'evidence_refs':['archive:one'],'observations':{'markets':['BTC'],
                'market_mechanisms':[mechanism_profile(catalog,'BTC')],
                'execution_data_readiness':{'market_ws_observed':True,'account_ws_observed':False,'funding_ws_observed':False}}}
            with patch('tamtam_again.discovery.protected_addresses',return_value={fixture.reserved}):
                context=attach_execution_context(packet,ROOT,store=fixture.store)
            witnesses=context['scenario']['execution']['funding_witnesses']
            self.assertEqual(witnesses['addresses'],[fixture.witness])
            self.assertFalse(context['funding_witness_sources']['coverage_proven'])
            self.assertEqual(packet['funding_witness_source_periods'][0]['address'],fixture.witness)
            self.assertEqual(context['funding_sensitivity_source']['policy_id'],
                'user-authorized-adverse-funding-sensitivity-20261028')
            sensitivity=context['funding_sensitivity_calibration']['contract']
            self.assertFalse(sensitivity['promotion_authorized'])
            self.assertEqual(sensitivity['debit_usdc_per_base_unit'],'0.1')
            self.assertNotIn('funding_sensitivity_scenario',context['scenario']['execution'])
            hypothesis=self.hypothesis(packet)
            hypothesis['type']='autonomous';spec=hypothesis['executable_spec'];spec['type']='autonomous'
            spec['signal']={'kind':'momentum','lookback_ms':1000,'threshold_bps':'2'}
            spec['sizing']={'units':'0.01','scale':'1'}
            spec['data_sources']=['bbo','streamHealth','userFundings']
            self.assertEqual(validate_packet_compilation(hypothesis,hypothesis['experiment_profile'],packet,'request')['state'],'executable')
            from copy import deepcopy
            alternative=deepcopy(hypothesis)
            optional=context['available_execution_profiles']['funding_sensitivity_v1']
            alternative['executable_spec']['engine']=optional['engine']
            alternative['executable_spec']['execution'].update(optional['execution_overrides'])
            self.assertEqual(validate_packet_compilation(alternative,alternative['experiment_profile'],packet,'request')['state'],'executable')
            alternative['executable_spec']['execution']['funding_exposure_policy']='flat_at_settlement_v1'
            with self.assertRaisesRegex(ValueError,'mutually exclusive'):
                validate_packet_compilation(alternative,alternative['experiment_profile'],packet,'request')
            with patch('tamtam_again.funding_sensitivity.build_scenario',side_effect=ValueError('bounded calibration refused')), \
                    patch('tamtam_again.discovery.protected_addresses',return_value={fixture.reserved}):
                fallback=attach_execution_context(packet,ROOT,store=fixture.store)
            self.assertEqual(fallback['funding_sensitivity_calibration']['status'],'technical_required')
            self.assertEqual(fallback['funding_sensitivity_calibration']['reason'],'bounded calibration refused')
            self.assertNotIn('funding_sensitivity_v1',fallback['available_execution_profiles'])
            self.assertEqual(fallback['scenario'],context['scenario'])
            del spec['execution']['funding_witnesses']
            with self.assertRaisesRegex(ValueError,'simulation assumptions'):
                validate_packet_compilation(hypothesis,hypothesis['experiment_profile'],packet,'request')
        finally:fixture.tearDown()

    def packet(self):
        from tamtam_again.market_rules import mechanism_profile
        catalog={'available_ms':90,'evidence_refs':['raw_observations:1'],
                 'instruments':{'BTC':{'currency':'USDC','token_id':'fixture-usdc',
                    'sz_decimals':4,'max_leverage':40,'is_delisted':False}}}
        return {'available_ms': 100, 'evidence_refs': ['archive:one','raw_observations:1'],
                'observations': {'markets': ['BTC'],
                    'market_mechanisms':[mechanism_profile(catalog,'BTC')]}}

    def test_existing_scenario_preserves_values_without_inventing_rule_or_measurements(self):
        packet = self.packet()
        original = json.loads((ROOT / 'config/research-policy.json').read_text())
        context = attach_execution_context(packet, ROOT)
        expected={key: original['strategy_template'][key] for key in
            ('max_exposure','fees','slippage','latency_ms','starting_capital_usdc','execution')}
        expected['execution']={**expected['execution'],'funding_observation_interval_ms':3600000,
            'funding_settlement_clock':'reported_hour_with_inventory_invariance_v1'}
        self.assertEqual(context['scenario'],expected)
        self.assertNotIn('funding_interval_ms',context['scenario']['execution'])
        for key in ('signal', 'sizing', 'horizon_ms', 'market', 'entry', 'exit'):
            self.assertNotIn(key, context['scenario'])
        self.assertNotIn('system_measurements', packet['observations'])
        self.assertFalse(context['market_evidence'])
        self.assertFalse(context['paper_authorized'])
        self.assertFalse(context['real_orders_authorized'])
        self.assertEqual(attach_execution_context(packet, ROOT), context)

    def test_profile_changes_are_provenanced_and_invalid_profile_has_no_defaults(self):
        original = json.loads((ROOT / 'config/research-policy.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config').mkdir()
            path = root / 'config/research-policy.json'
            path.write_text(json.dumps(original))
            first = attach_execution_context(self.packet(), root)
            original['strategy_template']['latency_ms'] += 1
            path.write_text(json.dumps(original))
            second = attach_execution_context(self.packet(), root)
            self.assertNotEqual(first['source']['sha256'], second['source']['sha256'])
            self.assertNotEqual(first['fingerprint'], second['fingerprint'])
            original['strategy_template']['fees']['maker_bps'] = '-1'
            path.write_text(json.dumps(original))
            with self.assertRaises(ValueError):
                attach_execution_context(self.packet(), root)

    def hypothesis(self, packet):
        context = packet['execution_research_context']
        spec = {**context['scenario'], 'schema_version': 2, 'market': 'BTC',
                'type': 'follower', 'data_sources': ['bbo', 'userFills', 'streamHealth', 'userFundings'],
                'signal': {'kind': 'leader_delta'}, 'entry': {'kind': 'target_position'},
                'exit': {'kind': 'horizon_or_target'}, 'sizing': {'scale': '0.001'},
                'horizon_ms': 60000, 'invalidation_conditions': ['insufficient observations']}
        spec['execution']={**spec['execution'], 'market_rules':context['market_scope'].get('rules')}
        profile = {'schema_version': 1, 'hypothesis_id': 'request',
            'justification': 'Fixture only; declared simulation sensitivity', 'max_variants': 1,
            'selection_rule': 'comparison_then_one_final', 'axes': [{
                'parameter': 'latency_ms', 'values': [context['scenario']['latency_ms']],
                'category': 'system_capacity', 'justification': 'Existing scenario, not a measurement',
                'evidence_refs': ['packet.execution_research_context'], 'measurement_status': 'simulated'}]}
        hypothesis = {key: 'Fixture only' for key in ('mechanism', 'signal', 'entry', 'exit',
            'sizing', 'risk', 'horizon_justification', 'execution_constraints', 'rejection_criteria')}
        hypothesis.update(type='follower', markets=['BTC'], required_data=[],
            evidence_refs=['archive:one', 'packet.execution_research_context'],
            executable_spec=spec, experiment_profile=profile)
        return hypothesis

    def test_scenario_axis_can_compile_but_cannot_be_misrepresented_as_measurement(self):
        packet = self.packet()
        attach_execution_context(packet, ROOT)
        hypothesis = self.hypothesis(packet)
        self.assertEqual(validate_packet_compilation(hypothesis,
            hypothesis['experiment_profile'], packet, 'request')['state'], 'executable')
        axis = hypothesis['experiment_profile']['axes'][0]
        axis.update(measurement_status='measured_reference',
                    measurement_ref='packet.execution_research_context', measurement_available_ms=100)
        with self.assertRaisesRegex(ValueError, 'Measured execution-delay'):
            validate_packet_compilation(hypothesis, hypothesis['experiment_profile'], packet, 'request')

    def test_spot_non_usdc_unrooted_and_future_metadata_cannot_compile(self):
        changes=[('spot',lambda p:p['observations']['market_mechanisms'][0].update(instrument_type='spot')),
                 ('nonusdc',lambda p:p['observations']['market_mechanisms'][0]['collateral'].update(currency='USDH')),
                 ('unrooted',lambda p:p['observations']['market_mechanisms'][0].update(evidence_refs=['raw_observations:999'])),
                 ('future',lambda p:p['observations']['market_mechanisms'][0].update(available_ms=101)),
                 ('incomplete',lambda p:p['observations']['market_mechanisms'][0]['minimum_order'].pop('denomination'))]
        for label,change in changes:
            with self.subTest(label=label):
                packet=self.packet();change(packet)
                context=attach_execution_context(packet,ROOT)
                self.assertNotEqual(context['market_scope']['state'],'supported')
                hypothesis=self.hypothesis(packet)
                with self.assertRaisesRegex(ValueError,'Verified matching USDC perpetual'):
                    validate_packet_compilation(hypothesis,hypothesis['experiment_profile'],packet,'request')

    def test_spot_symbol_alone_and_tampered_or_missing_rules_do_not_bypass_scope(self):
        packet=self.packet();packet['observations']['markets']=['@1']
        packet['observations']['market_mechanisms'][0]['instrument']='@1'
        self.assertNotEqual(attach_execution_context(packet,ROOT)['market_scope']['state'],'supported')
        packet=self.packet();attach_execution_context(packet,ROOT)
        hypothesis=self.hypothesis(packet)
        hypothesis['executable_spec']['execution']['market_rules']['minimum_order_usdc']='1'
        with self.assertRaises(ValueError):
            validate_packet_compilation(hypothesis,hypothesis['experiment_profile'],packet,'request')
        packet=self.packet();attach_execution_context(packet,ROOT)
        hypothesis=self.hypothesis(packet)
        del hypothesis['executable_spec']['execution']['market_rules']
        with self.assertRaisesRegex(ValueError,'Execution market rules'):
            validate_packet_compilation(hypothesis,hypothesis['experiment_profile'],packet,'request')

    def test_venue_rules_preserve_precision_minimum_and_cost_risk_guards(self):
        packet=self.packet();context=attach_execution_context(packet,ROOT)
        rules=context['market_scope']['rules']
        self.assertEqual(rules['minimum_order_usdc'],'10')
        self.assertEqual(rules['sz_decimals'],4)
        self.assertEqual(rules['available_ms'],90)
        hypothesis=self.hypothesis(packet)
        self.assertEqual(validate_packet_compilation(hypothesis,
            hypothesis['experiment_profile'],packet,'request')['state'],'executable')
        hypothesis['executable_spec']['execution']['unknown_quote_max_age_ms']+=1
        with self.assertRaisesRegex(ValueError,'preserve'):
            validate_packet_compilation(hypothesis,hypothesis['experiment_profile'],packet,'request')

    def test_raw_metadata_reconstruction_roots_only_verified_archived_catalog(self):
        from tamtam_again.collateral import build_catalog
        from tamtam_again.market_rules import mechanism_profile
        from tamtam_again.storage import Store
        perps=[{'collateralToken':0,'universe':[{'name':'BTC','szDecimals':4,'maxLeverage':40}]}]
        spot=[{'tokens':[{'index':0,'name':'USDC','tokenId':'fixture-usdc'}]},[]]
        refs=['raw_observations:1','raw_observations:2']
        catalog=build_catalog(perps,spot,available_ms=90,evidence_refs=refs)
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'db')
            with patch('tamtam_again.storage.utc_now',return_value='1970-01-01T00:00:00.050+00:00'):
                for endpoint,payload in [('allPerpMetas',perps),('spotMetaAndAssetCtxs',spot)]:
                    store.save_observation(network='fixture',source='hyperliquid-population-rest-v1',
                        entity_type='market',entity_id='collateral:all',endpoint=endpoint,payload=payload,
                        request_payload={'type':endpoint})
            packet=self.packet();packet['network']='fixture';packet['evidence_refs']=['archive:one']
            packet['observations']['market_mechanisms']=[mechanism_profile(catalog,'BTC')]
            store.connection.execute('pragma query_only=on')
            context=attach_execution_context(packet,ROOT,store=store)
            self.assertEqual(context['market_scope']['state'],'supported')
            self.assertEqual(context['metadata_resolution']['state'],'verified')
            self.assertTrue(set(refs)<=set(packet['evidence_refs']))
            store.connection.execute('pragma query_only=off')
            store.connection.execute("update raw_observations set response_sha256='corrupt' where observation_id=1")
            store.connection.commit()
            packet['evidence_refs']=['archive:one']
            context=attach_execution_context(packet,ROOT,store=store)
            self.assertEqual(context['market_scope']['state'],'unknown')
            self.assertEqual(packet['evidence_refs'],['archive:one'])
            store.close()

    def test_readiness_blocks_unavailable_streams_without_forcing_hypothesis_type(self):
        packet=self.packet();attach_execution_context(packet,ROOT)
        packet['observations']['execution_data_readiness']={
            'market_ws_observed':True,'account_ws_observed':False,'funding_ws_observed':True}
        hypothesis=self.hypothesis(packet)
        with self.assertRaisesRegex(ValueError,'account WebSocket'):
            validate_packet_compilation(hypothesis,hypothesis['experiment_profile'],packet,'request')
        response={'decision':'hypothesis','diagnostic':'Fixture only','wake':{},'hypothesis':hypothesis}
        with self.assertRaisesRegex(ValueError,'account WebSocket'):
            validate_response(response,packet,request_id='request')
        hypothesis['type']='autonomous'
        spec=hypothesis['executable_spec'];spec['type']='autonomous'
        spec['signal']={'kind':'momentum','lookback_ms':1000,'threshold_bps':'1'}
        spec['data_sources']=['bbo','streamHealth','userFundings']
        spec['sizing']={'scale':'0.001','units':'0.01'}
        self.assertEqual(validate_packet_compilation(hypothesis,
            hypothesis['experiment_profile'],packet,'request')['state'],'executable')
        packet['observations']['execution_data_readiness']['market_ws_observed']=False
        with self.assertRaisesRegex(ValueError,'market stream'):
            validate_packet_compilation(hypothesis,hypothesis['experiment_profile'],packet,'request')
        del hypothesis['executable_spec'];del hypothesis['experiment_profile']
        validate_response(response,packet,request_id='request')
        self.assertIn('REST receipt is not an account WebSocket signal',build_proposal_prompt(packet,'request'))

    def test_autonomous_market_stream_without_supported_funding_cannot_allocate(self):
        packet=self.packet();attach_execution_context(packet,ROOT)
        packet['observations']['execution_data_readiness']={
            'market_ws_observed':True,'account_ws_observed':True,'funding_ws_observed':False}
        hypothesis=self.hypothesis(packet)
        with self.assertRaisesRegex(ValueError,'funding stream'):
            validate_packet_compilation(hypothesis,hypothesis['experiment_profile'],packet,'request')
        hypothesis['type']='autonomous';hypothesis['executable_spec']['type']='autonomous'
        with self.assertRaisesRegex(ValueError,'funding stream'):
            validate_packet_compilation(hypothesis,hypothesis['experiment_profile'],packet,'request')

    def test_context_alone_cannot_be_market_evidence_and_prompt_keeps_hypothesis_scope(self):
        packet = self.packet()
        attach_execution_context(packet, ROOT)
        hypothesis = self.hypothesis(packet)
        response = {'decision': 'hypothesis', 'diagnostic': 'Fixture only', 'wake': {},
                    'hypothesis': hypothesis}
        validate_response(response, packet, request_id='request')
        hypothesis['evidence_refs'] = ['packet.execution_research_context']
        with self.assertRaises(ValueError):
            validate_response(response, packet, request_id='request')
        prompt = build_proposal_prompt(packet, 'request')
        self.assertIn('Source-trader intentions', prompt)
        self.assertIn('scenario-dependent', prompt)
        self.assertIn('not measured venue costs or latency', prompt)

    def test_compiler_rejects_invented_cheaper_costs_and_expanded_risk(self):
        packet = self.packet()
        attach_execution_context(packet, ROOT)
        for field, value in [('fees', {'maker_bps': '0', 'taker_bps': '0'}),
                             ('max_exposure', {'notional_usdc': '1000000',
                                              'max_drawdown_usdc': '10', 'max_leverage': '1'})]:
            hypothesis = self.hypothesis(packet)
            # The fixture uses context subobjects: copying before replacement
            # ensures the supplied source remains independently sealed.
            hypothesis['executable_spec'][field] = value
            with self.assertRaises(ValueError):
                validate_packet_compilation(hypothesis, hypothesis['experiment_profile'], packet, 'request')
        hypothesis = self.hypothesis(packet)
        hypothesis['executable_spec']['fees'] = {'maker_bps': '6', 'taker_bps': '6'}
        hypothesis['experiment_profile']['justification'] = 'Fixture declared upward cost stress'
        self.assertEqual(validate_packet_compilation(hypothesis,
            hypothesis['experiment_profile'], packet, 'request')['state'], 'executable')


if __name__ == '__main__':
    unittest.main()
