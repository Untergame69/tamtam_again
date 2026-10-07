"""Preregister future population windows once, using explicit justified budgets."""
import json
from .engine import canonical,fingerprint,number
from .experiments import compile_family
from .population_routing import route
from .population_experiments import _register_experiment
from .research import scheduler_lock
from .validation import create_plan,now_ms,validate_criteria


def prepare_plan(store,request_id,policy,profile):
    if policy.get('version')!='population-plan-v1' or not policy.get('justification'):
        raise ValueError('Versioned prospective-window justification required')
    for key in ('max_plans','comparison_delay_ms','comparison_duration_ms','selection_gap_ms','final_duration_ms'):
        if type(policy.get(key)) is not int or policy[key]<1:raise ValueError('Explicit positive window/plan budget required: '+key)
    if policy.get('isolation') not in ('unavailable','separate_principal'):
        raise ValueError('Explicit actual isolation availability required')
    validate_criteria(policy['criteria'])
    contract=fingerprint({'request_id':request_id,'policy':policy,'profile':profile})
    with scheduler_lock(store):
        store.connection.execute('create table if not exists population_plan_drafts '
            '(request_id text primary key,contract_fingerprint text not null,created_ms integer not null,plan_json text not null)')
        store.connection.commit()
        prior=store.connection.execute('select * from population_plan_drafts where request_id=?',(request_id,)).fetchone()
        if prior:
            if prior['contract_fingerprint']!=contract:raise ValueError('Preregistered windows and criteria are immutable')
            plan=json.loads(prior['plan_json'])
            plan_id=fingerprint(plan)
            linked=store.connection.execute("select 1 from sqlite_master where name='population_experiment_links'").fetchone()
            if linked and store.connection.execute('select 1 from population_experiment_links where request_id=?',(request_id,)).fetchone():
                return _register_experiment(store,request_id,plan_id,profile)
        else:
            if store.connection.execute('select count(*) from population_plan_drafts').fetchone()[0]>=policy['max_plans']:
                return {'status':'budget_exhausted','promotion_authorized':False}
            decision=route(store,request_id)
            if decision['state']!='prospective_plan_required':
                return {'status':decision['state'],'promotion_authorized':False,'next_action':decision['next_action']}
            job=store.connection.execute('select network,address,updated_ms,packet_json,result_json from population_research_jobs where request_id=?',(request_id,)).fetchone()
            spec=json.loads(job['result_json'])['proposal']['hypothesis']['executable_spec']
            specs=compile_family(profile,spec)
            embargo=max(max(s['horizon_ms'],s['signal'].get('lookback_ms',0))+s['latency_ms'] for s in specs)
            now=now_ms();packet=json.loads(job['packet_json'])
            if packet['available_ms']>now or job['updated_ms']>now:
                raise ValueError('Reviewed hypothesis information must already be available')
            development_end=max(packet['available_ms']+1,job['updated_ms']+1)
            comparison_start=max(now+policy['comparison_delay_ms'],development_end+embargo)
            comparison_end=comparison_start+policy['comparison_duration_ms']
            final_start=comparison_end+max(embargo,policy['selection_gap_ms'])
            final_end=final_start+policy['final_duration_ms']
            budget=policy['budget']
            for key in ('max_runs','max_same_input_corrections','max_duration_ms'):
                if type(budget.get(key)) is not int or budget[key]<1:raise ValueError('Explicit positive evaluation budget required')
            if (len(specs)+1>budget['max_runs'] or budget['max_duration_ms']<final_end-now or
                not number(budget.get('max_cost_usd')).is_finite() or number(budget['max_cost_usd'])<=0):
                raise ValueError('Evaluation budget must cover comparisons and final window')
            if profile.get('hypothesis_id')!=request_id:raise ValueError('Profile must reference reviewed hypothesis')
            plan={'network':job['network'],'address':job['address'],'coin':spec['market'],
                'synthetic':job['network']=='synthetic','isolation':policy['isolation'],
                'exploration':{'start_ms':0,'end_ms':development_end},
                'comparison':{'start_ms':comparison_start,'end_ms':comparison_end},
                'final':{'start_ms':final_start,'end_ms':final_end},'embargo_ms':embargo,
                'criteria':policy['criteria'],'budget':budget,
                'population_origin':{'request_id':request_id,'policy_fingerprint':fingerprint(policy),
                    'justification':policy['justification'],'created_ms':now}}
            # Save the anchor before downstream commits. Recovery reuses it,
            # never silently moves an exposed or missed final into the future.
            store.connection.execute('insert into population_plan_drafts values(?,?,?,?)',
                (request_id,contract,now,canonical(plan)));store.connection.commit()
        result=create_plan(store,plan)
        return _register_experiment(store,request_id,result['plan_id'],profile)
