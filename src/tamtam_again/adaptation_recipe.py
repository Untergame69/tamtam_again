"""Chronological synthetic population -> paper diagnosis -> prospective decision."""
import json,tempfile
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
from .storage import Store
from .recipe import synthetic_plan,synthetic_spec,synthetic_events
from .population_scheduler import tick
from .pipeline import synthetic_tick


def run_recipe(output,*,observation_followup=False):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    clock=[1000]
    policy={'version':'population-research-v1','max_requests':3 if observation_followup else 2,'max_packet_chars':40000,
        'max_prompt_chars':60000,'minimum_interval_ms':1,'max_request_age_ms':3600000,
        'timeout_seconds':1,'max_output_tokens':1000,'model':'synthetic-fixture','call_reservation_usd':'1'}
    paper_policy={**policy,'version':'paper-adaptation-research-v1','justification':'fixture shared tranche only'}
    allocation={'version':'experiment-allocation-v1','policy_id':'synthetic-adaptation-v1',
        'justification':'fixture allocation only','max_profile_variants':1,'plan_template':{
        'version':'population-plan-v1','justification':'fixture only','max_plans':2,
        'comparison_delay_ms':100,'comparison_duration_ms':6000,'selection_gap_ms':2000,
        'final_duration_ms':6000,'criteria':synthetic_plan()['criteria'],
        'budget':synthetic_plan()['budget'],'isolation':'unavailable'}}
    calls=[]
    def inference(policy,prompt,*,on_response=None):
        calls.append(clock[0])
        usage={'cost_usd':0,'cost_status':'synthetic_fixture','duration_ms':0}
        if prompt.startswith('Review'):
            return json.dumps({'decision':'consistent','diagnostic':'fixture causal review only','wake':{}}),usage
        request=prompt.split('Request id: ')[1].split('\n')[0]
        packet=json.loads(prompt.split('\nPacket:\n',1)[1]);ref=packet['evidence_refs'][0]
        spec=synthetic_spec();spec['max_exposure']['max_drawdown_usdc']='1'
        hypothesis={k:'fixture unproven mechanism' for k in ('mechanism','signal','entry','exit','sizing','risk',
            'horizon_justification','execution_constraints','rejection_criteria')}
        hypothesis.update(type='follower',markets=['SYNTH'],required_data=[],evidence_refs=[ref],executable_spec=spec,
            experiment_profile={'schema_version':1,'hypothesis_id':request,'justification':'fixture only','max_variants':1,
                'selection_rule':'comparison_then_one_final','axes':[{'parameter':'horizon_ms','values':[500],
                'category':'hypothesis','justification':'fixture timing','evidence_refs':[ref],'measurement_status':'simulated'}]})
        if observation_followup and packet['schema_version']=='paper-diagnostic-research-v1' and 'parent_research' not in packet:
            hypothesis['required_data']=['public funding archive on the declared development interval']
            hypothesis['observation_requests']=[{'required_data_index':0,'source':'public_rest_history',
                'endpoint':'userFunding','start_ms':100,'end_ms':500,'proof':'pagination_coverage',
                'decision_use':'inspect archived funding before designing the next prospective rule'}]
        return json.dumps({'decision':'hypothesis','diagnostic':'fixture only','wake':{},'hypothesis':hypothesis}),usage
    with tempfile.TemporaryDirectory(prefix='tamtam-adaptation-synthetic-') as directory:
        db=Path(directory)/'recipe.sqlite3'
        with patch('tamtam_again.validation.datetime') as date,patch('time.time',side_effect=lambda:clock[0]/1000),\
                patch('tamtam_again.population_runtime.verify'),patch('tamtam_again.population_runtime.call',side_effect=inference):
            date.now.side_effect=lambda *args:datetime.fromtimestamp(clock[0]/1000,timezone.utc)
            with Store(db) as store:
                store.connection.execute('create table account_scope_reports(report_id text,network text,address text,available_ms integer,payload_json text)')
                address='0x'+'3'*40 if observation_followup else 'fixture-only'
                report={'address':address,'markets':['SYNTH'],'activity':{'observed_unique_fills':1,'observed_fill_content_fingerprint':'fixture-new-input'}}
                store.connection.execute('insert into account_scope_reports values(?,?,?,?,?)',('fixture','synthetic',address,900,json.dumps(report)));store.connection.commit()
                scheduled=tick(store,'synthetic',policy,experiment_policy=allocation,paper_policy=paper_policy)
                family=scheduled['plans'][0];variant=family['attempts'][0]['variant_id']
                plan=json.loads(store.connection.execute('select plan_json from validation_plans where plan_id=?',(family['plan_id'],)).fetchone()[0])
                fixtures={variant:{'comparison':synthetic_events(plan['comparison']['start_ms'])}}
                clock[0]=plan['comparison']['end_ms']
                synthetic_tick(store,fixtures,chronological=True)
                synthetic_tick(store,fixtures,chronological=True)
                if store.connection.execute('select count(*) from paper_sessions').fetchone()[0]:raise ValueError('Paper before final')
                if store.connection.execute("select count(*) from validation_evaluations where stage='final'").fetchone()[0]:raise ValueError('Final evaluated before its window ended')
                clock[0]=plan['final']['end_ms']
                fixtures[variant]['final']=synthetic_events(plan['final']['start_ms'])
                synthetic_tick(store,fixtures,chronological=True)
                session=store.connection.execute('select session_id from paper_sessions').fetchone()
                if not session:raise ValueError('No deterministic paper promotion')
                evaluated=store.connection.execute('select status from validation_evaluations').fetchall()
                if len(evaluated)!=2 or any(r[0]!='passed' for r in evaluated):raise ValueError('Deterministic validation gates incomplete')
                paper_start=clock[0]+1000
                events=synthetic_events(paper_start)
                for e in events:
                    if e['kind']=='bbo' and e['bid']=='102':e.update(bid='90',ask='90.1')
                clock[0]=events[-1]['received_ms']
                fixtures[variant]['paper']=events
                synthetic_tick(store,fixtures,chronological=True)
                diagnosis=store.connection.execute('select diagnostic_json from paper_adaptation_requests').fetchone()
                if not diagnosis or json.loads(diagnosis[0])['state']!='research_budget_required':raise ValueError('No event-driven research diagnosis')
                original=store.connection.execute('select state_json,status from paper_sessions').fetchone()[:]
            # Actual connection/process boundary; decisions and positions must persist.
            with Store(db) as resumed:
                clock[0]+=1
                revised=tick(resumed,'synthetic',policy,experiment_policy=allocation,paper_policy=paper_policy)
                if observation_followup:
                    if revised['paper_research']['plans']:raise ValueError('Plan despite missing observations')
                    from .population import enroll,claim
                    from .research_need_collection import tick_for_job
                    resumed.add_candidate('synthetic',address,'synthetic-recipe')
                    collection_policy=json.loads((Path(__file__).resolve().parents[2]/'config/population-policy.json').read_text())
                    collection_policy.pop('allocation')
                    enroll(resumed,'synthetic',collection_policy,now_ms=clock[0]);job=claim(resumed,'synthetic',now_ms=clock[0])
                    class PublicFixture:
                        def post_info(self,query):return []
                    need_policy={'version':'research-need-collection-v1','policy_id':'synthetic-adaptation-needs-v1',
                        'justification':'fixture bounded acquisition','max_needs_per_job':1,'max_pages_per_need':1,'max_attempts_per_need':2}
                    receipt=datetime.fromtimestamp(clock[0]/1000,timezone.utc).isoformat()
                    with patch('tamtam_again.storage.utc_now',return_value=receipt),patch('tamtam_again.population_history.utc_now',return_value=receipt):
                        acquired=tick_for_job(resumed,PublicFixture(),job,need_policy,clock_ms=clock[0])
                    if len(acquired['wakes'])!=1:raise ValueError('Observation request did not wake from archived evidence')
                    # New process boundary: wake and parent survive independently.
                    clock[0]+=1
                    with Store(db) as after_acquisition:
                        revised=tick(after_acquisition,'synthetic',policy,experiment_policy=allocation,paper_policy=paper_policy)
                    if len(revised['paper_research']['processed'])!=1:raise ValueError('Paper followup not dispatched')
                new=revised['paper_research']['plans'][0]
                prospective=json.loads(resumed.connection.execute('select plan_json from validation_plans where plan_id=?',(new['plan_id'],)).fetchone()[0])
                if prospective['comparison']['start_ms']<=clock[0]:raise ValueError('New comparison not prospective')
                if prospective['population_origin']['parent_session_id']!=session[0]:raise ValueError('Lost parent attribution')
                if resumed.connection.execute('select state_json,status from paper_sessions').fetchone()[:]!=original:raise ValueError('Old positions changed')
                repeated=tick(resumed,'synthetic',policy,experiment_policy=allocation,paper_policy=paper_policy)
                if repeated['paper_research']['plans'] or len(calls)!=(6 if observation_followup else 4):raise ValueError('Retry spent trials or recreated plan')
                counts={t:resumed.connection.execute('select count(*) from '+t).fetchone()[0] for t in
                    ('population_research_jobs','paper_research_jobs','validation_plans','paper_sessions','paper_adaptation_requests')}
            result={'synthetic':True,'real_strategy_validated':False,'real_model_calls':0,'real_provider_calls':0,
                'simulated_role_calls':len(calls),'counts':counts,'restart_and_duplicate_verified':True,
                'new_prospective_decision':True,'old_session_preserved':True,
                'observation_followup_verified':observation_followup,
                'limits':['source qualification report is a fixture; accounting is verified separately',
                    'market and model responses are fixtures, not evidence of profitability',
                    'new plan is registered; replacement and its future evaluation are not claimed']}
            (output/'adaptation-recipe-result.json').write_text(json.dumps(result,indent=2)+'\n')
            return result
