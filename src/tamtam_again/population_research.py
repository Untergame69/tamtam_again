"""Independent bounded population research registry; sealing never calls a model."""
from .engine import canonical, fingerprint, number
from .population_packet import packet_for_account
from .validation import now_ms


def initialize(store):
    store.connection.execute('create table if not exists population_research_jobs '
        '(request_id text primary key,network text not null,address text not null,'
        'input_fingerprint text not null,packet_json text not null,policy_json text not null,'
        'created_ms integer not null,status text not null,reserved_cost_usd text,'
        'actual_cost_usd text,result_json text,usage_json text,updated_ms integer not null,'
        'unique(network,address,input_fingerprint))')


def validate_policy(policy):
    if policy.get('version')!='population-research-v1':raise ValueError('Versioned population research policy required')
    for key in ('max_requests','max_packet_chars','minimum_interval_ms','timeout_seconds','max_output_tokens','max_request_age_ms'):
        if type(policy.get(key)) is not int or policy[key]<1:raise ValueError('Positive population research budget required: '+key)
    if not isinstance(policy.get('model'),str) or not policy['model'].strip():raise ValueError('Explicit isolated model required')
    if 'max_prompt_chars' in policy and (type(policy['max_prompt_chars']) is not int or policy['max_prompt_chars']<policy['max_packet_chars']):
        raise ValueError('Prompt budget must accommodate the population packet')
    mode=policy.get('usage_mode','pay_as_you_go')
    if mode=='subscription':
        if 'call_reservation_usd' in policy:
            raise ValueError('Subscription policies must not contain a fictive USD reservation')
        for key in ('max_model_calls','max_input_tokens_per_call','max_total_input_tokens',
                    'max_total_output_tokens','max_total_duration_ms'):
            if type(policy.get(key)) is not int or policy[key]<1:
                raise ValueError('Positive subscription usage limit required: '+key)
        if policy['max_model_calls']>2 or policy['max_total_input_tokens']<policy['max_input_tokens_per_call']:
            raise ValueError('Subscription usage limits exceed this runtime contract')
    elif mode=='pay_as_you_go':
        cost=number(policy.get('call_reservation_usd'))
        if not cost.is_finite() or cost<=0:raise ValueError('Finite positive call reservation required')
    else:
        raise ValueError('Explicit supported usage mode required')


def seal(store,network,address,policy,*,clock_ms=None):
    validate_policy(policy)
    clock=now_ms() if clock_ms is None else clock_ms
    result=packet_for_account(store,network,address,as_of_ms=clock,max_chars=policy['max_packet_chars'])
    if result['status']!='packet_ready':return result
    packet=result['packet'];address=packet['address']
    if not (packet['observations'].get('activity',{}).get('observed_unique_fills') or 0):
        return {'status':'needs_data','reason':'no observed activity to motivate descriptive inference'}
    if not packet['observations']['activity'].get('observed_fill_content_fingerprint'):
        return {'status':'needs_data','reason':'fill content fingerprint absent; equal counts do not establish unchanged input'}
    initialize(store);store.connection.commit()
    store.connection.execute('begin immediate')
    try:
        digest=packet['research_input_fingerprint']
        prior=store.connection.execute('select request_id from population_research_jobs where network=? and address=? and input_fingerprint=?',
            (network,address,digest)).fetchone()
        if prior:
            store.connection.commit();return {'status':'unchanged_no_inference','request_id':prior[0]}
        from .research_jobs import request_count
        if request_count(store)>=policy['max_requests']:
            store.connection.commit();return {'status':'budget_exhausted'}
        latest=store.connection.execute('select max(created_ms) from population_research_jobs where network=? and address=?',
            (network,address)).fetchone()[0]
        if latest is not None and clock-latest<policy['minimum_interval_ms']:
            store.connection.commit();return {'status':'waiting','wake_ms':latest+policy['minimum_interval_ms']}
        identity=fingerprint({'network':network,'address':address,'input_fingerprint':digest})
        store.connection.execute('insert into population_research_jobs values(?,?,?,?,?,?,?, ?,NULL,NULL,NULL,NULL,?)',
            (identity,network,address,digest,canonical(packet),canonical(policy),clock,'sealed',clock))
        store.connection.commit()
        return {'status':'sealed','request_id':identity,'model_calls':0}
    except BaseException:
        store.connection.rollback();raise
