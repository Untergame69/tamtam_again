import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tamtam_again.engine import canonical
from tamtam_again.paper_followup import present_report
from tamtam_again.paper_local_resolution import prepare_from_local_archives, packet_for_resolution
from tamtam_again.research_jobs import request_count
from tests.test_paper_followup import FollowupTests


REQUESTS=[
    'Canonical per-attempt paper records with unique attempt IDs, retry ancestry, decision IDs, intent, intended target, pre/post inventory, unrounded and rounded adjustment, eligibility price/notional, refusal reason, quote ID, displayed-size cap and exact fill IDs; include opening state and frozen target-update semantics.',
    'Event-level HYPE quote and stream-health archive with event, receive, archive and processing timestamps, connection transitions, depth used and quote-selection lineage for each attempt.',
    'Persisted source-event-to-decision causal keys and ordered source-event payloads with local availability timestamps; if keys were never stored, declare retrospective exact attribution unavailable.',
    'Subsequent paper inventory, pending-order resolution, fill and marking records through observed closure or an explicitly censored endpoint, with funding coverage for the full held-inventory interval.',
]


def iso(ms):
    return datetime.fromtimestamp(ms/1000,timezone.utc).isoformat(timespec='milliseconds')


class PaperLocalResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp,self.store=FollowupTests()._runtime_fixture()
        self.task=present_report(self.store,'s','r',clock_ms=30)
        self.request_id=self.task['job_id']
        self.store.connection.execute('update paper_research_jobs set status=?,activated_ms=?,data_available_ms=?,updated_ms=?,result_json=? where request_id=?',
            ('needs_data',40,20,50,canonical({'proposal':{'hypothesis':{'required_data':REQUESTS}},
                'critique':{'decision':'needs_data','diagnostic':{'finding':'fixture'},'wake':{'kind':'missing_observations_available'}},
                'promotion_authorized':False,'profitability_proven':False}),self.request_id))
        opportunities=[
            {'signal_decision_ms':11,'due_ms':11,'execution_decision_ms':12,'intent':'reduction','outcome':'missed',
             'eligible':True,'reason':'below_venue_minimum_order_value','position_before':'1','position_after':None,
             'order_size':'-0.01','fill_size':None,'order_notional_usdc':'0.8','quote_age_ms':1,
             'quote_received_ms':11,'quote_available_ms':11,'quote_source':'bbo','connection_id':'c1',
             'partial_fill':False,'order_selection':None},
            {'signal_decision_ms':13,'due_ms':13,'execution_decision_ms':14,'intent':'reduction','outcome':'partial',
             'eligible':True,'reason':None,'position_before':'1','position_after':'0.5','order_size':'-1',
             'fill_size':'-0.5','order_notional_usdc':'50','quote_age_ms':1,
             'quote_received_ms':13,'quote_available_ms':13,'quote_source':'l2Book','connection_id':'c1',
             'partial_fill':True,'order_selection':'closeable_full'}]
        state={'last_ms':20,'position':'0.5','pending':[{'intent':'reduction','target':'0'}],
            'fills':[{'received_ms':14,'price':'100','size':'-0.5','fee':'0.1'}],
            'execution_opportunities':opportunities,'funding':'0','funding_events':0}
        self.store.connection.execute('update paper_sessions set state_json=?,status=? where session_id=?',
            (canonical(state),'suspended','s'))
        self.store.connection.execute('insert into paper_suspensions values(?,?,?)',('s',20,'["paper_duration_budget_exhausted"]'))
        self._observation('market','HYPE','bbo',11,15,{'events':[{'received_at':iso(11),'message':{
            '_stream':{'connection_id':'c1'},'data':{'time':10,'bbo':[{'px':'100','sz':'10'},{'px':'101','sz':'8'}]}}}]})
        self._observation('market','HYPE','l2Book',13,16,{'events':[{'received_at':iso(13),'message':{
            '_stream':{'connection_id':'c1'},'data':{'coin':'HYPE','time':12,
            'levels':[[{'px':'99','sz':'4'}],[{'px':'102','sz':'5'}]]}}}]})
        self._observation('stream','c1','streamHealth',15,16,{'connected':True,'kind':'heartbeat','markets':['HYPE']})
        self._observation('account','0xabc','userFills',17,18,{'_stream':{'connection_id':'c1'},
            'data':{'isSnapshot':False,'fills':[{'coin':'HYPE','time':16,'tid':'123','sz':'0.5','side':'B'}]}},
            request={'user_fills_stream':{'connection_id':'c1','sequence':2}})
        self.store.connection.commit()

    def tearDown(self):
        self.store.connection.close();self.tmp.cleanup()

    def _observation(self,entity_type,entity_id,endpoint,received_ms,available_ms,payload,request=None):
        body=json.dumps(payload,separators=(',',':'))
        self.store.connection.execute('insert into raw_observations '
            '(network,source,entity_type,entity_id,endpoint,request_json,requested_at,observed_at,window_start_ms,'
            'window_end_ms,record_count,complete,response_encoding,response_sha256,response_json) '
            'values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            ('hyperliquid-mainnet','hyperliquid-websocket-v1',entity_type,entity_id,endpoint,
             json.dumps(request or {}),iso(received_ms),iso(available_ms),received_ms,available_ms,1,1,'json',
             hashlib.sha256(body.encode()).hexdigest(),body))

    def test_local_archive_resolution_prepares_deduplicated_child_without_model_calls(self):
        original=self.store.connection.execute('select packet_json,result_json from paper_research_jobs where request_id=?',(self.request_id,)).fetchone()[:]
        with unittest.mock.patch('tamtam_again.population_runtime.call') as model:
            first=prepare_from_local_archives(self.store,self.request_id,clock_ms=1000)
            same=prepare_from_local_archives(self.store,self.request_id,clock_ms=1001)
        model.assert_not_called()
        self.assertEqual(first['status'],'prepared')
        self.assertEqual(same['status'],'unchanged')
        self.assertEqual(first['resolution_id'],same['resolution_id'])
        self.assertLessEqual(first['packet_chars'],225_000)
        self.assertEqual([x['classification'] for x in first['classifications']],
            ['partially_available','available_with_ambiguity','historical_link_unavailable','censored_endpoint_incomplete'])
        child=self.store.connection.execute('select status,activated_ms,local_resolution_id,parent_request_id,packet_json '
            'from paper_research_jobs where request_id=?',(first['child_request_id'],)).fetchone()
        self.assertEqual(child['status'],'budget_required')
        self.assertIsNone(child['activated_ms'])
        self.assertEqual(child['local_resolution_id'],first['resolution_id'])
        self.assertEqual(child['parent_request_id'],self.request_id)
        packet=json.loads(child['packet_json'])
        self.assertEqual(packet['schema_version'],'paper-local-evidence-research-v2')
        self.assertEqual(packet['observations']['local_archive_bundle']['coverage']['archive_event_counts']['bbo'],1)
        self.assertTrue(packet['observations']['local_archive_bundle']['archive_observation_manifest'])
        self.assertEqual(packet['observations']['local_archive_bundle']['paper_endpoint']['position'],'0.5')
        self.assertEqual(packet['observations']['local_archive_bundle']['paper_endpoint']['observation_boundary'],'censored_open_position')
        self.assertEqual(packet['observations']['local_archive_bundle']['paper_endpoint']['terminal_result'],'incomplete_censored')
        self.assertEqual(packet_for_resolution(self.store,first['resolution_id'],clock_ms=1001,max_chars=225_000)['packet'],packet)
        self.assertEqual(self.store.connection.execute('select count(*) from paper_local_evidence_resolutions').fetchone()[0],1)
        self.assertEqual(self.store.connection.execute('select count(*) from paper_research_jobs where parent_request_id=?',(self.request_id,)).fetchone()[0],1)
        self.assertEqual(self.store.connection.execute('select packet_json,result_json from paper_research_jobs where request_id=?',(self.request_id,)).fetchone()[:],original)

    def test_local_child_activation_runtime_decision_and_replay_without_second_call(self):
        from tamtam_again.paper_research import authorize_task, seal
        from tamtam_again.paper_runtime import run
        from tamtam_again.population_routing import route
        from tamtam_again.engine import canonical
        from unittest.mock import patch
        prepared=prepare_from_local_archives(self.store,self.request_id,clock_ms=1000)
        child_id=prepared['child_request_id']
        child=self.store.connection.execute('select adaptation_request_id,packet_json,status from paper_research_jobs where request_id=?',
            (child_id,)).fetchone()
        self.assertEqual(child['status'],'budget_required')
        policy={'version':'paper-adaptation-research-v1','justification':'fixture activation only',
            'max_requests':1,'max_packet_chars':225000,'max_prompt_chars':260000,
            'minimum_interval_ms':1,'timeout_seconds':120,'max_output_tokens':5000,
            'max_request_age_ms':3600000,'model':'fixture','usage_mode':'subscription',
            'max_model_calls':2,'max_input_tokens_per_call':80000,
            'max_total_input_tokens':160000,'max_total_output_tokens':10000,
            'max_total_duration_ms':240000}
        dormant=seal(self.store,child['adaptation_request_id'],policy,clock_ms=1100,
            local_resolution_id=prepared['resolution_id'])
        self.assertEqual(dormant['status'],'budget_exhausted')
        self.assertEqual(self.store.connection.execute('select status,activated_ms from paper_research_jobs where request_id=?',
            (child_id,)).fetchone()[:],('budget_required',None))
        auth=authorize_task(self.store,child_id,authorization_ref='fixture-local-child-approval',
            authorized_ms=1101,packet_fingerprint_value=json.loads(child['packet_json'])['fingerprint'],
            max_calls=2,usage_mode='subscription',max_input_tokens_per_call=80000,
            max_total_input_tokens=160000,max_total_output_tokens=10000,max_total_duration_ms=240000)
        self.assertEqual(auth['status'],'authorized')
        activated=seal(self.store,child['adaptation_request_id'],policy,clock_ms=1200,
            local_resolution_id=prepared['resolution_id'])
        self.assertEqual(activated['status'],'sealed')
        persisted=self.store.connection.execute('select status,activated_ms,local_resolution_id from paper_research_jobs where request_id=?',
            (child_id,)).fetchone()
        self.assertEqual(tuple(persisted),('sealed',1200,prepared['resolution_id']))
        self.assertEqual(packet_for_resolution(self.store,prepared['resolution_id'],clock_ms=1200,
            max_chars=225000,phase='execute')['packet']['fingerprint'],
            json.loads(child['packet_json'])['fingerprint'])
        # Keep the execution-phase protections explicit: identity, packet
        # fingerprint and the exact task authorization must all revalidate.
        self.store.connection.execute('update paper_local_evidence_resolutions set child_request_id=? where resolution_id=?',
            ('wrong-child',prepared['resolution_id']))
        with self.assertRaisesRegex(ValueError,'identity or dormant state'):
            packet_for_resolution(self.store,prepared['resolution_id'],clock_ms=1200,max_chars=225000,phase='execute')
        self.store.connection.execute('update paper_local_evidence_resolutions set child_request_id=? where resolution_id=?',
            (child_id,prepared['resolution_id']))
        saved_packet=self.store.connection.execute('select packet_json from paper_research_jobs where request_id=?',(child_id,)).fetchone()[0]
        self.store.connection.execute('update paper_research_jobs set packet_json=? where request_id=?',
            (canonical({'fingerprint':'tampered'}),child_id))
        with self.assertRaisesRegex(ValueError,'packet fingerprint mismatch'):
            packet_for_resolution(self.store,prepared['resolution_id'],clock_ms=1200,max_chars=225000,phase='execute')
        self.store.connection.execute('update paper_research_jobs set packet_json=? where request_id=?',(saved_packet,child_id))
        saved_auth=self.store.connection.execute('select packet_fingerprint from paper_research_task_authorizations where request_id=?',
            (child_id,)).fetchone()[0]
        self.store.connection.execute('update paper_research_task_authorizations set packet_fingerprint=? where request_id=?',
            ('tampered',child_id))
        with self.assertRaisesRegex(ValueError,'matching active task authorization'):
            packet_for_resolution(self.store,prepared['resolution_id'],clock_ms=1200,max_chars=225000,phase='execute')
        self.store.connection.execute('update paper_research_task_authorizations set packet_fingerprint=? where request_id=?',
            (saved_auth,child_id))
        proposal={'decision':'needs_data','diagnostic':'Fixture: causal keys are still absent.',
            'wake':{'kind':'named_data','conditions':['fixture only']}}
        usage={'cost_status':'included','cost_usd':0,'input_tokens':1200,'output_tokens':90,
            'duration_ms':300,'model':'fixture'}
        with patch('tamtam_again.population_runtime.now_ms',return_value=1201), \
             patch('tamtam_again.population_runtime.verify'), \
             patch('tamtam_again.population_runtime.call',return_value=(canonical(proposal),usage)) as model:
            first=run(self.store,child_id)
            second=run(self.store,child_id)
        self.assertEqual(first['status'],'needs_data')
        self.assertEqual(second['status'],'unchanged_no_inference')
        model.assert_called_once()
        decision=route(self.store,child_id,kind='paper')
        self.assertEqual(decision['state'],'needs_data')
        self.assertEqual(route(self.store,child_id,kind='paper'),decision)
        saved=self.store.connection.execute('select status,result_json,usage_json from paper_research_jobs where request_id=?',
            (child_id,)).fetchone()
        self.assertEqual(saved['status'],'needs_data')
        self.assertEqual(json.loads(saved['result_json'])['proposal'],proposal)
        self.assertEqual(len(json.loads(saved['usage_json'])),1)
        self.assertEqual(self.store.connection.execute('select calls_started,state from paper_research_task_authorizations where request_id=?',
            (child_id,)).fetchone()[:],(1,'completed'))

    def test_provider_artifacts_precede_validation_and_survive_reopen_without_retry(self):
        from tamtam_again.paper_research import authorize_task, seal
        from tamtam_again.paper_runtime import run
        from tamtam_again.engine import canonical
        from tamtam_again.storage import Store
        from unittest.mock import patch
        cases=[
            ('included_valid',{'cost_status':'included','cost_usd':0,'input_tokens':1200,'output_tokens':90},
                canonical({'decision':'needs_data','diagnostic':'Specific observations remain absent.',
                    'wake':{'kind':'named_data','conditions':['fixture']}}),'result_validated',None),
            ('tokens_missing',{'cost_status':'included','cost_usd':0,'output_tokens':90},
                canonical({'decision':'needs_data','diagnostic':'fixture','wake':{}}),'rejected',
                ('token_usage_missing_or_invalid','usage.input_tokens',None)),
            ('tokens_over_limit',{'cost_status':'included','cost_usd':0,'input_tokens':80001,'output_tokens':90},
                canonical({'decision':'needs_data','diagnostic':'fixture','wake':{}}),'rejected',
                ('per_call_token_limit_exceeded','usage.input_tokens',80001)),
            ('malformed',{'cost_status':'included','cost_usd':0,'input_tokens':1200,'output_tokens':90},
                '{not json','rejected',('malformed_provider_response','response',{'type':'JSONDecodeError',
                    'length_chars':9,'line':1,'column':2})),
            ('interrupted',None,None,'interrupted',('response_not_received','provider_response',None)),
        ]
        for name,usage,response,expected_stage,expected_diag in cases:
            with self.subTest(name=name):
                helper=PaperLocalResolutionTests();helper.setUp()
                try:
                    prepared=prepare_from_local_archives(helper.store,helper.request_id,clock_ms=1000)
                    child_id=prepared['child_request_id']
                    child=helper.store.connection.execute('select adaptation_request_id,packet_json from paper_research_jobs where request_id=?',
                        (child_id,)).fetchone()
                    policy={'version':'paper-adaptation-research-v1','justification':'isolated provider-contract fixture',
                        'max_requests':8,'max_packet_chars':225000,'max_prompt_chars':260000,
                        'minimum_interval_ms':86400000,'timeout_seconds':120,'max_output_tokens':5000,
                        'max_request_age_ms':3600000,'model':'fixture','usage_mode':'subscription',
                        'max_model_calls':2,'max_input_tokens_per_call':80000,'max_total_input_tokens':160000,
                        'max_total_output_tokens':10000,'max_total_duration_ms':240000}
                    authorize_task(helper.store,child_id,authorization_ref='fixture-'+name,authorized_ms=1101,
                        packet_fingerprint_value=json.loads(child['packet_json'])['fingerprint'],max_calls=2,
                        usage_mode='subscription',max_input_tokens_per_call=80000,max_total_input_tokens=160000,
                        max_total_output_tokens=10000,max_total_duration_ms=240000)
                    self.assertEqual(seal(helper.store,child['adaptation_request_id'],policy,clock_ms=1200,
                        local_resolution_id=prepared['resolution_id'])['status'],'sealed')
                    provider={'response':response,'usage':usage or {},'duration_ms':300}
                    inference_patch=patch('tamtam_again.research.infer',
                        side_effect=InterruptedError('simulated interruption')) if name=='interrupted' else \
                        patch('tamtam_again.research.infer',return_value=provider)
                    with patch('tamtam_again.population_runtime.verify'), \
                         patch('tamtam_again.population_runtime.now_ms',return_value=1201), \
                         inference_patch as infer:
                        result=run(helper.store,child_id)
                    expected_job='needs_data' if name=='included_valid' else 'suspended'
                    self.assertEqual(result['status'],expected_job)
                    artifact=helper.store.connection.execute('select * from isolated_research_call_artifacts '
                        'where job_kind=? and request_id=? and call_index=1',('paper',child_id)).fetchone()
                    self.assertIsNotNone(artifact)
                    self.assertEqual(artifact['state'],expected_stage)
                    self.assertIsNotNone(artifact['reserved_ms']);self.assertIsNotNone(artifact['engaged_ms'])
                    diagnostic=json.loads(artifact['diagnostic_json']) if artifact['diagnostic_json'] else None
                    if expected_diag:
                        self.assertEqual((diagnostic['code'],diagnostic['field'],diagnostic['observed']),expected_diag)
                    if name=='interrupted':
                        self.assertIsNone(artifact['response_received_ms'])
                        self.assertIsNone(artifact['response_json'])
                    else:
                        self.assertIsNotNone(artifact['response_received_ms'])
                        self.assertEqual(json.loads(artifact['response_json'])['response'],response)
                        metadata=json.loads(artifact['metadata_json'])
                        self.assertEqual(metadata['usage'],usage)
                    if name=='included_valid':
                        self.assertIsNotNone(artifact['result_validated_ms'])
                        self.assertEqual(json.loads(helper.store.connection.execute(
                            'select usage_json from paper_research_jobs where request_id=?',(child_id,)).fetchone()[0])[0]['input_tokens'],1200)
                    if name=='malformed':
                        self.assertNotIn('proposal',json.loads(helper.store.connection.execute(
                            'select result_json from paper_research_jobs where request_id=?',(child_id,)).fetchone()[0]))
                    helper.store.connection.close()
                    helper.store=Store(Path(helper.tmp.name)/'paper.sqlite3')
                    with patch('tamtam_again.population_runtime.verify'), \
                         patch('tamtam_again.population_runtime.now_ms',return_value=1202), \
                         patch('tamtam_again.research.infer') as replay_infer:
                        replay=run(helper.store,child_id)
                    self.assertEqual(replay['status'],'unchanged_no_inference')
                    replay_infer.assert_not_called()
                    self.assertEqual(helper.store.connection.execute('select count(*) from isolated_research_call_artifacts '
                        'where job_kind=? and request_id=?',('paper',child_id)).fetchone()[0],1)
                    self.assertEqual(helper.store.connection.execute('select calls_started from paper_research_task_authorizations '
                        'where request_id=?',(child_id,)).fetchone()[0],1)
                    infer.assert_called_once()
                finally:
                    helper.tearDown()

    def test_one_compact_retry_is_linked_to_failure_and_keeps_original_immutable(self):
        from tamtam_again.paper_research import authorize_task, seal
        from tamtam_again.paper_runtime import run
        from tamtam_again.paper_local_resolution import prepare_single_analysis_retry
        from tamtam_again.population_runtime import build_proposal_prompt
        from tamtam_again.population_routing import route
        from tamtam_again.engine import canonical
        from unittest.mock import patch
        prepared=prepare_from_local_archives(self.store,self.request_id,clock_ms=1000)
        failed_id=prepared['child_request_id']
        old=self.store.connection.execute('select adaptation_request_id,packet_json from paper_research_jobs where request_id=?',
            (failed_id,)).fetchone()
        policy={'version':'paper-adaptation-research-v1','justification':'single corrected diagnostic attempt',
            'max_requests':8,'max_packet_chars':225000,'max_prompt_chars':260000,
            'minimum_interval_ms':86400000,'timeout_seconds':120,'max_output_tokens':5000,
            'max_request_age_ms':3600000,'model':'fixture','usage_mode':'subscription',
            'max_model_calls':2,'max_input_tokens_per_call':80000,'max_total_input_tokens':160000,
            'max_total_output_tokens':10000,'max_total_duration_ms':240000}
        authorize_task(self.store,failed_id,authorization_ref='fixture-initial-failed-attempt',authorized_ms=1100,
            packet_fingerprint_value=json.loads(old['packet_json'])['fingerprint'],max_calls=2,
            usage_mode='subscription',max_input_tokens_per_call=80000,max_total_input_tokens=160000,
            max_total_output_tokens=10000,max_total_duration_ms=240000)
        self.assertEqual(seal(self.store,old['adaptation_request_id'],policy,clock_ms=1200,
            local_resolution_id=prepared['resolution_id'])['status'],'sealed')
        failed_reply={'response':canonical({'decision':'needs_data','diagnostic':{'demonstrated':[]},'wake':{}}),
            'usage':{'cost_status':'included','cost_usd':0,'output_tokens':30},'duration_ms':50}
        with patch('tamtam_again.population_runtime.verify'),patch('tamtam_again.population_runtime.now_ms',return_value=1201), \
             patch('tamtam_again.research.infer',return_value=failed_reply) as failed_call:
            self.assertEqual(run(self.store,failed_id)['status'],'suspended')
        failed_call.assert_called_once()
        original_packet=json.loads(old['packet_json'])
        retry=prepare_single_analysis_retry(self.store,failed_id,clock_ms=1300)
        self.assertEqual(retry['status'],'prepared')
        same=prepare_single_analysis_retry(self.store,failed_id,clock_ms=1301)
        self.assertEqual(same['status'],'unchanged')
        self.assertEqual(same['retry_request_id'],retry['retry_request_id'])
        retry_id=retry['retry_request_id']
        self.assertNotEqual(retry['packet_fingerprint'],original_packet['fingerprint'])
        self.assertEqual(retry['source_packet_fingerprint'],original_packet['fingerprint'])
        self.assertLess(retry['packet_chars'],prepared['packet_chars'])
        self.assertEqual(self.store.connection.execute('select status from paper_research_jobs where request_id=?',
            (failed_id,)).fetchone()[0],'suspended')
        compact_row=self.store.connection.execute('select adaptation_request_id,packet_json,local_resolution_id from paper_research_jobs where request_id=?',
            (retry_id,)).fetchone()
        compact=json.loads(compact_row['packet_json'])
        self.assertEqual(compact['schema_version'],'paper-local-evidence-analysis-v1')
        prompt=build_proposal_prompt(compact,retry_id)
        self.assertLess(len(prompt),policy['max_prompt_chars'])
        self.assertLess(len(prompt),50000)
        self.assertIn('Do not request historical source→decision links again',prompt)
        self.assertIn('Do not request a later live collection to close v5',prompt)
        self.assertIn('complete top-level hypothesis object',prompt)
        self.assertEqual(packet_for_resolution(self.store,retry['resolution_id'],clock_ms=1301,
            max_chars=225000)['packet'],compact)
        authorize_task(self.store,retry_id,authorization_ref='fixture-one-retry-only',authorized_ms=1350,
            packet_fingerprint_value=compact['fingerprint'],max_calls=2,usage_mode='subscription',
            max_input_tokens_per_call=80000,max_total_input_tokens=160000,
            max_total_output_tokens=10000,max_total_duration_ms=240000)
        self.assertEqual(seal(self.store,compact_row['adaptation_request_id'],policy,clock_ms=1400,
            local_resolution_id=retry['resolution_id'])['status'],'sealed')
        analysis={'decision':'needs_data','diagnostic':{
                'demonstrated':['Recorded refusal classifications and timestamp discrepancies are descriptive evidence.'],
                'hypothesis':['Quote admissibility, thresholds and rounding may interact with inventory.'],
                'irrecoverable_retroactively':['Exact source event to decision to fill links were not persisted.'],
                'additional_observations':['Prospective causal IDs and the quote actually selected at each decision.'],
                'recommendation':'Instrument future decisions before considering a separately authorized prospective test.'},
            'wake':{'kind':'new_causal_instrumentation_available'}}
        provider={'response':canonical(analysis),'usage':{'cost_status':'included','cost_usd':0,
            'input_tokens':12000,'output_tokens':700},'duration_ms':250}
        with patch('tamtam_again.population_runtime.verify'),patch('tamtam_again.population_runtime.now_ms',return_value=1401), \
             patch('tamtam_again.research.infer',return_value=provider) as infer:
            result=run(self.store,retry_id)
        self.assertEqual(result['status'],'needs_data')
        infer.assert_called_once()
        route_result=route(self.store,retry_id,kind='paper')
        self.assertEqual(route_result['state'],'needs_data')
        self.assertEqual(route(self.store,retry_id,kind='paper'),route_result)
        self.assertEqual(self.store.connection.execute('select status from paper_research_jobs where request_id=?',
            (failed_id,)).fetchone()[0],'suspended')
        self.assertEqual(self.store.connection.execute('select count(*) from paper_research_jobs where retry_of_request_id=?',
            (failed_id,)).fetchone()[0],1)
        self.assertEqual(self.store.connection.execute('select count(*) from isolated_research_call_artifacts where request_id=?',
            (retry_id,)).fetchone()[0],1)
        self.assertEqual(self.store.connection.execute('select calls_started from paper_research_task_authorizations where request_id=?',
            (failed_id,)).fetchone()[0],1)

    def test_changed_archived_quote_prepares_new_fingerprint_but_never_duplicate(self):
        first=prepare_from_local_archives(self.store,self.request_id,clock_ms=1000)
        second=self._observation('market','HYPE','bbo',11,17,{'events':[{'received_at':iso(11),'message':{
            '_stream':{'connection_id':'c1'},'data':{'time':10,'bbo':[{'px':'100.5','sz':'7'},{'px':'101','sz':'6'}]}}}]})
        self.store.connection.commit()
        changed=prepare_from_local_archives(self.store,self.request_id,clock_ms=1100)
        self.assertEqual(changed['status'],'prepared')
        self.assertNotEqual(first['evidence_fingerprint'],changed['evidence_fingerprint'])
        self.assertNotEqual(first['child_request_id'],changed['child_request_id'])
        again=prepare_from_local_archives(self.store,self.request_id,clock_ms=1200)
        self.assertEqual(again['status'],'unchanged')
        self.assertEqual(again['child_request_id'],changed['child_request_id'])
        self.assertEqual(self.store.connection.execute('select count(*) from paper_research_jobs where parent_request_id=?',(self.request_id,)).fetchone()[0],2)

    def test_unreleased_period_blocks_state_and_archive_payload_reads(self):
        statements=[]
        self.store.connection.set_trace_callback(statements.append)
        with unittest.mock.patch('tamtam_again.paper_local_resolution.authorized_period',return_value=False), \
             unittest.mock.patch('tamtam_again.paper_local_resolution.archive_events') as archive:
            with self.assertRaisesRegex(ValueError,'not released'):
                prepare_from_local_archives(self.store,self.request_id,clock_ms=1000)
            archive.assert_not_called()
        self.store.connection.set_trace_callback(None)
        self.assertFalse(any('state_json' in query.lower() for query in statements))

    def test_scheduler_resolves_needs_data_once_without_counting_preparation_as_attempt(self):
        from tamtam_again.paper_scheduler import tick
        from tamtam_again.recipe import synthetic_plan
        plan=synthetic_plan()
        allocation={'version':'experiment-allocation-v1','policy_id':'local-resolver-test-v1',
            'justification':'fixture only','max_profile_variants':1,
            'plan_template':{'version':'population-plan-v1','justification':'fixture only',
                'max_plans':1,'comparison_delay_ms':100,'comparison_duration_ms':6000,
                'selection_gap_ms':1000,'final_duration_ms':6000,'criteria':plan['criteria'],
                'budget':plan['budget'],'isolation':'unavailable'}}
        policy={'version':'paper-adaptation-research-v1','justification':'fixture only',
            'max_requests':8,'max_packet_chars':225000,'max_prompt_chars':260000,
            'minimum_interval_ms':1,'timeout_seconds':120,'max_output_tokens':5000,
            'max_request_age_ms':3600000,'model':'fixture','usage_mode':'subscription',
            'max_model_calls':2,'max_input_tokens_per_call':80000,
            'max_total_input_tokens':160000,'max_total_output_tokens':10000,
            'max_total_duration_ms':240000,'max_diagnoses_per_tick':8}
        before=request_count(self.store)
        with unittest.mock.patch('tamtam_again.population_runtime.call') as model:
            first=tick(self.store,policy,experiment_policy=allocation,dispatch=False,max_jobs=1)
            second=tick(self.store,policy,experiment_policy=allocation,dispatch=False,max_jobs=1)
        model.assert_not_called()
        self.assertEqual(first['local_resolutions'][0]['status'],'prepared')
        self.assertEqual(second['local_resolutions'][0]['status'],'unchanged')
        self.assertEqual(request_count(self.store),before)
        self.assertEqual(self.store.connection.execute('select count(*) from paper_research_jobs where parent_request_id=?',(self.request_id,)).fetchone()[0],1)


if __name__=='__main__':
    unittest.main()
