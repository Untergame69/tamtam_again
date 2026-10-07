"""Causal registry metadata export; no raw observations or evaluation results."""
from __future__ import annotations
from datetime import datetime
from .discovery import fingerprint


def registry_trace(store, *, as_of_ms):
    if type(as_of_ms) is not int or as_of_ms<0:
        raise ValueError('Explicit trace cutoff required')
    events=[]
    exists=lambda table: bool(store.connection.execute(
        "select 1 from sqlite_master where type='table' and name=?",(table,)).fetchone())
    def stamp(value):return int(datetime.fromisoformat(value).timestamp()*1000)
    def emit(kind,identity,available,details):
        if available<=as_of_ms:
            events.append({'kind':kind,'id':identity,'available_ms':available,**details})
    if exists('adaptation_events'):
        for row in store.connection.execute('select event_id,available_ms,input_fingerprint from adaptation_events where available_ms<=?',(as_of_ms,)):
            emit('population_diagnostic',row['event_id'],row['available_ms'],
                 {'input_fingerprint':row['input_fingerprint'],'evidence_ref':'adaptation_events:'+row['event_id']})
    if exists('population_attempts'):
        for row in store.connection.execute('select attempt_id,started_ms,completed_ms,status from population_attempts where started_ms<=?',(as_of_ms,)):
            emit('population_attempt_started',row['attempt_id'],row['started_ms'],{})
            if row['completed_ms'] is not None:
                emit('population_attempt_finished',row['attempt_id'],row['completed_ms'],{'status':row['status']})
    if exists('isolated_research_jobs'):
        for row in store.connection.execute('select run_id,plan_id,input_fingerprint,status,reserved_cost_usd,actual_cost_usd,created_at,updated_at from isolated_research_jobs'):
            emit('research_registered',row['run_id'],stamp(row['created_at']),
                 {'plan_id':row['plan_id'],'input_fingerprint':row['input_fingerprint'],
                  'reserved_cost_usd':row['reserved_cost_usd']})
            # Current mutable status is exported only at its latest update time.
            emit('research_latest_status',row['run_id'],stamp(row['updated_at']),
                 {'status':row['status'],'actual_cost_usd':row['actual_cost_usd']})
    if exists('population_research_jobs'):
        for row in store.connection.execute('select request_id,created_ms,input_fingerprint from population_research_jobs where created_ms<=?',(as_of_ms,)):
            emit('population_research_sealed',row['request_id'],row['created_ms'],
                 {'input_fingerprint':row['input_fingerprint'],'evidence_ref':'population_research_jobs:'+row['request_id']})
    if exists('strategy_variants'):
        for row in store.connection.execute('select variant_id,plan_id,frozen_ms from strategy_variants where frozen_ms<=?',(as_of_ms,)):
            emit('variant_frozen',row['variant_id'],row['frozen_ms'],{'plan_id':row['plan_id']})
    if exists('paper_sessions'):
        for row in store.connection.execute('select session_id,variant_id,started_ms from paper_sessions where started_ms<=?',(as_of_ms,)):
            emit('paper_session_started',row['session_id'],row['started_ms'],{'variant_id':row['variant_id']})
    if exists('paper_retirements'):
        for row in store.connection.execute('select session_id,retired_ms from paper_retirements where retired_ms<=?',(as_of_ms,)):
            emit('paper_session_retired',row['session_id'],row['retired_ms'],
                 {'evidence_ref':'paper_retirements:'+row['session_id']})
    if exists('paper_suspensions'):
        for row in store.connection.execute('select session_id,suspended_ms from paper_suspensions where suspended_ms<=?',(as_of_ms,)):
            emit('paper_session_suspended',row['session_id'],row['suspended_ms'],
                 {'evidence_ref':'paper_suspensions:'+row['session_id']})
    if exists('paper_handovers'):
        for row in store.connection.execute('select new_session_id,prior_session_id,available_ms from paper_handovers where available_ms<=?',(as_of_ms,)):
            emit('paper_handover',row['new_session_id'],row['available_ms'],
                 {'prior_session_id':row['prior_session_id'],'evidence_ref':'paper_handovers:'+row['new_session_id']})
    if exists('paper_snapshots'):
        for row in store.connection.execute('select snapshot_id,session_id,available_ms from paper_snapshots where available_ms<=?',(as_of_ms,)):
            emit('paper_snapshot_available',row['snapshot_id'],row['available_ms'],
                 {'session_id':row['session_id'],'evidence_ref':'paper_snapshots:'+row['snapshot_id']})
    events.sort(key=lambda e:(e['available_ms'],e['kind'],e['id']))
    result={'version':'registry-metadata-trace-v1','as_of_ms':as_of_ms,'events':events,
            'performance_status':'unknown','net_adaptation_result':None,
            'limits':['mutable registries do not reconstruct intermediate historical states',
                      'no raw observations, research packets or evaluation results consumed',
                      'diagnostics and frozen variants are not paper selections',
                      'outcome and policy-selection adapters still required for procedure replay']}
    result['fingerprint']=fingerprint(result)
    return result
