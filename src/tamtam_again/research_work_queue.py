"""Persistent, idempotent queue for bounded research follow-up work."""
from __future__ import annotations

from .engine import canonical, fingerprint
from .validation import now_ms

STATUSES = {'ready', 'waiting_data', 'waiting_deadline', 'budget_exhausted',
            'technical_required', 'completed'}


def initialize(store):
    store.connection.execute('''create table if not exists research_work_queue (
        work_id text primary key, source_kind text not null, source_id text not null,
        input_fingerprint text not null, status text not null, reason text not null,
        wake_at_ms integer, payload_json text not null, outcome_json text,
        created_ms integer not null, updated_ms integer not null,
        unique(source_kind,source_id,input_fingerprint))''')
    store.connection.execute('create index if not exists idx_research_work_queue_due on research_work_queue(status,wake_at_ms,created_ms)')
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
    store.connection.commit()
    return dict(store.connection.execute('select * from research_work_queue where work_id=?',(work_id,)).fetchone()), True


def set_status(store, work_id, status, reason='', *, wake_at_ms=None, outcome=None, clock_ms=None):
    if status not in STATUSES: raise ValueError('Unknown research queue status')
    store.connection.execute('update research_work_queue set status=?,reason=?,wake_at_ms=?,outcome_json=?,updated_ms=? where work_id=?',
        (status,reason,wake_at_ms,canonical(outcome) if outcome is not None else None,
         now_ms() if clock_ms is None else clock_ms,work_id))
    store.connection.commit()


def tick(store, *, clock_ms=None, max_jobs=1):
    """Advance due deadlines and process ready deterministic report references.

    Does not call a model. A ready observation report is converted into a compact,
    hash-addressed work record; model activation remains a separate authorized step.
    """
    initialize(store)
    clock = now_ms() if clock_ms is None else clock_ms
    store.connection.execute("update research_work_queue set status='ready',reason='deadline reached',updated_ms=? where status='waiting_deadline' and wake_at_ms<=?",(clock,clock))
    rows=store.connection.execute("select * from research_work_queue where status='ready' and source_kind='eth_observation_report' order by created_ms,work_id limit ?",(max_jobs,)).fetchall()
    advanced=[]
    for row in rows:
        payload=__import__('json').loads(row['payload_json'])
        if row['source_kind']=='eth_observation_report':
            if not store.connection.execute("select 1 from sqlite_master where type='table' and name='eth_observation_reports'").fetchone():
                set_status(store,row['work_id'],'waiting_data','observation report store is not initialized',clock_ms=clock)
                advanced.append({'work_id':row['work_id'],'status':'waiting_data'}); continue
            report=store.connection.execute('select report_json from eth_observation_reports where protocol_id=? and stage=?',(payload['protocol_id'],payload['stage'])).fetchone()
            if not report:
                set_status(store,row['work_id'],'waiting_data','referenced report is not yet persisted',clock_ms=clock)
                advanced.append({'work_id':row['work_id'],'status':'waiting_data'}); continue
            value=__import__('json').loads(report[0])
            compact={'version':'eth-observation-review-packet-v1','protocol_id':payload['protocol_id'],'stage':payload['stage'],
                'report_fingerprint':fingerprint(value),'decision':value.get('decision'),'coverage':value.get('coverage'),
                'summary':value.get('summary'),'next_action':value.get('next_action') or value.get('route',{}).get('next_action'),
                'evidence_refs':value.get('evidence_refs',[])}
            set_status(store,row['work_id'],'completed','deterministic packet prepared; human/research policy review required',
                outcome=compact,clock_ms=clock)
            advanced.append({'work_id':row['work_id'],'status':'completed','packet_fingerprint':fingerprint(compact)})
        else:
            set_status(store,row['work_id'],'technical_required','no deterministic handler registered for source kind',clock_ms=clock)
            advanced.append({'work_id':row['work_id'],'status':'technical_required'})
    store.connection.commit()
    return {'advanced':advanced,'pending':store.connection.execute("select count(*) from research_work_queue where status in ('ready','waiting_data','waiting_deadline')").fetchone()[0],
        'model_calls':0}
