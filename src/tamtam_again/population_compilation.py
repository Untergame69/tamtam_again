"""Optional executable output is checked without coercing unknown mechanisms."""
from copy import deepcopy
import re
from .experiments import compile_family
from .harness_extensions import capability,CONTRACTS


FUNDING_CONTRACT_PATH = ('packet.execution_research_context.available_execution_profiles.'
    'funding_sensitivity_v1.execution_overrides.funding_sensitivity_scenario')


def bind_execution_contracts(hypothesis, execution_context):
    """Resolve one exact sealed contract reference on a copy, without choosing rules.

    Full-object specifications retain their existing validation path. References
    are frontend notation only; engines and persisted proposals receive objects.
    """
    resolved=deepcopy(hypothesis)
    if not isinstance(resolved,dict):return resolved,[]
    spec=resolved.get('executable_spec')
    if not isinstance(spec,dict) or not isinstance(spec.get('execution'),dict):return resolved,[]
    execution=spec['execution'];reference=execution.get('funding_sensitivity_scenario')
    if not isinstance(reference,str):return resolved,[]
    if re.fullmatch(r'sealed:[0-9a-f]{64}',reference) is None:
        raise ValueError('Exact sealed funding sensitivity reference required')
    from .engine import fingerprint
    from .funding_sensitivity import validate_scenario
    context=deepcopy(execution_context)
    if not isinstance(context,dict):raise ValueError('Sealed execution context required for contract reference')
    claimed=context.pop('fingerprint',None)
    if claimed!=fingerprint(context):raise ValueError('Sealed execution context fingerprint mismatch')
    selected=context.get('available_execution_profiles',{}).get('funding_sensitivity_v1',{})
    contract=selected.get('execution_overrides',{}).get('funding_sensitivity_scenario')
    validate_scenario(contract,market=spec.get('market'))
    if reference!='sealed:'+contract['fingerprint']:
        raise ValueError('Sealed funding sensitivity reference does not match supplied contract')
    execution['funding_sensitivity_scenario']=deepcopy(contract)
    return resolved,[{'version':'sealed-execution-contract-binding-v1',
        'field':'hypothesis.executable_spec.execution.funding_sensitivity_scenario',
        'source':FUNDING_CONTRACT_PATH,'reference':reference,
        'contract_fingerprint':contract['fingerprint'],'execution_context_fingerprint':claimed}]


def compiler_contract():
    return {'engines':CONTRACTS,'sealed_execution_contract_reference':{
        'field':'executable_spec.execution.funding_sensitivity_scenario',
        'value':'sealed:<exact 64 lowercase hex contract fingerprint>',
        'source':FUNDING_CONTRACT_PATH,
        'rule':'Select only the supplied exact contract; runtime resolves it before full validation. Other execution overrides must still be copied exactly.'},'single_perp_v2_fields':[
        'schema_version=2','type','market','data_sources','signal','entry','exit','sizing',
        'max_exposure: notional_usdc,max_drawdown_usdc,max_leverage','fees: maker_bps,taker_bps',
        'slippage: bps','latency_ms','horizon_ms','starting_capital_usdc',
        'execution: kind,heartbeat_timeout_ms,unknown_quote_max_age_ms,order_ttl_ms,displayed_size_fraction',
        'invalidation_conditions'],
        'single_perp_v2_rules':{'entry':'target_position','exit':'horizon_or_target',
            'follower_signal':'leader_delta with positive sizing.scale',
            'autonomous_signal':'momentum with lookback_ms,threshold_bps and positive sizing.units AND sizing.scale; data_sources must exclude userFills'},
        'experiment_profile':{'schema_version':1,'hypothesis_id':'request_id','justification':'required',
            'max_variants':'explicit integer 1..64','selection_rule':'comparison_then_one_final',
            'axes':'horizon_ms, latency_ms or scale; each declares values, category, justification, evidence_refs, measurement_status'},
        'limits':['these are current engine capabilities, not universal strategy assumptions',
            'never replace a different mechanism with momentum or leader_delta to fit the engine',
            'do not invent costs, measured delays, risk budgets or missing observations',
            'measured_reference requires measurement_ref pointing to an execution_delay_reference in sealed system_measurements; REST response time is not execution delay',
            'unknown mechanisms remain hypotheses or unsupported; no economic rejection',
            'packet.execution_research_context, when supplied, is chosen simulation and risk context, never market evidence or measured execution capacity',
            'promotion criteria and future window policy are supplied separately, never by this output']}


def packet_references(packet):
    from .sealed_references import expanded_evidence_refs
    refs=set(packet.get('evidence_refs',[]))|set(expanded_evidence_refs(packet))
    observations=packet.get('observations',{})
    refs.update((observations.get('current_pass_behavior_profile') or {}).get('evidence_refs',[]))
    for mechanism in observations.get('market_mechanisms',[]):refs.update(mechanism.get('evidence_refs',[]))
    refs.update(observations.get('system_measurements',{}))
    if isinstance(packet.get('execution_research_context'), dict):
        refs.add('packet.execution_research_context')
    return refs


def validate_packet_compilation(hypothesis,profile,packet,request_id):
    return validate_compilation({**hypothesis,'experiment_profile':profile},packet_references(packet),
        request_id=request_id,measurements=packet.get('observations',{}).get('system_measurements',{}),
        as_of_ms=packet.get('available_ms'),execution_context=packet.get('execution_research_context'),
        readiness=packet.get('observations',{}).get('execution_data_readiness'),
        prospective_constraints=packet.get('prospective_experiment_constraints'))


def validate_compilation(hypothesis,allowed_refs,*,request_id=None,measurements=None,as_of_ms=None,execution_context=None,readiness=None,prospective_constraints=None):
    present={'executable_spec','experiment_profile'}&hypothesis.keys()
    if not present:return None
    if present!={'executable_spec','experiment_profile'}:
        raise ValueError('Executable output requires both rule and justified experiment profile')
    hypothesis,_=bind_execution_contracts(hypothesis,execution_context)
    spec=hypothesis['executable_spec'];profile=hypothesis['experiment_profile']
    if not isinstance(spec,dict) or not isinstance(profile,dict):raise ValueError('Structured compiler output required')
    if prospective_constraints is not None:
        maximum=prospective_constraints.get('max_profile_variants') if isinstance(prospective_constraints,dict) else None
        requested=profile.get('max_variants')
        if type(maximum) is not int or maximum<1 or type(requested) is not int or not 1<=requested<=maximum:
            raise ValueError('Experiment profile exceeds its supplied external variant allowance')
    if readiness is not None:
        if not isinstance(readiness,dict) or readiness.get('market_ws_observed') is not True:
            raise ValueError('Observed public market stream required before executable allocation')
        if spec.get('type')=='follower' and readiness.get('account_ws_observed') is not True:
            raise ValueError('Observed account WebSocket fills required for follower allocation; REST is not a live signal')
        frozen=(execution_context or {}).get('scenario',{}).get('execution',{}).get('funding_witnesses')
        if readiness.get('funding_ws_observed') is not True and not frozen:
            raise ValueError('Observed supported funding stream required before allocation; missing funding is not zero funding')
    if execution_context is not None:
        from .execution_research_context import validate_scenario_spec
        validate_scenario_spec(execution_context,spec)
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
