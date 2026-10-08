"""Release closed population experiments for development, preserving spent finals.

Only linked population experiments are eligible. Legacy pilots are never released
by this policy. Metadata is sufficient; reserved outcomes are never loaded here.
"""
import json
from datetime import datetime,timezone
from .engine import canonical,fingerprint
from .validation import now_ms

SCHEMA='''
CREATE TABLE IF NOT EXISTS reserve_cycle_policies (
 policy_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,policy_json TEXT NOT NULL,registered_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS research_window_releases (
 plan_id TEXT NOT NULL,stage TEXT NOT NULL,released_ms INTEGER NOT NULL,
 release_kind TEXT NOT NULL,evaluation_ids_json TEXT NOT NULL,policy_json TEXT NOT NULL,
 PRIMARY KEY(plan_id,stage));'''


def validate_policy(policy):
    if policy.get('version')!='reserve-cycle-v1' or not policy.get('policy_id') or not policy.get('justification'):
        raise ValueError('Explicit versioned reserve lifecycle policy required')
    for key in ('grace_ms','abandon_unfinished_after_ms'):
        if type(policy.get(key)) is not int or policy[key]<0:raise ValueError('Explicit nonnegative release delay required')
    if policy['abandon_unfinished_after_ms']<policy['grace_ms']:
        raise ValueError('Abandonment cannot precede release grace')
    if type(policy.get('max_plans_per_tick')) is not int or policy['max_plans_per_tick']<1:
        raise ValueError('Explicit reserve-processing budget required')


def tick(store,policy,*,clock_ms=None):
    validate_policy(policy);clock=now_ms() if clock_ms is None else clock_ms
    if type(clock) is not int or clock<0:raise ValueError('Explicit release clock required')
    store.connection.executescript(SCHEMA)
    digest=fingerprint(policy)
    previous=store.connection.execute('select fingerprint from reserve_cycle_policies where policy_id=?',(policy['policy_id'],)).fetchone()
    if previous and previous[0]!=digest:raise ValueError('Reserve policy identity is immutable')
    store.connection.execute('insert or ignore into reserve_cycle_policies values(?,?,?,?)',
        (policy['policy_id'],digest,canonical(policy),clock));store.connection.commit()
    if not store.connection.execute("select 1 from sqlite_master where name='population_experiment_links'").fetchone():
        return {'released':[],'waiting':[],'legacy_pilots_changed':False}
    # This join admits only plans bound by the reviewed-hypothesis experiment path.
    plans=store.connection.execute('select p.plan_id,p.network,p.address,p.coin,p.plan_json,l.request_id '
        'from validation_plans p join population_experiment_links l using(plan_id) '
        'order by p.created_ms,p.plan_id').fetchall()
    released=[];waiting=[]
    for row in plans:
        plan=json.loads(row['plan_json'])
        if plan.get('population_origin',{}).get('request_id')!=row['request_id']:
            waiting.append({'plan_id':row['plan_id'],'reason':'population origin/link mismatch'});continue
        if store.connection.execute('select count(*) from research_window_releases where plan_id=?',(row['plan_id'],)).fetchone()[0]==2:continue
        if len(released)>=policy['max_plans_per_tick']:break
        end=plan['final']['end_ms']
        if clock<end+policy['grace_ms']:
            waiting.append({'plan_id':row['plan_id'],'reason':'reserve or grace not ended','wake_ms':end+policy['grace_ms']});continue
        store.connection.execute('begin immediate')
        try:
            evaluations=store.connection.execute('select evaluation_id,stage,status from validation_evaluations where plan_id=?',(row['plan_id'],)).fetchall()
            if any(e['status']=='running' for e in evaluations):
                waiting.append({'plan_id':row['plan_id'],'reason':'evaluation still running; no release or inferred interruption'})
                store.connection.rollback();continue
            finals=[e for e in evaluations if e['stage']=='final' and e['status'] in ('passed','failed','error')]
            if not finals and clock<end+policy['abandon_unfinished_after_ms']:
                waiting.append({'plan_id':row['plan_id'],'reason':'await final evaluation or explicit abandonment deadline',
                                'wake_ms':end+policy['abandon_unfinished_after_ms']})
                store.connection.rollback();continue
            if any(not store.connection.execute('select 1 from consumed_holdouts where evaluation_id=? '
                    'and network=? and address=? and coin=? and start_ms=? and end_ms=?',
                    (e['evaluation_id'],row['network'],row['address'],row['coin'],plan['final']['start_ms'],plan['final']['end_ms'])).fetchone() for e in finals):
                waiting.append({'plan_id':row['plan_id'],'reason':'terminal final lacks consumed proof; repair evaluation provenance'})
                store.connection.rollback();continue
            for stage in ('comparison','final'):
                proof=[e['evaluation_id'] for e in evaluations if e['stage']==stage and e['status'] in ('passed','failed','error')]
                kind='evaluated' if proof else 'abandoned_for_development'
                if stage=='final' and not proof:
                    window=plan['final']
                    # A spent development window is not a fabricated evaluation.
                    # The existing holdout overlap gate must still reject its reuse.
                    identity='development-release:'+row['plan_id']+':final'
                    store.connection.execute('insert or ignore into consumed_holdouts values(?,?,?,?,?,?,?)',
                        (identity,row['network'],row['address'],row['coin'],window['start_ms'],window['end_ms'],
                         datetime.fromtimestamp(clock/1000,timezone.utc).isoformat(timespec='milliseconds')))
                store.connection.execute('insert or ignore into research_window_releases values(?,?,?,?,?,?)',
                    (row['plan_id'],stage,clock,kind,canonical(sorted(proof)),canonical(policy)))
            store.connection.commit()
            released.append({'plan_id':row['plan_id'],'released_ms':clock,
                             'final_kind':'evaluated' if finals else 'abandoned_for_development',
                             'original_evaluations_retained':True,'periods_are_virgin':False})
        except BaseException:store.connection.rollback();raise
    return {'released':released,'waiting':waiting,'legacy_pilots_changed':False}


def abandoned_final(store,plan_id,clock_ms):
    if not store.connection.execute("select 1 from sqlite_master where name='research_window_releases'").fetchone():return False
    return bool(store.connection.execute("select 1 from research_window_releases where plan_id=? and stage='final' "
        "and release_kind='abandoned_for_development' and released_ms<=?",(plan_id,clock_ms)).fetchone())
