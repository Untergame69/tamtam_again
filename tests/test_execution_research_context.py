import json
from pathlib import Path
import tempfile
import unittest

from tamtam_again.execution_research_context import attach_execution_context
from tamtam_again.population_compilation import validate_packet_compilation
from tamtam_again.population_runtime import build_proposal_prompt, validate_response


ROOT = Path(__file__).resolve().parents[1]


class ExecutionResearchContextTests(unittest.TestCase):
    def packet(self):
        return {'available_ms': 100, 'evidence_refs': ['archive:one'],
                'observations': {'markets': ['BTC']}}

    def test_existing_scenario_preserves_values_without_inventing_rule_or_measurements(self):
        packet = self.packet()
        original = json.loads((ROOT / 'config/research-policy.json').read_text())
        context = attach_execution_context(packet, ROOT)
        self.assertEqual(context['scenario'], {key: original['strategy_template'][key]
            for key in ('max_exposure', 'fees', 'slippage', 'latency_ms',
                        'starting_capital_usdc', 'execution')})
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
