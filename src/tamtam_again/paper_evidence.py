"""Immutable paper result observations; caller owns the state transaction."""
from .engine import canonical, fingerprint


def initialize(store):
    store.connection.execute('create table if not exists paper_snapshots '
        '(snapshot_id text primary key,session_id text not null,available_ms integer not null,'
        'observation_cursor integer not null,state_fingerprint text not null,metrics_json text not null)')
    store.connection.execute('create index if not exists idx_paper_snapshot_time '
        'on paper_snapshots(session_id,available_ms)')


def record(store,session_id,available_ms,cursor,state,observed_metrics):
    if type(available_ms) is not int or available_ms<state['last_ms']:
        raise ValueError('Paper snapshot cannot precede its processed information')
    latest=store.connection.execute('select max(available_ms) from paper_snapshots where session_id=?',
        (session_id,)).fetchone()[0]
    if latest is not None and available_ms<latest:
        raise ValueError('Paper snapshots cannot be inserted retrospectively')
    state_fp=fingerprint(state)
    snapshot_id=fingerprint({'session_id':session_id,'available_ms':available_ms,
        'cursor':cursor,'state_fingerprint':state_fp,'metrics':observed_metrics})
    store.connection.execute('insert or ignore into paper_snapshots values(?,?,?,?,?,?)',
        (snapshot_id,session_id,available_ms,cursor,state_fp,canonical(observed_metrics)))
    return snapshot_id
