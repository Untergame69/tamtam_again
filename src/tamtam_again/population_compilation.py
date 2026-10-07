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
            'measured_reference requires measurement_ref pointing to an execution_delay_reference in sealed system_measurements; REST response time is not execution delay',
            'unknown mechanisms remain hypotheses or unsupported; no economic rejection',
            'promotion criteria and future window policy are supplied separately, never by this output']}


def packet_references(packet):
    refs=set(packet.get('evidence_refs',[]))
    observations=packet.get('observations',{})
    refs.update((observations.get('current_pass_behavior_profile') or {}).get('evidence_refs',[]))
    for mechanism in observations.get('market_mechanisms',[]):refs.update(mechanism.get('evidence_refs',[]))
    refs.update(observations.get('system_measurements',{}))
    return refs


def validate_packet_compilation(hypothesis,profile,packet,request_id):
    return validate_compilation({**hypothesis,'experiment_profile':profile},packet_references(packet),
        request_id=request_id,measurements=packet.get('observations',{}).get('system_measurements',{}),
        as_of_ms=packet.get('available_ms'))


def validate_compilation(hypothesis,allowed_refs,*,request_id=None,measurements=None,as_of_ms=None):
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
        if axis.get('measurement_status')=='measured_reference':
            reference=axis.get('measurement_ref')
            proof=(measurements or {}).get(reference)
            if (not proof or reference not in axis['evidence_refs'] or
                proof.get('kind')!='execution_delay_reference' or proof.get('parameter')!='latency_ms' or
                type(proof.get('available_ms')) is not int or type(as_of_ms) is not int or
                not 0<=proof['available_ms']<=as_of_ms or
                axis.get('measurement_available_ms')!=proof['available_ms']):
                raise ValueError('Measured execution-delay reference requires available sealed measurement proof')
            if type(proof.get('value_ms')) is not int or proof['value_ms']<0:
                raise ValueError('Explicit measured delay value required')
    supported=capability(spec)
    if supported['state']=='invalid_specification':raise ValueError('Invalid executable compiler specification: '+supported['reason'])
    if supported['state']=='executable':compile_family(profile,spec)
    return supported
