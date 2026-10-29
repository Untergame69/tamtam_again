"""Explicit, source-linked simulation assumptions for research proposals.

These are chosen parameters from the existing pilot configuration, never venue
measurements or permission to trade. They supply a counterfactual execution
scenario without supplying an entry signal, sizing rule or holding horizon.
"""
from copy import deepcopy
import hashlib
import json
import re
import zlib
from pathlib import Path
from datetime import datetime, timezone

from .engine import fingerprint, number


SOURCE = 'config/research-policy.json'
REFERENCE = 'packet.execution_research_context'
SCENARIO_FIELDS = ('max_exposure', 'fees', 'slippage', 'latency_ms',
                   'starting_capital_usdc', 'execution')


def _paper_cadence(repo_root):
    path=Path(repo_root)/'systemd/user/tamtam-again-paper.timer'
    if not path.is_file():return None
    raw=path.read_bytes()
    match=re.search(r'^OnUnitActiveSec=([0-9]+)(ms|s)\s*$',raw.decode(),re.MULTILINE)
    if not match:return None
    value=int(match[1])*(1000 if match[2]=='s' else 1)
    if value<=0:return None
    return {'path':'systemd/user/tamtam-again-paper.timer','sha256':hashlib.sha256(raw).hexdigest(),
        'configured_tick_ms':value,'classification':'configured_target_not_measured_lag'}


def _market_scope(packet):
    from .market_rules import execution_rules_from_profile
    observations=packet.get('observations',{})
    markets=observations.get('markets',[])
    if not isinstance(markets,list) or len(markets)!=1:
        return {'state':'unknown','reason':'Exactly one market needs verified perpetual metadata'}
    market=markets[0]
    matches=[row for row in observations.get('market_mechanisms',[])
             if isinstance(row,dict) and row.get('instrument')==market]
    if len(matches)!=1:
        return {'state':'unknown','market':market,'reason':'One unambiguous matching metadata profile required'}
    try:
        rules=execution_rules_from_profile(matches[0],market,cutoff_ms=packet.get('available_ms'),
                                          evidence_refs=packet.get('evidence_refs',[]))
    except ValueError as exc:
        return {'state':'unsupported' if 'Unsupported mechanism' in str(exc) else 'unknown',
                'market':market,'reason':str(exc)}
    interval=matches[0].get('funding',{}).get('interval_ms')
    if type(interval) is not int or interval<=0:
        return {'state':'unknown','market':market,'reason':'Observed perpetual funding interval required'}
    return {'state':'supported','market':market,'rules':rules,'funding_observation_interval_ms':interval,
            'evidence_refs':list(rules['evidence_refs']),
            'scope':'Identified USDC perpetual; venue liquidation and isolated-tier dynamics remain unmodelled.'}


def _root_verified_metadata(packet, store):
    """Verify the two catalog observations before exporting their references.

    This only reads public metadata already archived. It neither fills a missing
    catalog from a network call nor changes a historical scope report.
    """
    from .collateral import build_catalog
    from .market_rules import mechanism_profile
    from .population_local_join import _decode_verified
    observations=packet.get('observations',{})
    markets=observations.get('markets',[])
    if not isinstance(markets,list) or len(markets)!=1:
        raise ValueError('Exactly one market needs verified metadata')
    all_profiles=observations.get('market_mechanisms',[])
    profiles=[row for row in all_profiles
              if isinstance(row,dict) and row.get('instrument')==markets[0]]
    if len(profiles)>1:raise ValueError('One matching archived market profile required')
    derived=not profiles
    if derived:
        # A later fill may reveal a market omitted by the older account scope.
        # Its metadata can still be reconstructed from the SAME sealed global
        # catalog; no new provider request or guessed market rules are needed.
        roots=set();anchors=[]
        for candidate in all_profiles:
            if not isinstance(candidate,dict):raise ValueError('Structured archived catalog profiles required')
            refs=candidate.get('evidence_refs');available=candidate.get('available_ms')
            if (not isinstance(refs,list) or len(refs)!=2 or any(not isinstance(r,str) for r in refs)
                    or type(available) is not int):raise ValueError('Unambiguous archived catalog roots required')
            roots.add((tuple(sorted(refs)),available));anchors.append(candidate)
        if len(roots)!=1:raise ValueError('One unambiguous archived catalog required for an omitted market')
        profile=anchors[0]
    else:profile=profiles[0]
    refs=profile.get('evidence_refs');available=profile.get('available_ms')
    cutoff=packet.get('available_ms')
    if (not isinstance(refs,list) or len(refs)!=2 or len(set(refs))!=2
            or type(available) is not int or type(cutoff) is not int
            or not 0<=available<=cutoff):
        raise ValueError('Complete causal two-observation catalog references required')
    payloads={}
    for ref in refs:
        if not isinstance(ref,str) or not ref.startswith('raw_observations:') or not ref.split(':',1)[1].isdigit():
            raise ValueError('Exact raw metadata identity required')
        row=store.connection.execute('select * from raw_observations where observation_id=? '
                                     'and length(response_json)<=2000000',
                                     (int(ref.split(':',1)[1]),)).fetchone()
        if (row is None or row['network']!=packet.get('network')
                or row['source']!='hyperliquid-population-rest-v1'
                or row['entity_type']!='market' or row['entity_id']!='collateral:all'
                or row['endpoint'] not in {'allPerpMetas','spotMetaAndAssetCtxs'}
                or row['endpoint'] in payloads
                or json.loads(row['request_json']).get('type')!=row['endpoint']):
            raise ValueError('Matching archived perpetual/token metadata sources required')
        received=int(datetime.fromisoformat(row['observed_at'].replace('Z','+00:00')).timestamp()*1000)
        if not 0<=received<=available:raise ValueError('Metadata must be received before catalog availability')
        payloads[row['endpoint']]=_decode_verified(row,max_decoded_bytes=2_000_000)
    if set(payloads)!={'allPerpMetas','spotMetaAndAssetCtxs'}:
        raise ValueError('Both perpetual and collateral-token metadata are required')
    catalog=build_catalog(payloads['allPerpMetas'],payloads['spotMetaAndAssetCtxs'],
                          available_ms=available,evidence_refs=list(refs))
    anchor=mechanism_profile(catalog,profile.get('instrument'))
    if fingerprint(anchor)!=fingerprint(profile):
        raise ValueError('Archived market profile must equal its raw metadata reconstruction')
    rebuilt=mechanism_profile(catalog,markets[0])
    if not derived and fingerprint(rebuilt)!=fingerprint(profile):
        raise ValueError('Archived market profile must equal its raw metadata reconstruction')
    if derived:observations['market_mechanisms']=[*all_profiles,rebuilt]
    packet['evidence_refs']=list(dict.fromkeys([*packet.get('evidence_refs',[]),*refs]))
    return {'state':'verified','evidence_refs':list(refs),
            'profile_origin':'derived_from_same_archived_catalog' if derived else 'matching_archived_profile',
            'profile_fingerprint':fingerprint(rebuilt)}


def _freeze_funding_witnesses(packet, store, scope):
    """Freeze eligible existing sources, without reading their account payloads.

    Observed subscription envelopes establish a possible source, never future
    settlement coverage. The evaluator independently verifies each coefficient.
    """
    from .discovery import protected_addresses
    from .research_memory import authorized_account_history
    from .funding_witnesses import validate_contract
    cutoff=packet['available_ms'];network=packet.get('network');address=packet.get('address','').lower()
    if not isinstance(network,str) or not network or len(scope.get('evidence_refs',[]))!=2:return None
    blocked=protected_addresses(store);selected=[];metadata=[]
    stamp=datetime.fromtimestamp(cutoff/1000,timezone.utc).isoformat(timespec='milliseconds')
    for row in store.connection.execute("select address,added_at from candidates where network=? and status='tracked' order by address limit 64",(network,)):
        witness=row['address'].lower()
        if witness==address or witness in blocked or not authorized_account_history(store,network,witness,cutoff):continue
        try:added=int(datetime.fromisoformat(row['added_at'].replace('Z','+00:00')).timestamp()*1000)
        except (TypeError,ValueError):continue
        if added>cutoff:continue
        source=store.connection.execute('select observation_id,response_sha256,observed_at from raw_observations '
            "where network=? and source='hyperliquid-websocket-v1' and entity_type='account' and entity_id=? "
            "and endpoint='userFundings' and observed_at<=? order by observed_at desc,observation_id desc limit 1",
            (network,witness,stamp)).fetchone()
        if source is None:continue
        selected.append(witness);metadata.append({'address':witness,'evidence_ref':'raw_observations:'+str(source['observation_id']),
            'response_sha256':source['response_sha256'],'archived_at':source['observed_at']})
        if len(selected)==9:break
    if not selected:return None
    contract={'version':'settled-funding-witnesses-v1','network':network,'market':scope['market'],
        'currency':'USDC','available_ms':cutoff,'addresses':selected,'evidence_refs':list(scope['evidence_refs'])}
    validate_contract(contract,network=network,market=scope['market'],address=address)
    return {'contract':contract,'source_metadata':metadata,
        'coverage_proven':False,'use':'Settled cost coefficients only; no account fills or trade signals.',
        'source_periods':[{'network':network,'address':a,'market':'*','start_ms':0,'end_ms':cutoff+1} for a in selected]}


def attach_execution_context(packet, repo_root, *, store=None):
    """Attach existing parameters before sealing; do not mutate observations.

    Absence or invalidity fails explicitly, rather than creating defaults. The
    source hash binds the exact configuration even if a future revision changes
    it. References to this context may justify scenario axes, but cannot alone
    support a hypothesis about market behaviour.
    """
    path = Path(repo_root) / SOURCE
    raw = path.read_bytes()
    policy = json.loads(raw)
    template = policy.get('strategy_template')
    if (not isinstance(template, dict) or template.get('schema_version') != 2
            or not isinstance(policy.get('version'), str) or not policy['version']):
        raise ValueError('Existing versioned pilot strategy template required')
    scenario = {key: deepcopy(template[key]) for key in SCENARIO_FIELDS}
    if (set(scenario['fees']) != {'maker_bps', 'taker_bps'}
            or any(number(value) < 0 for value in scenario['fees'].values())
            or number(scenario['slippage']['bps']) < 0
            or type(scenario['latency_ms']) is not int or scenario['latency_ms'] < 0
            or number(scenario['starting_capital_usdc']) <= 0
            or any(number(scenario['max_exposure'][key]) <= 0 for key in
                   ('notional_usdc', 'max_drawdown_usdc', 'max_leverage'))
            or scenario['execution'].get('kind') != 'market_ioc'):
        raise ValueError('Explicit nonnegative costs and bounded IOC pilot scenario required')
    metadata_resolution=None
    if store is not None:
        try:metadata_resolution=_root_verified_metadata(packet,store)
        except (ValueError,TypeError,KeyError,ArithmeticError,zlib.error) as exc:
            metadata_resolution={'state':'unverified','reason':str(exc)}
    market_scope=_market_scope(packet)
    if metadata_resolution is not None and metadata_resolution['state']!='verified':
        market_scope={'state':'unknown','reason':metadata_resolution['reason']}
    if market_scope.get('state')=='supported':
        # A coverage interval describes when settled costs must be observed. It
        # is separate from funding_interval_ms, which changes order behaviour
        # by avoiding settlement boundaries in the execution engine.
        scenario['execution']['funding_observation_interval_ms']=market_scope['funding_observation_interval_ms']
        scenario['execution']['funding_settlement_clock']='reported_hour_with_inventory_invariance_v1'
    cadence=_paper_cadence(repo_root)
    witnesses=None
    if store is not None and market_scope.get('state')=='supported' and metadata_resolution.get('state')=='verified':
        witnesses=_freeze_funding_witnesses(packet,store,market_scope)
        if witnesses:
            scenario['execution']['funding_witnesses']=witnesses['contract']
            packet['funding_witness_source_periods']=deepcopy(witnesses['source_periods'])
    sensitivity=None;sensitivity_source=None
    sensitivity_path=Path(repo_root)/'config/funding-sensitivity-policy.json'
    if witnesses and sensitivity_path.is_file():
        from .funding_sensitivity import build_scenario
        sensitivity_raw=sensitivity_path.read_bytes()
        sensitivity_policy=json.loads(sensitivity_raw)
        try:
            sensitivity=build_scenario(store,witnesses['contract'],network=packet['network'],
                address=packet['address'],market=market_scope['market'],cutoff_ms=packet['available_ms'],
                policy=sensitivity_policy)
        except ValueError as exc:
            # An optional sensitivity refusal cannot invalidate independent
            # strict accounting or descriptive market evidence. Never invent a
            # replacement rate; retain the exact typed refusal in the packet.
            sensitivity={'contract':None,'status':'technical_required',
                'reason':str(exc),'evidence_refs':[],'source_periods':[]}
        sensitivity_source={'path':'config/funding-sensitivity-policy.json',
            'sha256':hashlib.sha256(sensitivity_raw).hexdigest(),'policy_id':sensitivity_policy['policy_id']}
        if sensitivity.get('contract'):
            packet['evidence_refs']=list(dict.fromkeys([*packet['evidence_refs'],*sensitivity['evidence_refs']]))
            periods=packet.setdefault('funding_witness_source_periods',[])
            for period in sensitivity['source_periods']:
                if period not in periods:periods.append(period)
            union={}
            for period in periods:
                key=(period['network'],period['address'],period['market'],period['start_ms'])
                if key not in union or period['end_ms']>union[key]['end_ms']:union[key]=period
            packet['funding_witness_source_periods']=[union[key] for key in sorted(union)]
    profiles={}
    if market_scope.get('state')=='supported' and cadence is not None:
        common={'small_residual_policy':'avoid_uncloseable_residual_v1',
                'max_quote_age_ms':scenario['execution']['unknown_quote_max_age_ms'],
                'paper_tick_target_ms':cadence['configured_tick_ms']}
        profiles['flat_at_settlement_v1']={'engine':'single_perp_v3',
            'execution_overrides':{**common,'funding_exposure_policy':'flat_at_settlement_v1'},
            'use':'Optional for independently justified intraday mechanisms only; preserve the proposed entry signal.',
            'constraints':'Wait for current-hour reported settlement clock before new exposure. Entry must leave horizon, exit latency, TTL and quote-age headroom before the next hour. Actual exits and residual inventory remain audited; intended flatness is not proof.',
            'funding_claim':'Zero only when the executed ledger proves zero inventory throughout each scheduled-to-reported interval; exposed or ambiguous costs remain unknown.'}
        if sensitivity and sensitivity.get('contract'):
            profiles['funding_sensitivity_v1']={'engine':'single_perp_v3',
                'execution_overrides':{**common,'funding_sensitivity_scenario':sensitivity['contract']},
                'use':'Optional user-authorized, frozen adverse cost sensitivity for an evidence-motivated policy; never a live-cost validation.',
                'constraints':'Mutually exclusive with flat_at_settlement_v1. Freeze before new evaluation data. All sample, execution and risk gates remain. This evidence cannot authorize final selection or paper even if numerical criteria pass.',
                'funding_claim':'Chosen symmetric debit from a bounded historical sample, not a physical bound or prediction. Actual funding coverage remains separately unknown when missing or conflicting.'}
    context = {
        'schema_version': 'execution-research-context-v1',
        'source': {'path': SOURCE, 'policy_version': policy['version'],
                   'sha256': hashlib.sha256(raw).hexdigest()},
        'classification': 'chosen_simulation_scenario_not_measured_capacity',
        'scope': 'Our single-perpetual IOC counterfactual only; not the source trader execution policy.',
        'scenario': scenario,
        'market_scope': market_scope,
        'metadata_resolution': metadata_resolution or {'state':'sealed_root_references_only'},
        'funding_witness_sources':witnesses,
        'funding_sensitivity_source':sensitivity_source,
        'funding_sensitivity_calibration':sensitivity,
        'paper_cadence_reference':cadence,
        'available_execution_profiles':profiles,
        'parameter_status': {
            'fees': 'Configured debit scenario, not our verified venue fee schedule or a maker rebate entitlement.',
            'slippage': 'Configured additional cost scenario, not measured impact.',
            'latency_ms': 'Configured simulated delay, not measured decision-to-execution latency.',
            'starting_capital_usdc': 'Chosen virtual capital, not source account equity.',
            'max_exposure': 'Chosen virtual risk limits, not evidence of source account risk.',
            'execution': 'Configured conservative visible-liquidity simulation; no guaranteed fill or passive queue model.',
        },
        'research_use': [
            'A falsifiable policy for our own decisions may be tested without identifying the trader private intentions.',
            'A follower policy begins only at locally received public fills; REST event time is not signal availability.',
            'Entry trigger, exit horizon and sizing remain hypotheses requiring market evidence and explicit justification.',
            'Use measurement_status=simulated for scenario axes; do not cite this context as measured_reference.',
            'A result applies to the declared scenario; it is not a demonstrated live execution return.',
        ],
        'market_evidence': False,
        'economic_validation': False,
        'paper_authorized': False,
        'real_orders_authorized': False,
    }
    context['fingerprint'] = fingerprint(context)
    packet['execution_research_context'] = context
    return context


def validate_scenario_spec(context, spec):
    """Keep configured assumptions explicit when the packet supplies them.

    Hypothesis axes may vary a declared simulated delay; the base specification
    remains the source scenario. No risk expansion or cheaper fee assumption is
    inferred merely because a model cites the configuration.
    """
    original = deepcopy(context)
    claimed = original.pop('fingerprint', None)
    if (claimed != fingerprint(original)
            or context.get('schema_version') != 'execution-research-context-v1'
            or context.get('classification') != 'chosen_simulation_scenario_not_measured_capacity'
            or any(context.get(key) is not False for key in
                   ('market_evidence', 'economic_validation', 'paper_authorized', 'real_orders_authorized'))):
        raise ValueError('Verified non-promotional execution scenario required')
    scenario = context['scenario']
    scope=context.get('market_scope',{})
    if scope.get('state')!='supported' or spec.get('market')!=scope.get('market'):
        raise ValueError('Verified matching USDC perpetual metadata required before compilation')
    execution_spec=spec.get('execution',{})
    profile=execution_spec.get('funding_exposure_policy')
    if 'funding_sensitivity_scenario' in execution_spec:
        if profile is not None:raise ValueError('Funding sensitivity and flat exposure policies are mutually exclusive')
        profile='funding_sensitivity_v1'
    selected=context.get('available_execution_profiles',{}).get(profile) if profile is not None else None
    if profile is not None and not selected:
        raise ValueError('Only an explicitly supplied optional execution profile can be selected')
    allowed_engines=(selected['engine'],) if selected else (None,'single_perp_v2')
    if spec.get('engine') not in allowed_engines:
        # A portfolio or passive model needs a separately supplied scenario,
        # rather than inheriting single-perp assumptions without accounting.
        raise ValueError('Execution context covers only the declared single-perp IOC scenario')
    execution=deepcopy(spec.get('execution',{}))
    rules=execution.pop('market_rules',None)
    if rules!=scope['rules']:
        raise ValueError('Execution market rules must equal the verified metadata projection')
    expected_execution={**scenario['execution'],**(selected['execution_overrides'] if selected else {})}
    if (execution!=expected_execution or any(spec.get(key) != scenario[key] for key in
           ('latency_ms', 'starting_capital_usdc'))):
        raise ValueError('Executable base specification must preserve the supplied simulation assumptions')
    costs = spec.get('fees', {})
    if (set(costs) != set(scenario['fees'])
            or any(number(costs[key]) < number(value) for key, value in scenario['fees'].items())
            or number(spec.get('slippage', {}).get('bps', '-1')) < number(scenario['slippage']['bps'])):
        raise ValueError('Configured costs may be stressed upward, never reduced without separate evidence')
    risk = spec.get('max_exposure', {})
    if any(key not in risk or number(risk[key]) > number(limit) or number(risk[key]) <= 0
           for key, limit in scenario['max_exposure'].items()):
        raise ValueError('Executable risk limits must remain within the supplied virtual scenario')
