"""Large proof pools stay in the existing lossless archive; host verifies every citation."""
from copy import deepcopy
import gzip
import json
import unittest
from unittest.mock import patch

from tamtam_again.continuous_research import initialize
from tamtam_again.continuous_research_identity import semantic_identity,wake_identities
from tamtam_again.engine import canonical,fingerprint
from tamtam_again.population_runtime import run,validate_response
from tamtam_again.sealed_references import (compact_reference_manifest,expanded_evidence_refs,
    load_manifest_reference_pool,model_packet_view)
from tests import test_population_runtime as runtime_fixtures


class ArchivedReferenceManifestTests(unittest.TestCase):
    def setUp(self):
        self.runtime=runtime_fixtures.RuntimeTests();self.runtime.setUp()
        self.addCleanup(self.runtime.tearDown);self.store=self.runtime.s;initialize(self.store)
        raw=['raw_observations:'+str(i)+'#sha256:'+fingerprint(i) for i in range(6432)]
        refs=['account_scope_reports:one','research_observation_wakes:wake']+raw
        evidence={'promotion_authorized':False,'economic_completeness_proven':False,
            'proofs':[{'source_request':{'source':'public_rest_history','endpoint':'userFillsByTime',
                'proof':'pagination_coverage'},'pagination_status':'covered','evidence_refs':[raw[0]]}]}
        detail={'market':'BTC','observed_fill_content_fingerprint':'all-fills',
            'execution_activity':{'count':1000},'position_path':{'segments':[]},
            'by_utc_day':{'day':{'count':1000}},'fees_signed_by_token':{'USDC':'10'},
            'evidence_refs':raw,'detail_fingerprint':'original'}
        self.source={'network':'test','address':'account','available_ms':20,'evidence_refs':refs,
            'observations':{'markets':['BTC'],'market_execution_detail_v1':{'BTC':detail},
                'descriptive_history_v1':{'markets':{'BTC':{'all_statistics':'kept'}},'evidence_refs':raw},
                'completed_observation_requests':[{'request_id':'wake','evidence':evidence,
                    'evidence_fingerprint':fingerprint(evidence),'pages':[{'evidence_ref':raw[0]}]}]}}
        self.source_fp=fingerprint(self.source)
        self.store.connection.execute('insert into continuous_research_projections values(?,?,?)',
            (self.source_fp,20,gzip.compress(canonical(self.source).encode(),mtime=0)))
        self.packet=deepcopy(self.source)
        compact_reference_manifest(self.packet,self.source,self.source_fp)
        self.packet['fingerprint']=fingerprint(self.packet)
        h={key:'fixture' for key in ('mechanism','signal','entry','exit','sizing','risk',
            'horizon_justification','execution_constraints','rejection_criteria')}
        h.update(type='autonomous',markets=['BTC'],required_data=[],
            evidence_refs=['packet.observations.market_execution_detail_v1.BTC'])
        self.response={'decision':'hypothesis','diagnostic':'fixture','wake':{},'hypothesis':h}

    def test_complete_source_statistics_identity_wakes_and_sections_remain_exact(self):
        self.assertGreater(len(canonical(self.source)),225000)
        self.assertLess(len(canonical(self.packet)),10000)
        self.assertEqual(semantic_identity(self.packet,'BTC'),semantic_identity(self.source,'BTC'))
        self.assertEqual(wake_identities(self.packet),wake_identities(self.source))
        detail=self.packet['observations']['market_execution_detail_v1']['BTC']
        for field in ['execution_activity','position_path','by_utc_day','fees_signed_by_token']:
            self.assertEqual(detail[field],self.source['observations']['market_execution_detail_v1']['BTC'][field])
        pool=load_manifest_reference_pool(self.store,self.packet)
        self.assertEqual(pool,self.source['evidence_refs'])
        self.assertEqual(len(expanded_evidence_refs(self.packet)),4)
        self.assertIn(self.source['evidence_refs'][2],self.packet['evidence_refs'])
        with self.assertRaises(ValueError):validate_response(self.response,self.packet)
        validate_response(self.response,self.packet,source_reference_pool=pool)
        self.response['hypothesis']['evidence_refs']=[self.packet['evidence_source_manifest']['source_reference']]
        validate_response(self.response,self.packet,source_reference_pool=pool)
        self.assertEqual(self.source_fp,fingerprint(self.source))

    def test_forged_count_order_hash_scope_size_and_archive_body_fail_closed(self):
        for field,value in [('reference_count',1),('ordered_source_fingerprint','0'*64),
                ('source_fingerprint','0'*64),('network','other'),('address','other'),
                ('available_ms',21),('source_canonical_bytes',1)]:
            packet=deepcopy(self.packet);packet['evidence_source_manifest'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):load_manifest_reference_pool(self.store,packet)
        packet=deepcopy(self.packet);packet['evidence_refs'].append('forged:reference')
        with self.assertRaises(ValueError):load_manifest_reference_pool(self.store,packet)
        self.store.connection.execute('update continuous_research_projections set body_gzip=?',
            (gzip.compress(canonical({**self.source,'address':'other'}).encode(),mtime=0),))
        with self.assertRaises(ValueError):load_manifest_reference_pool(self.store,self.packet)

    def test_guards_reject_before_body_read(self):
        statements=[];self.store.connection.set_trace_callback(statements.append)
        for guard in [patch('tamtam_again.discovery.protected_addresses',return_value={'account'}),
                patch('tamtam_again.research_memory.authorized_account_history',return_value=False)]:
            with guard,self.assertRaises(ValueError):load_manifest_reference_pool(self.store,self.packet)
        self.assertFalse(any('select body_gzip' in statement.lower() for statement in statements))
        self.store.connection.set_trace_callback(None)

    def test_runtime_both_prompts_compact_source_verified_and_no_replay_calls(self):
        self.store.connection.execute('update population_research_jobs set packet_json=?,policy_json=?',
            (canonical(self.packet),canonical({**self.runtime.policy,'max_prompt_chars':100000})))
        self.store.connection.commit()
        before=deepcopy(self.packet)
        critique={'decision':'consistent','diagnostic':'fixture','wake':{}}
        with patch('tamtam_again.population_runtime.verify'),patch('tamtam_again.population_runtime.call',
                side_effect=[(canonical(self.response),self.runtime.usage),(canonical(critique),self.runtime.usage)]) as caller:
            self.assertEqual(run(self.store,self.runtime.request)['status'],'hypothesis_recorded')
            self.assertEqual(run(self.store,self.runtime.request)['status'],'unchanged_no_inference')
            self.assertEqual(caller.call_count,2)
        prompts=[item.args[1] for item in caller.call_args_list]
        view1=json.loads(prompts[0].split('\nPacket:\n')[1])
        view2=json.loads(prompts[1].split('\nPacket:\n')[1].split('\nProposal:\n')[0])
        self.assertEqual(view1,view2);self.assertEqual(view1,model_packet_view(self.packet))
        row=self.store.connection.execute('select packet_json,result_json,usage_json from population_research_jobs').fetchone()
        self.assertEqual(json.loads(row['packet_json']),before)
        self.assertEqual(json.loads(row['result_json'])['proposal'],self.response)
        self.assertEqual(len(json.loads(row['usage_json'])),2)

    def test_bad_manifest_suspends_before_any_call_and_never_retries(self):
        self.packet['evidence_source_manifest']['reference_count']+=1
        self.store.connection.execute('update population_research_jobs set packet_json=?',(canonical(self.packet),))
        self.store.connection.commit()
        with patch('tamtam_again.population_runtime.verify'),patch('tamtam_again.population_runtime.call') as caller:
            self.assertEqual(run(self.store,self.runtime.request)['status'],'suspended')
            self.assertEqual(run(self.store,self.runtime.request)['status'],'unchanged_no_inference')
            caller.assert_not_called()
