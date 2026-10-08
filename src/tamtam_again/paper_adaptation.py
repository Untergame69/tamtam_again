"""Immutable suspension diagnoses from paper evidence, never from reserved archives."""
import json
from .engine import canonical,fingerprint

COLLECTION={'connection_interrupted','market_subscription_missing',
            'connection_changed_without_reconciliation','missing_live_heartbeat'}
PERFORMANCE={'paper_net_loss_budget_exhausted','risk_drawdown_limit'}


def initialize(store):
    store.connection.execute('create table if not exists paper_adaptation_requests '
        '(request_id text primary key,session_id text not null unique,created_ms integer not null,'
        'suspension_ms integer not null,diagnostic_json text not null)')


def diagnose(codes):
    if not isinstance(codes,list) or not codes or any(not isinstance(c,str) or not c for c in codes):
        raise ValueError('Explicit nonempty paper diagnostics required')
    codes=sorted(set(codes));unrecognized=set(codes)-COLLECTION-PERFORMANCE-{'leader_signal_not_live','paper_duration_budget_exhausted'}
    triggers=[]
    if set(codes)&COLLECTION:triggers.append('collection_failure')
    if set(codes)&PERFORMANCE:triggers.append('performance_degradation')
    if 'leader_signal_not_live' in codes:triggers.append('signal_availability_failure')
    if 'paper_duration_budget_exhausted' in codes:triggers.append('experiment_budget_exhausted')
    # A loss with broken collection cannot be safely attributed to a strategy.
    if unrecognized:
        state='diagnostic_review_required';action='classify unrecognized deterministic diagnostics'
        wake={'known_diagnostic_mapping_required':sorted(unrecognized)}
    elif 'collection_failure' in triggers:
        state='collection_correction_required';action='reconcile the interrupted feed and paper position before new research'
        wake={'healthy_stream_and_reconciled_state_evidence_required':True,
              'new_observation_fingerprint_required':True}
    elif 'signal_availability_failure' in triggers:
        state='execution_model_review_required';action='resolve actual signal availability; do not relabel REST fills as live'
        wake={'causal_live_signal_or_explicit_delayed_model_required':True}
    elif 'performance_degradation' in triggers:
        state='research_budget_required';action='register a bounded diagnostic research policy and a new prospective comparison'
        wake={'new_research_policy_required':True,'fresh_prospective_windows_required':True,
              'position_handover_policy_required':True}
    else:
        state='experiment_complete';action='preserve outcomes and explicitly budget any subsequent experiment'
        wake={'new_experiment_policy_and_future_windows_required':True}
    return {'diagnostics':codes,'triggers':triggers,'state':state,'next_action':action,'wake':wake,
      'performance_attribution':'unproven' if 'collection_failure' in triggers else 'risk limit observed, mechanism unproven',
      'promotion_authorized':False,'resume_authorized':False,'model_calls_authorized':0,
      'limits':['loss-budget crossing is a safety trigger, not statistical proof of an edge change',
                'diagnosis proposes work; no rule parameters or promotion criteria are optimized',
                'old session, positions, ledger and frozen version remain attributed to their original identity']}


def record(store,session_id,*,clock_ms):
    """Caller owns transaction. One sealed request per immutable suspension."""
    initialize(store)
    old=store.connection.execute('select diagnostic_json from paper_adaptation_requests where session_id=?',(session_id,)).fetchone()
    if old:return json.loads(old[0])
    if type(clock_ms) is not int or clock_ms<0:raise ValueError('Explicit diagnostic availability required')
    suspension=store.connection.execute('select * from paper_suspensions where session_id=?',(session_id,)).fetchone()
    session=store.connection.execute('select * from paper_sessions where session_id=?',(session_id,)).fetchone()
    if not suspension or not session or session['status'] not in ('suspended','retired') or suspension['suspended_ms']>clock_ms:
        raise ValueError('Available suspended session required')
    state=json.loads(session['state_json']);state_fp=fingerprint(state)
    snapshot=store.connection.execute('select snapshot_id,available_ms,metrics_json from paper_snapshots where session_id=? and state_fingerprint=? and available_ms<=? order by available_ms desc,snapshot_id limit 1',
        (session_id,state_fp,clock_ms)).fetchone()
    if not snapshot:raise ValueError('Matching immutable paper snapshot required')
    codes=json.loads(suspension['diagnostics_json'])
    if set(codes)!=set(state.get('diagnostics',[])):
        raise ValueError('Suspension and preserved state disagree')
    result=diagnose(codes)
    identity=fingerprint({'session_id':session_id,'suspension_ms':suspension['suspended_ms']})
    result.update(request_id=identity,session_id=session_id,variant_id=session['variant_id'],
      created_ms=clock_ms,suspension_ms=suspension['suspended_ms'],
      paper_snapshot_available_ms=snapshot['available_ms'],
      evidence_refs=['paper_suspensions:'+session_id,'paper_snapshots:'+snapshot['snapshot_id']],
      observed_paper_metrics=json.loads(snapshot['metrics_json']),
      input_fingerprint=fingerprint({'diagnostics':codes,'snapshot_id':snapshot['snapshot_id']}))
    store.connection.execute('insert or ignore into paper_adaptation_requests values(?,?,?,?,?)',
        (identity,session_id,clock_ms,suspension['suspended_ms'],canonical(result)))
    return json.loads(store.connection.execute('select diagnostic_json from paper_adaptation_requests where session_id=?',(session_id,)).fetchone()[0])


def recover(store,*,clock_ms,max_requests=8):
    """Recover missed diagnosis commits; no archive reads, model calls or rearm."""
    if type(max_requests) is not int or not 1<=max_requests<=16:raise ValueError('Bounded recovery required')
    if not store.connection.execute("select 1 from sqlite_master where name='paper_suspensions'").fetchone():return []
    initialize(store);store.connection.commit()
    sessions=store.connection.execute('select p.session_id from paper_suspensions p '
      'left join paper_adaptation_requests a on a.session_id=p.session_id '
      'where a.session_id is null and p.suspended_ms<=? order by p.suspended_ms,p.session_id limit ?',
      (clock_ms,max_requests)).fetchall()
    outputs=[]
    for row in sessions:
        try:
            store.connection.execute('begin immediate')
            outputs.append(record(store,row[0],clock_ms=clock_ms));store.connection.commit()
        except ValueError as exc:
            store.connection.rollback()
            outputs.append({'session_id':row[0],'state':'paper_evidence_required','reason':str(exc),
                            'model_calls_authorized':0})
        except BaseException:store.connection.rollback();raise
    return outputs
