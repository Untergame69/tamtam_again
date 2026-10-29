import copy
import gzip
import unittest

from tamtam_again.engine import canonical,fingerprint
from tamtam_again.position_projection import compact_records,restore_records
from tamtam_again.sealed_references import (compact_evidence_refs,expanded_evidence_refs,
    compact_section_reference_indices,section_reference_indices)
from tamtam_again.continuous_research_identity import semantic_identity,wake_identities
from tamtam_again.population_runtime import validate_response,sealed_section_reference_paths
from tamtam_again.population_compilation import packet_references


class PositionTablesTests(unittest.TestCase):
    def records(self):
        return {str(i):{'start_ms':i*1000,'end_ms':i*1000+500,'activity':{
            'fills':i+2,'maker':True,'fee_tokens':{} if i%2 else {'USDC':str(i)},
            'direction':'long','unknown':None,'tags':['one','two']}} for i in range(100)}

    def test_every_record_type_missing_key_and_order_round_trips(self):
        records=self.records();records['5']['activity']['extra']=False
        for source in (records,list(reversed(list(records.values())))):
            encoded=compact_records(source)
            self.assertLess(len(canonical(encoded)),len(canonical(source)))
            self.assertEqual(restore_records(encoded),source)
            self.assertEqual(fingerprint(restore_records(encoded)),fingerprint(source))

    def test_corruption_duplicate_rows_and_incomplete_columns_fail_closed(self):
        original=compact_records(self.records())
        corruptions=[]
        bad=copy.deepcopy(original);bad['source_fingerprint']='0'*64;corruptions.append(bad)
        bad=copy.deepcopy(original);bad['record_count']+=1;corruptions.append(bad)
        bad=copy.deepcopy(original);bad['groups'][0]['rows'].append(bad['groups'][0]['rows'][0]);corruptions.append(bad)
        bad=copy.deepcopy(original);bad['groups'][0]['columns'].append(True);corruptions.append(bad)
        for bad in corruptions:
            with self.assertRaises(ValueError):restore_records(bad)

    def test_large_constant_cannot_amplify_past_restored_size_bound(self):
        table={'projection_version':'position-record-table-v1','kind':'list','record_count':10000,
            'source_fingerprint':'deliberately-not-a-real-source-hash','groups':[{
                'layout':{'blob':0},'field_count':1,'constants':{'0':'x'*10000},'columns':[],
                'rows':[[i,[]] for i in range(10000)]}]}
        self.assertLess(len(canonical(table)),225000)
        with self.assertRaisesRegex(ValueError,'restored-size bound'):
            restore_records(table)


class ReferenceProjectionTests(unittest.TestCase):
    def test_reference_runs_preserve_every_index_order_and_source_binding(self):
        refs=['fixture:'+str(i) for i in range(1000)]
        indices=list(range(700))+list(range(900,950))+list(range(900,920))
        section={'evidence_ref_indices':indices,'reference_projection':{
            'version':'sealed-root-reference-indices-v1','reference_pool':'packet.evidence_refs',
            'reference_count':len(indices),'ordered_reference_fingerprint':fingerprint([refs[i] for i in indices])}}
        before=copy.deepcopy(section);compact_section_reference_indices(section)
        self.assertEqual(section_reference_indices(section,len(refs)),indices)
        self.assertLess(len(canonical(section)),len(canonical(before)))
        packet={'evidence_refs':refs,'observations':{'markets':['COIN'],
            'market_execution_detail_v1':{'COIN':section}}}
        self.assertIn('packet.observations.market_execution_detail_v1.COIN',
            sealed_section_reference_paths(packet,set(refs))[0])
        section['reference_projection']['ordered_reference_fingerprint']='0'*64
        self.assertNotIn('packet.observations.market_execution_detail_v1.COIN',
            sealed_section_reference_paths(packet,set(refs))[0])
        for runs in ([[0,1000000000]],[[-1,2]],[[0,0]],[[True,2]]):
            bad={'evidence_ref_runs':runs,'reference_projection':{'version':'sealed-root-reference-ranges-v1'}}
            with self.assertRaises(ValueError):section_reference_indices(bad,len(refs))

    def test_all_hash_bytes_and_reference_indices_round_trip(self):
        refs=['raw_observations:'+str(i)+'#sha256:'+fingerprint({'row':i}) for i in range(100)]
        packet={'evidence_refs':refs+['raw_observations:1000','fixture:source']}
        original=copy.deepcopy(packet)
        compact_evidence_refs(packet)
        self.assertEqual(expanded_evidence_refs(packet),original['evidence_refs'])
        self.assertLess(len(canonical(packet)),len(canonical(original)))
        again=copy.deepcopy(packet);compact_evidence_refs(packet);self.assertEqual(packet,again)
        packet['evidence_refs'][0]=packet['evidence_refs'][1]
        with self.assertRaises(ValueError):expanded_evidence_refs(packet)

    def test_missing_header_and_malformed_codec_are_not_silently_accepted(self):
        for refs in (['raw85:1:bad'],['raw85:1:'+('é'*40)]):
            with self.assertRaises(ValueError):expanded_evidence_refs({'evidence_refs':refs})
        packet={'evidence_refs':['raw_observations:1#sha256:'+('1'*64)]};compact_evidence_refs(packet)
        packet['evidence_refs'][0]='raw85:1:'+('é'*40)
        with self.assertRaises(ValueError):expanded_evidence_refs(packet)

    def test_completed_wake_keeps_its_exact_canonical_page_binding(self):
        ref='raw_observations:1#sha256:'+('b'*64)
        evidence={'promotion_authorized':False,'economic_completeness_proven':False,
            'proofs':[{'source_request':{'source':'public_rest_history','endpoint':'userFillsByTime',
                'proof':'pagination_coverage'},'pagination_status':'covered','evidence_refs':[ref]}]}
        packet={'evidence_refs':['research_observation_wakes:fixture',ref],
            'observations':{'completed_observation_requests':[{'request_id':'fixture',
                'evidence':evidence,'evidence_fingerprint':fingerprint(evidence),'pages':[{'evidence_ref':ref}]}]}}
        before=wake_identities(packet);compact_evidence_refs(packet)
        self.assertEqual(wake_identities(packet),before)

    def test_compiled_response_may_cite_exact_short_or_original_reference(self):
        from tests.test_execution_research_context import ExecutionResearchContextTests,ROOT
        from tamtam_again.execution_research_context import attach_execution_context
        fixture=ExecutionResearchContextTests();packet=fixture.packet();ref='raw_observations:123#sha256:'+('a'*64)
        packet['evidence_refs'].append(ref);attach_execution_context(packet,ROOT)
        hypothesis=fixture.hypothesis(packet);hypothesis['evidence_refs']=[ref,'packet.execution_research_context']
        compact_evidence_refs(packet)
        for reference in (ref,next(r for r in packet['evidence_refs'] if r.startswith('raw85:'))):
            hypothesis['evidence_refs']=[reference,'packet.execution_research_context']
            validate_response({'decision':'hypothesis','diagnostic':'fixture','wake':{},'hypothesis':hypothesis},packet,request_id='request')


class ProductionProjectionIdentityTests(unittest.TestCase):
    def test_lossless_position_and_reference_projection_preserves_semantic_identity(self):
        from tests.test_continuous_research import ContinuousPreparationTests
        from tamtam_again.continuous_research import _project_other_markets
        fixture=ContinuousPreparationTests();fixture.setUp()
        try:
            refs=['raw_observations:'+str(i)+'#sha256:'+fingerprint(i) for i in range(100)]
            detail={'market':'COIN','observed_fill_content_fingerprint':'all-fills',
                'execution_activity':{'count':1000},'position_path':{'segments':PositionTablesTests().records(),
                    'ruptures':[{'time':i,'before':'0','after':str(i)} for i in range(50)]},
                'by_utc_day':{'day':{'count':1000}},'fees_signed_by_token':{'USDC':'10'},
                'evidence_refs':refs,'detail_fingerprint':'original-detail'}
            packet={'network':'fixture','address':'fixture','evidence_refs':refs,
                'observations':{'markets':['COIN'],'market_execution_detail_v1':{'COIN':detail},
                    'descriptive_history_v1':{'markets':{'COIN':{'positions':{'position_chain_segments':list(PositionTablesTests().records().values())}}},'evidence_refs':refs}}}
            before=copy.deepcopy(packet);identity=semantic_identity(packet,'COIN');source=fingerprint(packet)
            _project_other_markets(fixture.store,packet,'COIN',200)
            self.assertEqual(semantic_identity(packet,'COIN'),identity)
            self.assertLess(len(canonical(packet)),len(canonical(before)))
            paths,_=sealed_section_reference_paths(packet,packet_references(packet))
            self.assertIn('packet.observations.market_execution_detail_v1.COIN',paths)
            blob=fixture.store.connection.execute('select body_gzip from continuous_research_projections where source_fingerprint=?',(source,)).fetchone()[0]
            self.assertEqual(__import__('json').loads(gzip.decompress(blob)),before)
        finally:fixture.tearDown()
