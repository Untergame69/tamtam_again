"""Preregister bounded experiment families; preserve every failed variant."""
from __future__ import annotations
from copy import deepcopy
from itertools import product
import json,time
from typing import Any
from .engine import canonical,fingerprint,number,validate_spec
from .storage import Store,utc_now
from .validation import initialize,register_variant

SCHEMA='''
CREATE TABLE IF NOT EXISTS experiment_families (
 family_id TEXT PRIMARY KEY,plan_id TEXT NOT NULL,created_ms INTEGER NOT NULL,
 profile_json TEXT NOT NULL,base_spec_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS experiment_attempts (
 family_id TEXT NOT NULL,attempt_index INTEGER NOT NULL,spec_json TEXT NOT NULL,
 status TEXT NOT NULL,variant_id TEXT,diagnostic TEXT NOT NULL,
 PRIMARY KEY(family_id,attempt_index));
CREATE TABLE IF NOT EXISTS experiment_selections (
 family_id TEXT PRIMARY KEY,variant_id TEXT,selected_ms INTEGER NOT NULL,
 status TEXT NOT NULL,evidence_json TEXT NOT NULL);'''
AXES={'horizon_ms':('hypothesis',),'latency_ms':('system_capacity','hypothesis'),
      'scale':('risk_budget','hypothesis')}

def compile_family(profile:dict[str,Any],base_spec:dict[str,Any]) -> list[dict[str,Any]]:
    if profile.get('schema_version')!=1 or not profile.get('hypothesis_id') or not profile.get('justification'):
        raise ValueError('Versioned hypothesis and experiment justification required')
    maximum=profile.get('max_variants')
    if type(maximum) is not int or not 1<=maximum<=64:raise ValueError('Explicit variant budget between one and 64 required')
    if profile.get('selection_rule')!='comparison_then_one_final':raise ValueError('Preregister one final selection after comparison')
    axes=profile.get('axes')
    if not isinstance(axes,list) or not axes:raise ValueError('Explicit experimental axes required')
    names=[];values=[];count=1
    for axis in axes:
        key=axis.get('parameter')
        if key not in AXES or key in names:raise ValueError('Unsupported or duplicate experimental axis')
        if axis.get('category') not in AXES[key] or not axis.get('justification') or not axis.get('evidence_refs'):
            raise ValueError('Classified and evidenced parameter justification required')
        choices=axis.get('values')
        if not isinstance(choices,list) or not choices:raise ValueError('Nonempty parameter choices required')
        if len({canonical(v) for v in choices})!=len(choices):raise ValueError('Duplicate choices inflate trial budget')
        if key in ('horizon_ms','latency_ms'):
            if any(type(v) is not int or v<(1 if key=='horizon_ms' else 0) for v in choices):raise ValueError('Invalid time choices')
        elif any(number(v)<=0 for v in choices):raise ValueError('Positive scale choices required')
        if axis.get('measurement_status') not in ('simulated','measured_reference'):
            raise ValueError('Distinguish simulated delays from measured references')
        if axis['measurement_status']=='measured_reference':
            if type(axis.get('measurement_available_ms')) is not int or axis['measurement_available_ms']>int(time.time()*1000):
                raise ValueError('Measurement reference must already be available')
            if key!='latency_ms':raise ValueError('Measured execution-delay references apply only to latency axes')
        count*=len(choices)
        if count>maximum:raise ValueError('Experiment Cartesian product exceeds declared budget')
        names.append(key);values.append(choices)
    specs=[]
    for combination in product(*values):
        spec=deepcopy(base_spec)
        for key,value in zip(names,combination):
            if key=='scale':spec['sizing']['scale']=value
            else:spec[key]=value
        specs.append(spec)
    return specs

def register_family(store:Store,plan_id:str,profile:dict[str,Any],base_spec:dict[str,Any]) -> dict[str,Any]:
    initialize(store);store.connection.executescript(SCHEMA)
    specs=compile_family(profile,base_spec)
    family_id=fingerprint({'plan_id':plan_id,'profile':profile,'base_spec':base_spec})
    existing=store.connection.execute('select 1 from experiment_families where family_id=?',(family_id,)).fetchone()
    if existing:return family_status(store,family_id)
    plan=store.connection.execute('select * from validation_plans where plan_id=?',(plan_id,)).fetchone()
    if not plan:raise ValueError('Unknown prospective plan')
    plan_data=json.loads(plan['plan_json'])
    if store.connection.execute('select 1 from strategy_variants where plan_id=?',(plan_id,)).fetchone():
        raise ValueError('Use a fresh plan; existing frozen variants are preserved')
    if len(specs)+1>plan_data['budget']['max_runs']:raise ValueError('Family needs comparisons plus one final within plan budget')
    if not plan['synthetic'] and int(time.time()*1000)>=plan_data['comparison']['start_ms']:
        raise ValueError('Family must be registered before prospective comparison begins')
    # Registration and all failures are atomic: an invalid combination is evidence,
    # not a reason to retain only the combinations that happened to validate.
    store.connection.execute('begin immediate')
    try:
        if store.connection.execute('select 1 from strategy_variants where plan_id=?',(plan_id,)).fetchone():
            raise ValueError('Fresh plan acquired frozen variants concurrently')
        store.connection.execute('insert into experiment_families values (?,?,?,?,?)',
            (family_id,plan_id,int(time.time()*1000),canonical(profile),canonical(base_spec)))
        for index,spec in enumerate(specs):
            try:
                validate_spec(spec)
                variant=register_variant(store,plan_id,spec,commit=False)
                status='frozen';variant_id=variant['variant_id'];diagnostic='await preregistered comparison; no economic promotion'
            except ValueError as exc:
                diagnostic=str(exc)
                status='unsupported_mechanism' if diagnostic.startswith(('Unsupported mechanism','Supported signals:','Unsupported entry/exit','Unsupported execution model')) else 'invalid_specification'
                variant_id=None
            store.connection.execute('insert into experiment_attempts values (?,?,?,?,?,?)',
                (family_id,index,canonical(spec),status,variant_id,diagnostic))
        store.connection.commit()
    except BaseException:store.connection.rollback();raise
    return family_status(store,family_id)

def select_final(store:Store,family_id:str) -> dict[str,Any]:
    prior=store.connection.execute('select * from experiment_selections where family_id=?',(family_id,)).fetchone()
    if prior:return dict(prior)
    family=store.connection.execute('select * from experiment_families where family_id=?',(family_id,)).fetchone()
    if not family:raise ValueError('Unknown experiment family')
    plan=store.connection.execute('select plan_json,synthetic from validation_plans where plan_id=?',(family['plan_id'],)).fetchone()
    data=json.loads(plan['plan_json']);now=int(time.time()*1000)
    if not plan['synthetic'] and not data['comparison']['end_ms']<=now<data['final']['start_ms']:
        raise ValueError('Selection requires completed comparison and an unopened final window')
    candidates=[];evidence=[]
    for attempt in store.connection.execute("select variant_id from experiment_attempts where family_id=? and status='frozen'",(family_id,)):
        evaluation=store.connection.execute("select * from validation_evaluations where variant_id=? and stage='comparison' order by created_at desc limit 1",(attempt['variant_id'],)).fetchone()
        if not evaluation or evaluation['status']=='running':raise ValueError('All frozen family comparisons must be terminal before selection')
        evidence.append({'variant_id':attempt['variant_id'],'evaluation_id':evaluation['evaluation_id'],'status':evaluation['status']})
        if evaluation['status']=='passed':
            result=json.loads(evaluation['result_json'])
            candidates.append((number(result['stress_metrics']['net_pnl']),attempt['variant_id']))
    # This fixed ranking is part of the v1 profile contract, not an IA decision.
    winner=sorted(candidates,key=lambda x:(-x[0],x[1]))[0][1] if candidates else None
    payload={'comparison_evidence':evidence,'ranking':'passed comparisons, descending stressed net PnL; variant-id tie break','final_results_used':False}
    store.connection.execute('insert or ignore into experiment_selections values (?,?,?,?,?)',
        (family_id,winner,now,'selected' if winner else 'no_candidate',canonical(payload)))
    store.connection.commit()
    return dict(store.connection.execute('select * from experiment_selections where family_id=?',(family_id,)).fetchone())

def require_final_selection(store:Store,variant_id:str):
    if not store.connection.execute("select 1 from sqlite_master where name='experiment_attempts'").fetchone():return
    membership=store.connection.execute('select family_id from experiment_attempts where variant_id=?',(variant_id,)).fetchone()
    if not membership:return
    selected=store.connection.execute('select variant_id from experiment_selections where family_id=?',(membership['family_id'],)).fetchone()
    if not selected or selected['variant_id']!=variant_id:
        raise ValueError('Final reserved for the preregistered comparison winner')

def family_status(store:Store,family_id:str) -> dict[str,Any]:
    row=store.connection.execute('select * from experiment_families where family_id=?',(family_id,)).fetchone()
    if not row:raise ValueError('Unknown experiment family')
    attempts=[dict(r) for r in store.connection.execute('select attempt_index,status,variant_id,diagnostic from experiment_attempts where family_id=? order by attempt_index',(family_id,))]
    return {'family_id':family_id,'plan_id':row['plan_id'],'created_ms':row['created_ms'],
            'attempts':attempts,'selection_status':'comparison_required','economic_validation':False,
            'limits':['a measured reference does not make experimental delays observed execution latency',
                      'failed specifications count as attempts','one final winner must be selected before holdout evaluation']}
