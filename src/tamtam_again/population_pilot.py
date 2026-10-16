"""Dedicated, non-renewing research allowance scoped to the three reviewed candidates."""
import json
import hashlib
from copy import deepcopy

from .engine import canonical, fingerprint
from .validation import now_ms


def validate_policy(policy):
    if policy.get('version') not in {'research-loop-pilot-v1','research-loop-pilot-v2'} or policy.get('renewal') is not False:
        raise ValueError('Explicit non-renewing research pilot policy required')
    if policy.get('usage_mode') != 'subscription':
        raise ValueError('This pilot is subscription-only')
    admission = policy.get('admission', {})
    if (admission.get('source') != 'historical-selection-20261012-f1-f4'
            or admission.get('required_status') != 'credible_deep_dive_candidate'
            or admission.get('cutoff_ms') != policy.get('evidence', {}).get('max_archive_cutoff_ms')
            or not admission.get('owner_authorization') or 'does not grant' not in admission['owner_authorization']):
        raise ValueError('Explicit research-only admission authorization and cutoff required')
    limits = policy.get('pilot_limits', {})
    if policy.get('authorization_scope') == 'single_task':
        expected = {'max_tasks': 1, 'max_calls': 2, 'max_input_tokens': 160000,
                    'max_output_tokens': 10000, 'max_duration_ms': 240000}
        if policy.get('pilot_id') != 'eth-mechanism-followup-20261014-v1':
            raise ValueError('Single-task authorization must use its dedicated immutable allowance id')
        candidates = policy.get('selection', [])
        if (len(candidates) != 1 or candidates[0].get('candidate') != '67f7'
                or candidates[0].get('address','').lower() != '0x67f7aa8fb95c47e6ea9c517b623e0701cbf9d9ba'
                or candidates[0].get('descriptive_markets') != ['ETH']):
            raise ValueError('Single-task authorization is bound to 67f7 and its ETH evidence only')
    else:
        expected = {'max_tasks': 3, 'max_calls': 6, 'max_input_tokens': 480000,
                    'max_output_tokens': 30000, 'max_duration_ms': 720000}
    if limits != expected:
        raise ValueError('Pilot allowance differs from the specifically authorized ceilings')
    task = policy.get('task_policy', {})
    if (task.get('version') != 'population-research-v1' or task.get('usage_mode') != 'subscription'
            or task.get('max_model_calls') != 2 or task.get('timeout_seconds') != 120
            or task.get('max_output_tokens') != 5000 or task.get('max_input_tokens_per_call') != 80000
            or task.get('max_total_input_tokens') != 160000
            or task.get('max_total_output_tokens') != 10000
            or task.get('max_total_duration_ms') != 240000):
        raise ValueError('Per-call and per-task research limits must remain bounded')
    candidates = policy.get('selection', [])
    if policy.get('authorization_scope') != 'single_task':
        if len(candidates) != 3 or {c.get('candidate') for c in candidates} != {'a880', '67f7', 'be504'}:
            raise ValueError('Pilot scope must remain the three preselected candidates')
        if len({c.get('address', '').lower() for c in candidates}) != 3:
            raise ValueError('Distinct candidate addresses required')


def initialize(store, policy):
    validate_policy(policy)
    store.connection.execute('create table if not exists population_research_pilot_allowances '
        '(pilot_id text primary key,policy_fingerprint text not null,policy_json text not null,created_ms integer not null)')
    store.connection.execute('create table if not exists population_research_pilot_tasks '
        '(request_id text primary key,pilot_id text not null,candidate text not null,address text not null,'
        'packet_fingerprint text not null,authorized_ms integer not null,state text not null,'
        'foreign key(pilot_id) references population_research_pilot_allowances(pilot_id))')
    store.connection.execute('create table if not exists population_research_pilot_calls '
        '(request_id text not null,call_index integer not null,pilot_id text not null,state text not null,'
        'reserved_ms integer not null,max_input_tokens integer not null,max_output_tokens integer not null,'
        'max_duration_ms integer not null,actual_input_tokens integer,actual_output_tokens integer,'
        'actual_duration_ms integer,provider_usage_json text,primary key(request_id,call_index))')
    task_schema=store.connection.execute("select sql from sqlite_master where type='table' and name='population_research_pilot_tasks'").fetchone()[0]
    if 'unique(pilot_id,candidate)' in task_schema.replace(' ','').lower():
        # Earlier pilot drafts allowed one task per candidate. Preserve all rows
        # while permitting a new task for the same candidate only after a new
        # input fingerprint and within the same non-renewing task allowance.
        store.connection.execute('begin immediate')
        store.connection.execute('alter table population_research_pilot_tasks rename to population_research_pilot_tasks_v0')
        store.connection.execute('create table population_research_pilot_tasks '
            '(request_id text primary key,pilot_id text not null,candidate text not null,address text not null,'
            'packet_fingerprint text not null,authorized_ms integer not null,state text not null,'
            'foreign key(pilot_id) references population_research_pilot_allowances(pilot_id))')
        store.connection.execute('insert into population_research_pilot_tasks select * from population_research_pilot_tasks_v0')
        store.connection.execute('drop table population_research_pilot_tasks_v0')
        store.connection.commit()
    existing = store.connection.execute('select policy_fingerprint from population_research_pilot_allowances where pilot_id=?',
        (policy['pilot_id'],)).fetchone()
    fp = fingerprint(policy)
    if existing and existing[0] != fp:
        raise ValueError('Pilot id already bound to a different immutable policy')
    if not existing:
        store.connection.execute('insert into population_research_pilot_allowances values(?,?,?,?)',
            (policy['pilot_id'], fp, canonical(policy), now_ms()))
    store.connection.commit()


def authorize_task(store, policy, *, request_id, candidate, address, packet_fingerprint_value, authorized_ms=None):
    initialize(store, policy)
    selected = {item['candidate']: item for item in policy['selection']}
    item = selected.get(candidate)
    if not item or item['address'].lower() != address.lower():
        raise ValueError('Candidate is outside the exact authorized pilot scope')
    if not request_id or not packet_fingerprint_value:
        raise ValueError('Sealed task and packet fingerprint required')
    stamp = now_ms() if authorized_ms is None else authorized_ms
    old = store.connection.execute('select * from population_research_pilot_tasks where request_id=?',
        (request_id,)).fetchone()
    if old:
        if (old['pilot_id'] == policy['pilot_id'] and old['candidate'] == candidate
                and old['address'] == address.lower() and old['packet_fingerprint'] == packet_fingerprint_value):
            return {'status': 'already_authorized', 'request_id': request_id}
        raise ValueError('Task already has a different or consumed pilot authorization')
    count = store.connection.execute('select count(*) from population_research_pilot_tasks where pilot_id=?',
        (policy['pilot_id'],)).fetchone()[0]
    if count >= policy['pilot_limits']['max_tasks']:
        raise ValueError('Dedicated pilot task allowance exhausted')
    job = store.connection.execute('select status,packet_json from population_research_jobs where request_id=?',
        (request_id,)).fetchone()
    if not job or job['status'] != 'sealed':
        raise ValueError('Only an exact sealed population research task can be authorized')
    packet = json.loads(job['packet_json'])
    if packet.get('fingerprint') != packet_fingerprint_value:
        raise ValueError('Packet fingerprint does not match the sealed task')
    store.connection.execute('insert into population_research_pilot_tasks values(?,?,?,?,?,?,?)',
        (request_id, policy['pilot_id'], candidate, address.lower(), packet_fingerprint_value, stamp, 'authorized'))
    store.connection.commit()
    return {'status': 'authorized', 'request_id': request_id, 'candidate': candidate}


def reserve_call(store, request_id, call_index, policy):
    """Consume a worst-case reservation before provider entry; failed calls stay consumed."""
    initialize(store, policy)
    task = store.connection.execute('select pilot_id,state from population_research_pilot_tasks where request_id=?',
        (request_id,)).fetchone()
    if not task or task['pilot_id'] != policy['pilot_id'] or task['state'] not in {'authorized','needs_critique'}:
        raise ValueError('Task lacks an active task-specific pilot authorization')
    per_task = policy['task_policy']
    if not 1 <= call_index <= per_task['max_model_calls']:
        raise ValueError('Per-task model call ceiling exhausted')
    old = store.connection.execute('select 1 from population_research_pilot_calls where request_id=? and call_index=?',
        (request_id, call_index)).fetchone()
    if old:
        raise ValueError('Pilot call reservation already consumed; no retry')
    limits = policy['pilot_limits']
    rows = store.connection.execute('select count(*),coalesce(sum(max_input_tokens),0),'
        'coalesce(sum(max_output_tokens),0),coalesce(sum(max_duration_ms),0) '
        'from population_research_pilot_calls where pilot_id=?', (policy['pilot_id'],)).fetchone()
    reserve = (per_task['max_input_tokens_per_call'], per_task['max_output_tokens'],
               per_task['timeout_seconds'] * 1000)
    if rows[0] + 1 > limits['max_calls']:
        raise ValueError('Dedicated pilot call allowance exhausted')
    if rows[1] + reserve[0] > limits['max_input_tokens']:
        raise ValueError('Dedicated pilot input-token reservation exhausted')
    if rows[2] + reserve[1] > limits['max_output_tokens']:
        raise ValueError('Dedicated pilot output-token reservation exhausted')
    if rows[3] + reserve[2] > limits['max_duration_ms']:
        raise ValueError('Dedicated pilot duration reservation exhausted')
    store.connection.execute('insert into population_research_pilot_calls '
        '(request_id,call_index,pilot_id,state,reserved_ms,max_input_tokens,max_output_tokens,max_duration_ms) '
        'values(?,?,?,\'reserved\',?,?,?,?)',
        (request_id, call_index, policy['pilot_id'], now_ms(), *reserve))
    store.connection.commit()
    return {'max_input_tokens': reserve[0], 'max_output_tokens': reserve[1], 'max_duration_ms': reserve[2]}


def record_provider_response(store, request_id, call_index, response):
    usage = response.get('usage') if isinstance(response, dict) else None
    if not isinstance(usage, dict):
        store.connection.execute('update population_research_pilot_calls set state=\'response_received\',provider_usage_json=? '
            'where request_id=? and call_index=?', (canonical({'usage': 'unknown'}), request_id, call_index))
    else:
        fields = (usage.get('input_tokens'), usage.get('output_tokens'), response.get('duration_ms'))
        normalized = tuple(value if type(value) is int and value >= 0 else None for value in fields)
        store.connection.execute('update population_research_pilot_calls set state=\'response_received\', '
            'actual_input_tokens=?,actual_output_tokens=?,actual_duration_ms=?,provider_usage_json=? '
            'where request_id=? and call_index=?', (*normalized, canonical(usage), request_id, call_index))
    store.connection.commit()


def mark_call_state(store, request_id, call_index, state):
    allowed={'usage_validated','result_validated','structurally_revalidated','response_rejected','interrupted'}
    if state not in allowed:raise ValueError('Known pilot inference attempt state required')
    store.connection.execute('update population_research_pilot_calls set state=? where request_id=? and call_index=?',
        (state,request_id,call_index))
    store.connection.commit()


def finish_task(store, request_id, state):
    store.connection.execute('update population_research_pilot_tasks set state=? where request_id=?',
        (state, request_id))
    store.connection.commit()


def adapt_required_data_objects_v1(response):
    """Losslessly project structured missing-observation objects to string contract fields."""
    if not isinstance(response, dict) or response.get('decision') != 'hypothesis':
        raise ValueError('Adapter v1 applies only to a hypothesis response')
    adapted = deepcopy(response)
    hypothesis = adapted.get('hypothesis')
    items = hypothesis.get('required_data') if isinstance(hypothesis, dict) else None
    required_keys = {'index', 'observation', 'source', 'decision_use'}
    if not isinstance(items, list) or not items or any(not isinstance(item, dict) or set(item) != required_keys
            or not isinstance(item.get('observation'), str) or not item['observation'].strip()
            or not isinstance(item.get('source'), str) or not item['source'].strip()
            or not isinstance(item.get('decision_use'), str) or not item['decision_use'].strip()
            or type(item.get('index')) is not int for item in items):
        raise ValueError('Response does not have the exact unambiguous required-data object shape')
    if [item['index'] for item in items] != list(range(len(items))):
        raise ValueError('Required-data object indices are not a lossless ordered sequence')
    hypothesis['required_data'] = [item['observation'] for item in items]
    hypothesis['required_data_context_v1'] = deepcopy(items)
    return adapted


def adapt_eth_evidence_paths_v1(response, packet):
    """Project the exact ETH packet-section paths used by the provider to source refs.

    This adapter does not edit or add claims. Policy/text-only paths are recorded as
    omitted; any other unknown path fails closed. The caller preserves source JSON.
    """
    if not isinstance(response, dict) or response.get('decision') != 'hypothesis':
        raise ValueError('Evidence-path adapter applies only to a hypothesis response')
    adapted = deepcopy(response)
    hypothesis = adapted.get('hypothesis')
    refs = hypothesis.get('evidence_refs') if isinstance(hypothesis, dict) else None
    if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) for ref in refs):
        raise ValueError('Evidence refs must be a nonempty list of strings')
    allowed = set(packet.get('evidence_refs', []))
    observations = packet.get('observations', {})
    details = observations.get('market_execution_detail_v1', {})
    descriptive = observations.get('descriptive_history_v1', {})
    mechanisms = observations.get('market_mechanisms', [])
    # The validator explicitly admits these references from each mechanism row,
    # even when its source archive predates the newer sha256 suffix convention.
    for item in mechanisms:
        if isinstance(item, dict):
            allowed.update(ref for ref in item.get('evidence_refs', []) if isinstance(ref, str))
    projection = {
        'observations.market_execution_detail_v1.ETH.execution_activity':
            details.get('ETH', {}).get('evidence_refs', []),
        'observations.market_execution_detail_v1.ETH.position_path':
            details.get('ETH', {}).get('evidence_refs', []),
        'observations.descriptive_history_v1.coverage': descriptive.get('evidence_refs', []),
        'observations.market_mechanisms': [ref for item in mechanisms if isinstance(item, dict)
            for ref in item.get('evidence_refs', [])],
    }
    metadata_only = {'observations.market_execution_detail_v1.ETH.interpretation_limits',
        'pilot_research', 'research_contract'}
    output, mapped, omitted = [], [], []
    for ref in refs:
        if ref in allowed:
            candidates = [ref]
        elif ref in projection:
            candidates = projection[ref]
            if not candidates:
                raise ValueError('Known evidence path has no source references: ' + ref)
            mapped.append({'source_path': ref, 'source_refs': candidates})
        elif ref in metadata_only:
            omitted.append(ref)
            continue
        else:
            raise ValueError('Unrecognized evidence path; adaptation is ambiguous: ' + ref)
        for candidate in candidates:
            if not isinstance(candidate, str) or candidate not in allowed:
                raise ValueError('Evidence path resolved outside the sealed packet allowlist')
            if candidate not in output:
                output.append(candidate)
    if not output:
        raise ValueError('Evidence-path projection produced no verifiable source refs')
    hypothesis['evidence_refs'] = output
    return adapted, {'mapped_paths': mapped, 'omitted_metadata_paths': omitted,
        'source_ref_count': len(refs), 'adapted_ref_count': len(output)}


def _eth_execution_local_resolution(store, packet):
    """Resolve a deterministic-calculation request from the sealed cutoff only."""
    from .population_descriptive import prepare_inventory_execution_association
    source_detail = packet.get('observations', {}).get('market_execution_detail_v1', {}).get('ETH')
    if not isinstance(source_detail, dict):
        raise ValueError('Sealed packet does not contain ETH execution detail')
    cutoff_ms = source_detail.get('cutoff_ms')
    if type(cutoff_ms) is not int:
        raise ValueError('Sealed ETH detail lacks its integer archive cutoff')
    result = prepare_inventory_execution_association(store, packet['network'], packet['address'],
        cutoff_ms=cutoff_ms, market='ETH')
    if result['source_detail_fingerprint'] != source_detail.get('detail_fingerprint'):
        raise ValueError('Local calculation differs from the sealed ETH source detail')
    return {'version': 'population-eth-inventory-execution-resolution-v1',
        'state': 'partially_resolved_from_authorized_local_archives',
        'artifact': 'docs/continuous-research/POPULATION-67F7-ETH-INVENTORY-ASSOCIATION-20261014.json',
        'analysis_fingerprint': result['analysis_fingerprint'],
        'source_detail_fingerprint': result['source_detail_fingerprint'],
        'cutoff_ms': result['cutoff_ms'], 'coverage': result['coverage'],
        'inventory_magnitude_quantile_cuts': result['inventory_magnitude_quantile_cuts'],
        'by_position_side_inventory_bucket_and_crossed': result['by_position_side_inventory_bucket_and_crossed'],
        'by_segment_utc_day_inventory_side_bucket_and_crossed': result['by_segment_utc_day_inventory_side_bucket_and_crossed'],
        'interpretation_limits': result['interpretation_limits'],
        'data_requests': [
            {'required_data_index': 0, 'classification': 'missing_calculation',
                'state': 'resolved_offline_without_new_links',
                'finding': 'For long and short positions, the share of executed quantity reducing inventory is higher in Q4 than Q1 for maker and taker fills. Reversals are split at zero. This is an execution association, not evidence of order placement or causal intent.'},
            {'required_data_index': 1, 'classification': 'future_accessible_observation',
                'state': 'not_present_in_authorized_cutoff_archives',
                'finding': 'Prospective receipt-time fills and independent ETH position snapshots are not established in the sealed archives. Historical fills do not prove complete continuity or availability.'}],
        'model_calls_for_resolution': 0}


def _attach_critique_to_local_resolution(local_resolution, critique):
    """Retain resolved local work while appending the persisted provider decision."""
    result = deepcopy(local_resolution) if isinstance(local_resolution, dict) else {
        'version': 'population-pilot-local-resolution-v1',
        'state': 'no_local_calculation_attached', 'model_calls': 0}
    diagnostic = critique.get('diagnostic', {}) if isinstance(critique, dict) else {}
    testability = diagnostic.get('testability', {}) if isinstance(diagnostic, dict) else {}
    requirements = testability.get('required_observations', []) if isinstance(testability, dict) else []
    result['provider_decision'] = critique.get('decision')
    result['provider_diagnostic'] = diagnostic
    result['prospective_observations_requested'] = requirements
    result['provider_wake'] = deepcopy(critique.get('wake', {}))
    return result


def revalidate_and_critique(store, policy, request_id):
    """Apply only the versioned structural adapter, then use the task's remaining critique call."""
    from .population_runtime import (STATES, _initialize_call_artifacts, _advance_call,
        _reserve_call, _safe_response_parts, call, parse_response, validate_response, verify)
    job = store.connection.execute('select * from population_research_jobs where request_id=?',
        (request_id,)).fetchone()
    auth = store.connection.execute('select pilot_id,state from population_research_pilot_tasks where request_id=?',
        (request_id,)).fetchone()
    if not job or job['status'] != 'suspended' or not auth or auth['pilot_id'] != policy['pilot_id']:
        return {'status': 'unchanged_no_inference', 'request_id': request_id}
    prior = json.loads(job['result_json'] or '{}')
    diagnostic = prior.get('validation_diagnostic') or {}
    if diagnostic.get('code') not in {'required_data_invalid', 'evidence_reference_invalid'}:
        return {'status': 'unchanged_no_inference', 'request_id': request_id,
            'reason': 'no registered deterministic adapter for the recorded rejection'}
    if auth['state'] != 'suspended':
        return {'status': 'unchanged_no_inference', 'request_id': request_id,
            'reason': 'task is not in the expected rejected-response state'}
    raw = prior.get('raw_proposal')
    if not isinstance(raw, str):
        return {'status': 'suspended', 'request_id': request_id, 'reason': 'rejected raw proposal is absent'}
    source = parse_response(raw)
    packet = json.loads(job['packet_json'])
    adapted = source
    projection_details = None
    if diagnostic.get('code') == 'required_data_invalid':
        adapted = adapt_required_data_objects_v1(adapted)
    elif diagnostic.get('code') == 'evidence_reference_invalid':
        adapted, projection_details = adapt_eth_evidence_paths_v1(adapted, packet)
        # This task's provider used two exact, structured missing-data records. Their
        # narrative remains intact; the runtime receives the contract's string list.
        if all(isinstance(item, dict) for item in adapted.get('hypothesis', {}).get('required_data', [])):
            items = adapted['hypothesis']['required_data']
            keys = {'required_data_index', 'classification', 'observation', 'scope',
                'decision_use', 'acquisition'}
            if any(set(item) != keys or type(item['required_data_index']) is not int
                    or not all(isinstance(item[k], str) and item[k].strip()
                        for k in keys - {'required_data_index'}) for item in items):
                raise ValueError('Structured required-data records are not losslessly projectable')
            if [item['required_data_index'] for item in items] != list(range(len(items))):
                raise ValueError('Structured required-data indices are not consecutive')
            adapted['hypothesis']['required_data'] = [item['observation'] for item in items]
            adapted['hypothesis']['required_data_context_v1'] = deepcopy(items)
    validate_response(adapted, packet, request_id=request_id)
    local_resolution = _eth_execution_local_resolution(store, packet) if projection_details is not None else None
    source_sha = hashlib.sha256(raw.encode()).hexdigest()
    mark_call_state(store,request_id,1,'structurally_revalidated')
    store.connection.execute('create table if not exists population_research_adaptation_artifacts '
        '(request_id text not null,adapter_version text not null,source_response_sha256 text not null,'
        'source_response_json text not null,adapted_response_json text not null,validation_state text not null,'
        'created_ms integer not null,primary key(request_id,adapter_version))')
    adapter_version = ('eth-evidence-path-projection-v1' if projection_details is not None
        else 'required-data-object-projection-v1')
    artifact = store.connection.execute('select source_response_sha256,adapted_response_json from '
        'population_research_adaptation_artifacts where request_id=? and adapter_version=?',
        (request_id, adapter_version)).fetchone()
    if artifact:
        if artifact['source_response_sha256'] != source_sha or artifact['adapted_response_json'] != canonical(adapted):
            raise ValueError('Structural adaptation artifact identity changed')
        return {'status': 'already_adapted', 'request_id': request_id,
            'adapter_version': adapter_version}
    store.connection.execute('insert into population_research_adaptation_artifacts values(?,?,?,?,?,?,?)',
        (request_id, adapter_version, source_sha, canonical(source),
         canonical(adapted), 'revalidated', now_ms()))
    prior['structural_adaptation'] = {'adapter_version': adapter_version,
        'source_response_sha256': source_sha, 'validation_state': 'revalidated',
        'projection_details': projection_details, 'adapted_proposal': adapted}
    if local_resolution is not None:
        prior['local_resolution'] = local_resolution
    store.connection.execute('update population_research_jobs set result_json=?,updated_ms=? where request_id=? and status=\'suspended\'',
        (canonical(prior), now_ms(), request_id))
    store.connection.execute("update population_research_pilot_tasks set state='needs_critique' where request_id=? and state='suspended'",
        (request_id,))
    store.connection.commit()
    try:
        verify(policy['task_policy']['model'])
        store.connection.execute("update population_research_jobs set status='running',updated_ms=? where request_id=? and status='suspended'",
            (now_ms(), request_id));store.connection.commit()
        _initialize_call_artifacts(store)
        existing_usage=json.loads(job['usage_json'] or '[]')
        call_index=len(existing_usage)+1
        if call_index != 2:
            raise ValueError('Critique is the only remaining call after one proposal; no task retry')
        task_policy=policy['task_policy']
        if (sum(int(u.get('input_tokens') or 0) for u in existing_usage)+task_policy['max_input_tokens_per_call']>task_policy['max_total_input_tokens']
                or sum(int(u.get('output_tokens') or 0) for u in existing_usage)+task_policy['max_output_tokens']>task_policy['max_total_output_tokens']
                or sum(int(u.get('duration_ms') or 0) for u in existing_usage)+task_policy['timeout_seconds']*1000>task_policy['max_total_duration_ms']):
            raise ValueError('Per-task aggregate subscription ceiling prevents the single critique; no retry')
        reserve_call(store, request_id, call_index, policy)
        _reserve_call(store, 'population', request_id, call_index)
        captured=False
        def capture(response):
            nonlocal captured
            record_provider_response(store, request_id, call_index, response)
            body, metadata = _safe_response_parts(response)
            _advance_call(store, 'population', request_id, call_index, 'response_received',
                time_field='response_received_ms', response_json=body, metadata_json=metadata)
            captured=True
        prompt=('Review only causal consistency and testability. This is the same preserved proposal '
            'after a deterministic, versioned structural projection; do not rewrite its content. No tools. '
            'Do not claim profitability or authorize strategy promotion. Return JSON with decision '
            'consistent|needs_data|non_identifiable|unsupported_mechanism|reject, diagnostic and wake. '
            'Treat prospective lifecycle, continuous order/quote timing and fee schedule observations as required '
            'where the packet does not contain them. A deterministic local calculation is available as a '
            'separate post-proposal addendum: it measures ETH pre-fill inventory side and quartile against '
            'maker/taker executed quantities, reversal close/open splits, fees, day and segment. Treat it as '
            'descriptive archive evidence only, with one local chain rupture and censored endpoints; it does '
            'not establish causality or order placement. Resolve the proposal\'s missing_calculation request '
            'from this addendum and do not request it again. Local calculation addendum:\n'+
            canonical(local_resolution or {})+'\nPacket:\n'+canonical(packet)+'\nProposal:\n'+canonical(adapted))
        try:
            critique_raw, measured=call(policy['task_policy'], prompt, on_response=capture)
        except Exception as exc:
            failed=prior
            failed.update(error_type=type(exc).__name__, validation_diagnostic=getattr(exc,'diagnostic',
                {'stage':'provider_call','code':'critique_call_failed','field':'critique','observed':type(exc).__name__,
                 'limit':'one critique only; no retry'}))
            store.connection.execute("update population_research_jobs set status='suspended',result_json=?,usage_json=?,updated_ms=? where request_id=? and status='running'",
                (canonical(failed),canonical(existing_usage),now_ms(),request_id));store.connection.commit()
            _advance_call(store,'population',request_id,call_index,'interrupted' if not captured else 'rejected',
                diagnostic_json=canonical(failed['validation_diagnostic']))
            finish_task(store, request_id, 'suspended')
            return {'status':'suspended','request_id':request_id,'validation_diagnostic':failed['validation_diagnostic']}
        usage=existing_usage+[measured]
        mark_call_state(store,request_id,call_index,'usage_validated')
        _advance_call(store,'population',request_id,call_index,'response_validated',time_field='response_validated_ms')
        critique=parse_response(critique_raw)
        if not critique.get('diagnostic') or not isinstance(critique.get('wake'),dict) or critique.get('decision') not in STATES|{'consistent'}:
            raise ValueError('Critique response did not satisfy the existing decision contract')
        mark_call_state(store,request_id,call_index,'result_validated')
        _advance_call(store,'population',request_id,call_index,'result_validated',time_field='result_validated_ms')
        adaptation = deepcopy(prior.get('structural_adaptation', {}))
        adaptation.update({'critique_call_index': call_index,
            'original_rejection_preserved': True, 'critique_source_response_sha256': source_sha})
        prior.update(proposal=adapted,critique=critique,structural_adaptation=adaptation,
            promotion_authorized=False,profitability_proven=False)
        state='hypothesis_recorded' if critique['decision']=='consistent' else critique['decision']
        if state=='needs_data' and isinstance(critique.get('diagnostic'),dict):
            prior['local_resolution'] = _attach_critique_to_local_resolution(
                local_resolution or prior.get('local_resolution'), critique)
        from .research import usage_accounting
        accounting=usage_accounting(usage);prior['usage_accounting']=accounting
        store.connection.execute('update population_research_jobs set status=?,result_json=?,usage_json=?,actual_cost_usd=NULL,updated_ms=? where request_id=? and status=\'running\'',
            (state,canonical(prior),canonical(usage),now_ms(),request_id));store.connection.commit()
        finish_task(store, request_id, state)
        from .population_routing import route
        routed=route(store,request_id)
        if routed.get('state')=='needs_data' and state=='hypothesis_recorded':
            from .research_needs import register
            local=register(store,request_id)
        elif routed.get('state')=='needs_data':
            local=prior.get('local_resolution')
        else:local=None
        return {'status':state,'request_id':request_id,'route':routed,'local_resolution':local,
            'adapter_version':adapter_version,'usage_accounting':accounting}
    except Exception as exc:
        diagnostic=getattr(exc,'diagnostic',{'stage':'adapted_critique','code':'deterministic_adaptation_or_critique_failed',
            'field':'adapted_response','observed':type(exc).__name__,'limit':'preserve artifacts; no retry'})
        prior['adapted_critique_diagnostic']=diagnostic
        store.connection.execute("update population_research_jobs set status='suspended',result_json=?,updated_ms=? where request_id=? and status in ('running','suspended')",
            (canonical(prior),now_ms(),request_id));store.connection.commit()
        finish_task(store,request_id,'suspended')
        return {'status':'suspended','request_id':request_id,'diagnostic':diagnostic}


def report(store, policy):
    initialize(store, policy)
    p = policy['pilot_id']
    calls = store.connection.execute('select count(*),coalesce(sum(max_input_tokens),0),'
        'coalesce(sum(max_output_tokens),0),coalesce(sum(max_duration_ms),0),'
        'coalesce(sum(actual_input_tokens),0),coalesce(sum(actual_output_tokens),0),'
        'coalesce(sum(actual_duration_ms),0) from population_research_pilot_calls where pilot_id=?', (p,)).fetchone()
    tasks = store.connection.execute('select candidate,request_id,state from population_research_pilot_tasks '
        'where pilot_id=? order by authorized_ms,candidate', (p,)).fetchall()
    return {'pilot_id': p, 'tasks': [dict(row) for row in tasks],
        'calls_reserved': calls[0], 'input_tokens_reserved': calls[1], 'output_tokens_reserved': calls[2],
        'duration_ms_reserved': calls[3], 'input_tokens_reported': calls[4],
        'output_tokens_reported': calls[5], 'duration_ms_reported': calls[6],
        'non_renewing': True}


def _historically_qualified(store, network, address, cutoff):
    from .research_memory import authorized_account_history
    if not authorized_account_history(store, network, address, cutoff):
        return False, 'account history is outside the authorized archive scope'
    row = store.connection.execute('select status,decision_json from population_historical_decisions '
        'where network=? and address=? and as_of_ms<=? order by as_of_ms desc,decision_id desc limit 1',
        (network, address.lower(), cutoff)).fetchone()
    if not row:
        return False, 'no reviewed historical decision is available'
    try:
        decision = json.loads(row['decision_json'])
    except (TypeError, ValueError):
        return False, 'historical decision payload is invalid'
    # User explicitly authorized this isolated descriptive-research exception.
    # Preserve the false economic-validation state as evidence; never mutate the
    # shared gate or imply strategy/experiment eligibility.
    if row['status'] != 'credible_deep_dive_candidate':
        return False, 'candidate is not one of the archived historical prescreens'
    return True, 'authorized historical prescreen verified; economic validation remains false'


def _seal_candidate(store, policy, candidate, *, clock_ms=None):
    from .population_packet import packet_for_authorized_pilot
    from .population_descriptive import prepare_pilot_packet
    initialize(store, policy)
    item = next(row for row in policy['selection'] if row['candidate'] == candidate)
    clock = now_ms() if clock_ms is None else clock_ms
    cutoff = policy['admission']['cutoff_ms']
    admitted, reason = _historically_qualified(store, policy['network'], item['address'], cutoff)
    if not admitted:
        return {'status': 'candidate_ineligible', 'candidate': candidate, 'reason': reason}
    task_policy = policy['task_policy']
    base = packet_for_authorized_pilot(store, policy['network'], item['address'],
        as_of_ms=cutoff, max_chars=task_policy['max_packet_chars'],
        allowed_addresses=[entry['address'] for entry in policy['selection']])
    if base.get('status') != 'packet_ready':
        return {'status': base.get('status', 'needs_data'), 'candidate': candidate,
            'reason': base.get('reason', 'authorized descriptive packet not ready')}
    packet = base['packet']
    packet = prepare_pilot_packet(store, packet, candidate=candidate, item=item,
        pilot_id=policy['pilot_id'], policy_version=policy['version'], cutoff_ms=cutoff)
    packet_chars = len(canonical(packet))
    if packet_chars > task_policy['max_packet_chars']:
        return {'status': 'packet_too_large', 'candidate': candidate,
            'reason': 'versioned descriptive evidence exceeds the existing packet character limit',
            'required_chars': packet_chars, 'max_chars': task_policy['max_packet_chars']}
    activity = packet.get('observations', {}).get('activity', {})
    if not activity.get('observed_unique_fills'):
        return {'status': 'needs_data', 'candidate': candidate,
            'reason': 'no observed activity to motivate descriptive inference'}
    if not activity.get('observed_fill_content_fingerprint'):
        return {'status': 'needs_data', 'candidate': candidate,
            'reason': 'fill content fingerprint absent; equal counts do not establish unchanged input'}
    digest = packet['research_input_fingerprint']
    # Policy/schema version changes do not constitute new evidence. When a prior
    # task asked the same question over the same frozen cutoff and fill content,
    # do not reseal it merely because a newer packet adapter serialized it anew.
    prior = store.connection.execute('select j.request_id,j.status,j.packet_json from population_research_jobs j '
        'join population_research_pilot_tasks t using(request_id) where j.network=? and j.address=? '
        'and t.candidate=? order by t.authorized_ms desc',
        (policy['network'],item['address'].lower(),candidate)).fetchall()
    current_activity=activity.get('observed_fill_content_fingerprint')
    for old in prior:
        try: old_packet=json.loads(old['packet_json'])
        except (TypeError,ValueError): continue
        old_activity=old_packet.get('observations',{}).get('activity',{}).get('observed_fill_content_fingerprint')
        old_question=old_packet.get('pilot_research',{}).get('question')
        if (old_packet.get('available_ms')==packet.get('available_ms') and old_activity==current_activity
                and old_question==item.get('question')):
            return {'status':'unchanged_no_inference','candidate':candidate,'request_id':old['request_id'],
                'source_status':old['status'],'reason':'same question, archive cutoff and fill-content fingerprint already processed'}
    existing = store.connection.execute('select request_id,status from population_research_jobs '
        'where network=? and address=? and input_fingerprint=?',
        (policy['network'], item['address'].lower(), digest)).fetchone()
    if existing:
        return {'status': 'unchanged_no_inference', 'candidate': candidate,
            'request_id': existing['request_id'], 'source_status': existing['status']}
    used_tasks = store.connection.execute('select count(*) from population_research_pilot_tasks where pilot_id=?',
        (policy['pilot_id'],)).fetchone()[0]
    if used_tasks >= policy['pilot_limits']['max_tasks']:
        return {'status': 'task_allowance_exhausted', 'candidate': candidate,
            'reason': 'non-renewing pilot task ceiling already consumed'}
    request_id = fingerprint({'network': policy['network'], 'address': item['address'].lower(),
        'research_input_fingerprint': digest, 'pilot_id': policy['pilot_id']})
    from .population_research import initialize as init_jobs
    init_jobs(store)
    store.connection.execute('begin immediate')
    try:
        store.connection.execute('insert into population_research_jobs '
            '(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,updated_ms) '
            'values(?,?,?,?,?,?,? ,\'sealed\',?)',
            (request_id, policy['network'], item['address'].lower(), digest, canonical(packet),
             canonical(task_policy), clock, clock))
        store.connection.commit()
    except BaseException:
        store.connection.rollback()
        raise
    auth = authorize_task(store, policy, request_id=request_id, candidate=candidate,
        address=item['address'], packet_fingerprint_value=packet['fingerprint'], authorized_ms=clock)
    return {'status': 'sealed', 'candidate': candidate, 'request_id': request_id,
        'packet_fingerprint': packet['fingerprint'], 'authorization': auth, 'model_calls': 0}


def seal_final_eth_observation(store, policy, report, *, semantic_fingerprint, clock_ms=None):
    """Seal a v2 task only from the persisted final 67f7/ETH report and its evidence."""
    from copy import deepcopy
    from .population_packet import packet_for_authorized_pilot
    from .population_descriptive import prepare_pilot_packet
    from .population_research import initialize as initialize_jobs
    validate_policy(policy); initialize(store, policy)
    if policy['pilot_id'] != 'research-loop-pilot-20261014-v2':
        raise ValueError('Final ETH follow-up must use its dedicated v2 allowance')
    protocol_id='67f7-eth-public-observation-24h-20261014-v1'
    report_row=store.connection.execute("select input_fingerprint,report_json from eth_observation_reports where protocol_id=? and stage='final_24h'",(protocol_id,)).fetchone()
    run=store.connection.execute('select status,protocol_json from eth_observation_runs where protocol_id=?',(protocol_id,)).fetchone()
    if not report_row or not run or run['status']!='finalised':
        return {'status':'waiting_deadline','reason':'final report is not durably published'}
    persisted=json.loads(report_row['report_json'])
    if persisted != report or persisted.get('stage')!='final_24h':
        raise ValueError('Supplied report differs from the persisted final report')
    if report_row['input_fingerprint']!=report.get('input_fingerprint'):
        raise ValueError('Persisted report input fingerprint differs from its payload')
    protocol=json.loads(run['protocol_json'])
    item=next(x for x in policy['selection'] if x['candidate']=='67f7')
    if (protocol.get('network')!=policy['network'] or protocol.get('address','').lower()!=item['address'].lower()
            or protocol.get('market')!='ETH'):
        raise ValueError('Final report protocol identity is outside the v2 67f7 authorization')
    admitted,reason=_historically_qualified(store,policy['network'],item['address'],policy['admission']['cutoff_ms'])
    if not admitted: return {'status':'technical_required','reason':reason}
    allowed_decisions={'signal_exploratory_favorable','signal_exploratory_unfavorable','indeterminate'}
    if report.get('decision')=='data_insufficient':
        return {'status':'analysis_skipped','reason':'deterministic report classifies the observation as data_insufficient',
            'next_action':report.get('route',{}).get('next_action')}
    if report.get('decision') not in allowed_decisions:
        return {'status':'analysis_skipped','reason':'no recognized new prospective question is justified by the report decision',
            'next_action':report.get('route',{}).get('next_action')}
    if semantic_fingerprint != eth_report_semantic_fingerprint(report):
        raise ValueError('Final report evidence fingerprint mismatch')
    cutoff=policy['admission']['cutoff_ms'];task_policy=policy['task_policy']
    base=packet_for_authorized_pilot(store,policy['network'],item['address'],as_of_ms=cutoff,
        max_chars=task_policy['max_packet_chars'],allowed_addresses=[x['address'] for x in policy['selection']])
    if base.get('status')!='packet_ready': return {'status':'waiting_data','reason':base.get('reason','historical packet unavailable')}
    question=('Does the prospective ETH window for 67f7 show a different 60-second directional markout '
        'for observed taker executions reducing inventory versus opening or inverting it, and do coverage '
        'and market context support or contradict the historical association? Treat future prices only as '
        'outcome measurements, not as historical signals; do not infer unobserved order-placement decisions.')
    research_item=deepcopy(item);research_item['question']=question
    packet=prepare_pilot_packet(store,base['packet'],candidate='67f7',item=research_item,
        pilot_id=policy['pilot_id'],policy_version=policy['version'],cutoff_ms=cutoff)
    semantic=eth_report_semantic_fingerprint(report)
    reference=f"eth_observation_reports:{protocol_id}:final_24h#sha256:{semantic}"
    from .eth_report_projection import project as project_eth_report, size_proof as report_size_proof
    eth_projection=project_eth_report(report)
    packet['observations']['prospective_eth_observation_v1']=eth_projection
    if reference not in packet['evidence_refs']:
        packet['evidence_refs'].append(reference)
    packet['available_ms']=max(packet.get('available_ms',0),report.get('generated_at_ms',0))
    packet['research_contract']['purpose']='compare the authorized historical description with a completed prospective observation; no paper, order, profitability or strategy approval'
    packet['research_input_fingerprint']=fingerprint({'base':packet['research_input_fingerprint'],
        'question':question,'prospective_eth_report':semantic})
    packet.pop('fingerprint',None);packet['fingerprint']=fingerprint(packet)
    packet_chars=len(canonical(packet))
    source_size=report_size_proof(report,eth_projection,serialized_report_chars=len(report_row['report_json']))
    if packet_chars>task_policy['max_packet_chars']:
        return {'status':'technical_required','reason':'prospective report packet exceeds the existing character limit',
            'packet_chars':packet_chars,'packet_char_limit':task_policy['max_packet_chars'],
            'size_proof':source_size}
    digest=packet['research_input_fingerprint']
    request_id=fingerprint({'pilot_id':policy['pilot_id'],'protocol_id':protocol_id,
        'semantic_report_fingerprint':semantic,'research_input_fingerprint':digest})
    from .population_runtime import build_proposal_prompt
    prompt_chars=len(build_proposal_prompt(packet,request_id))
    if prompt_chars>task_policy['max_prompt_chars']:
        return {'status':'technical_required','reason':'prospective report prompt exceeds the existing character limit',
            'packet_chars':packet_chars,'packet_char_limit':task_policy['max_packet_chars'],
            'proposal_prompt_chars':prompt_chars,'prompt_char_limit':task_policy['max_prompt_chars'],
            'size_proof':source_size}
    old=store.connection.execute('select request_id,status,packet_json from population_research_jobs where network=? and address=? and input_fingerprint=?',
        (policy['network'],item['address'].lower(),digest)).fetchone()
    if old:
        auth=store.connection.execute('select pilot_id,packet_fingerprint,state from population_research_pilot_tasks where request_id=?',(old['request_id'],)).fetchone()
        if old['status']=='sealed' and not auth and old['request_id']==request_id and json.loads(old['packet_json']).get('fingerprint')==packet['fingerprint']:
            count=store.connection.execute('select count(*) from population_research_pilot_tasks where pilot_id=?',(policy['pilot_id'],)).fetchone()[0]
            if count>=policy['pilot_limits']['max_tasks']:
                return {'status':'budget_exhausted','reason':'v2 task allowance exhausted before authorization recovery'}
            auth_result=authorize_task(store,policy,request_id=request_id,candidate='67f7',address=item['address'],
                packet_fingerprint_value=packet['fingerprint'],authorized_ms=clock_ms)
            return {'status':'analysis_ready','request_id':request_id,'packet_fingerprint':packet['fingerprint'],
                'authorization':auth_result,'model_calls':0,'evidence_ref':reference,'semantic_fingerprint':semantic,
                'packet_chars':packet_chars,'packet_char_limit':task_policy['max_packet_chars'],
                'proposal_prompt_chars':prompt_chars,'prompt_char_limit':task_policy['max_prompt_chars'],
                'size_proof':source_size}
        if auth and auth['pilot_id']==policy['pilot_id'] and auth['packet_fingerprint']==json.loads(old['packet_json']).get('fingerprint'):
            return {'status':'analysis_ready','request_id':old['request_id'],'packet_fingerprint':auth['packet_fingerprint'],
                'authorization':{'status':'already_authorized','request_id':old['request_id']},'model_calls':0,
                'evidence_ref':reference,'semantic_fingerprint':semantic,'packet_chars':packet_chars,
                'packet_char_limit':task_policy['max_packet_chars'],'proposal_prompt_chars':prompt_chars,
                'prompt_char_limit':task_policy['max_prompt_chars'],'size_proof':source_size}
        return {'status':'unchanged_no_inference','request_id':old['request_id'],'source_status':old['status']}
    count=store.connection.execute('select count(*) from population_research_pilot_tasks where pilot_id=?',(policy['pilot_id'],)).fetchone()[0]
    if count>=policy['pilot_limits']['max_tasks']:
        return {'status':'budget_exhausted','reason':'v2 task allowance exhausted'}
    clock=now_ms() if clock_ms is None else clock_ms
    initialize_jobs(store)
    store.connection.execute('begin immediate')
    try:
        store.connection.execute('insert into population_research_jobs '
            '(request_id,network,address,input_fingerprint,packet_json,policy_json,created_ms,status,updated_ms) '
            'values(?,?,?,?,?,?,?,\'sealed\',?)',
            (request_id,policy['network'],item['address'].lower(),digest,canonical(packet),canonical(task_policy),clock,clock))
        store.connection.commit()
    except BaseException:
        store.connection.rollback();raise
    auth=authorize_task(store,policy,request_id=request_id,candidate='67f7',address=item['address'],
        packet_fingerprint_value=packet['fingerprint'],authorized_ms=clock)
    return {'status':'analysis_ready','request_id':request_id,'packet_fingerprint':packet['fingerprint'],
        'authorization':auth,'model_calls':0,'evidence_ref':reference,'semantic_fingerprint':semantic,
        'packet_chars':packet_chars,'packet_char_limit':task_policy['max_packet_chars'],
        'proposal_prompt_chars':prompt_chars,'prompt_char_limit':task_policy['max_prompt_chars'],
        'size_proof':source_size}


def eth_report_semantic_fingerprint(report):
    """Fingerprint only decision-relevant report content, excluding serialization metadata."""
    from .eth_report_projection import semantic_fingerprint
    return semantic_fingerprint(report)


def tick_locked(store, policy, *, dispatch=True, clock_ms=None):
    """One bounded pilot transition, called under the existing research scheduler lock."""
    validate_policy(policy)
    initialize(store, policy)
    clock = now_ms() if clock_ms is None else clock_ms
    existing = store.connection.execute('select t.request_id,t.candidate,j.status from population_research_pilot_tasks t '
        'join population_research_jobs j using(request_id) where t.pilot_id=? order by t.authorized_ms,t.candidate',
        (policy['pilot_id'],)).fetchall()
    by_candidate = {}
    for row in existing:
        by_candidate.setdefault(row['candidate'], []).append(row)

    def execute_sealed(result, *, prior_request_id=None):
        if result.get('status') != 'sealed' or not dispatch:
            return result
        from .population_runtime import execute_job
        from .population_routing import route
        job = store.connection.execute('select * from population_research_jobs where request_id=?',
            (result['request_id'],)).fetchone()
        executed = execute_job(store, result['request_id'], job)
        routed = route(store, result['request_id'])
        plan = None
        if routed.get('state') == 'needs_data':
            terminal = store.connection.execute('select status from population_research_jobs where request_id=?',
                (result['request_id'],)).fetchone()
            # Structured acquisition planning applies only to an accepted
            # hypothesis. A needs_data critique is already a terminal
            # research decision and has no hypothesis payload to register.
            if terminal and terminal['status'] == 'hypothesis_recorded':
                from .research_needs import register
                plan = register(store, result['request_id'], clock_ms=clock)
        result.update(status=executed['status'], route=routed, local_resolution=plan)
        if prior_request_id:
            result['prior_request_id'] = prior_request_id
        return result

    evaluations = []
    for item in sorted(policy['selection'], key=lambda row: row['rank']):
        candidate = item['candidate']
        rows = by_candidate.get(candidate, [])
        latest = rows[-1] if rows else None
        if latest and latest['status'] in {'sealed', 'running'}:
            if latest['status'] == 'running':
                evaluations.append({'candidate': candidate, 'status': 'waiting_runtime',
                    'request_id': latest['request_id']})
                continue
            result = execute_sealed({'status': 'sealed', 'candidate': candidate,
                'request_id': latest['request_id']})
            result['allowance'] = report(store, policy)
            return result

        if latest and latest['status'] == 'suspended':
            saved = store.connection.execute('select result_json from population_research_jobs where request_id=?',
                (latest['request_id'],)).fetchone()
            prior = json.loads(saved[0] or '{}') if saved else {}
            if (prior.get('validation_diagnostic') or {}).get('code') == 'required_data_invalid':
                if not dispatch:
                    evaluations.append({'candidate': candidate, 'status': 'structural_revalidation_ready',
                        'request_id': latest['request_id'], 'model_calls': 0})
                    continue
                result = revalidate_and_critique(store, policy, latest['request_id'])
                result.update(candidate=candidate, allowance=report(store, policy))
                return result

        prior_request_id = latest['request_id'] if latest else None
        if latest:
            from .population_routing import route
            routed = route(store, latest['request_id'])
            if routed.get('state') != 'needs_data':
                # A terminal or technical route belongs to this candidate only.
                evaluations.append({'candidate': candidate, 'status': 'terminal_route',
                    'request_id': latest['request_id'], 'route': routed.get('state')})
                continue

        result = _seal_candidate(store, policy, candidate, clock_ms=clock)
        if result.get('status') in {'unchanged_no_inference', 'needs_data', 'candidate_ineligible'}:
            evaluations.append({'candidate': candidate, 'status': result['status'],
                'request_id': result.get('request_id'), 'reason': result.get('reason')})
            continue
        if result.get('status') == 'sealed':
            result = execute_sealed(result, prior_request_id=prior_request_id)
            result['allowance'] = report(store, policy)
            result['prior_candidates'] = evaluations
            return result
        evaluations.append({'candidate': candidate, 'status': result.get('status'),
            'reason': result.get('reason')})

    return {'status': 'no_admissible_candidate', 'candidate_evaluations': evaluations,
        'allowance': report(store, policy)}
