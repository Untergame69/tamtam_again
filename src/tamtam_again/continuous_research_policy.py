"""Renewable descriptive subscription allowance; historical trial ledgers stay intact.

UTC daily periods bound attempts, not successful results. Reservations are never
refunded, and evidence identity is permanent across period and policy changes.
"""
from .engine import canonical, fingerprint
from .validation import now_ms
from .descriptive_admission import BASE_MIN_FILLS, BASE_MIN_DAYS, DAY_MS

VERSION = 'continuous-descriptive-research-v1'


def validate_policy(policy):
    if (policy.get('version') != VERSION or policy.get('renewal') is not True
            or policy.get('usage_mode') != 'subscription' or policy.get('period_ms') != DAY_MS
            or not isinstance(policy.get('policy_id'), str) or not policy['policy_id']
            or not isinstance(policy.get('network'), str) or not policy['network']):
        raise ValueError('Explicit daily renewable descriptive subscription policy required')
    if any(policy.get(key) is not False for key in ('economic_validation', 'paper_authorized', 'real_orders_authorized')):
        raise ValueError('Continuous descriptive policy cannot authorize promotion or orders')
    limits = policy.get('period_limits', {})
    keys = {'max_tasks', 'max_calls', 'max_input_tokens', 'max_output_tokens', 'max_duration_ms'}
    if set(limits) != keys or any(type(v) is not int or v <= 0 for v in limits.values()):
        raise ValueError('Finite positive per-period task/call/token/time ceilings required')
    task = policy.get('task_policy', {})
    expected = {'version': 'population-research-v1', 'usage_mode': 'subscription',
        'max_model_calls': 2, 'timeout_seconds': 120, 'max_output_tokens': 5000,
        'max_input_tokens_per_call': 80000, 'max_total_input_tokens': 160000,
        'max_total_output_tokens': 10000, 'max_total_duration_ms': 240000}
    if any(task.get(k) != v for k, v in expected.items()) or 'call_reservation_usd' in task:
        raise ValueError('Existing bounded subscription runtime limits required')
    for key in ('max_requests', 'max_packet_chars', 'max_prompt_chars', 'minimum_interval_ms', 'max_request_age_ms'):
        if type(task.get(key)) is not int or task[key] <= 0:
            raise ValueError('Finite task dispatch limits required')
    if not isinstance(task.get('model'), str) or not task['model']:
        raise ValueError('Explicit model required')


def initialize(store, policy):
    validate_policy(policy)
    conn = store.connection
    conn.execute('create table if not exists continuous_research_allowances '
        '(policy_id text primary key,policy_fingerprint text not null,policy_json text not null,created_ms integer not null)')
    conn.execute('create table if not exists continuous_research_tasks '
        '(request_id text primary key,policy_id text not null,network text not null,candidate text not null,'
        'address text not null,market text not null,packet_fingerprint text not null,semantic_fingerprint text not null,'
        'period_start_ms integer not null,authorized_ms integer not null,state text not null,'
        'unique(network,address,market,semantic_fingerprint))')
    conn.execute('create table if not exists continuous_research_calls '
        '(request_id text not null,call_index integer not null,policy_id text not null,period_start_ms integer not null,'
        'state text not null,reserved_ms integer not null,max_input_tokens integer not null,max_output_tokens integer not null,'
        'max_duration_ms integer not null,actual_input_tokens integer,actual_output_tokens integer,'
        'actual_duration_ms integer,provider_usage_json text,primary key(request_id,call_index))')
    old = conn.execute('select policy_fingerprint from continuous_research_allowances where policy_id=?', (policy['policy_id'],)).fetchone()
    if old and old[0] != fingerprint(policy):
        raise ValueError('Continuous allowance id already bound to a different immutable policy')
    if not old:
        conn.execute('insert into continuous_research_allowances values(?,?,?,?)',
            (policy['policy_id'], fingerprint(policy), canonical(policy), now_ms()))
    conn.commit()


def authorize_task(store, policy, *, request_id, candidate, address, market,
                   packet_fingerprint_value, semantic_fingerprint_value, authorized_ms=None, sealed_job=None):
    initialize(store, policy)
    stamp = now_ms() if authorized_ms is None else authorized_ms
    if type(stamp) is not int or stamp < 0 or not all(isinstance(x, str) and x for x in
            (request_id, candidate, address, market, packet_fingerprint_value, semantic_fingerprint_value)):
        raise ValueError('Exact scoped sealed task and semantic evidence fingerprint required')
    period = stamp // DAY_MS * DAY_MS
    conn = store.connection
    conn.execute('begin immediate')
    try:
        old = conn.execute('select * from continuous_research_tasks where request_id=?', (request_id,)).fetchone()
        if old:
            if (old['policy_id'], old['address'], old['market'], old['packet_fingerprint'], old['semantic_fingerprint']) != (
                    policy['policy_id'], address.lower(), market, packet_fingerprint_value, semantic_fingerprint_value):
                raise ValueError('Task already has a different immutable authorization')
            conn.commit()
            return {'status': 'already_authorized', 'request_id': request_id}
        if conn.execute('select 1 from continuous_research_tasks where network=? and address=? and market=? and semantic_fingerprint=?',
                (policy['network'], address.lower(), market, semantic_fingerprint_value)).fetchone():
            raise ValueError('Unchanged semantic evidence already consumed; no inference')
        used = conn.execute('select count(*) from continuous_research_tasks where policy_id=? and period_start_ms=?',
            (policy['policy_id'], period)).fetchone()[0]
        if used >= policy['period_limits']['max_tasks']:
            raise ValueError('Daily continuous task allowance exhausted')
        if sealed_job is not None:
            # The population job and its dedicated allowance must commit as one
            # unit. A process death cannot leave an unowned dispatchable job.
            import json
            fields = {'network','address','input_fingerprint','packet_json','policy_json','created_ms'}
            if not isinstance(sealed_job, dict) or set(sealed_job) != fields:
                raise ValueError('Exact sealed job fields required')
            if (sealed_job['network'] != policy['network'] or sealed_job['address'].lower() != address.lower()
                    or not isinstance(sealed_job['input_fingerprint'], str) or not sealed_job['input_fingerprint']
                    or type(sealed_job['created_ms']) is not int or sealed_job['created_ms'] < 0):
                raise ValueError('Sealed job identity differs from authorization')
            packet = json.loads(sealed_job['packet_json'])
            if (not isinstance(packet, dict) or packet.get('fingerprint') != packet_fingerprint_value
                    or fingerprint({k:v for k,v in packet.items() if k != 'fingerprint'}) != packet_fingerprint_value
                    or packet.get('network') != policy['network'] or str(packet.get('address','')).lower() != address.lower()
                    or json.loads(sealed_job['policy_json']) != policy['task_policy']):
                raise ValueError('Sealed packet hash, origin or task policy differs from authorization')
            conn.execute('insert into population_research_jobs '
                '(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,updated_ms) '
                "values(?,?,?,?,?,?,?,'sealed',?)", (request_id, policy['network'], address.lower(),
                sealed_job['input_fingerprint'], sealed_job['packet_json'], sealed_job['policy_json'],
                sealed_job['created_ms'], sealed_job['created_ms']))
        job = conn.execute('select network,address,status,packet_json,policy_json from population_research_jobs where request_id=?', (request_id,)).fetchone()
        if (not job or job['status'] != 'sealed' or job['network'] != policy['network']
                or job['address'].lower() != address.lower()):
            raise ValueError('Exact sealed population task required')
        import json
        packet = json.loads(job['packet_json'])
        if packet.get('fingerprint') != packet_fingerprint_value or json.loads(job['policy_json']) != policy['task_policy']:
            raise ValueError('Sealed packet or task policy differs from allowance')
        conn.execute('insert into continuous_research_tasks values(?,?,?,?,?,?,?,?,?,?,?)',
            (request_id, policy['policy_id'], policy['network'], candidate, address.lower(), market,
             packet_fingerprint_value, semantic_fingerprint_value, period, stamp, 'authorized'))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {'status': 'authorized', 'request_id': request_id, 'period_start_ms': period}


def reserve_call(store, request_id, call_index, policy, *, clock_ms=None):
    """Atomically charge worst-case usage before provider entry, including failures."""
    initialize(store, policy)
    stamp = now_ms() if clock_ms is None else clock_ms
    conn = store.connection
    conn.execute('begin immediate')
    try:
        task = conn.execute('select * from continuous_research_tasks where request_id=?', (request_id,)).fetchone()
        if not task or task['policy_id'] != policy['policy_id'] or task['state'] not in {'authorized', 'needs_critique'}:
            raise ValueError('Active continuous task authorization required')
        if not task['authorized_ms'] <= stamp < task['period_start_ms'] + DAY_MS:
            raise ValueError('Task daily allowance expired; no dispatch in another period')
        per_task = policy['task_policy']
        if type(call_index) is not int or not 1 <= call_index <= per_task['max_model_calls']:
            raise ValueError('Per-task model call ceiling exhausted')
        if conn.execute('select 1 from continuous_research_calls where request_id=? and call_index=?', (request_id, call_index)).fetchone():
            raise ValueError('Call already consumed; no retry')
        if call_index > 1 and not conn.execute('select 1 from continuous_research_calls where request_id=? and call_index=? and state=\'result_validated\'',
                (request_id, call_index - 1)).fetchone():
            raise ValueError('Prior call must be validated before critique')
        rows = conn.execute('select count(*),coalesce(sum(max_input_tokens),0),coalesce(sum(max_output_tokens),0),coalesce(sum(max_duration_ms),0) '
            'from continuous_research_calls where policy_id=? and period_start_ms=?', (policy['policy_id'], task['period_start_ms'])).fetchone()
        reserve = (per_task['max_input_tokens_per_call'], per_task['max_output_tokens'], per_task['timeout_seconds'] * 1000)
        ceilings = policy['period_limits']
        for used, added, key in zip(rows, (1, *reserve), ('max_calls', 'max_input_tokens', 'max_output_tokens', 'max_duration_ms')):
            if used + added > ceilings[key]:
                raise ValueError('Daily continuous ' + key + ' reservation exhausted')
        conn.execute('insert into continuous_research_calls '
            '(request_id,call_index,policy_id,period_start_ms,state,reserved_ms,max_input_tokens,max_output_tokens,max_duration_ms) '
            'values(?,?,?,?,\'reserved\',?,?,?,?)', (request_id, call_index, policy['policy_id'], task['period_start_ms'], stamp, *reserve))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return dict(zip(('max_input_tokens', 'max_output_tokens', 'max_duration_ms'), reserve))


def record_provider_response(store, request_id, call_index, response):
    usage = response.get('usage') if isinstance(response, dict) else None
    fields = (usage.get('input_tokens'), usage.get('output_tokens'), response.get('duration_ms')) if isinstance(usage, dict) else (None, None, None)
    normalized = tuple(x if type(x) is int and x >= 0 else None for x in fields)
    store.connection.execute('update continuous_research_calls set state=\'response_received\',actual_input_tokens=?,actual_output_tokens=?,actual_duration_ms=?,provider_usage_json=? where request_id=? and call_index=?',
        (*normalized, canonical(usage if isinstance(usage, dict) else {'usage': 'unknown'}), request_id, call_index))
    store.connection.commit()


def mark_call_state(store, request_id, call_index, state):
    if state not in {'usage_validated', 'result_validated', 'response_rejected', 'interrupted'}:
        raise ValueError('Known inference attempt state required')
    store.connection.execute('update continuous_research_calls set state=? where request_id=? and call_index=?', (state, request_id, call_index))
    store.connection.commit()


def finish_task(store, request_id, state):
    store.connection.execute('update continuous_research_tasks set state=? where request_id=?', (state, request_id))
    store.connection.commit()


def report(store, policy, *, clock_ms=None):
    initialize(store, policy)
    stamp = now_ms() if clock_ms is None else clock_ms
    period = stamp // DAY_MS * DAY_MS
    rows = store.connection.execute('select count(*),coalesce(sum(max_input_tokens),0),coalesce(sum(max_output_tokens),0),coalesce(sum(max_duration_ms),0) from continuous_research_calls where policy_id=? and period_start_ms=?', (policy['policy_id'], period)).fetchone()
    tasks = store.connection.execute('select request_id,candidate,market,state from continuous_research_tasks where policy_id=? and period_start_ms=? order by authorized_ms,request_id', (policy['policy_id'], period)).fetchall()
    return {'policy_id': policy['policy_id'], 'period_start_ms': period, 'period_end_ms': period + DAY_MS,
        'tasks': [dict(x) for x in tasks], 'calls_reserved': rows[0], 'input_tokens_reserved': rows[1],
        'output_tokens_reserved': rows[2], 'duration_ms_reserved': rows[3], 'renewable': True}


def candidates_for_admission(admission_report, *, market_evidence=None):
    """Use every qualified observation, never the report's short priority queue.

    Optional per-market proof is keyed by (lowercase address, instrument), with
    period_start_ms/cutoff_ms, fills, active_days, coverage dict and evidence_ref.
    Account totals alone never admit a market of a multi-market account.
    """
    proofs = market_evidence or {}
    selected = []
    for row in admission_report['candidate_evaluations']:
        if row.get('disposition') not in {'admissible_descriptive', 'needs_more_evidence'} or not row.get('candidate_id'):
            continue
        scope = row['scope']; address = row['candidate_id'].lower()
        markets = scope.get('markets', [])
        if scope.get('additional_markets_omitted'):
            markets = sorted({*markets, *(m for a, m in proofs if a == address)})
        for market in markets:
            proof = proofs.get((address, market))
            single = scope.get('market_count') == 1 and row['disposition'] == 'admissible_descriptive'
            if not single:
                if not isinstance(proof, dict):
                    continue
                if (proof.get('period_start_ms') != scope['period_start_ms'] or proof.get('cutoff_ms') != scope['cutoff_ms']
                        or type(proof.get('fills')) is not int or proof['fills'] < BASE_MIN_FILLS
                        or type(proof.get('active_days')) is not int or proof['active_days'] < BASE_MIN_DAYS
                        or not isinstance(proof.get('coverage'), dict) or not proof['coverage'] or not proof.get('evidence_ref')):
                    continue
            selected.append({'candidate': row['candidate_alias'] + ':' + market, 'address': address,
                'descriptive_markets': [market], 'market': market,
                'question': (row['research_question'] if single else
                    f'For {market} only, describe observed fills by UTC day and documented coverage; do not attribute account-level PnL or aggregate markets.'),
                'period_start_ms': scope['period_start_ms'], 'cutoff_ms': scope['cutoff_ms'],
                'source_ref': row['source_ref'], 'market_evidence': proof,
                'priority': row.get('priority', 'P3')})
    return sorted(selected, key=lambda x: (x['priority'], x['address'], x['market']))
