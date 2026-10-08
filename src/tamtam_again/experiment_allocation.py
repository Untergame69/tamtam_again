"""External, immutable allocation policy for reviewed executable hypotheses."""
from copy import deepcopy
from .engine import canonical, fingerprint, number
from .experiments import compile_family
from .validation import validate_criteria, now_ms


def validate_policy(policy):
    if policy.get('version')!='experiment-allocation-v1' or not policy.get('policy_id') or not policy.get('justification'):
        raise ValueError('Versioned external experiment allocation required')
    if type(policy.get('max_profile_variants')) is not int or not 1<=policy['max_profile_variants']<=64:
        raise ValueError('Explicit allocation variant cap required')
    template=policy.get('plan_template',{})
    if template.get('version')!='population-plan-v1' or not template.get('justification'):
        raise ValueError('Explicit prospective plan template required')
    for key in ('max_plans','comparison_delay_ms','comparison_duration_ms','selection_gap_ms','final_duration_ms'):
        if type(template.get(key)) is not int or template[key]<1:raise ValueError('Positive plan allocation required: '+key)
    if template.get('isolation') not in ('unavailable','separate_principal'):
        raise ValueError('Actual isolation availability required')
    validate_criteria(template['criteria'])
    budget=template.get('budget',{})
    for key in ('max_runs','max_same_input_corrections','max_duration_ms'):
        if type(budget.get(key)) is not int or budget[key]<1:raise ValueError('Positive evaluation allocation required: '+key)
    cost=number(budget.get('max_cost_usd'))
    if not cost.is_finite() or cost<=0:raise ValueError('Explicit evaluation cost cap required')


def bind_policy(store,policy):
    validate_policy(policy)
    store.connection.execute('create table if not exists experiment_allocation_policies '
        '(policy_id text primary key,fingerprint text not null,policy_json text not null,available_ms integer not null)')
    digest=fingerprint(policy)
    row=store.connection.execute('select fingerprint from experiment_allocation_policies where policy_id=?',(policy['policy_id'],)).fetchone()
    if row and row[0]!=digest:raise ValueError('Allocation policy identity is immutable; publish a new policy_id')
    store.connection.execute('insert or ignore into experiment_allocation_policies values(?,?,?,?)',
        (policy['policy_id'],digest,canonical(policy),now_ms()))
    store.connection.commit()
    return digest


def plan_policy(policy,profile,spec):
    validate_policy(policy)
    if profile['max_variants']>policy['max_profile_variants']:
        raise ValueError('Hypothesis trial budget exceeds externally allocated variant cap')
    specs=compile_family(profile,spec)
    result=deepcopy(policy['plan_template'])
    # Blocks/windows adapt to the submitted causal footprint before observation,
    # never to future outcomes. This does not prove block independence.
    footprint=max(max(s['horizon_ms'],s['signal'].get('lookback_ms',0))+s['latency_ms'] for s in specs)
    criteria=result['criteria']
    criteria['block_ms']=max(criteria['block_ms'],footprint)
    criteria['regime_window_ms']=max(criteria['regime_window_ms'],footprint)
    minimum_span=criteria['block_ms']*criteria['min_blocks']
    result['comparison_duration_ms']=max(result['comparison_duration_ms'],minimum_span)
    result['final_duration_ms']=max(result['final_duration_ms'],minimum_span)
    result['allocation_origin']={'policy_id':policy['policy_id'],'policy_fingerprint':fingerprint(policy),
        'causal_footprint_ms':footprint,'rule':'fixed external criteria; windows cover declared block count'}
    # _prepare_plan checks the complete anchored horizon against max_duration_ms.
    # No budget or criterion is raised to make an oversized request fit.
    return result
