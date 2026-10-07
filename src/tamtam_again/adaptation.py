"""Immutable population diagnostics; observation changes never authorize promotion."""
from __future__ import annotations
import json
from .discovery import fingerprint


def initialize(store):
    store.connection.execute('create table if not exists adaptation_events '
        '(event_id text primary key,network text not null,address text not null,'
        'available_ms integer not null,input_fingerprint text not null,'
        'payload_json text not null)')
    store.connection.execute('create index if not exists idx_adaptation_address '
        'on adaptation_events(network,address,available_ms)')


def observe_population(store, job, report, available_ms):
    """Caller owns the transaction; emit once per changed descriptive input."""
    if type(available_ms) is not int or available_ms<0:
        raise ValueError('Explicit diagnostic availability required')
    descriptor={'mode':report.get('mode'),'markets':sorted(set(report.get('markets',[]))),
        'activity':report.get('activity',{}).get('observed_unique_fills'),
        'history_states':{k:v.get('pagination_status') for k,v in report.get('histories',{}).items()},
        'performance_status':report.get('performance_status'),
        'reproducibility_status':report.get('reproducibility_status')}
    digest=fingerprint(descriptor)
    prior=store.connection.execute('select input_fingerprint,payload_json,available_ms from adaptation_events '
        'where network=? and address=? order by available_ms desc,rowid desc limit 1',
        (job['network'],job['address'])).fetchone()
    event_id=fingerprint({'source_attempt':job['attempt_id'],'network':job['network'],
                          'address':job['address'],'version':'population-diagnostic-v1'})
    existing=store.connection.execute('select event_id from adaptation_events where event_id=?',
                                      (event_id,)).fetchone()
    if existing:return {'status':'already_recorded','event_id':event_id}
    if prior and available_ms<prior['available_ms']:
        raise ValueError('Cannot insert retrospective adaptation decision')
    if prior and prior['input_fingerprint']==digest:
        return {'status':'unchanged_no_reanalysis','input_fingerprint':digest}
    backlog=any(v!='pagination_exhausted' for v in descriptor['history_states'].values())
    payload={'version':'population-diagnostic-v1','trigger':'new_descriptive_information',
        'descriptor':descriptor,'previous_input_fingerprint':prior['input_fingerprint'] if prior else None,
        'diagnostic':'history backlog remains' if backlog else 'inventory changed; economic qualification remains unproven',
        'state':'needs_data','evidence_refs':['population_attempts:'+job['attempt_id']],
        'wake_condition':{'requires':'new qualified accounting or behavior evidence',
                          'different_from_input_fingerprint':digest},
        'next_action':'continue_bounded_history_collection' if backlog else 'assess_accounting_coverage',
        'ai_call_authorized':False,'promotion_authorized':False}
    store.connection.execute('insert into adaptation_events values(?,?,?,?,?,?)',
        (event_id,job['network'],job['address'],available_ms,digest,json.dumps(payload,sort_keys=True)))
    return {'status':'diagnostic_recorded','event_id':event_id}
