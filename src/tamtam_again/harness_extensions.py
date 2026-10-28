"""Capability contract distinguishes unsupported mechanisms from bad economics."""
from typing import Any
from . import engine,portfolio_engine

CONTRACTS={
 'single_perp_v2':{'markets':1,'currencies':['USDC'],'signals':['leader_delta','momentum'],
                   'execution':['market_ioc','passive_conservative'],'real_validation_adapter':True},
 'single_perp_v3':{'markets':1,'currencies':['USDC'],'signals':['leader_delta','momentum'],
                   'execution':['market_ioc'],'venue_rules_required':True,
                   'priority_reductions':True,'real_validation_adapter':True},
 'portfolio_reference_v1':{'markets':2,'currencies':['USDC'],'signals':['fixed_pair_reference'],
                           'execution':['independent_ioc_legs'],'real_validation_adapter':False}}

def capability(spec:dict[str,Any]) -> dict[str,Any]:
    name=spec.get('engine','single_perp_v2')
    if name not in CONTRACTS:return {'state':'unsupported_mechanism','engine':name,'reason':'No registered engine contract','economic_rejection':False}
    if name=='single_perp_v3' and (spec.get('execution',{}).get('kind')!='market_ioc'
            or 'market_rules' not in spec.get('execution',{})):
        return {'state':'invalid_specification','engine':name,
            'reason':'Versioned IOC execution and explicit venue rules required','economic_rejection':False}
    validator=portfolio_engine.validate if name=='portfolio_reference_v1' else engine.validate_spec
    try:validator(spec)
    except ValueError as exc:
        message=str(exc)
        unsupported=message.startswith(('Unsupported mechanism','Supported signals:','Unsupported entry/exit','Unsupported execution model'))
        return {'state':'unsupported_mechanism' if unsupported else 'invalid_specification','engine':name,'reason':message,'economic_rejection':False}
    return {'state':'executable_experimental' if name=='portfolio_reference_v1' else 'executable',
            'engine':name,'contract':CONTRACTS[name],'economic_validation':False}

def replay(spec:dict[str,Any],events:list[dict[str,Any]], **options) -> dict[str,Any]:
    supported=capability(spec)
    if supported['state'] not in ('executable','executable_experimental'):return supported
    if supported['engine']=='portfolio_reference_v1':return portfolio_engine.replay(spec,events,stress=options.get('stress',1))
    return engine.replay(spec,events,**options)
