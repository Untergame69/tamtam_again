import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tamtam_again.storage import Store
from tamtam_again.population_research import seal
from tamtam_again.population_runtime import run


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db')
        self.s.connection.execute('create table account_scope_reports(report_id text,network text,address text,available_ms integer,payload_json text)')
        report={'markets':['BTC','ETH'],'activity':{'observed_unique_fills':1,'observed_fill_content_fingerprint':'fixture'}}
        self.s.connection.execute('insert into account_scope_reports values(?,?,?,?,?)',('one','test','account',10,json.dumps(report)));self.s.connection.commit()
        policy={'version':'population-research-v1','max_requests':2,'max_packet_chars':10000,
            'minimum_interval_ms':10,'timeout_seconds':1,'max_output_tokens':100,'max_request_age_ms':1000,
            'model':'fixture','call_reservation_usd':'1'}
        self.request=seal(self.s,'test','account',policy,clock_ms=20)['request_id']
        self.policy=policy
        self.clock=patch('tamtam_again.population_runtime.now_ms',return_value=30);self.clock.start()
        self.usage={'cost_usd':0,'cost_status':'included','duration_ms':1}

    def tearDown(self):self.clock.stop();self.s.close();self.tmp.cleanup()

    def test_scheduler_recovers_interrupted_without_retry_or_losing_checkpoint(self):
        from tamtam_again.population_scheduler import tick
        self.s.connection.execute("update population_research_jobs set status='running',reserved_cost_usd='2',result_json=?,usage_json=?",(json.dumps({'raw_proposal':'fixture checkpoint'}),json.dumps([self.usage])));self.s.connection.commit()
        with patch('tamtam_again.population_scheduler.now_ms',return_value=30),patch('tamtam_again.population_runtime.call') as call:
            result=tick(self.s,'test',self.policy,dispatch=False)
            call.assert_not_called()
        self.assertEqual(result['interrupted_without_retry'],[self.request])
        row=self.s.connection.execute('select * from population_research_jobs').fetchone()
        self.assertEqual(row['status'],'interrupted');self.assertEqual(row['reserved_cost_usd'],'2')
        self.assertIsNone(row['actual_cost_usd']);self.assertIn('fixture checkpoint',row['result_json'])

    def test_expired_request_does_not_infer(self):
        with patch('tamtam_again.population_runtime.now_ms',return_value=1021),patch('tamtam_again.population_runtime.verify') as verify,patch('tamtam_again.population_runtime.call') as call:
            self.assertEqual(run(self.s,self.request)['status'],'expired')
            verify.assert_not_called();call.assert_not_called()

    def test_projected_evidence_allowed_and_invented_reference_rejected(self):
        from tamtam_again.population_runtime import validate_response
        hypothesis={k:'fixture' for k in ('mechanism','signal','entry','exit','sizing','risk','horizon_justification','execution_constraints','rejection_criteria')}
        hypothesis.update(type='autonomous',markets=['BTC'],required_data=[],evidence_refs=['projected'])
        response={'decision':'hypothesis','diagnostic':{'observed':'fixture'},'wake':{},'hypothesis':hypothesis}
        packet={'evidence_refs':['report'],'observations':{'markets':['BTC'],'market_mechanisms':[{'evidence_refs':['projected']}]}}
        validate_response(response,packet)
        hypothesis['evidence_refs']=['invented']
        with self.assertRaises(ValueError):validate_response(response,packet)

    def test_memory_import_preserves_hypothesis_and_cutoff(self):
        from tamtam_again.population_memory import remember
        from tamtam_again.research_memory import export_knowledge
        hypothesis={'mechanism':'fixture multi-market hypothesis','markets':['BTC','ETH'],
            'required_data':['causal prices'],'rejection_criteria':'fixture reject condition',
            'execution_constraints':'fixture execution limits','risk':'fixture risk'}
        result={'proposal':{'hypothesis':hypothesis},'critique':{'decision':'consistent'},
            'promotion_authorized':False,'profitability_proven':False}
        self.s.connection.execute("update population_research_jobs set status='hypothesis_recorded',result_json=?,updated_ms=30",(json.dumps(result),));self.s.connection.commit()
        with patch('tamtam_again.research_memory.clock',return_value=100):
            saved=remember(self.s,self.request)
            self.assertEqual(remember(self.s,self.request)['status'],'already_recorded')
            early=export_knowledge(self.s,as_of_ms=99,network='test',address='account',market='BTC')
            later=export_knowledge(self.s,as_of_ms=100,network='test',address='account',market='ETH')
        self.assertEqual(early,[]);self.assertEqual(later[0]['knowledge_id'],saved['knowledge_id'])
        self.assertEqual(later[0]['item']['status'],'hypothesis')
        self.assertEqual(later[0]['item']['experiments'],[])
        self.assertFalse(saved['economic_validation'])

    def test_memory_import_cannot_hide_reserved_period(self):
        from tamtam_again.population_memory import remember
        from tamtam_again.recipe import synthetic_plan
        from tamtam_again.validation import create_plan
        plan=synthetic_plan()
        plan['network']='test';plan['address']='account';plan['coin']='BTC'
        create_plan(self.s,plan)
        hypothesis={'mechanism':'fixture','markets':['ETH'],'required_data':[],
            'rejection_criteria':'reject','execution_constraints':'limits','risk':'risk'}
        result={'proposal':{'hypothesis':hypothesis},'critique':{'decision':'consistent'},
            'promotion_authorized':False,'profitability_proven':False}
        packet=json.loads(self.s.connection.execute('select packet_json from population_research_jobs').fetchone()[0])
        packet['available_ms']=30000
        self.s.connection.execute("update population_research_jobs set status='hypothesis_recorded',result_json=?,packet_json=?,updated_ms=30",
            (json.dumps(result),json.dumps(packet)));self.s.connection.commit()
        with patch('tamtam_again.research_memory.clock',return_value=100000):
            with self.assertRaisesRegex(ValueError,'unreleased reserved'):remember(self.s,self.request)
        self.assertEqual(self.s.connection.execute('select count(*) from research_knowledge').fetchone()[0],0)
        self.assertEqual(self.s.connection.execute('select count(*) from population_research_memory').fetchone()[0],0)

    def test_routing_records_missing_data_without_inventing_rule(self):
        from tamtam_again.population_routing import route
        result={'proposal':{'hypothesis':{'required_data':['causal funding history']}},
            'critique':{'decision':'consistent','diagnostic':'fixture','wake':{}},
            'promotion_authorized':False,'profitability_proven':False}
        self.s.connection.execute("update population_research_jobs set status='hypothesis_recorded',result_json=?",(json.dumps(result),));self.s.connection.commit()
        routed=route(self.s,self.request)
        self.assertEqual(routed['state'],'needs_data')
        self.assertTrue(routed['wake']['new_input_fingerprint_required'])
        self.assertFalse(routed['promotion_authorized'])
        result['proposal']['hypothesis']['required_data']=[]
        self.s.connection.execute('update population_research_jobs set result_json=?',(json.dumps(result),));self.s.connection.commit()
        self.assertEqual(route(self.s,self.request),routed)
        self.assertFalse(self.s.connection.execute("select 1 from sqlite_master where name='strategy_variants'").fetchone())

    def test_routing_requires_contract_and_never_promotes(self):
        from tamtam_again.population_routing import route
        result={'proposal':{'hypothesis':{'required_data':[]}},
            'critique':{'decision':'consistent','diagnostic':'fixture','wake':{}},
            'promotion_authorized':False,'profitability_proven':False}
        self.s.connection.execute("update population_research_jobs set status='hypothesis_recorded',result_json=?",(json.dumps(result),));self.s.connection.commit()
        self.assertEqual(route(self.s,self.request)['state'],'specification_required')

    def test_routing_capability_requires_new_prospective_plan(self):
        from tamtam_again.population_routing import route
        from tamtam_again.recipe import synthetic_spec
        result={'proposal':{'hypothesis':{'required_data':[],'executable_spec':synthetic_spec(),'markets':['SYNTH'],'type':synthetic_spec()['type']}},
            'critique':{'decision':'consistent','diagnostic':'fixture','wake':{}},
            'promotion_authorized':False,'profitability_proven':False}
        self.s.connection.execute("update population_research_jobs set status='hypothesis_recorded',result_json=?",(json.dumps(result),));self.s.connection.commit()
        routed=route(self.s,self.request)
        self.assertEqual(routed['state'],'prospective_plan_required')
        self.assertFalse(routed['promotion_authorized'])
        self.assertFalse(self.s.connection.execute("select 1 from sqlite_master where name='validation_plans'").fetchone())

    def test_memory_import_preserves_cross_account_inherited_periods(self):
        from tamtam_again.population_memory import remember
        from tamtam_again.research_memory import migrate,save_knowledge
        migrate(self.s)
        inherited_period={'network':'test','address':'other-account','market':'SOL','start_ms':1,'end_ms':10}
        inherited={'periods':[inherited_period],'origin_accounts':['other-account'], 'origin_markets':['SOL']}
        self.s.connection.execute('insert into research_knowledge values(?,?,?)',('ancestor',40,json.dumps(inherited)))
        packet=json.loads(self.s.connection.execute('select packet_json from population_research_jobs').fetchone()[0])
        packet['available_ms']=40
        packet['research_memory']=[{'knowledge_id':'ancestor','created_ms':40,'item':inherited}]
        result={'proposal':{'hypothesis':{'mechanism':'fixture','markets':['BTC'],
            'required_data':[],'rejection_criteria':'reject','execution_constraints':'limits','risk':'risk'}},
            'critique':{'decision':'consistent'},'promotion_authorized':False,'profitability_proven':False}
        self.s.connection.execute("update population_research_jobs set status='hypothesis_recorded',result_json=?,packet_json=?,updated_ms=50",
            (json.dumps(result),json.dumps(packet)));self.s.connection.commit()
        with patch('tamtam_again.research_memory.clock',return_value=100):
            saved=remember(self.s,self.request)
            item=json.loads(self.s.connection.execute('select item_json from research_knowledge where knowledge_id=?',(saved['knowledge_id'],)).fetchone()[0])
            self.assertIn(inherited_period,item['periods'])
            self.assertIn('other-account',item['origin_accounts'])
            self.assertIn({'kind':'knowledge','id':'ancestor'},item['evidence_refs'])
            item['periods'].remove(inherited_period)
            with self.assertRaisesRegex(ValueError,'inherited periods'):save_knowledge(self.s,item)

    def test_scheduler_compiled_hypothesis_prepares_plan_only_with_external_policy(self):
        from tamtam_again.recipe import synthetic_spec,synthetic_plan
        from tamtam_again.population_scheduler import tick
        packet=json.loads(self.s.connection.execute('select packet_json from population_research_jobs').fetchone()[0])
        packet['network']='synthetic'
        self.s.connection.execute('update population_research_jobs set network=?,packet_json=?',('synthetic',json.dumps(packet)));self.s.connection.commit()
        spec=synthetic_spec();spec['market']='BTC'
        profile={'schema_version':1,'hypothesis_id':self.request,'justification':'fixture only','max_variants':1,'selection_rule':'comparison_then_one_final',
            'axes':[{'parameter':'horizon_ms','values':[500],'category':'hypothesis','justification':'fixture','evidence_refs':['account_scope_reports:one'],'measurement_status':'simulated'}]}
        hypothesis={k:'fixture' for k in ('mechanism','signal','entry','exit','sizing','risk','horizon_justification','execution_constraints','rejection_criteria')}
        hypothesis.update(type='follower',markets=['BTC'],required_data=[],evidence_refs=['account_scope_reports:one'],executable_spec=spec,experiment_profile=profile)
        proposal={'decision':'hypothesis','diagnostic':'fixture','wake':{},'hypothesis':hypothesis}
        critique={'decision':'consistent','diagnostic':'fixture','wake':{}}
        with patch('tamtam_again.population_runtime.verify'),patch('tamtam_again.population_runtime.call',side_effect=[(json.dumps(proposal),self.usage),(json.dumps(critique),self.usage)]):
            self.assertEqual(run(self.s,self.request)['status'],'hypothesis_recorded')
        without=tick(self.s,'synthetic',self.policy,dispatch=False)
        self.assertEqual(without['plans'],[])
        self.assertEqual(self.s.connection.execute('select count(*) from validation_plans').fetchone()[0],0)
        policy={'version':'population-plan-v1','justification':'fixture only','max_plans':1,'comparison_delay_ms':100,
            'comparison_duration_ms':6000,'selection_gap_ms':2000,'final_duration_ms':6000,
            'criteria':synthetic_plan()['criteria'],'budget':synthetic_plan()['budget'],'isolation':'unavailable'}
        with patch('tamtam_again.population_runtime.call') as call:
            result=tick(self.s,'synthetic',self.policy,dispatch=False,plan_policies={self.request:policy})
            self.assertEqual(result['plans'][0]['status'],'registered');call.assert_not_called()
            again=tick(self.s,'synthetic',self.policy,dispatch=False,plan_policies={self.request:policy})
            self.assertEqual(again['plans'],[])
        self.assertEqual(self.s.connection.execute('select count(*) from strategy_variants').fetchone()[0],1)
        self.assertEqual(self.s.connection.execute('select count(*) from paper_sessions').fetchone()[0],0)

    def test_open_hypothesis_and_review_never_promote(self):
        hypothesis={k:'fixture testable specification' for k in ('mechanism','signal','entry','exit','sizing','risk','horizon_justification','execution_constraints','rejection_criteria')}
        hypothesis.update(type='autonomous',markets=['BTC','ETH'],required_data=['causal price paths'],evidence_refs=['account_scope_reports:one'])
        proposal={'decision':'hypothesis','diagnostic':{'observations':['fixture only']},'wake':{},'hypothesis':hypothesis}
        critique={'decision':'consistent','diagnostic':'testable fixture','wake':{}}
        with patch('tamtam_again.population_runtime.verify'),patch('tamtam_again.population_runtime.call',side_effect=[(json.dumps(proposal),self.usage),(json.dumps(critique),self.usage)]) as call:
            result=run(self.s,self.request)
            self.assertEqual(result['status'],'hypothesis_recorded');self.assertFalse(result['promotion_authorized'])
            self.assertEqual(run(self.s,self.request)['status'],'unchanged_no_inference');self.assertEqual(call.call_count,2)
        self.assertFalse(self.s.connection.execute("select 1 from sqlite_master where name='strategy_variants'").fetchone())

    def test_isolation_and_timeout_are_fail_closed(self):
        with patch('tamtam_again.population_runtime.verify',side_effect=RuntimeError),patch('tamtam_again.population_runtime.call') as call:
            with self.assertRaises(RuntimeError):run(self.s,self.request)
            call.assert_not_called()
        with patch('tamtam_again.population_runtime.verify'),patch('tamtam_again.population_runtime.call',side_effect=TimeoutError) as call:
            self.assertEqual(run(self.s,self.request)['status'],'suspended')
            self.assertEqual(run(self.s,self.request)['status'],'unchanged_no_inference');self.assertEqual(call.call_count,1)
        row=self.s.connection.execute('select reserved_cost_usd,actual_cost_usd from population_research_jobs').fetchone()
        self.assertEqual(row['reserved_cost_usd'],'2');self.assertIsNone(row['actual_cost_usd'])
