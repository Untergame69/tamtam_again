from copy import deepcopy
import json
import unittest

from tamtam_again.engine import canonical,fingerprint
from tamtam_again.population_runtime import validate_response
from tamtam_again.sealed_references import (bind_model_evidence_refs,compact_evidence_refs,
    expanded_evidence_refs,model_packet_view)
from tamtam_again.continuous_research_identity import wake_identities
from tests import test_execution_contract_binding as binding_fixtures


class ModelPacketViewTests(unittest.TestCase):
    def packet(self):
        refs=['raw_observations:'+str(i)+'#sha256:'+fingerprint({'row':i}) for i in range(8)]
        packet={'evidence_refs':refs,'observations':{'statistics':{'all_rows':8},
            'descriptive_history_v1':{'evidence_ref_indices':[0,7],'reference_projection':{
                'ordered_reference_fingerprint':fingerprint([refs[0],refs[7]])}}}}
        compact_evidence_refs(packet)
        packet['fingerprint']=fingerprint(packet)
        return packet,refs

    def test_view_changes_only_display_pool_and_preserves_source_indices_and_wakes(self):
        packet,refs=self.packet();before=deepcopy(packet);wakes=wake_identities(packet)
        view=model_packet_view(packet)
        self.assertEqual(view['evidence_refs'],['proof_ref:'+str(i) for i in range(8)])
        self.assertEqual(view['observations'],packet['observations'])
        self.assertNotIn('fingerprint',view)
        self.assertEqual(view['model_packet_view']['source_body_fingerprint'],fingerprint(packet))
        self.assertEqual(view['model_packet_view']['source_sealed_fingerprint'],packet['fingerprint'])
        self.assertEqual(view['evidence_reference_projection'],packet['evidence_reference_projection'])
        self.assertEqual(packet,before);self.assertEqual(wake_identities(packet),wakes)
        for operation in [lambda:expanded_evidence_refs(view),lambda:model_packet_view(view),
                lambda:bind_model_evidence_refs({},view),lambda:validate_response({'decision':'reject','diagnostic':'fixture','wake':{}},view)]:
            with self.assertRaises(ValueError):operation()

    def test_only_finite_evidence_locations_resolve_exactly_without_mutation(self):
        packet,refs=self.packet()
        response={'evidence_refs':['proof_ref:7'],'diagnostic':'proof_ref:1',
            'hypothesis':{'evidence_refs':['proof_ref:0','literal'],
                'experiment_profile':{'axes':[{'evidence_refs':['proof_ref:3']}]},
                'signal':{'evidence_refs':['proof_ref:2']}}}
        before=deepcopy(response)
        resolved,provenance=bind_model_evidence_refs(response,packet)
        self.assertEqual(resolved['evidence_refs'],[refs[7]])
        self.assertEqual(resolved['hypothesis']['evidence_refs'],[refs[0],'literal'])
        self.assertEqual(resolved['hypothesis']['experiment_profile']['axes'][0]['evidence_refs'],[refs[3]])
        self.assertEqual(resolved['hypothesis']['signal'],response['hypothesis']['signal'])
        self.assertEqual(resolved['diagnostic'],response['diagnostic']);self.assertEqual(response,before)
        self.assertEqual(len(provenance[0]['bindings']),3)

    def test_invalid_alias_and_corrupt_or_reordered_source_fail_closed(self):
        packet,_=self.packet()
        for alias in ['proof_ref:8','proof_ref:-1','proof_ref:01','proof_ref:1.0','proof_ref:','proof_ref:1\n']:
            with self.subTest(alias=alias),self.assertRaises(ValueError):
                bind_model_evidence_refs({'hypothesis':{'evidence_refs':[alias]}},packet)
        plain={'evidence_refs':['original:first','original:second']}
        plain['fingerprint']=fingerprint(plain);plain['evidence_refs'].reverse()
        with self.assertRaises(ValueError):
            bind_model_evidence_refs({'hypothesis':{'evidence_refs':['proof_ref:0']}},plain)
        for mutation in ['reorder','bad_header','alias_pool']:
            broken=deepcopy(packet)
            if mutation=='reorder':broken['evidence_refs'].reverse()
            if mutation=='bad_header':broken['evidence_reference_projection']['ordered_source_fingerprint']='0'*64
            if mutation=='alias_pool':broken['evidence_refs'][0]='proof_ref:0'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                bind_model_evidence_refs({'hypothesis':{'evidence_refs':['proof_ref:0']}},broken)


class RuntimeModelViewTests(unittest.TestCase):
    setUp=binding_fixtures.ExecutionContractBindingTests.setUp
    tearDown=binding_fixtures.ExecutionContractBindingTests.tearDown
    run_fixture=binding_fixtures.ExecutionContractBindingTests.run_fixture

    def test_both_prompts_use_same_view_and_persist_resolved_aliases(self):
        self.hypothesis['evidence_refs']=['proof_ref:0','packet.execution_research_context']
        self.hypothesis['experiment_profile']['axes'][0]['evidence_refs']=['proof_ref:1']
        before=deepcopy(self.packet)
        outcome,caller,artifacts,usage,raw,response,row=self.run_fixture()
        self.assertEqual(outcome['status'],'hypothesis_recorded');self.assertEqual(caller.call_count,2)
        self.assertEqual(artifacts['source_proposal'],response);self.assertEqual(artifacts['raw_proposal'],raw)
        self.assertEqual(artifacts['proposal']['hypothesis']['evidence_refs'][0],expanded_evidence_refs(self.packet)[0])
        self.assertEqual(artifacts['proposal']['hypothesis']['experiment_profile']['axes'][0]['evidence_refs'],[expanded_evidence_refs(self.packet)[1]])
        self.assertEqual(artifacts['proposal']['hypothesis']['executable_spec']['execution']['funding_sensitivity_scenario'],self.contract)
        prompts=[item.args[1] for item in caller.call_args_list]
        first=json.loads(prompts[0].split('\nPacket:\n')[1])
        second=json.loads(prompts[1].split('\nPacket:\n')[1].split('\nProposal:\n')[0])
        self.assertEqual(first,second);self.assertEqual(first,model_packet_view(self.packet))
        self.assertEqual(json.loads(prompts[1].split('\nProposal:\n')[1]),response)
        self.assertEqual(len(artifacts['evidence_reference_bindings'][0]['bindings']),2)
        self.assertEqual(self.packet,before);self.assertEqual(len(usage),2)

    def test_unknown_alias_consumes_one_call_and_never_critiques(self):
        self.hypothesis['evidence_refs']=['proof_ref:999']
        outcome,caller,artifacts,usage,raw,response,row=self.run_fixture()
        self.assertEqual(outcome['status'],'suspended');self.assertEqual(caller.call_count,1)
        self.assertEqual(artifacts['source_proposal'],response);self.assertEqual(artifacts['raw_proposal'],raw)
        self.assertNotIn('proposal',artifacts);self.assertNotIn('critique',artifacts)
