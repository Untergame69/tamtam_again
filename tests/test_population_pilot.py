import json
import tempfile
import unittest
from pathlib import Path

from tamtam_again.engine import fingerprint
from tamtam_again.engine import canonical
from tamtam_again.population_research import initialize as initialize_jobs
from tamtam_again.population_pilot import (authorize_task, initialize, record_provider_response,
    report, reserve_call, tick_locked, validate_policy)
from tamtam_again.population_runtime import execute_job, run
from tamtam_again.storage import Store


ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / 'config/research-loop-pilot-v1.json').read_text())
ETH_TASK_POLICY = json.loads((ROOT / 'config/research-task-67f7-ETH-20261014-v1.json').read_text())


class PopulationPilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'pilot.sqlite3')
        initialize_jobs(self.store)
        self.store.connection.execute('create table account_scope_reports '
            '(report_id text,network text,address text,available_ms integer,payload_json text)')
        self.store.connection.execute('create table population_historical_decisions '
            '(decision_id text,network text,address text,as_of_ms integer,status text,decision_json text)')
        self.add_candidate('a880', active=True)
        self.store.connection.commit()

    def tearDown(self):
        self.store.close(); self.tmp.cleanup()

    def add_candidate(self, name, *, active):
        item = next(row for row in POLICY['selection'] if row['candidate'] == name)
        report = {'markets': ['HYPE'] if name == 'a880' else ['ETH'],
            'activity': {'observed_unique_fills': 3 if active else 0,
                'observed_fill_content_fingerprint': 'fixture-evidence' if active else None}}
        self.store.connection.execute('insert into account_scope_reports values(?,?,?,?,?)',
            ('report-' + name, POLICY['network'], item['address'], 20, json.dumps(report)))
        decision = {'economic_validation': True, 'economic_research_readiness': {
            'status': 'approved_for_re', 'eligible_for_ai_research': True, 'evidence_refs': ['fixture']}}
        self.store.connection.execute('insert into population_historical_decisions '
            'values(?,?,?,?,?,?)', ('decision-' + name, POLICY['network'], item['address'], 10,
                'credible_deep_dive_candidate', json.dumps(decision)))

    def sealed_task(self, candidate, request_id):
        item = next(row for row in POLICY['selection'] if row['candidate'] == candidate)
        pkt = {'fingerprint': fingerprint({'fixture': request_id})}
        self.store.connection.execute('insert into population_research_jobs '
            '(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,updated_ms) '
            'values(?,?,?,?,?,?,?,\'sealed\',?)',
            (request_id, POLICY['network'], item['address'], 'input-' + request_id,
                json.dumps(pkt), json.dumps(POLICY['task_policy']), 30, 30))
        self.store.connection.commit()
        authorize_task(self.store, POLICY, request_id=request_id, candidate=candidate,
            address=item['address'], packet_fingerprint_value=pkt['fingerprint'], authorized_ms=30)
        return request_id

    def test_wait_and_missing_data_do_not_call_models(self):
        result = tick_locked(self.store, POLICY, dispatch=False, clock_ms=30)
        self.assertEqual(result['status'], 'sealed')
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(report(self.store, POLICY)['calls_reserved'], 0)

        other = Store(Path(self.tmp.name) / 'missing.sqlite3')
        try:
            self.store.close()
            self.store = other
            self.store.connection.execute('create table account_scope_reports '
                '(report_id text,network text,address text,available_ms integer,payload_json text)')
            self.store.connection.execute('create table population_historical_decisions '
                '(decision_id text,network text,address text,as_of_ms integer,status text,decision_json text)')
            initialize_jobs(self.store)
            self.add_candidate('a880', active=False)
            self.store.connection.commit()
            missing = tick_locked(self.store, POLICY, dispatch=False, clock_ms=30)
            self.assertEqual(missing['status'], 'no_admissible_candidate')
            self.assertEqual(missing['candidate_evaluations'][0]['status'], 'needs_data')
            self.assertEqual(report(self.store, POLICY)['calls_reserved'], 0)
        finally:
            self.store.close()

    def test_task_scope_replay_and_provider_error_are_consumed_without_retry(self):
        request = self.sealed_task('a880', 'task-1')
        item = next(row for row in POLICY['selection'] if row['candidate'] == 'a880')
        with self.assertRaisesRegex(ValueError, 'different or consumed pilot authorization'):
            authorize_task(self.store, POLICY, request_id=request, candidate='67f7',
                address=next(row for row in POLICY['selection'] if row['candidate']=='67f7')['address'],
                packet_fingerprint_value='wrong', authorized_ms=31)
        reserve_call(self.store, request, 1, POLICY)
        record_provider_response(self.store, request, 1, {'failed': True, 'error_type': 'TimeoutError'})
        with self.assertRaisesRegex(ValueError, 'already consumed'):
            reserve_call(self.store, request, 1, POLICY)
        row = self.store.connection.execute('select state,actual_input_tokens from population_research_pilot_calls '
            'where request_id=? and call_index=1', (request,)).fetchone()
        self.assertEqual(row['state'], 'response_received')
        self.assertIsNone(row['actual_input_tokens'])
        self.assertEqual(report(self.store, POLICY)['calls_reserved'], 1)

    def test_dedicated_eth_task_has_its_own_two_call_nonrenewing_allowance(self):
        from copy import deepcopy
        validate_policy(ETH_TASK_POLICY)
        invalid=deepcopy(ETH_TASK_POLICY);invalid['pilot_limits']['max_calls']=3
        with self.assertRaisesRegex(ValueError,'ceilings'):
            validate_policy(invalid)
        invalid=deepcopy(ETH_TASK_POLICY);invalid['selection'][0]['descriptive_markets']=['xyz:DRAM']
        with self.assertRaisesRegex(ValueError,'67f7 and its ETH evidence'):
            validate_policy(invalid)
        initialize(self.store,POLICY)
        item=ETH_TASK_POLICY['selection'][0]
        packet={'fingerprint':fingerprint({'new-packet':'67f7-ETH'})}
        self.store.connection.execute('insert into population_research_jobs '
            '(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,updated_ms) '
            'values(?,?,?,?,?,?,?,\'sealed\',?)',('eth-task',ETH_TASK_POLICY['network'],item['address'],
                'new-input',json.dumps(packet),json.dumps(ETH_TASK_POLICY['task_policy']),30,30))
        self.store.connection.commit()
        self.assertEqual(authorize_task(self.store,ETH_TASK_POLICY,request_id='eth-task',
            candidate='67f7',address=item['address'],packet_fingerprint_value=packet['fingerprint'],
            authorized_ms=30)['status'],'authorized')
        reserve_call(self.store,'eth-task',1,ETH_TASK_POLICY)
        reserve_call(self.store,'eth-task',2,ETH_TASK_POLICY)
        with self.assertRaisesRegex(ValueError,'ceiling exhausted'):
            reserve_call(self.store,'eth-task',3,ETH_TASK_POLICY)
        self.assertEqual(report(self.store,ETH_TASK_POLICY)['calls_reserved'],2)
        self.assertEqual(report(self.store,POLICY)['calls_reserved'],0)
        self.assertNotIn('call_reservation_usd',ETH_TASK_POLICY['task_policy'])

    def test_real_runtime_contract_mocked_once_routes_persistently_and_replays_without_call(self):
        from unittest.mock import patch
        from tamtam_again.population_routing import route
        item = next(row for row in POLICY['selection'] if row['candidate'] == 'a880')
        self.add_candidate('a880', active=True)
        self.store.connection.commit()
        from tamtam_again.population_pilot import _seal_candidate
        sealed = _seal_candidate(self.store, POLICY, 'a880', clock_ms=30)
        self.assertEqual(sealed['status'], 'sealed')
        proposal = {'decision': 'needs_data', 'diagnostic': 'A scoped prospective observation remains missing.',
            'wake': {'condition': 'only reassess after genuinely new authorized observations'}}
        usage = {'cost_usd': 0, 'cost_status': 'included', 'input_tokens': 1200,
            'output_tokens': 80, 'duration_ms': 40, 'model': POLICY['task_policy']['model']}
        with patch('tamtam_again.population_runtime.now_ms', return_value=31), patch(
                'tamtam_again.population_runtime.verify'), patch(
                'tamtam_again.population_runtime.call', return_value=(json.dumps(proposal), usage)) as call:
            job = self.store.connection.execute('select * from population_research_jobs where request_id=?',
                (sealed['request_id'],)).fetchone()
            result = execute_job(self.store, sealed['request_id'], job)
            saved_route = route(self.store, sealed['request_id'])
            replay = run(self.store, sealed['request_id'])
            self.assertEqual(replay['status'], 'unchanged_no_inference')
            call.assert_called_once()
        self.assertEqual(result['status'], 'needs_data')
        self.assertEqual(saved_route['state'], 'needs_data')
        self.assertEqual(report(self.store, POLICY)['input_tokens_reported'], 1200)
        callrow = self.store.connection.execute('select state,actual_input_tokens,actual_output_tokens '
            'from population_research_pilot_calls where request_id=? and call_index=1',
            (sealed['request_id'],)).fetchone()
        self.assertEqual(tuple(callrow), ('result_validated', 1200, 80))

    def test_pilot_provider_error_stays_consumed_and_does_not_retry(self):
        from unittest.mock import patch
        from tamtam_again.population_pilot import _seal_candidate
        self.add_candidate('a880', active=True)
        self.store.connection.commit()
        sealed = _seal_candidate(self.store, POLICY, 'a880', clock_ms=30)
        with patch('tamtam_again.population_runtime.now_ms', return_value=31), patch(
                'tamtam_again.population_runtime.verify'), patch(
                'tamtam_again.population_runtime.call', side_effect=TimeoutError) as call:
            job = self.store.connection.execute('select * from population_research_jobs where request_id=?',
                (sealed['request_id'],)).fetchone()
            result = execute_job(self.store, sealed['request_id'], job)
            replay = run(self.store, sealed['request_id'])
            call.assert_called_once()
        self.assertEqual(result['status'], 'suspended')
        self.assertEqual(replay['status'], 'unchanged_no_inference')
        usage = self.store.connection.execute('select state from population_research_pilot_calls '
            'where request_id=?', (sealed['request_id'],)).fetchone()[0]
        self.assertEqual(usage, 'interrupted')
        self.assertEqual(report(self.store, POLICY)['calls_reserved'], 1)

    def test_structural_projection_preserves_rejection_and_uses_only_remaining_critique(self):
        from unittest.mock import patch
        from tamtam_again.population_pilot import (_seal_candidate, revalidate_and_critique,
            reserve_call, record_provider_response)
        sealed = _seal_candidate(self.store, POLICY, 'a880', clock_ms=30)
        request = sealed['request_id']
        packet = json.loads(self.store.connection.execute('select packet_json from population_research_jobs '
            'where request_id=?', (request,)).fetchone()[0])
        hypothesis = {k:'versioned fixture content' for k in ('mechanism','signal','entry','exit','sizing',
            'risk','horizon_justification','execution_constraints','rejection_criteria')}
        hypothesis.update(type='follower',markets=['HYPE'],required_data=[{'index':0,
            'observation':'Prospective order lifecycle events','source':'operator instrumentation',
            'decision_use':'separate submitted decisions from completed fills'}],
            evidence_refs=[packet['evidence_refs'][0]])
        rejected={'decision':'hypothesis','diagnostic':'fixture evidence summary','wake':{},'hypothesis':hypothesis}
        usage={'cost_status':'included','cost_usd':0,'input_tokens':1000,'output_tokens':100,
            'duration_ms':50,'model':POLICY['task_policy']['model']}
        self.store.connection.execute("update population_research_jobs set status='suspended',result_json=?,usage_json=?,updated_ms=30 where request_id=?",
            (json.dumps({'raw_proposal':json.dumps(rejected),'validation_diagnostic':{'code':'required_data_invalid',
                'stage':'result_validation','field':'hypothesis.required_data','observed':'list',
                'limit':'list of nonempty strings'}},),json.dumps([usage]),request))
        self.store.connection.commit()
        reserve_call(self.store,request,1,POLICY);record_provider_response(self.store,request,1,{'response':json.dumps(rejected),'usage':usage,'duration_ms':50})
        self.store.connection.execute("update population_research_pilot_tasks set state='suspended' where request_id=?",(request,))
        self.store.connection.commit()
        critique={'decision':'consistent','diagnostic':'Structural projection retained all source fields; missing events are prospective.',
            'wake':{'condition':'reassess only after new authorized evidence'}}
        next_usage={**usage,'input_tokens':1200,'output_tokens':80,'duration_ms':60}
        with patch('tamtam_again.population_runtime.now_ms',return_value=31),patch(
                'tamtam_again.population_runtime.verify'),patch('tamtam_again.population_runtime.call',
                return_value=(json.dumps(critique),next_usage)) as call:
            result=revalidate_and_critique(self.store,POLICY,request)
            call.assert_called_once()
        self.assertEqual(result['status'],'hypothesis_recorded')
        self.assertEqual(result['adapter_version'],'required-data-object-projection-v1')
        self.assertEqual(result['route']['state'],'needs_data')
        self.assertEqual(result['local_resolution']['state'],'structured_request_required')
        saved=json.loads(self.store.connection.execute('select result_json from population_research_jobs where request_id=?',(request,)).fetchone()[0])
        self.assertEqual(saved['validation_diagnostic']['code'],'required_data_invalid')
        self.assertEqual(saved['proposal']['hypothesis']['required_data'],['Prospective order lifecycle events'])
        artifact=self.store.connection.execute('select validation_state,source_response_sha256 from population_research_adaptation_artifacts where request_id=?',(request,)).fetchone()
        self.assertEqual(artifact['validation_state'],'revalidated')
        self.assertEqual(len(artifact['source_response_sha256']),64)
        states=[row[0] for row in self.store.connection.execute('select state from population_research_pilot_calls where request_id=? order by call_index',(request,))]
        self.assertEqual(states,['structurally_revalidated','result_validated'])
        self.assertEqual(report(self.store,POLICY)['calls_reserved'],2)

    def test_eth_evidence_path_projection_uses_only_exact_packet_sources(self):
        from tamtam_again.population_pilot import adapt_eth_evidence_paths_v1
        raw_a='raw_observations:fill-a#sha256:'+'a'*64
        raw_b='raw_observations:fill-b#sha256:'+'b'*64
        raw_c='raw_observations:book-c#sha256:'+'c'*64
        scope='account_scope_reports:scope#sha256:'+'d'*64
        packet={'evidence_refs':[scope,raw_a,raw_b,raw_c], 'observations':{
            'market_execution_detail_v1':{'ETH':{'evidence_refs':[raw_a,raw_b]}},
            'descriptive_history_v1':{'evidence_refs':[raw_b]},
            'market_mechanisms':[{'evidence_refs':[raw_c]}]}}
        response={'decision':'hypothesis','hypothesis':{'evidence_refs':[scope,
            'observations.market_execution_detail_v1.ETH.execution_activity',
            'observations.market_execution_detail_v1.ETH.position_path',
            'observations.market_execution_detail_v1.ETH.interpretation_limits',
            'observations.descriptive_history_v1.coverage','observations.market_mechanisms',
            'pilot_research','research_contract']}}
        adapted, details=adapt_eth_evidence_paths_v1(response,packet)
        self.assertEqual(adapted['hypothesis']['evidence_refs'],[scope,raw_a,raw_b,raw_c])
        self.assertEqual(response['hypothesis']['evidence_refs'][1],
            'observations.market_execution_detail_v1.ETH.execution_activity')
        self.assertEqual(details['omitted_metadata_paths'],[
            'observations.market_execution_detail_v1.ETH.interpretation_limits',
            'pilot_research','research_contract'])
        invalid=json.loads(json.dumps(response))
        invalid['hypothesis']['evidence_refs'].append('observations.unknown')
        with self.assertRaisesRegex(ValueError,'Unrecognized evidence path'):
            adapt_eth_evidence_paths_v1(invalid,packet)

    def test_pilot_missing_prospective_evidence_routes_to_persistent_technical_task(self):
        from tamtam_again.population_pilot import _seal_candidate
        from tamtam_again.population_routing import route
        sealed=_seal_candidate(self.store,POLICY,'a880',clock_ms=30)
        req=sealed['request_id']
        diag={'required_missing_observations':['Prospective order lifecycle and receipt clocks',
            'Applicable fee and rebate schedule with settlement'],
            'limitations':['Maker-only comparison cannot identify a passive-execution causal effect.',
                'The current IOC engine cannot reproduce passive fills or queue priority.'],
            'testability':'Measure fees and price markouts prospectively.'}
        result={'critique':{'decision':'needs_data','diagnostic':diag,'wake':{
            'kind':'prospective_observation_and_technical_task','historical_backfill_requested':False,
            'trigger':'after authorized prospective observations'}},
            'promotion_authorized':False,'profitability_proven':False}
        self.store.connection.execute("update population_research_jobs set status='needs_data',result_json=? where request_id=?",
            (json.dumps(result),req));self.store.connection.commit()
        first=route(self.store,req);again=route(self.store,req)
        self.assertEqual(first['state'],'technical_task_required')
        self.assertEqual(first['technical_task']['required_observations'],diag['required_missing_observations'])
        self.assertIn('IOC engine',first['technical_task']['engine_constraint'])
        self.assertFalse(first['technical_task']['historical_backfill_requested'])
        self.assertEqual(first,again)
        count=self.store.connection.execute('select count(*) from population_hypothesis_routes where request_id=?',(req,)).fetchone()[0]
        self.assertEqual(count,1)

    def test_technical_and_unchanged_candidates_do_not_block_later_candidates(self):
        from tamtam_again.population_pilot import _seal_candidate
        from tamtam_again.population_routing import route
        # Keep the original a880 technical decision, then ensure the scheduler
        # checks the next candidate rather than returning early.
        self.add_candidate('67f7', active=True)
        self.add_candidate('be504', active=True)
        self.store.connection.commit()
        first = _seal_candidate(self.store, POLICY, 'a880', clock_ms=30)
        self.assertEqual(first['status'], 'sealed')
        req = first['request_id']
        diag = {'required_missing_observations':['Prospective order lifecycle and receipt clocks'],
            'limitations':['The current IOC engine cannot reproduce passive fills or queue priority.'],
            'testability':'Measure prospective execution.'}
        result = {'critique':{'decision':'needs_data','diagnostic':diag,'wake':{
            'kind':'prospective_observation_and_technical_task','historical_backfill_requested':False,
            'trigger':'new prospective observations'}}, 'promotion_authorized':False,
            'profitability_proven':False}
        self.store.connection.execute("update population_research_jobs set status='needs_data',result_json=? where request_id=?",
            (json.dumps(result),req)); self.store.connection.commit()
        self.assertEqual(route(self.store,req)['state'],'technical_task_required')

        # 67f7 is eligible and gets a useful sealed packet. Once it has a
        # needs-data decision on this same fingerprint, it must not be called
        # again and be504 must be considered next.
        first_next = tick_locked(self.store, POLICY, dispatch=False, clock_ms=31)
        self.assertEqual(first_next['candidate'],'67f7')
        self.assertEqual(first_next['status'],'sealed')
        req67 = first_next['request_id']
        self.store.connection.execute("update population_research_jobs set status='needs_data',result_json=? where request_id=?",
            (json.dumps({'critique':{'decision':'needs_data','diagnostic':{'required_missing_observations':['new data']},
                'wake':{'kind':'required_observations_available'}}}),req67)); self.store.connection.commit()
        self.assertEqual(route(self.store,req67)['state'],'needs_data')
        second_next = tick_locked(self.store, POLICY, dispatch=False, clock_ms=32)
        self.assertEqual(second_next['candidate'],'be504')
        self.assertEqual(second_next['status'],'sealed')
        self.assertEqual(second_next['prior_candidates'][0]['candidate'],'a880')
        self.assertEqual(second_next['prior_candidates'][0]['status'],'terminal_route')

        # Replaying a subsequent tick sees unchanged fingerprints for both
        # processed accounts, records their wait locally, and creates no task.
        reqbe = second_next['request_id']
        self.store.connection.execute("update population_research_jobs set status='needs_data',result_json=? where request_id=?",
            (json.dumps({'critique':{'decision':'needs_data','diagnostic':{'required_missing_observations':['new data']},
                'wake':{'kind':'required_observations_available'}}}),reqbe)); self.store.connection.commit()
        self.assertEqual(route(self.store,reqbe)['state'],'needs_data')
        task_count = report(self.store,POLICY)['tasks']
        replay = tick_locked(self.store, POLICY, dispatch=False, clock_ms=33)
        self.assertEqual(replay['status'],'no_admissible_candidate')
        self.assertEqual([e['status'] for e in replay['candidate_evaluations']],
            ['terminal_route','unchanged_no_inference','unchanged_no_inference'])
        self.assertEqual(report(self.store,POLICY)['tasks'],task_count)
        self.assertEqual(report(self.store,POLICY)['calls_reserved'],0)
        report_row = self.store.connection.execute("select report_id,payload_json from account_scope_reports where address=?",
            (next(row for row in POLICY['selection'] if row['candidate']=='67f7')['address'],)).fetchone()
        changed = json.loads(report_row['payload_json'])
        changed['activity']['observed_fill_content_fingerprint'] = 'new-authorized-observation'
        self.store.connection.execute('update account_scope_reports set payload_json=? where report_id=?',
            (json.dumps(changed),report_row['report_id'])); self.store.connection.commit()
        exhausted = tick_locked(self.store,POLICY,dispatch=False,clock_ms=34)
        self.assertEqual(exhausted['status'],'no_admissible_candidate')
        self.assertEqual(exhausted['candidate_evaluations'][1]['status'],'task_allowance_exhausted')
        self.assertEqual(report(self.store,POLICY)['tasks'],task_count)
        self.assertEqual(report(self.store,POLICY)['calls_reserved'],0)

    def test_needs_data_critique_routes_without_structured_hypothesis_registration(self):
        from unittest.mock import patch
        request = self.sealed_task('a880','needs-data-critique')
        response = {'critique':{'decision':'needs_data','diagnostic':'A new observation is needed.',
            'wake':{'condition':'reassess only on changed evidence'}},'promotion_authorized':False,
            'profitability_proven':False}
        def finish_critique(store, request_id, job):
            store.connection.execute("update population_research_jobs set status='needs_data',result_json=? where request_id=?",
                (json.dumps(response),request_id)); store.connection.commit()
            return {'status':'needs_data'}
        with patch('tamtam_again.population_runtime.execute_job',side_effect=finish_critique):
            result = tick_locked(self.store,POLICY,dispatch=True,clock_ms=31)
        self.assertEqual(result['route']['state'],'needs_data')
        self.assertIsNone(result['local_resolution'])
        plans = self.store.connection.execute("select name from sqlite_master where type='table' and name='research_observation_plans'").fetchone()
        self.assertIsNone(plans)

    def test_provider_execution_failure_route_is_consumed_without_retry(self):
        from tamtam_again.population_routing import route
        request = self.sealed_task('67f7','provider-failure-route')
        packet = json.loads(self.store.connection.execute('select packet_json from population_research_jobs where request_id=?',
            (request,)).fetchone()[0])
        packet['pilot_research'] = {'pilot_id':POLICY['pilot_id']}
        diagnostic = {'stage':'provider_execution','code':'isolated_inference_failed','field':'failed',
            'observed':{'failed':True,'exit_code':0},'limit':'successful isolated provider response'}
        self.store.connection.execute("update population_research_jobs set packet_json=?,status='suspended',result_json=? where request_id=?",
            (json.dumps(packet),json.dumps({'validation_diagnostic':diagnostic,'error_type':'InferenceExecutionError'}),request))
        self.store.connection.commit()
        result = route(self.store,request)
        self.assertEqual(result['wake']['kind'],'manual_runtime_diagnosis')
        self.assertTrue(result['wake']['attempt_consumed'])
        self.assertFalse(result['wake']['automatic_retry'])
        self.assertIn('not retried automatically',result['next_action'])

    def test_worker_recovery_marks_reserved_call_interrupted_and_never_retries(self):
        from unittest.mock import patch
        from tamtam_again.population_scheduler import tick
        request=self.sealed_task('a880','interrupted-task')
        reserve_call(self.store,request,1,POLICY)
        self.store.connection.execute("update population_research_jobs set status='running' where request_id=?",(request,))
        self.store.connection.commit()
        shared={'version':'population-research-v1','max_requests':8,'max_packet_chars':10000,
            'minimum_interval_ms':10,'timeout_seconds':1,'max_output_tokens':100,'max_request_age_ms':1000,
            'model':'fixture','call_reservation_usd':'1'}
        with patch('tamtam_again.population_scheduler.now_ms',return_value=31), patch(
                'tamtam_again.population_runtime.call') as call:
            result=tick(self.store,POLICY['network'],shared,dispatch=True,max_jobs=1,pilot_policy=POLICY)
            call.assert_not_called()
        state=self.store.connection.execute('select state from population_research_pilot_tasks where request_id=?',(request,)).fetchone()[0]
        self.assertEqual(state,'interrupted')
        self.assertEqual(result['pilot_research']['status'],'no_admissible_candidate')
        self.assertEqual(report(self.store,POLICY)['calls_reserved'],1)

    def test_exhaustion_is_separate_and_nonrenewing(self):
        requests = [self.sealed_task(name, 'task-' + name) for name in ('a880', '67f7', 'be504')]
        for request in requests:
            reserve_call(self.store, request, 1, POLICY)
            reserve_call(self.store, request, 2, POLICY)
        totals = report(self.store, POLICY)
        self.assertEqual(totals['calls_reserved'], 6)
        self.assertEqual(totals['input_tokens_reserved'], 480000)
        self.assertEqual(totals['output_tokens_reserved'], 30000)
        self.assertEqual(totals['duration_ms_reserved'], 720000)
        self.assertTrue(totals['non_renewing'])
        with self.assertRaisesRegex(ValueError, 'task allowance exhausted'):
            self.sealed_task('a880', 'task-four')

    def test_upgrade_preserves_existing_task_and_allows_changed_input_same_candidate(self):
        from tamtam_again.population_pilot import initialize as initialize_pilot
        item=next(row for row in POLICY['selection'] if row['candidate']=='a880')
        self.store.connection.execute('create table population_research_pilot_allowances '
            '(pilot_id text primary key,policy_fingerprint text not null,policy_json text not null,created_ms integer not null)')
        self.store.connection.execute('insert into population_research_pilot_allowances values(?,?,?,?)',
            (POLICY['pilot_id'],fingerprint(POLICY),canonical(POLICY),1))
        self.store.connection.execute('create table population_research_pilot_tasks '
            '(request_id text primary key,pilot_id text not null,candidate text not null,address text not null,'
            'packet_fingerprint text not null,authorized_ms integer not null,state text not null,'
            'unique(pilot_id,candidate),foreign key(pilot_id) references population_research_pilot_allowances(pilot_id))')
        self.store.connection.execute('insert into population_research_pilot_tasks values(?,?,?,?,?,?,?)',
            ('old-task',POLICY['pilot_id'],'a880',item['address'],'old-fp',1,'needs_data'))
        self.store.connection.commit()
        initialize_pilot(self.store,POLICY)
        self.store.connection.execute('insert into population_research_pilot_tasks values(?,?,?,?,?,?,?)',
            ('new-task',POLICY['pilot_id'],'a880',item['address'],'new-fp',2,'authorized'))
        self.store.connection.commit()
        rows=self.store.connection.execute('select request_id,packet_fingerprint from population_research_pilot_tasks '
            'where pilot_id=? order by request_id',(POLICY['pilot_id'],)).fetchall()
        self.assertEqual([tuple(row) for row in rows],[('new-task','new-fp'),('old-task','old-fp')])

    def test_same_input_no_new_task_changed_input_seals_new_task_without_call(self):
        from tamtam_again.population_pilot import _seal_candidate
        first=_seal_candidate(self.store,POLICY,'a880',clock_ms=30)
        unchanged=_seal_candidate(self.store,POLICY,'a880',clock_ms=31)
        self.assertEqual(unchanged['status'],'unchanged_no_inference')
        self.assertEqual(unchanged['request_id'],first['request_id'])
        item=next(row for row in POLICY['selection'] if row['candidate']=='a880')
        changed_scope={'markets':['HYPE'],'activity':{'observed_unique_fills':4,
            'observed_fill_content_fingerprint':'changed-fixture-evidence'}}
        self.store.connection.execute('insert into account_scope_reports values(?,?,?,?,?)',
            ('report-a880-new',POLICY['network'],item['address'],25,json.dumps(changed_scope)))
        self.store.connection.commit()
        changed=_seal_candidate(self.store,POLICY,'a880',clock_ms=32)
        self.assertEqual(changed['status'],'sealed')
        self.assertNotEqual(changed['request_id'],first['request_id'])
        self.assertEqual(changed_scope['activity']['observed_unique_fills'],4)
        self.assertEqual(self.store.connection.execute('select count(*) from population_research_pilot_tasks where pilot_id=?',
            (POLICY['pilot_id'],)).fetchone()[0],2)
        self.assertEqual(report(self.store,POLICY)['calls_reserved'],0)

    def test_pilot_jobs_do_not_consume_shared_research_request_ceiling(self):
        from tamtam_again.research_jobs import request_count
        self.store.connection.execute('insert into population_research_jobs '
            '(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,updated_ms) '
            'values(?,?,?,?,?,?,?,?,?)',('ordinary','test','other','ordinary-fp','{}','{}',1,'archived',1))
        self.store.connection.commit()
        self.sealed_task('a880','pilot-task')
        self.assertEqual(request_count(self.store),1)


if __name__ == '__main__':
    unittest.main()
