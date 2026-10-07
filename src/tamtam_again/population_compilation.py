"""Optional executable output is checked without coercing unknown mechanisms."""
from .experiments import compile_family
from .harness_extensions import capability,CONTRACTS


def compiler_contract():
    return {'engines':CONTRACTS,'single_perp_v2_fields':[
        'schema_version=2','type','market','data_sources','signal','entry','exit','sizing',
        'max_exposure: notional_usdc,max_drawdown_usdc,max_leverage','fees: maker_bps,taker_bps',
        'slippage: bps','latency_ms','horizon_ms','starting_capital_usdc',
        'execution: kind,heartbeat_timeout_ms,unknown_quote_max_age_ms,order_ttl_ms,displayed_size_fraction',
        'invalidation_conditions'],
        'single_perp_v2_rules':{'entry':'target_position','exit':'horizon_or_target',
            'follower_signal':'leader_delta','autonomous_signal':'momentum with lookback_ms,threshold_bps and sizing.units'},
        'experiment_profile':{'schema_version':1,'hypothesis_id':'request_id','justification':'required',
            'max_variants':'explicit integer 1..64','selection_rule':'comparison_then_one_final',
            'axes':'horizon_ms, latency_ms or scale; each declares values, category, justification, evidence_refs, measurement_status'},
        'limits':['these are current engine capabilities, not universal strategy assumptions',
            'never replace a different mechanism with momentum or leader_delta to fit the engine',
            'do not invent costs, measured delays, risk budgets or missing observations',
            'unknown mechanisms remain hypotheses or unsupported; no economic rejection',
            'promotion criteria and future window policy are supplied separately, never by this output']}


def validate_compilation(hypothesis,allowed_refs,*,request_id=None):
    present={'executable_spec','experiment_profile'}&hypothesis.keys()
    if not present:return None
    if present!={'executable_spec','experiment_profile'}:
        raise ValueError('Executable output requires both rule and justified experiment profile')
    spec=hypothesis['executable_spec'];profile=hypothesis['experiment_profile']
    if not isinstance(spec,dict) or not isinstance(profile,dict):raise ValueError('Structured compiler output required')
    markets=([leg.get('market') for leg in spec.get('legs',[])]
             if spec.get('engine')=='portfolio_reference_v1' else [spec.get('market')])
    if set(markets)!=set(hypothesis['markets']) or (spec.get('type') is not None and spec['type']!=hypothesis['type']):
        raise ValueError('Compiled rule must preserve hypothesis markets and type')
    if request_id is not None and profile.get('hypothesis_id')!=request_id:
        raise ValueError('Experiment must refer to its actual research request')
    for axis in profile.get('axes',[]):
        if not isinstance(axis,dict) or not set(axis.get('evidence_refs',[]))<=allowed_refs:
            raise ValueError('Experimental parameter evidence must be supplied in sealed packet')
    supported=capability(spec)
    if supported['state']=='invalid_specification':raise ValueError('Invalid executable compiler specification: '+supported['reason'])
    if supported['state']=='executable':compile_family(profile,spec)
    return supported
