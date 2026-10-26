from copy import deepcopy
import unittest

from tamtam_again.engine import fingerprint
from tamtam_again.population_runtime import sealed_section_reference_paths, validate_response
from tamtam_again.research import CallContractError


class SealedSectionReferenceTests(unittest.TestCase):
    def setUp(self):
        self.refs=['raw_observations:1#sha256:a','raw_observations:2#sha256:b']
        projection={'version':'sealed-root-reference-indices-v1',
            'reference_pool':'packet.evidence_refs','reference_count':2,
            'ordered_reference_fingerprint':fingerprint(self.refs)}
        self.packet={'evidence_refs':self.refs[:],'observations':{'markets':['BTC'],
            'descriptive_history_v1':{'evidence_ref_indices':[0,1], 'reference_projection':projection},
            'market_execution_detail_v1':{'BTC':{'evidence_refs':self.refs[:]}},
            'market_mechanisms':[{'evidence_refs':self.refs[:]}]},
            'pilot_research':{'question':'fixture'},'research_contract':{'purpose':'descriptive'}}
        self.response={'decision':'hypothesis','diagnostic':'fixture','wake':{},
            'hypothesis':{key:'fixture' for key in ('mechanism','signal','entry','exit','sizing',
                'risk','horizon_justification','execution_constraints','rejection_criteria')}}
        self.response['hypothesis'].update(type='autonomous',markets=['BTC'],required_data=[],
            evidence_refs=['packet.observations.descriptive_history_v1','packet.pilot_research'])

    def test_known_section_paths_resolve_to_exact_sealed_sources(self):
        before=deepcopy(self.packet)
        sources,context=sealed_section_reference_paths(self.packet,set(self.refs))
        self.assertIn('packet.observations.descriptive_history_v1',sources)
        self.assertIn('packet.observations.market_execution_detail_v1.BTC',sources)
        self.assertIn('packet.pilot_research',context)
        validate_response(self.response,self.packet)
        self.assertEqual(self.packet,before)

    def test_tampered_reference_projection_cannot_authorize_a_section_path(self):
        self.packet['observations']['descriptive_history_v1']['reference_projection']['ordered_reference_fingerprint']='f'*64
        with self.assertRaises(CallContractError):validate_response(self.response,self.packet)

    def test_unknown_paths_and_metadata_only_citations_are_rejected(self):
        for refs in [['packet.observations.future_quotes'],['packet.pilot_research'],
                ['packet.observations.market_execution_detail_v1.ETH'],['packet.research_contract']]:
            response=deepcopy(self.response);response['hypothesis']['evidence_refs']=refs
            with self.assertRaises(CallContractError):validate_response(response,self.packet)

    def test_out_of_pool_projection_and_unknown_source_refs_are_rejected(self):
        self.packet['observations']['descriptive_history_v1']['evidence_ref_indices']=[99]
        with self.assertRaises(CallContractError):validate_response(self.response,self.packet)
        self.packet['observations']['descriptive_history_v1']={'evidence_refs':['raw_observations:foreign']}
        with self.assertRaises(CallContractError):validate_response(self.response,self.packet)


if __name__=='__main__':unittest.main()
