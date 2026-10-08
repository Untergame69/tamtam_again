"""Three-period synthetic comparative and replacement procedure recipe, with no production DB input."""
import json,tempfile
from pathlib import Path
from unittest.mock import patch
from .storage import Store
from .recipe import synthetic_plan,synthetic_spec,synthetic_events
from .validation import create_plan,register_variant,evaluate
from .paper import start_paper,synthetic_recipe_tick
from .procedure_registry import register,record_choice,bind_session
from .procedure_references import start_reference
from .procedure_report import registered_report
from .engine import fingerprint,number


def run_recipe(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='tamtam-procedure-synthetic-') as directory:
        db=Path(directory)/'recipe.db'
        with Store(db) as store:
            spec=synthetic_spec();plan=synthetic_plan()
            pid=create_plan(store,plan)['plan_id'];variant=register_variant(store,pid,spec)['variant_id']
            for stage in ('comparison','final'):
                r=evaluate(store,variant,stage,synthetic_events(plan[stage]['start_ms']),provenance='synthetic')
                if r['status']!='passed' or r['promotable']:raise ValueError('Synthetic N1 gates/provenance failed')
            replacement_plan=synthetic_plan()
            for stage in ('exploration','comparison','final'):
                for bound in ('start_ms','end_ms'):replacement_plan[stage][bound]+=20000
            replacement_plan['paper_replacement']={'version':'suspended-flat-handover-v1',
                'predecessor_variant_id':variant,'minimum_session_age_ms':1000,
                'capital_policy':'carry_flat_cash','justification':'scripted replacement following new synthetic validation'}
            replacement_pid=create_plan(store,replacement_plan)['plan_id']
            replacement_spec={**spec,'horizon_ms':600}
            replacement_variant=register_variant(store,replacement_pid,replacement_spec)['variant_id']
            contract={'version':'prospective-procedure-v1','policy_version':'synthetic-wait-rule-replacement-v1',
                'justification':'three scripted periods to verify accounting and recorded choices; no profitability claim',
                'network':'synthetic','address':'fixture-only','initial_capital_usdc':spec['starting_capital_usdc'],
                'risk_budget_id':fingerprint({'starting_capital_usdc':spec['starting_capital_usdc'],'max_exposure':spec['max_exposure']}),
                'periods':[{'start_ms':30000,'end_ms':40000},{'start_ms':40000,'end_ms':50000},{'start_ms':50000,'end_ms':60000}],
                'references':[{'name':'fixed','kind':'fixed_rule','variant_id':variant,'available_ms':26000,'evidence_ref':'synthetic:N1'},
                              {'name':'cash','kind':'cash','available_ms':0,'evidence_ref':'synthetic:cash-convention'}]}
            with patch('tamtam_again.procedure_registry.now_ms',return_value=27000):
                identity=register(store,contract)['procedure_id']
            choice={'selected_variant_id':None,'considered_variant_ids':[variant],'knowledge_available_ms':[26000],
                'evidence_refs':['synthetic:wait-decision'],'diagnostic':'scripted wait; no retrospective winner','change_cost':'0'}
            with patch('tamtam_again.procedure_registry.now_ms',return_value=28000):record_choice(store,identity,0,choice)
            with patch('tamtam_again.paper.now_ms',return_value=29000),patch('tamtam_again.procedure_registry.now_ms',return_value=29000):
                reference=start_reference(store,identity,0,'fixed',synthetic_recipe=True)['session_id']
            def timer(t):return {'id':'timer:'+str(t),'kind':'timer','received_ms':t,'event_ms':t}
            def feed(session,stamp,events):
                events=events+[{'id':'heartbeat:'+str(stamp),'kind':'heartbeat','session':'fixture-session','received_ms':stamp,'event_ms':stamp}]
                events=sorted(events,key=lambda e:e['received_ms'])
                with patch('tamtam_again.paper.now_ms',return_value=stamp):return synthetic_recipe_tick(store,session,events,clock_ms=stamp)
            feed(reference,30000,synthetic_events(29900)[:2]+[timer(30000)])
            store.connection.execute('create table population_research_jobs(request_id text,network text,address text,created_ms integer,updated_ms integer,status text,actual_cost_usd text,reserved_cost_usd text)')
            store.connection.execute("insert into population_research_jobs values('failed-fixture','synthetic','fixture-only',35000,36000,'reject','2','4')");store.connection.commit()
            with patch('tamtam_again.procedure_registry.now_ms',return_value=39000),patch('tamtam_again.procedure_references.now_ms',return_value=39000),patch('tamtam_again.paper.now_ms',return_value=39000):
                record_choice(store,identity,1,{**choice,'selected_variant_id':variant,'knowledge_available_ms':[38000],
                    'evidence_refs':['synthetic:new-observation'],'diagnostic':'scripted new observation enables frozen rule'})
                adaptive=start_paper(store,variant,synthetic_recipe=True)['session_id']
                bind_session(store,identity,1,'adaptive',adaptive)
                continued=start_reference(store,identity,1,'fixed',synthetic_recipe=True)['session_id']
                if continued!=reference:raise ValueError('Fixed reference capital reset')
            feed(reference,40000,synthetic_events(31000)+[timer(40000)])
            feed(adaptive,40000,synthetic_events(39900)[:2]+[timer(40000)])
            for stage in ('comparison','final'):
                r=evaluate(store,replacement_variant,stage,synthetic_events(replacement_plan[stage]['start_ms']),provenance='synthetic')
                if r['status']!='passed' or r['promotable']:raise ValueError('Replacement synthetic N1 gates failed')
            with patch('tamtam_again.procedure_registry.now_ms',return_value=49000),patch('tamtam_again.procedure_references.now_ms',return_value=49000):
                record_choice(store,identity,2,{**choice,'selected_variant_id':replacement_variant,
                    'considered_variant_ids':[variant,replacement_variant],'knowledge_available_ms':[46000],
                    'evidence_refs':['synthetic:replacement-N1'],'diagnostic':'scripted replacement','change_cost':'1'})
                start_reference(store,identity,2,'fixed',synthetic_recipe=True)
            for session in (reference,adaptive):feed(session,50000,synthetic_events(41000)+[timer(50000)])
            # This is a scripted suspension, not a claim that noise justifies a change.
            old_state=store.connection.execute('select state_json from paper_sessions where session_id=?',(adaptive,)).fetchone()[0]
            store.connection.execute("update paper_sessions set status='suspended' where session_id=?",(adaptive,));store.connection.commit()
            with patch('tamtam_again.paper.now_ms',return_value=50000),patch('tamtam_again.procedure_registry.now_ms',return_value=50000):
                replacement=start_paper(store,replacement_variant,synthetic_recipe=True)['session_id']
                bind_session(store,identity,2,'adaptive',replacement)
            if store.connection.execute('select state_json from paper_sessions where session_id=?',(adaptive,)).fetchone()[0]!=old_state:
                raise ValueError('Replacement rewrote old version state')
            new_state=json.loads(store.connection.execute('select state_json from paper_sessions where session_id=?',(replacement,)).fetchone()[0])
            if new_state['cash']!=json.loads(old_state)['cash']:raise ValueError('Replacement reset capital')
            for session in (reference,replacement):feed(session,60000,synthetic_events(51000)+[timer(60000)])
            first=registered_report(store,identity,as_of_ms=60000)
        with Store(db) as resumed:
            repeated=registered_report(resumed,identity,as_of_ms=60000)
            if repeated!=first:raise ValueError('Procedure report changed after reconnect')
            fixed=first['comparisons']['fixed']
            if first['status']!='registered_model_inputs_evaluated' or fixed['wait_periods']!=1 or fixed['observed_research_cost']!='2':
                raise ValueError('Recorded procedure accounting failed')
            if number(fixed['fixed_net'])<=number(fixed['adaptive_net_after_research_and_change_costs']):
                raise ValueError('Recipe silently chose hindsight winner')
            resumed.connection.execute("update population_research_jobs set actual_cost_usd=null")
            unknown=registered_report(resumed,identity,as_of_ms=60000)
            if unknown['comparisons']['fixed']['adaptive_net_after_research_and_change_costs'] is not None:
                raise ValueError('Missing cost counted as zero')
        result={'synthetic':True,'real_strategy_validated':False,'real_model_calls':0,'real_provider_calls':0,
            'original_database_touched':False,'report':first,'restart_reproducible':True,
            'missing_cost_propagated':True,'replacement_capital_preserved':True,'old_version_preserved':True,'limits':['scripted events and decisions, not economic evidence',
                'no live scheduler or matching-cohort qualification demonstrated by this recipe']}
        (output/'procedure-recipe.json').write_text(json.dumps(result,indent=2)+'\n')
        return result
