"""Index common typed research blockers without executing model narration.

The existing work queue owns per-subject outcomes. This small index groups
technical work for supervision so repeated blockers increase priority instead
of creating an unlimited list of unrelated incidents. It grants no authority.
"""
import json
import re
from .engine import canonical, fingerprint

KINDS={'structured_observation_contract_required','structured_contract_required',
    'local_resolver_error','verified_adapter_or_provenance_correction','unsupported_mechanism',
    'unsupported_validation_adapter','specification_required','technical_required','technical_task_required'}


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
    wake=assessment.get('wake');wake=wake if isinstance(wake,dict) else {}
    task=assessment.get('technical_task');task=task if isinstance(task,dict) else {}
    proposed=(task.get('kind'),wake.get('kind'),route.get('state'))
    kind=next((v for v in proposed if isinstance(v,str) and v in KINDS),'technical_contract_unspecified')
    # Only machine fields classify the blocker. Free prose is retained on the
    # member and can never become a command, API request or automatic retry.
    code=wake.get('diagnostic_code')
    if not isinstance(code,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',code):code=None
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
    has_queue=store.connection.execute("select 1 from sqlite_master where name='research_work_queue'").fetchone()
    current=(' join research_work_queue q on q.work_id=m.work_id '
        "where q.status='technical_required' and not exists(select 1 from research_work_queue newer "
        'where newer.source_kind=q.source_kind and newer.source_id=q.source_id and '
        '(newer.updated_ms>q.updated_ms or (newer.updated_ms=q.updated_ms and newer.created_ms>q.created_ms) '
        'or (newer.updated_ms=q.updated_ms and newer.created_ms=q.created_ms and newer.rowid>q.rowid))) '
        if has_queue else '')
    rows=store.connection.execute('select b.*,count(distinct m.source_kind||char(0)||m.source_id) affected_subjects, '
        '(select count(distinct h.source_kind||char(0)||h.source_id) from research_technical_blocker_members h '
        'where h.blocker_id=b.blocker_id) historical_affected_subjects '
        'from research_technical_blockers b join research_technical_blocker_members m using(blocker_id) '+current+
        'group by b.blocker_id order by affected_subjects desc,b.first_seen_ms,b.blocker_id limit ?',(limit,))
    return [{**dict(row),'condition':json.loads(row['condition_json'])} for row in rows]
