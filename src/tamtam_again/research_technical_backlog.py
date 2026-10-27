"""Index common typed research blockers without executing model narration.

The existing work queue owns per-subject outcomes. This small index groups
technical work for supervision so repeated blockers increase priority instead
of creating an unlimited list of unrelated incidents. It grants no authority.
"""
import json
from .engine import canonical, fingerprint


def initialize(store):
    store.connection.execute('''create table if not exists research_technical_blockers (
        blocker_id text primary key,kind text not null,condition_json text not null,
        first_seen_ms integer not null,last_seen_ms integer not null)''')
    store.connection.execute('''create table if not exists research_technical_blocker_members (
        blocker_id text not null,source_kind text not null,source_id text not null,
        source_result_fingerprint text not null,work_id text not null,reason text,
        primary key(blocker_id,source_kind,source_id,source_result_fingerprint))''')
    store.connection.commit()


def record(store, *, source_kind, source_id, source_result_fingerprint, work_id,
           assessment, route, clock_ms):
    if assessment.get('state')!='technical':return None
    wake=assessment.get('wake') or {};task=assessment.get('technical_task') or {}
    kind=task.get('kind') or wake.get('kind') or route.get('state') or 'technical_contract_unspecified'
    # Only machine fields classify the blocker. Free prose is retained on the
    # member and can never become a command, API request or automatic retry.
    code=wake.get('diagnostic_code')
    condition={'kind':kind,'diagnostic_code':code,
        'required_proof':'a supported, tested adapter or a verified data/contract correction for each affected subject',
        'original_result_remains_immutable':True,'new_authorized_evidence_required':True,
        'automatic_code_execution':False,'automatic_inference_retry':False}
    blocker_id=fingerprint({'version':'research-technical-blocker-v1','kind':kind,'diagnostic_code':code})
    initialize(store)
    with store.connection:
        store.connection.execute('insert into research_technical_blockers values(?,?,?,?,?) '
            'on conflict(blocker_id) do update set last_seen_ms=max(last_seen_ms,excluded.last_seen_ms)',
            (blocker_id,kind,canonical(condition),clock_ms,clock_ms))
        store.connection.execute('insert or ignore into research_technical_blocker_members values(?,?,?,?,?,?)',
            (blocker_id,source_kind,source_id,source_result_fingerprint,work_id,assessment.get('reason')))
    return {'blocker_id':blocker_id,'kind':kind,'condition':condition}


def priority(store, *, limit=8):
    if type(limit) is not int or not 1<=limit<=64:raise ValueError('Bounded technical backlog limit required')
    if not store.connection.execute("select 1 from sqlite_master where name='research_technical_blockers'").fetchone():return []
    rows=store.connection.execute('select b.*,count(distinct m.source_kind||char(0)||m.source_id) affected_subjects '
        'from research_technical_blockers b join research_technical_blocker_members m using(blocker_id) '
        'group by b.blocker_id order by affected_subjects desc,b.first_seen_ms,b.blocker_id limit ?',(limit,))
    return [{**dict(row),'condition':json.loads(row['condition_json'])} for row in rows]
