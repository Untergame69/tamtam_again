"""Explicit venue precision and mechanism profiles, separate from risk budgets."""
from decimal import Decimal,ROUND_DOWN
from typing import Any

TICK_SOURCE='https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size'
ERROR_SOURCE='https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses'
FUNDING_SOURCE='https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding'

def valid_price(price: Any, sz_decimals: int, *, spot: bool=False) -> bool:
    if type(sz_decimals) is not int or not 0<=sz_decimals<=(8 if spot else 6):
        raise ValueError('Invalid venue size precision')
    p=Decimal(str(price))
    if not p.is_finite() or p<=0:return False
    if p==p.to_integral_value():return True
    normalized=p.normalize();digits=normalized.as_tuple().digits;exponent=normalized.as_tuple().exponent
    return len(digits)<=5 and max(0,-exponent)<=(8 if spot else 6)-sz_decimals

def round_size(size: Any, sz_decimals: int) -> Decimal:
    if type(sz_decimals) is not int or not 0<=sz_decimals<=8:raise ValueError('Invalid size precision')
    value=Decimal(str(size))
    if not value.is_finite():raise ValueError('Nonfinite size')
    return value.quantize(Decimal(1).scaleb(-sz_decimals),rounding=ROUND_DOWN)

def mechanism_profile(catalog:dict[str,Any], instrument:str) -> dict[str,Any]:
    asset=catalog['instruments'].get(instrument)
    if not asset:return {'instrument':instrument,'status':'unknown','reason':'instrument absent from current catalog'}
    return {'schema_version':1,'instrument':instrument,'available_ms':catalog['available_ms'],
        'collateral':{'currency':asset.get('currency'),'token_id':asset.get('token_id')},
        'precision':{'sz_decimals':asset.get('sz_decimals'),'price_significant_figures':5,
                     'max_price_decimals':6-asset['sz_decimals'] if type(asset.get('sz_decimals')) is int else None,
                     'integer_price_exception':True,'source':TICK_SOURCE},
        'minimum_order':{'documented_value':'10','denomination':'USD for perps; collateral FX not assumed','source':ERROR_SOURCE},
        'margin':{'max_leverage':asset.get('max_leverage'),'mode':asset.get('margin_mode'),
                  'only_isolated':asset.get('only_isolated'),'tiers':asset.get('margin_tables')},
        'funding':{'interval_ms':3600000,'notional_reference':'oracle price',
                   'hip3_parameters':'deployer-specific; multiplier/interest not inferred','source':FUNDING_SOURCE},
        'prices':{'oracle_definition':'requires market-specific reference documentation',
                  'mark':'valuation reference; not executable bid/ask',
                  'execution':'received bid/ask and available depth'},
        'liquidation':{'model_status':'not implemented; risk limits do not reproduce venue liquidation'},
        'engine_capabilities':{'single_instrument_ioc':'implemented conservative visible-liquidity model',
            'passive_queue':'unsupported; zero simulated fills','non_usdc_accounting':'unsupported in legacy strategy engine',
            'isolated_margin_tiers':'unsupported','multi_instrument':'extension required'},
        'status':'descriptive','is_delisted':asset.get('is_delisted'),
        'evidence_refs':catalog.get('evidence_refs',[]),
        'limits':['profile is not permission to promote a strategy','venue rules, measured capacity and chosen risk budgets are separate']}

def validate_execution_rules(rules:dict[str,Any],market:str):
    if not isinstance(rules,dict) or rules.get('version')!=1 or rules.get('instrument')!=market:
        raise ValueError('Versioned matching market rules required')
    if rules.get('currency')!='USDC':raise ValueError('Unsupported mechanism: non-USDC engine accounting')
    if type(rules.get('available_ms')) is not int or rules['available_ms']<0 or not rules.get('evidence_refs'):
        raise ValueError('Causally available market metadata proof required')
    if type(rules.get('sz_decimals')) is not int or not 0<=rules['sz_decimals']<=6:
        raise ValueError('Invalid perpetual precision')
    if Decimal(str(rules.get('minimum_order_usdc'))) != Decimal(10):raise ValueError('Documented perpetual order minimum required')
    leverage=Decimal(str(rules.get('max_leverage')))
    if not leverage.is_finite() or leverage<=0:raise ValueError('Positive venue leverage cap required')


def execution_rules_from_profile(profile:dict[str,Any], market:str, *,
                                 cutoff_ms:int, evidence_refs:list[str]) -> dict[str,Any]:
    """Project a source-backed perpetual profile, never a symbol-name guess.

    Archived v1 profiles predate an explicit instrument-type field. Their full
    precision/minimum/funding contract identifies the perpetual metadata path.
    No historical profile is rewritten and no missing field receives a default.
    """
    if (not isinstance(profile,dict) or profile.get('schema_version')!=1
            or profile.get('instrument')!=market or profile.get('status')!='descriptive'
            or profile.get('instrument_type') not in (None,'perpetual')
            or not isinstance(market,str) or market.startswith('@') or '/' in market
            or type(cutoff_ms) is not int):
        raise ValueError('Source-backed perpetual instrument profile required')
    available=profile.get('available_ms');refs=profile.get('evidence_refs')
    if (type(available) is not int or not 0<=available<=cutoff_ms
            or not isinstance(refs,list) or not refs
            or any(not isinstance(ref,str) or not ref.startswith('raw_observations:')
                   or ref not in evidence_refs for ref in refs)):
        raise ValueError('Available rooted metadata references required')
    collateral=profile.get('collateral',{})
    if (not isinstance(collateral,dict) or collateral.get('currency')!='USDC' or not isinstance(collateral.get('token_id'),str)
            or not collateral['token_id']):
        raise ValueError('Unsupported mechanism: identified USDC perpetual collateral required')
    precision=profile.get('precision',{});minimum=profile.get('minimum_order',{})
    funding=profile.get('funding',{})
    if not all(isinstance(section,dict) for section in (precision,minimum,funding,profile.get('margin'))):
        raise ValueError('Structured perpetual precision, minimum, margin and funding proof required')
    decimals=precision.get('sz_decimals')
    if (type(decimals) is not int or not 0<=decimals<=6
            or precision.get('source')!=TICK_SOURCE
            or precision.get('price_significant_figures')!=5
            or precision.get('max_price_decimals')!=6-decimals
            or precision.get('integer_price_exception') is not True
            or minimum.get('source')!=ERROR_SOURCE
            or minimum.get('denomination')!='USD for perps; collateral FX not assumed'
            or funding.get('source')!=FUNDING_SOURCE
            or funding.get('interval_ms')!=3600000
            or profile.get('is_delisted') is not False):
        raise ValueError('Complete perpetual precision, minimum and funding contract required')
    rules={'version':1,'instrument':market,'currency':collateral['currency'],
           'available_ms':available,'sz_decimals':decimals,
           'minimum_order_usdc':minimum.get('documented_value'),
           'max_leverage':profile.get('margin',{}).get('max_leverage'),
           'evidence_refs':list(refs)}
    try:validate_execution_rules(rules,market)
    except (ValueError,TypeError,ArithmeticError) as exc:
        raise ValueError('Valid causal perpetual execution rules required') from exc
    return rules
