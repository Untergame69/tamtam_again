"""Persistent, idempotent queue for bounded research follow-up work."""
from __future__ import annotations

import json

from .engine import canonical, fingerprint
from .validation import now_ms

STATUSES = {'ready', 'packet_prepared', 'analysis_ready', 'analysis_running',
            'analysis_skipped', 'analysis_completed', 'resolution_ready',
            'waiting_data', 'waiting_deadline', 'budget_exhausted',
            'technical_required', 'completed'}


def initialize(store):
    store.connection.execute('''create table if not exists research_work_queue (
        work_id text primary key, source_kind text not null, source_id text not null,
        input_fingerprint text not null, status text not null, reason text not null,
        wake_at_ms integer, payload_json text not null, outcome_json text,
        created_ms integer not null, updated_ms integer not null,
        unique(source_kind,source_id,input_fingerprint))''')
    store.connection.execute('create index if not exists idx_research_work_queue_due on research_work_queue(status,wake_at_ms,created_ms)')
    store.connection.execute('''create table if not exists research_work_queue_events (
        event_id text primary key, work_id text not null, status text not null,
        reason text not null, details_json text not null, created_ms integer not null,
        foreign key(work_id) references research_work_queue(work_id))''')
    store.connection.commit()


def enqueue(store, source_kind, source_id, payload, *, status='ready', reason='', wake_at_ms=None, clock_ms=None):
    if status not in STATUSES: raise ValueError('Unknown research queue status')
    initialize(store)
    body = canonical(payload)
    digest = fingerprint(payload)
    old = store.connection.execute('select * from research_work_queue where source_kind=? and source_id=? and input_fingerprint=?',
        (source_kind, source_id, digest)).fetchone()
    if old: return dict(old), False
    clock = now_ms() if clock_ms is None else clock_ms
    work_id = fingerprint({'source_kind':source_kind,'source_id':source_id,'input_fingerprint':digest})
    store.connection.execute('insert into research_work_queue values(?,?,?,?,?,?,?,?,?,?,?)',
        (work_id,source_kind,source_id,digest,status,reason,wake_at_ms,body,None,clock,clock))
    event={'work_id':work_id,'status':status,'reason':reason,'payload':payload}
    store.connection.execute('insert or ignore into research_work_queue_events values(?,?,?,?,?,?)',
        (fingerprint(event),work_id,status,reason,canonical({'payload':payload}),clock))
    store.connection.commit()
    return dict(store.connection.execute('select * from research_work_queue where work_id=?',(work_id,)).fetchone()), True


def set_status(store, work_id, status, reason='', *, wake_at_ms=None, outcome=None, payload=None, clock_ms=None):
    if status not in STATUSES: raise ValueError('Unknown research queue status')
    old=store.connection.execute('select status,reason from research_work_queue where work_id=?',(work_id,)).fetchone()
    clock=now_ms() if clock_ms is None else clock_ms
    store.connection.execute('update research_work_queue set status=?,reason=?,wake_at_ms=?,outcome_json=coalesce(?,outcome_json),payload_json=coalesce(?,payload_json),updated_ms=? where work_id=?',
        (status,reason,wake_at_ms,canonical(outcome) if outcome is not None else None,
         canonical(payload) if payload is not None else None,clock,work_id))
    if old and (old['status']!=status or old['reason']!=reason):
        event={'work_id':work_id,'status':status,'reason':reason,'outcome':outcome,'payload':payload}
        store.connection.execute('insert or ignore into research_work_queue_events values(?,?,?,?,?,?)',
            (fingerprint(event),work_id,status,reason,canonical({'outcome':outcome,'payload':payload}),clock))
    store.connection.commit()


def eth_report_semantic_fingerprint(report):
    from .eth_report_projection import semantic_fingerprint
    return semantic_fingerprint(report)


def eth_report_work_payload(protocol_id, stage, report):
    """Use report semantics for queue identity; keep serialization metadata out."""
    return {'protocol_id':protocol_id,'stage':stage,
        'semantic_fingerprint':eth_report_semantic_fingerprint(report)}


def tick(store, *, clock_ms=None, max_jobs=1, pilot_policy=None):
    """Prepare justified report tasks and reconcile analysis/local-resolution state."""
    initialize(store); clock=now_ms() if clock_ms is None else clock_ms
    store.connection.execute("update research_work_queue set status='ready',reason='deadline reached',updated_ms=? where status='waiting_deadline' and wake_at_ms<=?",(clock,clock))
    advanced=[]
    rows=store.connection.execute("select * from research_work_queue where status='ready' and source_kind='eth_observation_report' order by created_ms,work_id limit ?",(max_jobs,)).fetchall()
    for row in rows:
        payload=json.loads(row['payload_json'])
        report_row=store.connection.execute('select input_fingerprint,report_json from eth_observation_reports where protocol_id=? and stage=?',(payload['protocol_id'],payload['stage'])).fetchone() if store.connection.execute("select 1 from sqlite_master where type='table' and name='eth_observation_reports'").fetchone() else None
        if not report_row:
            set_status(store,row['work_id'],'waiting_data','final report is not durably persisted',clock_ms=clock); advanced.append({'work_id':row['work_id'],'status':'waiting_data'}); continue
        value=json.loads(report_row['report_json']); semantic=eth_report_semantic_fingerprint(value)
        if report_row['input_fingerprint']!=value.get('input_fingerprint'):
            set_status(store,row['work_id'],'technical_required','persisted report fingerprint does not match its payload',clock_ms=clock)
            advanced.append({'work_id':row['work_id'],'status':'technical_required'}); continue
        if payload.get('semantic_fingerprint') and payload['semantic_fingerprint']!=semantic:
            set_status(store,row['work_id'],'technical_required','queued report fingerprint no longer matches persisted evidence',clock_ms=clock); advanced.append({'work_id':row['work_id'],'status':'technical_required'}); continue
        decision=value.get('decision')
        from .eth_report_projection import project as project_eth_report, size_proof as report_size_proof
        projection=project_eth_report(value)
        compact={'version':'eth-observation-review-packet-v3','evidence_projection':projection,
            'next_action':value.get('route',{}).get('next_action')}
        compact['projection_size_proof']=report_size_proof(value,projection,
            serialized_report_chars=len(report_row['report_json']))
        compact['projection_size_proof']['queue_projection_packet_chars']=0
        while True:
            measured=len(canonical(compact))
            if compact['projection_size_proof']['queue_projection_packet_chars']==measured: break
            compact['projection_size_proof']['queue_projection_packet_chars']=measured
        if decision=='data_insufficient':
            outcome={**compact,'analysis':'skipped','reason':'deterministic report says data_insufficient',
                'next_action':'retain the result as insufficient; do not call IA or extend the observation'}
            set_status(store,row['work_id'],'analysis_skipped',outcome['reason'],outcome=outcome,clock_ms=clock)
            advanced.append({'work_id':row['work_id'],'status':'analysis_skipped'}); continue
        if pilot_policy is None:
            set_status(store,row['work_id'],'technical_required','dedicated v2 pilot policy was not supplied to scheduler',outcome=compact,clock_ms=clock)
            advanced.append({'work_id':row['work_id'],'status':'technical_required'}); continue
        try:
            from .population_pilot import seal_final_eth_observation
            sealed=seal_final_eth_observation(store,pilot_policy,value,semantic_fingerprint=semantic,clock_ms=clock)
        except Exception as exc:
            set_status(store,row['work_id'],'technical_required',type(exc).__name__+': '+str(exc)[:300],outcome=compact,clock_ms=clock)
            advanced.append({'work_id':row['work_id'],'status':'technical_required'}); continue
        state=sealed.get('status')
        if state=='analysis_ready':
            payload.update(request_id=sealed['request_id'],semantic_fingerprint=semantic)
            outcome={**compact,'analysis':'authorized_task_sealed','request_id':sealed['request_id'],
                'packet_fingerprint':sealed['packet_fingerprint'],'model_calls':0,
                'packet_chars':sealed.get('packet_chars'),'packet_char_limit':sealed.get('packet_char_limit'),
                'proposal_prompt_chars':sealed.get('proposal_prompt_chars'),'prompt_char_limit':sealed.get('prompt_char_limit'),
                'size_proof':sealed.get('size_proof',compact['projection_size_proof'])}
            outcome['queue_outcome_chars']=0
            while True:
                measured=len(canonical(outcome))
                if outcome['queue_outcome_chars']==measured: break
                outcome['queue_outcome_chars']=measured
            set_status(store,row['work_id'],'packet_prepared','evidence packet sealed and linked to the v2 allowance',payload=payload,outcome=outcome,clock_ms=clock)
            set_status(store,row['work_id'],'analysis_ready','new prospective evidence sealed for v2 runtime',payload=payload,outcome=outcome,clock_ms=clock)
        elif state=='budget_exhausted':
            set_status(store,row['work_id'],'budget_exhausted',sealed.get('reason','v2 allowance exhausted'),outcome=compact,clock_ms=clock)
        elif state in {'analysis_skipped','unchanged_no_inference'}:
            set_status(store,row['work_id'],'analysis_skipped',sealed.get('reason','no new useful question'),outcome={**compact,'analysis':'skipped','reason':sealed.get('reason'),'next_action':sealed.get('next_action')},clock_ms=clock)
        elif state=='waiting_data':
            set_status(store,row['work_id'],'waiting_data',sealed.get('reason','authorized source data unavailable'),outcome=compact,clock_ms=clock)
        else:
            set_status(store,row['work_id'],'technical_required',sealed.get('reason',state or 'task sealing failed'),outcome=compact,clock_ms=clock)
        advanced.append({'work_id':row['work_id'],'status':state,'request_id':sealed.get('request_id')})

    has_jobs=store.connection.execute("select 1 from sqlite_master where type='table' and name='population_research_jobs'").fetchone()
    linked=store.connection.execute("select * from research_work_queue where source_kind='eth_observation_report' and status in ('analysis_ready','analysis_running','resolution_ready')").fetchall() if has_jobs else []
    for row in linked:
        payload=json.loads(row['payload_json']); request_id=payload.get('request_id')
        job=store.connection.execute('select status,result_json from population_research_jobs where request_id=?',(request_id,)).fetchone() if request_id else None
        if not job:
            set_status(store,row['work_id'],'technical_required','linked v2 research job is absent',clock_ms=clock); continue
        if job['status']=='sealed': continue
        if job['status']=='running':
            set_status(store,row['work_id'],'analysis_running','existing runtime owns the linked job',clock_ms=clock); continue
        if job['status'] in {'suspended','interrupted'}:
            set_status(store,row['work_id'],'technical_required','runtime '+job['status']+'; no automatic retry',clock_ms=clock); continue
        from .population_routing import route
        routed=route(store,request_id)
        result=json.loads(job['result_json'] or '{}')
        outcome={'request_id':request_id,'analysis_status':job['status'],'decision':result.get('decision'),
            'route':routed,'next_action':routed.get('next_action'),'promotion_authorized':False}
        state=routed.get('state')
        if state=='local_archive_analysis_required':
            set_status(store,row['work_id'],'resolution_ready','deterministic local resolution is ready',outcome=outcome,clock_ms=clock)
        elif state=='local_archive_analysis_complete':
            set_status(store,row['work_id'],'completed','analysis and local resolution persisted',outcome=outcome,clock_ms=clock)
        elif state in {'needs_data','local_archive_data_required'}:
            set_status(store,row['work_id'],'waiting_data',routed.get('next_action','analysis requested data'),outcome=outcome,clock_ms=clock)
        elif state in {'technical_required','technical_task_required'}:
            set_status(store,row['work_id'],'technical_required',routed.get('next_action','technical intervention required'),outcome=outcome,clock_ms=clock)
        else:
            set_status(store,row['work_id'],'analysis_completed','analysis decision persisted; follow-up route recorded',outcome=outcome,clock_ms=clock)
    store.connection.commit()
    pending=store.connection.execute("select count(*) from research_work_queue where status in ('ready','analysis_ready','analysis_running','resolution_ready','waiting_data','waiting_deadline')").fetchone()[0]
    return {'advanced':advanced,'pending':pending,'model_calls':0}
