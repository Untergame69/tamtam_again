import hashlib
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

    def approved_43ad_policy(self):
        from copy import deepcopy
        policy = deepcopy(ETH_TASK_POLICY)
        policy.update(authorization_scope='approved_descriptive_task',
            pilot_id='43ad-btc-descriptive-20261026-v1')
        policy['admission'].update(source='research-admission-20261026',
            cutoff_ms=1793009400000,
            owner_authorization=('Owner authorizes one bounded descriptive task from the approved proposal. '
                'It does not grant economic approval, new collection, paper admission, or capital use.'))
        policy['selection'] = [{
            'candidate': '43ad',
            'address': '0xbb160cb61e694570f9d570f9fcde7c61dd2143ad',
            'rank': 1,
            'descriptive_markets': ['BTC'],
            'question': 'Only the approved descriptive scope is authorized.'
        }]
        policy['evidence'] = {
            'max_archive_cutoff_ms': 1793009400000,
            'period_start_ms': 1790417400000,
            'proposal_sha256': 'b01c8f3f4a1ee4b239a78def96875076c4709b6a31e583c0607bd5c2a03c398b'
        }
        policy['pilot_limits'] = {'max_tasks': 1, 'max_calls': 2,
            'max_input_tokens': 160000, 'max_output_tokens': 10000,
            'max_duration_ms': 240000}
        return policy

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

    def test_approved_43ad_policy_is_exact_and_rejects_scope_or_budget_changes(self):
        from copy import deepcopy
        policy = self.approved_43ad_policy()
        proposal = ROOT / 'docs/continuous-research/NEXT-DESCRIPTIVE-STUDY-PROPOSAL-20261026.json'
        self.assertEqual(hashlib.sha256(proposal.read_bytes()).hexdigest(), policy['evidence']['proposal_sha256'])
        validate_policy(policy)

        invalid = deepcopy(policy); invalid['selection'][0]['address'] = POLICY['selection'][0]['address']
        with self.assertRaisesRegex(ValueError, '43ad/BTC only'):
            validate_policy(invalid)
        invalid = deepcopy(policy); invalid['selection'][0]['descriptive_markets'] = ['BTC', 'ETH']
        with self.assertRaisesRegex(ValueError, '43ad/BTC only'):
            validate_policy(invalid)
        invalid = deepcopy(policy); invalid['admission']['cutoff_ms'] += 1
        with self.assertRaisesRegex(ValueError, 'exact 43ad/BTC proposal'):
            validate_policy(invalid)
        invalid = deepcopy(policy); invalid['evidence']['proposal_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'exact 43ad/BTC proposal'):
            validate_policy(invalid)
        invalid = deepcopy(policy); invalid['pilot_limits']['max_calls'] = 3
        with self.assertRaisesRegex(ValueError, 'specifically authorized ceilings'):
            validate_policy(invalid)
        invalid = deepcopy(policy); invalid['task_policy']['call_reservation_usd'] = '1'
        with self.assertRaisesRegex(ValueError, 'limits must remain bounded'):
            validate_policy(invalid)
        invalid = deepcopy(policy); invalid['task_policy']['max_packet_chars'] = 300000
        with self.assertRaisesRegex(ValueError, 'bounded subscription runtime'):
            validate_policy(invalid)
        invalid = deepcopy(policy); invalid['paper_authorized'] = True
        with self.assertRaisesRegex(ValueError, 'cannot authorize economic validation'):
            validate_policy(invalid)
        invalid = deepcopy(policy); invalid['grants'] = {'real_orders_authorized': True}
        with self.assertRaisesRegex(ValueError, 'cannot authorize economic validation'):
            validate_policy(invalid)

    def test_approved_43ad_allowance_stops_after_one_task_and_two_reserved_calls(self):
        policy = self.approved_43ad_policy()
        item = policy['selection'][0]

        def add_sealed(request_id):
            packet = {'fingerprint': fingerprint({'fixture': request_id})}
            self.store.connection.execute('insert into population_research_jobs '
                '(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,updated_ms) '
                'values(?,?,?,?,?,?,?,\'sealed\',?)',
                (request_id, policy['network'], item['address'], 'input-' + request_id,
                    json.dumps(packet), json.dumps(policy['task_policy']), 30, 30))
            self.store.connection.commit()
            return authorize_task(self.store, policy, request_id=request_id,
                candidate='43ad', address=item['address'],
                packet_fingerprint_value=packet['fingerprint'], authorized_ms=30)

        self.assertEqual(add_sealed('43ad-task-1')['status'], 'authorized')
        reserve_call(self.store, '43ad-task-1', 1, policy)
        reserve_call(self.store, '43ad-task-1', 2, policy)
        with self.assertRaisesRegex(ValueError, 'ceiling exhausted'):
            reserve_call(self.store, '43ad-task-1', 3, policy)
        with self.assertRaisesRegex(ValueError, 'allowance exhausted'):
            add_sealed('43ad-task-2')
        summary = report(self.store, policy)
        self.assertEqual(summary['calls_reserved'], 2)
        self.assertEqual(summary['input_tokens_reserved'], 160000)
        self.assertEqual(summary['output_tokens_reserved'], 10000)
        self.assertEqual(summary['duration_ms_reserved'], 240000)

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
            (json.dumps({'raw_proposal':json.dumps(rejected),'local_resolution':{'version':'fixture-local-v1',
                'state':'partially_resolved','analysis_fingerprint':'a'*64},'validation_diagnostic':{'code':'required_data_invalid',
                'stage':'result_validation','field':'hypothesis.required_data','observed':'list',
                'limit':'list of nonempty strings'}},),json.dumps([usage]),request))
        self.store.connection.commit()
        reserve_call(self.store,request,1,POLICY);record_provider_response(self.store,request,1,{'response':json.dumps(rejected),'usage':usage,'duration_ms':50})
        self.store.connection.execute("update population_research_pilot_tasks set state='suspended' where request_id=?",(request,))
        self.store.connection.commit()
        critique={'decision':'needs_data','diagnostic':{'testability':{
                'required_observations':['Prospective order lifecycle events']},
                'summary':'Structural projection retained all source fields; missing events are prospective.'},
            'wake':{'condition':'reassess only after new authorized evidence'}}
        next_usage={**usage,'input_tokens':1200,'output_tokens':80,'duration_ms':60}
        with patch('tamtam_again.population_runtime.now_ms',return_value=31),patch(
                'tamtam_again.population_runtime.verify'),patch('tamtam_again.population_runtime.call',
                return_value=(json.dumps(critique),next_usage)) as call:
            result=revalidate_and_critique(self.store,POLICY,request)
            call.assert_called_once()
        self.assertEqual(result['status'],'needs_data')
        self.assertEqual(result['adapter_version'],'required-data-object-projection-v1')
        self.assertEqual(result['route']['state'],'needs_data')
        self.assertEqual(result['local_resolution']['state'],'partially_resolved')
        saved=json.loads(self.store.connection.execute('select result_json from population_research_jobs where request_id=?',(request,)).fetchone()[0])
        self.assertEqual(saved['validation_diagnostic']['code'],'required_data_invalid')
        self.assertEqual(saved['proposal']['hypothesis']['required_data'],['Prospective order lifecycle events'])
        self.assertEqual(saved['structural_adaptation']['adapter_version'],'required-data-object-projection-v1')
        self.assertEqual(saved['local_resolution']['state'],'partially_resolved')
        self.assertEqual(saved['local_resolution']['analysis_fingerprint'],'a'*64)
        self.assertEqual(saved['local_resolution']['provider_decision'],'needs_data')
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
        mechanism_ref='raw_observations:book-c'
        scope='account_scope_reports:scope#sha256:'+'d'*64
        packet={'evidence_refs':[scope,raw_a,raw_b,raw_c], 'observations':{
            'market_execution_detail_v1':{'ETH':{'evidence_refs':[raw_a,raw_b]}},
            'descriptive_history_v1':{'evidence_refs':[raw_b]},
            'market_mechanisms':[{'evidence_refs':[mechanism_ref]}]}}
        response={'decision':'hypothesis','hypothesis':{'evidence_refs':[scope,
            'observations.market_execution_detail_v1.ETH.execution_activity',
            'observations.market_execution_detail_v1.ETH.position_path',
            'observations.market_execution_detail_v1.ETH.interpretation_limits',
            'observations.descriptive_history_v1.coverage','observations.market_mechanisms',
            'pilot_research','research_contract']}}
        adapted, details=adapt_eth_evidence_paths_v1(response,packet)
        self.assertEqual(adapted['hypothesis']['evidence_refs'],[scope,raw_a,raw_b,mechanism_ref])
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

    def test_local_archive_followup_precedes_collection_and_replays_as_route_history(self):
        from tamtam_again.population_routing import route
        item=ETH_TASK_POLICY['selection'][0]
        request='local-archive-followup'
        packet={'pilot_research':{'pilot_id':ETH_TASK_POLICY['pilot_id']}}
        followup={'kind':'offline_archive_join','title':
            'Align archived ETH fills with BBO/l2Book and account-state snapshots; report timing and coverage gaps.'}
        result={'critique':{'decision':'needs_data','diagnostic':{'testability':{'required_observations':['new order lifecycle data']}}},
            'local_resolution':{'version':'population-eth-research-resolution-v2',
                'state':'partially_resolved_from_local_archives','followup_task':followup},
            'promotion_authorized':False,'profitability_proven':False}
        self.store.connection.execute('insert into population_research_jobs '
            '(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,result_json,updated_ms) '
            'values(?,?,?,?,?,?,?,\'needs_data\',?,?)',
            (request,ETH_TASK_POLICY['network'],item['address'],'changed-local-input',json.dumps(packet),
                json.dumps(ETH_TASK_POLICY['task_policy']),30,json.dumps(result),31))
        self.store.connection.commit()
        first=route(self.store,request);again=route(self.store,request)
        self.assertEqual(first['state'],'local_archive_analysis_required')
        self.assertEqual(first['followup_task'],followup)
        self.assertEqual(first,again)
        self.assertEqual(first['wake']['model_calls_authorized'],0)
        self.assertFalse(first['wake']['collection_authorized'])

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

    def test_new_allowance_does_not_repeat_same_question_at_same_cutoff(self):
        from copy import deepcopy
        from tamtam_again.population_pilot import _seal_candidate
        self.add_candidate('a880',active=True)
        self.store.connection.commit()
        first=_seal_candidate(self.store,POLICY,'a880',clock_ms=30)
        self.assertEqual(first['status'],'sealed')
        newer=deepcopy(POLICY);newer['pilot_id']='research-loop-pilot-test-v2';newer['version']='research-loop-pilot-v2'
        replay=_seal_candidate(self.store,newer,'a880',clock_ms=31)
        self.assertEqual(replay['status'],'unchanged_no_inference')
        self.assertEqual(replay['request_id'],first['request_id'])
        self.assertIn('same question',replay['reason'])
        self.assertEqual(self.store.connection.execute('select count(*) from population_research_pilot_tasks where pilot_id=?',(newer['pilot_id'],)).fetchone()[0],0)

    def test_final_eth_report_drives_v2_proposal_critique_and_persistent_decision(self):
        from unittest.mock import patch
        from tamtam_again.research_work_queue import enqueue, tick as tick_queue, eth_report_semantic_fingerprint
        policy=json.loads((ROOT/'config/research-loop-pilot-v2.json').read_text())
        item=next(row for row in policy['selection'] if row['candidate']=='67f7')
        self.add_candidate('67f7',active=True);self.store.connection.commit()
        from tamtam_again.population_pilot import _seal_candidate
        prior_a880=_seal_candidate(self.store,POLICY,'a880',clock_ms=39)
        self.assertEqual(prior_a880['status'],'sealed')
        protocol_id='67f7-eth-public-observation-24h-20261014-v1'
        from datetime import datetime, timezone
        day_start=int(datetime(2026,10,14,tzinfo=timezone.utc).timestamp()*1000)
        protocol={'protocol_id':protocol_id,'network':policy['network'],'address':item['address'],'market':'ETH',
            'start_ms':day_start,'end_ms':day_start+86_400_000}
        finalised_ms=protocol['end_ms']+5_000
        task_clock=finalised_ms+2_000
        self.store.connection.execute('create table eth_observation_runs(protocol_id text,status text,protocol_fingerprint text,protocol_json text,finalised_ms integer)')
        self.store.connection.execute('create table eth_observation_reports(protocol_id text,stage text,input_fingerprint text,report_json text,created_ms integer,primary key(protocol_id,stage))')
        large_fills=[]
        volume_fills=12000
        fill_step_ms=7200  # 12,000 records spanning just under one UTC day.
        for index in range(volume_fills):
            action=('opens','reduces','inverts','unknown')[index%4]
            crossed=(index%2==0)
            large_fills.append({'tid':f'fill-{index:06d}','event_ms':day_start+index*fill_step_ms,
                'action':action,'crossed':crossed,'side':'A' if index%2==0 else 'B',
                'start_position':str((index%11)-5),'size':'0.125','price':'2500.1',
                'close_quantity':'0.025' if action in {'reduces','inverts'} else '0',
                'open_quantity':'0.1' if action in {'opens','inverts'} else '0',
                'fee':'-0.0001' if crossed is False else '0.0002','fee_token':'USDC',
                'event_to_fill_page_receipt_ms':1200,
                'fill_page_observation_id':50000+index//100,'fill_page_sha256':f'{index%16:x}'*64,
                'prefill_quote':{'event_ms':day_start+index*fill_step_ms-100,'age_ms':100,'bid':'2500.0',
                    'bid_size':'1.0','ask':'2500.2','ask_size':'1.1','channel':'bbo',
                    'received_at':'2026-10-14T00:00:00.000+00:00','archived_at':'2026-10-14T00:00:00.010+00:00',
                    'ref':f'raw_observations:{60000+index}#sha256:{index%16:x}#0'},
                'future_quote':{'ref':f'raw_observations:{70000+index}#sha256:{index%16:x}#0'},
                'event_time_markout_60s_bps':float((index%17)-8),
                'post_receipt_markout_60s_bps':float((index%13)-6)})
        large_source_refs=[{'observation_id':80000+i,'endpoint':'bbo','sha256':f'{i%16:x}'*64,
            'archived_at':'2026-10-14T00:00:00.000+00:00','frame_count':2} for i in range(12000)]
        report={'protocol_id':protocol_id,'protocol_fingerprint':fingerprint(protocol),'stage':'final_24h',
            'input_fingerprint':fingerprint({'report-source':'final-eth'}),
            'decision':'signal_exploratory_favorable','coverage':{'fills':{'page_count':40,'complete_page_count':40,
                'incomplete_page_count':0,'duplicate_fill_instances':0,'conflicting_fill_ids':[],
                'unique_eth_fills':volume_fills,'source_fingerprint':'fill-source-fp','pages':[]},
                'market':{'quotes':{'bbo':{'event_count':90000,'max_received_gap_ms':1200},
                    'l2Book':{'event_count':20000,'max_received_gap_ms':5000}},'rejected_events':{},
                    'source_fingerprint':'quote-source-fp','source_refs':large_source_refs}},
            'summary':{'taker':{'reduces':{'markout_60s_count':4},'opens':{'markout_60s_count':2}}},
            'fills':large_fills,
            'quote_latency_ms':{},'limits':['outcomes only'],'generated_at_ms':40,
            'window':{'start_ms':protocol['start_ms'],'end_ms':protocol['end_ms'],'interval':'[start_ms,end_ms)'},
            'route':{'next_action':'human review'}}
        report_json=json.dumps(report)
        self.assertGreater(len(report_json),policy['task_policy']['max_packet_chars'])
        self.store.connection.execute('insert into eth_observation_runs values(?,?,?,?,?)',
            (protocol_id,'finalised',fingerprint(protocol),json.dumps(protocol),finalised_ms))
        self.store.connection.execute('insert into eth_observation_reports values(?,?,?,?,?)',
            (protocol_id,'final_24h',report['input_fingerprint'],report_json,finalised_ms));self.store.connection.commit()
        semantic=eth_report_semantic_fingerprint(report)
        work,_=enqueue(self.store,'eth_observation_report',protocol_id,{'protocol_id':protocol_id,'stage':'final_24h','semantic_fingerprint':semantic},clock_ms=finalised_ms+1)
        prepared=tick_queue(self.store,clock_ms=task_clock,pilot_policy=policy)
        self.assertEqual(prepared['advanced'][0]['status'],'analysis_ready')
        queue_row=self.store.connection.execute('select outcome_json from research_work_queue where work_id=?',
            (work['work_id'],)).fetchone()
        queue_packet=json.loads(queue_row['outcome_json'])
        self.assertLessEqual(len(canonical(queue_packet)),policy['task_policy']['max_packet_chars'])
        self.assertEqual(queue_packet['evidence_projection']['population_statistics']['fill_count'],volume_fills)
        self.assertEqual(queue_packet['projection_size_proof']['fill_count'],volume_fills)
        self.assertEqual(queue_packet['projection_size_proof']['serialized_report_chars'],len(report_json))
        self.assertEqual(queue_packet['queue_outcome_chars'],len(canonical(queue_packet)))
        linked=json.loads(self.store.connection.execute('select payload_json from research_work_queue where work_id=?',(work['work_id'],)).fetchone()[0])
        request_id=linked['request_id']
        job=self.store.connection.execute('select * from population_research_jobs where request_id=?',(request_id,)).fetchone()
        packet=json.loads(job['packet_json']); projection=packet['observations']['prospective_eth_observation_v1']
        self.assertIn('local_analysis_contract_v1',packet)
        from tamtam_again.population_local_analysis_contract import validate_contract
        contract_validation=validate_contract(packet,packet['local_analysis_contract_v1'])
        self.assertEqual(packet['local_analysis_contract_v1']['source']['semantic_fingerprint'],semantic)
        self.assertIn(packet['local_analysis_contract_v1']['source']['report_ref'],packet['evidence_refs'])
        sealed_packet_json=job['packet_json']
        self.assertEqual(queue_packet['evidence_projection'],projection)
        self.assertEqual(queue_packet['projection_size_proof']['projected_evidence_chars'],len(canonical(projection)))
        evidence_ref=projection['source']['full_report_ref']
        self.assertEqual(projection['population_statistics']['fill_count'],volume_fills)
        self.assertEqual(len(projection['population_statistics']['by_utc_day']),1)
        self.assertEqual(projection['examples']['population_count'],volume_fills)
        self.assertLess(projection['examples']['selected_count'],volume_fills)
        self.assertEqual(prepared['advanced'][0]['status'],'analysis_ready')
        self.assertLessEqual(len(canonical(packet)),policy['task_policy']['max_packet_chars'])
        from tamtam_again.population_runtime import build_proposal_prompt
        prompt=build_proposal_prompt(packet,request_id)
        self.assertIn('local_analysis_contract_v1',prompt)
        self.assertIn(packet['local_analysis_contract_v1']['source']['report_ref'],prompt)
        self.assertLessEqual(len(canonical(packet)),policy['task_policy']['max_packet_chars'])
        self.assertLessEqual(len(prompt),policy['task_policy']['max_prompt_chars'])
        prepared_event=self.store.connection.execute("select details_json from research_work_queue_events where work_id=? and status='packet_prepared'",
            (work['work_id'],)).fetchone()
        size_proof=json.loads(prepared_event['details_json'])['outcome']
        self.assertEqual(size_proof['packet_chars'],len(canonical(packet)))
        self.assertEqual(size_proof['proposal_prompt_chars'],len(prompt))
        self.assertEqual(size_proof['size_proof']['fill_count'],volume_fills)
        self.assertEqual(size_proof['size_proof']['projected_evidence_chars'],len(canonical(projection)))
        self.assertEqual(size_proof['size_proof']['serialized_report_chars'],len(report_json))
        proposal={'decision':'hypothesis','diagnostic':'Comparaison descriptive seulement.','wake':{},'hypothesis':{
            'mechanism':'Observed taker inventory reductions may differ in subsequent price movement.',
            'type':'autonomous','markets':['ETH'],'signal':'Classify observed fills by inventory effect.',
            'entry':'Observed execution only; no order instruction.','exit':'Measure the 60 second outcome markout.',
            'sizing':'Not applicable to observed fills.','risk':'No profitability inference from this sample.',
            'horizon_justification':'The report already records 60 second markouts.',
            'required_data':['Join report fills and quotes through their sealed archive references.'],
            'execution_constraints':'No paper or live execution.','rejection_criteria':'No persistent difference or inadequate coverage.',
            'evidence_refs':[evidence_ref]}}
        critique={'decision':'consistent','diagnostic':'The question is falsifiable but remains exploratory.','wake':{}}
        usage={'cost_usd':0,'cost_status':'included','input_tokens':900,'output_tokens':80,'duration_ms':12,
            'model':policy['task_policy']['model']}
        with patch('tamtam_again.population_runtime.verify'),patch('tamtam_again.population_runtime.now_ms',return_value=task_clock+1),patch(
                'tamtam_again.population_runtime.call',side_effect=[(json.dumps(proposal),usage),(json.dumps(critique),usage)]) as call:
            run_result=tick_locked(self.store,policy,dispatch=True,clock_ms=task_clock+1)
            self.assertEqual(call.call_count,2,(run_result,dict(self.store.connection.execute('select status,result_json from population_research_jobs where request_id=?',(request_id,)).fetchone())))
            self.assertTrue(all(len(args.args[1])<=policy['task_policy']['max_prompt_chars'] for args in call.call_args_list))
            self.assertEqual(size_proof['proposal_prompt_chars'],len(call.call_args_list[0].args[1]))
            replay=tick_locked(self.store,policy,dispatch=True,clock_ms=task_clock+2)
            self.assertEqual(replay['status'],'no_admissible_candidate')
            self.assertEqual(call.call_count,2)
        saved=self.store.connection.execute('select status,result_json from population_research_jobs where request_id=?',(request_id,)).fetchone()
        self.assertEqual(saved['status'],'hypothesis_recorded')
        self.assertEqual(json.loads(saved['result_json'])['critique']['decision'],'consistent')
        after_runtime=self.store.connection.execute('select packet_json from population_research_jobs where request_id=?',
            (request_id,)).fetchone()[0]
        self.assertEqual(after_runtime,sealed_packet_json)
        self.assertEqual(validate_contract(json.loads(after_runtime),
            json.loads(after_runtime)['local_analysis_contract_v1'])['contract_fingerprint'],
            contract_validation['contract_fingerprint'])
        self.assertEqual(tick_queue(self.store,clock_ms=task_clock+3,pilot_policy=policy)['advanced'],[])
        queue=self.store.connection.execute('select status,outcome_json from research_work_queue where work_id=?',(work['work_id'],)).fetchone()
        self.assertEqual(queue['status'],'resolution_ready')
        self.assertEqual(json.loads(queue['outcome_json'])['promotion_authorized'],False)
        self.assertEqual(self.store.connection.execute('select count(*) from population_research_pilot_calls where pilot_id=?',(policy['pilot_id'],)).fetchone()[0],2)
        self.assertEqual(self.store.connection.execute("select count(*) from population_research_pilot_tasks where pilot_id=? and candidate='67f7'",(policy['pilot_id'],)).fetchone()[0],1)
        self.assertEqual(run_result['route']['state'],'local_archive_analysis_required')
        from gzip import compress
        from pathlib import Path
        from tamtam_again.population_scheduler import tick as scheduler_tick
        scheduler_policy=json.loads((ROOT/'config/population-research-policy.json').read_text())
        def write_artifact_to_temp(path,artifact):
            out=Path(self.tmp.name)/Path(path).name
            out.write_bytes(compress(canonical(artifact).encode('utf-8'),mtime=0))
        with patch('tamtam_again.population_local_archive_resolution._write_artifact',
                side_effect=write_artifact_to_temp):
            scheduler_result=scheduler_tick(self.store,policy['network'],scheduler_policy,
                dispatch=False,resume_local_resolution=request_id)
            resolution=scheduler_result['local_resolutions'][0]
        self.assertEqual(resolution['status'],'prepared')
        self.assertEqual(resolution['resolution']['state'],'partial')
        self.assertEqual(resolution['model_calls'],0)
        resolved_result=json.loads(self.store.connection.execute(
            'select result_json from population_research_jobs where request_id=?',(request_id,)).fetchone()[0])
        self.assertIn(resolution['contract_fingerprint'],resolved_result['local_archive_resolutions_v1'])
        with patch('tamtam_again.population_local_archive_resolution._write_artifact',
                side_effect=write_artifact_to_temp), \
                patch('tamtam_again.population_local_archive_resolution._fills',
                    side_effect=AssertionError('replayed resolution must not reload fills')), \
                patch('tamtam_again.population_local_archive_resolution._quotes',
                    side_effect=AssertionError('replayed resolution must not reload quotes')):
            replay_result=scheduler_tick(self.store,policy['network'],scheduler_policy,
                dispatch=False,resume_local_resolution=request_id)
        rerun=replay_result['local_resolutions'][0]
        self.assertEqual(rerun['status'],'unchanged')
        self.assertFalse(rerun['recalculated'])
        self.assertEqual(rerun['artifact_fingerprint'],resolution['artifact_fingerprint'])

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
