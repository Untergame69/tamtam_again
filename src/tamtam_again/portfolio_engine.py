"""Experimental two-perpetual reference; no real promotion or live order path."""
from __future__ import annotations
from decimal import Decimal
from typing import Any
from .engine import _fill,number,fingerprint

def validate(spec:dict[str,Any]):
    if spec.get('schema_version')!=1 or spec.get('engine')!='portfolio_reference_v1':raise ValueError('Explicit experimental portfolio contract required')
    if spec.get('currency')!='USDC':raise ValueError('Unsupported mechanism: cross-currency portfolio valuation')
    legs=spec.get('legs')
    if not isinstance(legs,list) or len(legs)!=2 or any(not isinstance(l,dict) or not isinstance(l.get('market'),str) for l in legs) or len({l['market'] for l in legs})!=2:
        raise ValueError('Two distinct market legs required')
    for leg in legs:
        if not isinstance(leg.get('market'),str) or not leg['market'] or not number(leg.get('target_units')):
            raise ValueError('Market and nonzero signed target required')
    for key in ('latency_ms','start_ms','horizon_ms','leg_timeout_ms','heartbeat_timeout_ms'):
        if type(spec.get(key)) is not int or spec[key]<(0 if key in ('latency_ms','start_ms') else 1):raise ValueError('Invalid portfolio timing: '+key)
    for key in ('capital_usdc','max_gross_usdc','max_loss_usdc'):
        if number(spec.get(key))<=0:raise ValueError('Positive portfolio risk budget required')
    for key in ('taker_fee_bps','slippage_bps'):
        if not 0<=number(spec.get(key))<10000:raise ValueError('Invalid portfolio cost')
    if not 0<number(spec.get('displayed_size_fraction'))<=1:raise ValueError('Invalid visible liquidity fraction')
    if spec.get('unhedged_policy')!='flatten_on_timeout':raise ValueError('Explicit leg-risk timeout policy required')
    if not spec.get('evidence_refs'):raise ValueError('Reference hypothesis evidence required')

def initial(spec:dict[str,Any]) -> dict[str,Any]:
    validate(spec)
    return {'engine':'portfolio_reference_v1','spec_fingerprint':fingerprint(spec),'last_ms':-1,
        'seen':{},'phase':'waiting','intent':None,'opened_ms':None,'diagnostics':[],
        'risk_halted':False,'peak_equity':str(spec['capital_usdc']),
        'legs':{l['market']:{'cash':'0','position':'0','average_price':'0','realized_pnl':'0',
            'fees':'0','funding':'0','opened_ms':None,'fills':[],'quote':None,
            'session':None,'connected':False,'healthy_ms':None} for l in spec['legs']}}

def healthy(leg:dict[str,Any],now:int,spec:dict[str,Any]) -> bool:
    q=leg['quote']
    return bool(q and q['available_ms']<now and leg['connected'] and q['session']==leg['session']
        and leg['healthy_ms'] is not None and 0<=now-leg['healthy_ms']<=spec['heartbeat_timeout_ms'])

def metrics(state:dict[str,Any],spec:dict[str,Any],now:int) -> dict[str,Any]:
    cash=number(spec['capital_usdc'])+sum((number(l['cash']) for l in state['legs'].values()),Decimal(0))
    unrealized=Decimal(0);gross=Decimal(0);net=Decimal(0);known=True
    for leg in state['legs'].values():
        pos=number(leg['position'])
        if not pos:continue
        if not healthy(leg,now,spec):known=False;continue
        q=leg['quote'];exit_price=number(q['bid'] if pos>0 else q['ask'])
        unrealized+=pos*(exit_price-number(leg['average_price']))
        value=pos*exit_price;gross+=abs(value);net+=value
    return {'cash_usdc':str(cash),'equity_usdc':str(cash+unrealized) if known else None,
        'gross_exposure_usdc':str(gross) if known else None,'net_exposure_usdc':str(net) if known else None,
        'realized_pnl_usdc':str(sum((number(l['realized_pnl']) for l in state['legs'].values()),Decimal(0))),
        'fees_usdc':str(sum((number(l['fees']) for l in state['legs'].values()),Decimal(0))),
        'funding_usdc':str(sum((number(l['funding']) for l in state['legs'].values()),Decimal(0))),
        'valuation_status':'observed_exit_quotes' if known else 'unknown_market_availability',
        'positions':{m:l['position'] for m,l in state['legs'].items()},'phase':state['phase'],
        'economic_validation':False,'experimental':True}

def _intent(state,spec,targets,now,purpose):
    state['intent']={'targets':targets,'due_ms':now+spec['latency_ms'],
                     'deadline_ms':now+spec['latency_ms']+spec['leg_timeout_ms'],'purpose':purpose}

def _execute(state,spec,now,stress):
    intent=state['intent']
    if not intent or now<intent['due_ms']:return
    if now>intent['deadline_ms']:
        state['diagnostics'].append({'at_ms':now,'kind':'leg_timeout','purpose':intent['purpose'],
                                    'positions':{m:l['position'] for m,l in state['legs'].items()}})
        state['intent']=None
        if any(number(l['position']) for l in state['legs'].values()):
            state['risk_halted']=True;state['phase']='flattening'
            _intent(state,spec,{m:'0' for m in state['legs']},now,'flatten')
        else:state['phase']='finished'
        return
    # Each leg gets one IOC attempt. Missing/partial fills do not fill the other
    # leg magically. Residual targets wait until timeout, then actual inventory flattens.
    if intent.get('attempted'):return
    intent['attempted']=True
    for market,target in intent['targets'].items():
        leg=state['legs'][market];delta=number(target)-number(leg['position'])
        if not delta:continue
        if not healthy(leg,now,spec):
            state['diagnostics'].append({'at_ms':now,'kind':'no_execution','market':market});continue
        q=leg['quote'];buy=delta>0
        available=number(q['ask_size'] if buy else q['bid_size'])*number(spec['displayed_size_fraction'])/stress
        size=min(abs(delta),available)*(1 if buy else -1)
        if not size:
            state['diagnostics'].append({'at_ms':now,'kind':'no_liquidity','market':market});continue
        price=number(q['ask'] if buy else q['bid'])*(1+number(spec['slippage_bps'])*stress/10000*(1 if buy else -1))
        if intent['purpose']=='open':
            # Gross exposure includes the entire portfolio and the proposed leg,
            # using adverse executable prices. The second leg is never netted away.
            current=metrics(state,spec,now)
            if current['gross_exposure_usdc'] is None:continue
            other=number(current['gross_exposure_usdc'])-abs(number(leg['position'])*number(q['bid'] if number(leg['position'])>=0 else q['ask']))
            if other+abs((number(leg['position'])+size)*price)>number(spec['max_gross_usdc']):
                state['diagnostics'].append({'at_ms':now,'kind':'aggregate_risk_limit','market':market});continue
        _fill(leg,size,price,number(spec['taker_fee_bps'])*stress,now)
        if abs(size)<abs(delta):state['diagnostics'].append({'at_ms':now,'kind':'partial_execution','market':market})
    complete=all(number(state['legs'][m]['position'])==number(t) for m,t in intent['targets'].items())
    if complete:
        state['intent']=None
        state['phase']='holding' if intent['purpose']=='open' else 'finished'
        if intent['purpose']=='open':state['opened_ms']=now
    else:state['phase']='unhedged' if intent['purpose']=='open' else 'flattening'

def reduce(state:dict[str,Any],spec:dict[str,Any],event:dict[str,Any], *,stress:Any=1):
    if state['spec_fingerprint']!=fingerprint(spec):raise ValueError('Portfolio version cannot change inside an existing journal')
    now=int(event.get('available_ms',event['received_ms']));receipt=int(event['received_ms']);stamp=int(event['event_ms'])
    identity=str(event['id']);digest=fingerprint(event);stress=number(stress)
    if identity in state['seen']:
        if state['seen'][identity]!=digest:raise ValueError('Conflicting event replay')
        return
    if not 0<=stamp<=receipt<=now or now<state['last_ms'] or not 1<=stress<100:
        raise ValueError('Noncausal event or invalid stress scenario')
    kind=event['kind'];market=event.get('market')
    if market is not None and market not in state['legs']:raise ValueError('Unknown portfolio instrument')
    if kind not in ('connection','heartbeat','bbo','funding','timer'):raise ValueError('Unsupported portfolio event')
    if kind!='timer' and market is None:raise ValueError('Market required for leg event')
    if kind in ('connection','heartbeat','bbo') and not isinstance(event.get('session'),str):raise ValueError('Connection session required')
    if kind=='connection' and type(event.get('connected')) is not bool:raise ValueError('Explicit connection state required')
    if kind=='bbo' and (not 0<number(event['bid'])<=number(event['ask']) or any(number(event[k])<0 for k in ('bid_size','ask_size'))):raise ValueError('Invalid executable quotes')
    if stress*number(spec['slippage_bps'])>=10000:raise ValueError('Stress scenario yields a nonpositive executable price')
    if kind=='funding':
        if stamp!=now:raise ValueError('Funding requires effective-time ordering; late settlement needs a replay')
        number(event['payment_per_unit'])
    # Apply disconnect before execution; a newly received quote cannot fill the
    # same event, but a disconnect cancels use of its previous connection.
    if kind=='connection':
        leg=state['legs'][market];leg['connected']=False;leg['quote']=None
    if kind=='funding':
        # Settlement precedes simulated orders due at exactly the same instant.
        leg=state['legs'][market];payment=number(event['payment_per_unit'])*number(leg['position'])
        leg['cash']=str(number(leg['cash'])+payment);leg['funding']=str(number(leg['funding'])+payment)
    _execute(state,spec,now,stress)
    if kind=='connection':
        leg=state['legs'][market];leg.update(session=event['session'],connected=event['connected'] is True,healthy_ms=now if event['connected'] is True else None,quote=None)
    elif kind=='heartbeat':
        leg=state['legs'][market]
        if leg['connected'] and event['session']==leg['session']:leg['healthy_ms']=now
    elif kind=='bbo':
        leg=state['legs'][market]
        if not 0<number(event['bid'])<=number(event['ask']) or any(number(event[k])<0 for k in ('bid_size','ask_size')):
            raise ValueError('Invalid executable quotes')
        leg['quote']={k:event[k] for k in ('bid','ask','bid_size','ask_size','session')}
        leg['quote']['available_ms']=now
    state['last_ms']=now;state['seen'][identity]=digest
    valuation=metrics(state,spec,now)
    if valuation['equity_usdc'] is not None:
        equity=number(valuation['equity_usdc']);peak=max(number(state['peak_equity']),equity);state['peak_equity']=str(peak)
        if peak-equity>number(spec['max_loss_usdc']) and not state['risk_halted']:
            state['risk_halted']=True;state['phase']='flattening'
            _intent(state,spec,{m:'0' for m in state['legs']},now,'flatten')
    if state['phase']=='waiting' and now>=spec['start_ms'] and not state['risk_halted'] and all(healthy(l,now,spec) for l in state['legs'].values()):
        targets={l['market']:str(l['target_units']) for l in spec['legs']}
        gross=sum(abs(number(targets[m]))*max(number(l['quote']['bid']),number(l['quote']['ask']))*(1+number(spec['slippage_bps'])*stress/10000) for m,l in state['legs'].items())
        if gross>number(spec['max_gross_usdc']):
            state['risk_halted']=True;state['phase']='finished';state['diagnostics'].append({'at_ms':now,'kind':'aggregate_risk_limit'})
        else:_intent(state,spec,targets,now,'open');state['phase']='opening'
    if state['phase']=='holding' and now-state['opened_ms']>=spec['horizon_ms']:
        state['phase']='flattening';_intent(state,spec,{m:'0' for m in state['legs']},now,'close')

def replay(spec:dict[str,Any],events:list[dict[str,Any]], *,stress:Any=1) -> dict[str,Any]:
    state=initial(spec)
    for event in sorted(events,key=lambda e:(e.get('available_ms',e['received_ms']),e['received_ms'])):reduce(state,spec,event,stress=stress)
    return {'state':state,'metrics':metrics(state,spec,state['last_ms']),
            'real_strategy_validated':False,'live_orders_enabled':False,
            'limits':['experimental fixed targets; not an inferred arbitrage strategy',
                      'two USDC perpetuals only; no liquidation/margin tiers or lot constraints yet',
                      'no paper promotion via this reference engine']}
