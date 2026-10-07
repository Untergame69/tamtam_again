"""Explicit synthetic acceptance of population runtime, planning and pipeline."""
import json,tempfile,time
from pathlib import Path
from unittest.mock import patch
from .storage import Store
from .recipe import synthetic_plan,synthetic_spec,synthetic_events
from .population_scheduler import tick as population_tick
from .pipeline import synthetic_tick


def run_recipe(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    research_policy={'version':'population-research-v1','max_requests':1,'max_packet_chars':10000,
        'max_prompt_chars':20000,'minimum_interval_ms':1000,'max_request_age_ms':3600000,
        'timeout_seconds':1,'max_output_tokens':1000,'model':'synthetic-fixture','call_reservation_usd':'1'}
    prospective_policy={'version':'population-plan-v1','justification':'synthetic acceptance only; no real parameter recommendation',
        'max_plans':1,'comparison_delay_ms':100,'comparison_duration_ms':6000,'selection_gap_ms':2000,
        'final_duration_ms':6000,'criteria':synthetic_plan()['criteria'],'budget':synthetic_plan()['budget'],'isolation':'unavailable'}
    with tempfile.TemporaryDirectory(prefix='tamtam-population-synthetic-') as directory:
        db=Path(directory)/'recipe.sqlite3'
        with Store(db) as store:
            store.connection.execute('create table account_scope_reports(report_id text,network text,address text,available_ms integer,payload_json text)')
            report={'address':'fixture-only','markets':['SYNTH'],'activity':{'observed_unique_fills':1,'observed_fill_content_fingerprint':'synthetic-fixture'}}
            store.connection.execute('insert into account_scope_reports values(?,?,?,?,?)',('fixture','synthetic','fixture-only',int(time.time()*1000),json.dumps(report)));store.connection.commit()
            preparation=population_tick(store,'synthetic',research_policy,dispatch=False)
            request_id=preparation['sealed'][0]['request_id']
            profile={'schema_version':1,'hypothesis_id':request_id,'justification':'synthetic engine integration only','max_variants':1,
                'selection_rule':'comparison_then_one_final','axes':[{'parameter':'horizon_ms','values':[500],
                'category':'hypothesis','justification':'scripted synthetic cycles only','evidence_refs':['account_scope_reports:fixture'],
                'measurement_status':'simulated'}]}
            hypothesis={key:'synthetic fixture only' for key in ('mechanism','signal','entry','exit','sizing','risk',
                'horizon_justification','execution_constraints','rejection_criteria')}
            hypothesis.update(type='follower',markets=['SYNTH'],required_data=[],evidence_refs=['account_scope_reports:fixture'],
                executable_spec=synthetic_spec(),experiment_profile=profile)
            responses=[{'decision':'hypothesis','diagnostic':'synthetic fixture only','wake':{},'hypothesis':hypothesis},
                {'decision':'consistent','diagnostic':'synthetic fixture only','wake':{}}]
            usage={'cost_usd':0,'cost_status':'synthetic_fixture','duration_ms':0}
            with patch('tamtam_again.population_runtime.verify') as isolation,patch('tamtam_again.population_runtime.call',
                    side_effect=[(json.dumps(response),usage) for response in responses]) as inference:
                scheduled=population_tick(store,'synthetic',research_policy,plan_policies={request_id:prospective_policy})
                if inference.call_count!=2 or isolation.call_count!=1:raise ValueError('Synthetic role dispatch contract failed')
            family=scheduled['plans'][0];variant=family['attempts'][0]['variant_id']
            plan=json.loads(store.connection.execute('select plan_json from validation_plans where plan_id=?',(family['plan_id'],)).fetchone()[0])
            fixtures={variant:{stage:synthetic_events(plan[stage]['start_ms']) for stage in ('comparison','final')}}
            fixtures[variant]['paper']=synthetic_events(plan['final']['end_ms']+1000)
            with patch('tamtam_again.pipeline.archive_events') as archive:
                first=synthetic_tick(store,fixtures)
                if store.connection.execute('select count(*) from paper_sessions').fetchone()[0]:raise ValueError('Paper started before final selection')
                second=synthetic_tick(store,fixtures)
                archive.assert_not_called()
            session=store.connection.execute('select session_id,state_json from paper_sessions').fetchone()
            if not session:raise ValueError('Synthetic scheduler did not reach paper')
            original_state=session['state_json']
        with Store(db) as resumed:
            with patch('tamtam_again.pipeline.archive_events') as archive:
                repeated=synthetic_tick(resumed,fixtures);archive.assert_not_called()
            if resumed.connection.execute('select state_json from paper_sessions').fetchone()[0]!=original_state:
                raise ValueError('Paper ledger changed on duplicate synthetic events')
            evaluations=[json.loads(row[0]) for row in resumed.connection.execute('select result_json from validation_evaluations')]
            if len(evaluations)!=2 or any(e['status']!='passed' or not e['synthetic'] or e['promotable'] for e in evaluations):
                raise ValueError('Synthetic N1 provenance or deterministic gates failed')
            counts={table:resumed.connection.execute('select count(*) from '+table).fetchone()[0] for table in
                ('population_research_jobs','research_knowledge','population_experiment_links','validation_plans',
                 'strategy_variants','validation_evaluations','paper_sessions')}
        result={'synthetic':True,'real_strategy_validated':False,'live_orders_enabled':False,
            'real_model_calls':0,'real_provider_calls':0,'simulated_role_calls':2,
            'isolation_verification':'mocked in this recipe; separate real isolation checks required',
            'counts':counts,'stages':[{'stage':e['stage'],'status':e['status'],'synthetic':e['synthetic'],'promotable':e['promotable']} for e in evaluations],
            'restart_and_duplicate_verified':True,'original_database_touched':False,
            'limits':['scripted profitability is fixture design, never evidence for a real strategy',
                'real collection, cost realism, isolation and latency require independent checks',
                'broad population qualification and multi-instrument integration remain separate requirements']}
        (output/'population-recipe-result.json').write_text(json.dumps(result,indent=2)+'\n')
        return result
