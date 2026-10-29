"""Deterministic, public-data-only strategy and virtual execution engine.

Same event reducer for replay and N2. Perpetual accounting: cash changes by
realized PnL, fees and funding; margin is not a spot purchase cash flow.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from statistics import NormalDist, mean, stdev
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def number(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Numeric value required") from exc
    if not result.is_finite():
        raise ValueError("Finite numeric value required")
    return result


def validate_spec(spec: dict[str, Any]) -> None:
    if isinstance(spec,dict) and spec.get('engine','single_perp_v2') not in {'single_perp_v2','single_perp_v3'}:
        raise ValueError('Unsupported mechanism: dedicated engine requires its own validation adapter')
    required = {"schema_version", "type", "market", "data_sources", "signal", "entry", "exit",
                "sizing", "max_exposure", "fees", "slippage", "latency_ms", "horizon_ms",
                "execution", "invalidation_conditions", "starting_capital_usdc"}
    if not isinstance(spec, dict) or not required <= spec.keys() or spec["schema_version"] != 2:
        raise ValueError("Executable strategy_spec v2 required; legacy prose is not executable")
    for key in ("signal", "entry", "exit", "sizing", "max_exposure", "fees", "slippage", "execution"):
        if not isinstance(spec[key],dict):
            raise ValueError(f"Structured {key} required")
    nested = {"sizing":{"scale"},"max_exposure":{"notional_usdc","max_drawdown_usdc","max_leverage"},"fees":{"maker_bps","taker_bps"},"slippage":{"bps"}}
    for key,fields in nested.items():
        if not fields <= spec[key].keys():
            raise ValueError(f"Missing executable {key} fields")
    if spec["type"] not in {"follower", "autonomous"}:
        raise ValueError("Explicit follower or autonomous type required")
    if not isinstance(spec["data_sources"], list) or not spec["data_sources"]:
        raise ValueError("Declare data sources")
    if spec["type"] == "autonomous" and "userFills" in spec["data_sources"]:
        raise ValueError("Autonomous strategies cannot use leader fills")
    expected = "leader_delta" if spec["type"] == "follower" else "momentum"
    if spec["signal"].get("kind") != expected:
        raise ValueError("Supported signals: follower leader_delta, autonomous momentum")
    if spec["entry"] != {"kind": "target_position"} or spec["exit"] != {"kind": "horizon_or_target"}:
        raise ValueError("Unsupported entry/exit rules")
    if spec["execution"].get("kind") not in {"market_ioc", "passive_conservative"}:
        raise ValueError("Unsupported execution model")
    if 'funding_witnesses' in spec['execution']:
        from .funding_witnesses import validate_contract
        validate_contract(spec['execution']['funding_witnesses'],market=spec['market'])
    funding_interval=spec["execution"].get("funding_observation_interval_ms")
    if funding_interval is not None and (type(funding_interval) is not int or funding_interval<=0):
        raise ValueError("Positive observed funding settlement interval required")
    settlement_clock=spec['execution'].get('funding_settlement_clock')
    if settlement_clock is not None and (settlement_clock!='reported_hour_with_inventory_invariance_v1'
                                         or funding_interval!=3_600_000):
        raise ValueError('Reported funding clock requires verified hourly settlement interval')
    sensitivity=spec['execution'].get('funding_sensitivity_scenario')
    if sensitivity is not None:
        from .funding_sensitivity import validate_scenario
        validate_scenario(sensitivity,market=spec['market'])
        if (spec.get('engine')!='single_perp_v3' or spec['execution'].get('funding_exposure_policy') is not None
                or spec['execution'].get('kind')!='market_ioc'):
            raise ValueError('Funding sensitivity requires priority IOC engine and excludes flat policy')
    exposure_policy=spec['execution'].get('funding_exposure_policy')
    if exposure_policy is not None:
        if (exposure_policy!='flat_at_settlement_v1' or spec.get('engine')!='single_perp_v3'
                or settlement_clock!='reported_hour_with_inventory_invariance_v1'
                or spec['execution'].get('kind')!='market_ioc'):
            raise ValueError('Flat-at-settlement policy requires hourly reported clock and priority IOC engine')
        quote_buffer=spec['execution'].get('max_quote_age_ms',spec['execution'].get('unknown_quote_max_age_ms'))
        if type(quote_buffer) is not int or quote_buffer<0:
            raise ValueError('Frozen quote-age funding exit buffer required')
    quote_contract=spec["execution"].get("quote_evidence_contract")
    if quote_contract is not None:
        if quote_contract!="bbo_or_l2book_v1" or not {"bbo","l2Book"}<=set(spec["data_sources"]):
            raise ValueError("BBO/l2Book quote contract requires both live market streams")
        if spec["execution"].get("max_quote_age_ms")!=1000:
            raise ValueError("BBO/l2Book execution freshness remains fixed at one second")
    residual_policy=spec["execution"].get("small_residual_policy")
    if residual_policy not in (None,"avoid_uncloseable_residual_v1"):
        raise ValueError("Unsupported small residual reduction policy")
    if residual_policy is not None and (spec.get('engine')!='single_perp_v3'
                                         or 'market_rules' not in spec['execution']):
        raise ValueError("Small residual policy requires versioned perp market rules")
    if 'market_rules' in spec['execution']:
        from .market_rules import validate_execution_rules
        validate_execution_rules(spec['execution']['market_rules'],spec['market'])
    for key in ("latency_ms", "horizon_ms"):
        if type(spec[key]) is not int or spec[key] < (1 if key == "horizon_ms" else 0):
            raise ValueError(f"Invalid {key}")
    if number(spec["starting_capital_usdc"]) <= 0 or number(spec["max_exposure"]["notional_usdc"]) <= 0:
        raise ValueError("Capital and exposure must be positive")
    for key in ("max_drawdown_usdc", "max_leverage"):
        if number(spec["max_exposure"][key]) <= 0:
            raise ValueError("Positive executable loss and leverage limits required")
    for value in (spec["fees"]["maker_bps"], spec["fees"]["taker_bps"], spec["slippage"]["bps"]):
        if number(value) < 0:
            raise ValueError("Nonnegative conservative costs required")
    for key in ("heartbeat_timeout_ms", "unknown_quote_max_age_ms", "order_ttl_ms"):
        if type(spec["execution"].get(key)) is not int or spec["execution"][key] < 1:
            raise ValueError(f"Positive execution.{key} required")
    if spec.get('engine') == 'single_perp_v3':
        for key in ('max_quote_age_ms','paper_tick_target_ms'):
            if type(spec['execution'].get(key)) is not int or spec['execution'][key] < 1:
                raise ValueError(f"Positive execution.{key} required for single_perp_v3")
    fraction = number(spec["execution"].get("displayed_size_fraction"))
    if not 0 < fraction <= 1:
        raise ValueError("Displayed size fraction must be in (0,1]")
    if not isinstance(spec["invalidation_conditions"], list) or not spec["invalidation_conditions"]:
        raise ValueError("Declare rejection conditions")
    if number(spec["sizing"]["scale"]) <= 0:
        raise ValueError("Positive size scale required")
    if expected == "momentum":
        if type(spec["signal"].get("lookback_ms")) is not int or spec["signal"]["lookback_ms"] < 1:
            raise ValueError("Positive momentum lookback required")
        if number(spec["signal"]["threshold_bps"]) <= 0 or number(spec["sizing"]["units"]) <= 0:
            raise ValueError("Positive momentum threshold and units required")


def initial_state(spec: dict[str, Any]) -> dict[str, Any]:
    validate_spec(spec)
    return {"cash": str(spec["starting_capital_usdc"]), "position": "0", "average_price": "0",
            "realized_pnl": "0", "fees": "0", "funding": "0", "quote": None,
            "session": None, "healthy_at_ms": None, "connected": False, "pending": [],
            "last_ms": -1, "opened_ms": None, "seen": [], "history": [], "fills": [],
            "equity_curve": [], "diagnostics": [], "missed_orders": 0, "partial_orders": 0,
            "execution_opportunities": [],
            "signals_received": 0, "max_exposure_notional_usdc": "0", "wait_conditions": [],
            "nonexecution_reasons": {},
            "exit_uncertainties": [], "paper_runtime": {},
            "leader_target": "0", "regimes": [], "funding_settlements": {}, "funding_events": 0, "risk_halted": False, "peak_equity": str(spec["starting_capital_usdc"]), "processing_lags_ms": []}


def quote_status(state: dict[str, Any], now: int, execution: dict[str, Any]) -> str:
    q = state["quote"]
    if not state["connected"] and state["session"] is not None:
        return "interrupted"
    if not q or q["received_ms"] >= now or q["event_ms"] > now:
        return "unavailable"
    if (execution.get("quote_evidence_contract")=="bbo_or_l2book_v1"
            and int(q.get("available_ms",10**18))>=now):
        return "unavailable"
    if (state["connected"] and q.get("session") == state["session"]
            and state["healthy_at_ms"] is not None
            and 0 <= now - state["healthy_at_ms"] <= execution["heartbeat_timeout_ms"]):
        max_age=execution.get('max_quote_age_ms')
        source_received=int(q.get('source_received_ms',q['received_ms']))
        if max_age is not None and not 0 <= now-source_received <= max_age:
            return "stale"
        return "continuous"
    if not state["connected"] and state["session"] is not None:
        return "interrupted"
    if 0 <= now - q["received_ms"] <= execution["unknown_quote_max_age_ms"]:
        return "unknown_recent"
    return "continuity_unknown"


def _fill(state: dict[str, Any], size: Decimal, price: Decimal, fee_bps: Decimal, now: int) -> None:
    old, average = number(state["position"]), number(state["average_price"])
    pnl = Decimal(0)
    if old * size < 0:
        closed = min(abs(old), abs(size))
        pnl = closed * (price - average) * (1 if old > 0 else -1)
    new = old + size
    if new == 0:
        average = Decimal(0)
    elif old == 0 or old * new < 0:
        average = price
    elif old * size > 0:
        average = (abs(old) * average + abs(size) * price) / abs(new)
    fee = abs(size) * price * fee_bps / 10000
    state["cash"] = str(number(state["cash"]) + pnl - fee)
    state["realized_pnl"] = str(number(state["realized_pnl"]) + pnl)
    state["fees"] = str(number(state["fees"]) + fee)
    state["position"], state["average_price"] = str(new), str(average)
    if old == 0 or old * new < 0:
        state["opened_ms"] = now if new else None
    if new == 0:
        state["opened_ms"] = None
    state["fills"].append({"received_ms": now, "size": str(size), "price": str(price),
                           "fee": str(fee), "realized_pnl": str(pnl)})


def _miss_order(state: dict[str, Any], reason: str) -> None:
    state["missed_orders"] += 1
    reasons=state.setdefault("nonexecution_reasons",{})
    reasons[reason]=reasons.get(reason,0)+1


def _is_reduction(position: Decimal, target: Decimal) -> bool:
    if position == 0:
        return target == 0
    if target == 0:
        return True
    return position * target > 0 and abs(target) <= abs(position)


def _wait_order(state: dict[str, Any], order: dict[str, Any], reason: str, now: int) -> None:
    if order.get('last_wait_reason') != reason:
        _miss_order(state,reason)
        order['last_wait_reason']=reason
    order['last_wait_ms']=now


def _record_v4_opportunity(state:dict[str,Any],spec:dict[str,Any],order:dict[str,Any],now:int,
                           *,eligible:bool,outcome:str,reason:str|None=None,fill_size:str|None=None,
                           order_size:str|None=None,order_notional_usdc:str|None=None,
                           order_selection:str|None=None,position_before:str|None=None,
                           position_after:str|None=None)->None:
    if spec.get('execution',{}).get('quote_evidence_contract')!='bbo_or_l2book_v1':return
    quote=state.get('quote') or {}
    received=quote.get('source_received_ms')
    state.setdefault('execution_opportunities',[]).append({
        'signal_decision_ms':order.get('decision_ms'),'due_ms':order.get('due_ms'),'execution_decision_ms':now,
        'intent':order.get('intent'),'eligible':eligible,'outcome':outcome,'reason':reason,
        'quote_source':quote.get('source'),'quote_received_ms':received,
        'quote_available_ms':quote.get('available_ms'),'quote_age_ms':now-int(received) if received is not None else None,
        'connection_id':quote.get('session'),
        'order_size':order_size,'order_notional_usdc':order_notional_usdc,
        'order_selection':order_selection,'partial_fill':outcome=='partial',
        'position_before':position_before if position_before is not None else str(state.get('position','0')),
        'position_after':position_after,'fill_size':fill_size})


def _funding_boundary(now: int, interval: int) -> int:
    return (now // interval + 1) * interval


def _funding_entry_guard(state,spec,now,target,*,at_execution=False):
    if (spec['execution'].get('funding_exposure_policy')!='flat_at_settlement_v1'
            or _is_reduction(number(state['position']),target)):
        return None
    interval=spec['execution']['funding_observation_interval_ms'];slot=now//interval*interval
    reports=[record for record in state.get('funding_settlements',{}).values()
             if record.get('scheduled_ms')==slot and record['available_ms']<now]
    if not reports:return 'current_hour_reported_funding_clock_unavailable'
    buffer=spec['execution'].get('max_quote_age_ms',spec['execution']['unknown_quote_max_age_ms'])
    lead=spec['horizon_ms']+spec['latency_ms']+spec['execution']['order_ttl_ms']+buffer
    if not at_execution:lead+=spec['latency_ms']
    if now+lead>=slot+interval:return 'entry_exit_buffer_overlaps_next_funding_hour'
    return None


def _execute_v3(state: dict[str, Any], spec: dict[str, Any], now: int, stress: Decimal) -> None:
    remaining=[]
    for order in state['pending']:
        pos=number(state['position'])
        if order['due_ms']>now:
            remaining.append(order);continue
        intent=order.get('intent')
        mandatory_exit=intent in {'horizon_exit','risk_exit'}
        # A target adjustment can be smaller than one venue lot. Resolve that
        # no-op before TTL handling so it cannot be mislabeled as a missed
        # mandatory close (or hold the priority slot indefinitely).
        rules=spec['execution'].get('market_rules')
        if order.get('reduce_only') and pos!=0 and not mandatory_exit and rules:
            from .market_rules import round_size
            adjustment_target=number(order['target'])
            if not _is_reduction(pos,adjustment_target):
                adjustment_target=Decimal(0)
            if not round_size(adjustment_target-pos,rules['sz_decimals']):
                _miss_order(state,'reduce_only_adjustment_rounded_to_zero')
                _record_v4_opportunity(state,spec,order,now,eligible=False,outcome='missed',reason='reduce_only_adjustment_rounded_to_zero')
                continue
        if now>order['expires_ms']:
            _miss_order(state,'order_ttl_expired')
            _record_v4_opportunity(state,spec,order,now,eligible=False,outcome='missed',reason='order_ttl_expired')
            if mandatory_exit and pos!=0:
                uncertainty={'at_ms':now,'reason':'priority_exit_expired_without_simulated_close',
                             'position':str(pos),'target':order['target']}
                state.setdefault('exit_uncertainties',[]).append(uncertainty)
                if 'priority_exit_unresolved_position' not in state['diagnostics']:
                    state['diagnostics'].append('priority_exit_unresolved_position')
                state['risk_halted']=True
            continue
        status=quote_status(state,now,spec['execution'])
        if status!='continuous':
            reason={'stale':'quote_stale_at_execution','interrupted':'quote_stream_interrupted',
                    'continuity_unknown':'quote_continuity_unknown'}.get(status,'quote_unavailable_at_execution')
            _wait_order(state,order,reason,now)
            _record_v4_opportunity(state,spec,order,now,eligible=False,outcome='missed',reason=reason)
            remaining.append(order);continue
        q=state['quote']
        if rules:
            from .market_rules import valid_price,round_size
            if rules['available_ms']>now or not all(valid_price(q[side],rules['sz_decimals']) for side in ('bid','ask')):
                _wait_order(state,order,'venue_rules_unavailable_or_price_precision_invalid',now)
                _record_v4_opportunity(state,spec,order,now,eligible=True,outcome='missed',reason='venue_rules_unavailable_or_price_precision_invalid')
                remaining.append(order);continue
        target=number(order['target'])
        if order.get('reduce_only'):
            if pos==0:
                continue
            # A reduce-only close cannot cross through flat or increase exposure.
            if not _is_reduction(pos,target):
                target=Decimal(0)
        elif target and not _is_reduction(pos,target):
            interval=spec['execution'].get('funding_interval_ms')
            if type(interval) is int and interval>0 and now+spec['horizon_ms']>=_funding_boundary(now,interval):
                _miss_order(state,'position_horizon_overlaps_funding_boundary_at_execution')
                _record_v4_opportunity(state,spec,order,now,eligible=True,outcome='missed',reason='position_horizon_overlaps_funding_boundary_at_execution')
                continue
        limit=number(spec['max_exposure']['notional_usdc'])
        mark=max(number(q['bid']),number(q['ask']))*(1+number(spec['slippage']['bps'])*stress/10000)
        equity=number(state['cash'])+pos*(number(q['bid'] if pos>=0 else q['ask'])-number(state['average_price']))
        limit=min(limit,max(Decimal(0),equity)*number(spec['max_exposure']['max_leverage']))
        if rules:limit=min(limit,max(Decimal(0),equity)*number(rules['max_leverage']))
        target=max(-limit/mark,min(limit/mark,target))
        residual_policy=spec['execution'].get('small_residual_policy')
        exit_px=number(q['bid'] if pos>0 else q['ask'])
        minimum=number(rules['minimum_order_usdc']) if rules else Decimal(0)
        order_selection=None
        if (residual_policy=='avoid_uncloseable_residual_v1' and rules
                and order.get('reduce_only') and pos!=0 and target*pos>0
                and abs(target)<abs(pos) and 0<abs(target)*exit_px<minimum
                and abs(pos)*exit_px>=minimum):
            # Choose the admissible full-close instruction before simulating
            # any depth-limited fill; the fill remains independent of policy.
            target=Decimal(0)
            order_selection='full_close_selected_to_avoid_subminimum_residual'
        delta=target-pos
        if rules:delta=round_size(delta,rules['sz_decimals'])
        order_notional=abs(delta)*number(q['ask'] if delta>0 else q['bid']) if delta else Decimal(0)
        if not delta:
            _miss_order(state,'zero_adjustment_after_rounding')
            _record_v4_opportunity(state,spec,order,now,eligible=True,outcome='missed',reason='zero_adjustment_after_rounding',
                order_size=str(delta),order_notional_usdc=str(order_notional),order_selection=order_selection)
            continue
        buy=delta>0
        if rules and abs(delta)*number(q['ask'] if buy else q['bid'])<number(rules['minimum_order_usdc']):
            if order.get('reduce_only'):
                if mandatory_exit:
                    _wait_order(state,order,'priority_exit_below_venue_minimum',now)
                    _record_v4_opportunity(state,spec,order,now,eligible=True,outcome='missed',reason='priority_exit_below_venue_minimum',
                        order_size=str(delta),order_notional_usdc=str(order_notional),order_selection=order_selection)
                    remaining.append(order)
                else:
                    _miss_order(state,'reduce_only_adjustment_below_venue_minimum')
                    _record_v4_opportunity(state,spec,order,now,eligible=True,outcome='missed',reason='reduce_only_adjustment_below_venue_minimum',
                        order_size=str(delta),order_notional_usdc=str(order_notional),order_selection=order_selection)
            else:
                _miss_order(state,'below_venue_minimum_order_value')
                _record_v4_opportunity(state,spec,order,now,eligible=True,outcome='missed',reason='below_venue_minimum_order_value',
                    order_size=str(delta),order_notional_usdc=str(order_notional),order_selection=order_selection)
            continue
        if spec['execution']['kind']=='passive_conservative':
            _miss_order(state,'passive_queue_priority_unavailable')
            _record_v4_opportunity(state,spec,order,now,eligible=True,outcome='missed',reason='passive_queue_priority_unavailable',
                order_size=str(delta),order_notional_usdc=str(order_notional),order_selection=order_selection)
            continue
        available=number(q['ask_size'] if buy else q['bid_size'])*number(spec['execution']['displayed_size_fraction'])/stress
        size=min(abs(delta),max(Decimal(0),available))*(1 if buy else -1)
        if rules:size=round_size(size,rules['sz_decimals'])
        if not size:
            if order.get('reduce_only'):
                _wait_order(state,order,'priority_exit_insufficient_visible_size',now)
                _record_v4_opportunity(state,spec,order,now,eligible=True,outcome='missed',reason='priority_exit_insufficient_visible_size',
                    order_size=str(delta),order_notional_usdc=str(order_notional),order_selection=order_selection)
                remaining.append(order)
            else:
                _miss_order(state,'insufficient_visible_size_or_lot_rounding')
                _record_v4_opportunity(state,spec,order,now,eligible=True,outcome='missed',reason='insufficient_visible_size_or_lot_rounding',
                    order_size=str(delta),order_notional_usdc=str(order_notional),order_selection=order_selection)
            continue
        if abs(size)<abs(delta):state['partial_orders']+=1
        price=number(q['ask'] if buy else q['bid'])
        price*=1+number(spec['slippage']['bps'])*stress/10000*(1 if buy else -1)
        position_before=str(state['position'])
        _record_v4_opportunity(state,spec,order,now,eligible=True,
            outcome='partial' if abs(size)<abs(delta) else 'executed',reason=None,fill_size=str(size),
            order_size=str(delta),order_notional_usdc=str(order_notional),order_selection=order_selection,
            position_before=position_before,position_after=str(number(position_before)+size))
        _fill(state,size,price,number(spec['fees']['taker_bps'])*stress,now)
        if order.get('reduce_only') and number(state['position'])!=0:
            order['due_ms']=now
            remaining.append(order)
    state['pending']=remaining


def _execute(state: dict[str, Any], spec: dict[str, Any], now: int, stress: Decimal) -> None:
    blocked=[]
    if spec['execution'].get('funding_exposure_policy')=='flat_at_settlement_v1':
        accepted=[]
        for order in state['pending']:
            reason=_funding_entry_guard(state,spec,now,number(order['target']),at_execution=True)
            if reason:
                _miss_order(state,reason)
                _record_v4_opportunity(state,spec,order,now,eligible=False,outcome='missed',reason=reason)
            else:accepted.append(order)
        state['pending']=accepted
    if state.get('funding_cost_status')=='pending':
        allowed=[]
        for order in state['pending']:
            if _is_reduction(number(state['position']),number(order['target'])):
                allowed.append(order)
            elif now>order['expires_ms']:
                _miss_order(state,'order_ttl_expired')
            else:
                _wait_order(state,order,'funding_cost_pending_new_exposure',now)
                blocked.append(order)
        state['pending']=allowed
    if spec.get('engine')=='single_perp_v3':
        _execute_v3(state,spec,now,stress)
        state['pending'].extend(blocked)
        return
    remaining = []
    for order in state["pending"]:
        if order["due_ms"] > now:
            remaining.append(order)
            continue
        if now > order["expires_ms"]:
            _miss_order(state,"order_ttl_expired")
            continue
        if quote_status(state, now, spec["execution"]) != "continuous":
            _miss_order(state,"quote_or_stream_unavailable")
            continue
        q = state["quote"]
        rules=spec['execution'].get('market_rules')
        if rules:
            from .market_rules import valid_price,round_size
            if rules['available_ms']>now or not all(valid_price(q[side],rules['sz_decimals']) for side in ('bid','ask')):
                _miss_order(state,"venue_rules_unavailable_or_price_precision_invalid")
                continue
        target = number(order["target"])
        limit = number(spec["max_exposure"]["notional_usdc"])
        # Check exposure against the adverse side including simulated slippage.
        mark = max(number(q["bid"]), number(q["ask"])) * (1 + number(spec["slippage"]["bps"]) * stress / 10000)
        pos = number(state["position"])
        equity = number(state["cash"]) + pos * (number(q["bid"] if pos >= 0 else q["ask"]) - number(state["average_price"]))
        limit = min(limit, max(Decimal(0), equity) * number(spec["max_exposure"]["max_leverage"]))
        if rules:limit=min(limit,max(Decimal(0),equity)*number(rules['max_leverage']))
        target = max(-limit / mark, min(limit / mark, target))
        delta = target - number(state["position"])
        if rules:delta=round_size(delta,rules['sz_decimals'])
        if not delta:
            continue
        buy = delta > 0
        if rules and abs(delta)*number(q['ask'] if buy else q['bid'])<number(rules['minimum_order_usdc']):
            _miss_order(state,"below_venue_minimum_order_value")
            continue
        passive = spec["execution"]["kind"] == "passive_conservative"
        if passive:
            # Public depth does not establish queue priority. Default no fill,
            # including when the limit is touched. Explicit future queue models
            # must be implemented/versioned before they can change this rule.
            _miss_order(state,"passive_queue_priority_unavailable")
            continue
        available_key = "ask_size" if buy else "bid_size"
        available = number(q.get(available_key, 0)) * number(spec["execution"]["displayed_size_fraction"]) / stress
        size = min(abs(delta), max(Decimal(0), available)) * (1 if buy else -1)
        if rules:size=round_size(size,rules['sz_decimals'])
        if not size:
            _miss_order(state,"insufficient_visible_size_or_lot_rounding")
            continue
        if abs(size) < abs(delta):
            state["partial_orders"] += 1
        price = number(q["ask"] if buy else q["bid"])
        price *= 1 + number(spec["slippage"]["bps"]) * stress / 10000 * (1 if buy else -1)
        _fill(state, size, price, number(spec["fees"]["taker_bps"]) * stress, now)
    state["pending"] = remaining+blocked


def _order(state: dict[str, Any], spec: dict[str, Any], target: Decimal, now: int,
           *, intent: str | None = None) -> None:
    reason=_funding_entry_guard(state,spec,now,target)
    if reason:
        _miss_order(state,reason)
        return
    if state.get('funding_cost_status')=='pending' and not _is_reduction(number(state['position']),target):
        _miss_order(state,'funding_cost_pending_new_exposure')
        return
    if state["risk_halted"] and target != 0:
        return
    if spec.get('engine')=='single_perp_v3':
        position=number(state['position'])
        inferred=intent or ('reduction' if _is_reduction(position,target) else 'signal_target')
        priority={'signal_target':10,'reduction':50,'horizon_exit':100,'risk_exit':200}.get(inferred,10)
        existing=state.get('pending',[])
        if existing and int(existing[0].get('priority',0))>priority:
            return
        if existing and existing[0].get('intent')=='horizon_exit' and inferred=='horizon_exit':
            return
        if number(target)==position:
            if existing and int(existing[0].get('priority',0))<=priority:
                state['pending']=[]
            return
        reduce_only=inferred in {'reduction','horizon_exit','risk_exit'} or _is_reduction(position,target)
        state['pending']=[{"target":str(target),"due_ms":now+spec['latency_ms'],
                           "expires_ms":now+spec['latency_ms']+spec['execution']['order_ttl_ms'],
                           "intent":inferred,"priority":priority,"reduce_only":reduce_only,
                           "decision_ms":now}]
        return
    state["pending"] = [{"target": str(target), "due_ms": now + spec["latency_ms"],
                         "expires_ms": now + spec["latency_ms"] + spec["execution"]["order_ttl_ms"]}]


def reduce_event(state: dict[str, Any], spec: dict[str, Any], event: dict[str, Any], *, stress: Decimal = Decimal(1), _seen_ids: set[str] | None = None) -> None:
    """Consume ordered local receipts. Equal-ms quotes cannot fill a decision.

    Timers execute before the incoming message, so the message being received
    cannot be used retrospectively to execute an older order.
    """
    receipt, exchange = int(event["received_ms"]), int(event["event_ms"])
    now = int(event.get("available_ms",receipt))
    if now < receipt:
        raise ValueError("Availability precedes local receipt")
    event_id = str(event["id"])
    if event_id in (state["seen"] if _seen_ids is None else _seen_ids):
        return
    if now < state["last_ms"] or exchange > receipt:
        raise ValueError("Noncausal or out-of-order event")
    if stress < 1:
        raise ValueError("Stress multiplier must be >= 1")
    state["seen"].append(event_id)
    if _seen_ids is not None:
        _seen_ids.add(event_id)
    state["processing_lags_ms"].append(now-receipt)
    if (spec.get('engine')=='single_perp_v3' and state.get('opened_ms') is not None
            and number(state['position'])!=0 and now-int(state['opened_ms'])>=spec['horizon_ms']):
        _order(state,spec,Decimal(0),now,intent='horizon_exit')
    unavailable = (event["kind"] == "connection" and event.get("connected") is False) or (event["kind"] in {"heartbeat","subscriptions"} and "markets" in event and spec["market"] not in event["markets"])
    if 'paper_funding_started_ms' in state:
        audit=funding_coverage(state,spec,{'start_ms':state['paper_funding_started_ms'],
            'end_ms':max(state['paper_funding_started_ms']+1,now+1)})
        state['funding_cost_status']='complete' if audit['state']=='complete' else 'pending'
    if 'funding_sensitivity_scenario' in spec['execution']:
        from .funding_sensitivity import apply_through
        apply_through(state,spec,now,stress)
    if not unavailable:
        _execute(state, spec, now, stress)
    state["last_ms"] = now
    kind = event["kind"]
    if kind == "connection":
        state["session"], state["connected"] = event["session"], event["connected"] is True
        state["healthy_at_ms"] = receipt if state["connected"] else None
        state["quote"] = None
        if not state["connected"]:
            state["pending"] = []
            if state.get("experimental_initial_feed") and not state.get("signals_received") and not state.get("fills") and number(state["position"]) == 0:
                state.setdefault("wait_conditions", []).append("initial_stream_reconnected_before_signal")
            else:
                state["diagnostics"].append("connection_interrupted")
    elif kind == "subscriptions":
        if spec["market"] not in event["markets"]:
            state["quote"] = None
            state["pending"] = []
            state["diagnostics"].append("market_subscription_missing")
    elif kind == "heartbeat":
        if "markets" in event and spec["market"] not in event["markets"]:
            state["quote"] = None
            state["pending"] = []
            state["diagnostics"].append("market_subscription_missing")
        if state["session"] != event["session"]:
            initial_rebind = (state.get("experimental_initial_feed") and not state.get("signals_received")
                              and not state.get("fills") and number(state["position"]) == 0
                              and not state["pending"])
            if state["session"] is not None and not initial_rebind:
                state["diagnostics"].append("connection_changed_without_reconciliation")
            if initial_rebind:
                state.setdefault("wait_conditions", []).append("initial_stream_reconnected_before_signal")
            state["session"], state["connected"] = event["session"], True
            state["quote"] = None
        if state["connected"] and event["session"] == state["session"]:
            state["healthy_at_ms"] = receipt
    elif kind in {"bbo", "l2book"}:
        bid, ask = number(event["bid"]), number(event["ask"])
        if not 0 < bid <= ask:
            raise ValueError("Invalid BBO/l2Book top level")
        state["quote"] = {k: event[k] for k in ("received_ms", "event_ms", "bid", "ask", "bid_size", "ask_size", "session")}
        state["quote"]["source"] = event.get("source", "bbo" if kind=="bbo" else "l2Book")
        state["quote"]["source_received_ms"] = receipt
        state["quote"]["available_ms"] = now
        if spec.get('engine')=='single_perp_v3':
            state["quote"]["processed_ms"] = now
        else:
            state["quote"]["received_ms"] = now
        mid = (bid + ask) / 2
        if spec["type"] == "autonomous":
            history = state["history"]
            cutoff = now - spec["signal"]["lookback_ms"]
            prior = [p for p in history if p[0] <= cutoff]
            if prior:
                change = (mid / number(prior[-1][1]) - 1) * 10000
                threshold = number(spec["signal"]["threshold_bps"])
                target = number(spec["sizing"]["units"]) * number(spec["sizing"]["scale"]) * (1 if change > threshold else -1 if change < -threshold else 0)
                _order(state, spec, target, now)
            history.append([now, str(mid)])
            # Retain one older point to anchor the causal lookback.
            older = [p for p in history if p[0] <= cutoff]
            state["history"] = older[-1:] + [p for p in history if p[0] > cutoff]
    elif kind == "leader_fill" and spec["type"] == "follower":
        if event.get("is_snapshot") is not False:
            state["diagnostics"].append("leader_signal_not_live")
        else:
            state["experimental_initial_feed"] = False
            state["signals_received"] = state.get("signals_received", 0) + 1
            target = number(state["leader_target"]) + number(event["delta"]) * number(spec["sizing"]["scale"])
            interval=spec["execution"].get("funding_interval_ms")
            horizon_expired=(spec.get('engine')=='single_perp_v3' and state.get('opened_ms') is not None
                             and number(state['position'])!=0
                             and now-int(state['opened_ms'])>=spec['horizon_ms'])
            if horizon_expired:
                _miss_order(state,'signal_after_horizon_exit_started')
                _order(state,spec,Decimal(0),now,intent='horizon_exit')
            elif target and type(interval) is int and interval>0:
                next_funding=_funding_boundary(now,interval)
                reduce_only=(spec.get('engine')=='single_perp_v3'
                             and _is_reduction(number(state['position']),target))
                lead=spec['latency_ms']+spec['horizon_ms']
                if not reduce_only and now+lead>=next_funding:
                    _miss_order(state,"position_horizon_overlaps_funding_boundary")
                else:
                    state["leader_target"]=str(target)
                    if spec.get('engine')=='single_perp_v3':
                        _order(state,spec,target,now,intent='reduction' if reduce_only else 'signal_target')
                    else:
                        _order(state,spec,target,now)
            else:
                state["leader_target"]=str(target)
                if spec.get('engine')=='single_perp_v3':
                    _order(state,spec,target,now,intent='reduction' if _is_reduction(number(state['position']),target) else 'signal_target')
                else:
                    _order(state,spec,target,now)
    elif kind == "funding":
        # Rate is applied to OUR position at this funding event; leader's USDC
        # funding payment is never reused. Event mark is an observed input.
        coefficient = (number(event["unit_funding_usdc"]) if "unit_funding_usdc" in event
                       else -number(event["mark"]) * number(event["rate"]))
        settlements=state.setdefault("funding_settlements",{})
        previous=settlements.get(str(exchange))
        reported_clock=spec['execution'].get('funding_settlement_clock')=='reported_hour_with_inventory_invariance_v1'
        scheduled=(exchange//spec['execution']['funding_observation_interval_ms'])*spec['execution']['funding_observation_interval_ms'] if reported_clock else exchange
        ambiguous=any(scheduled<=f['received_ms']<=exchange for f in state['fills'])
        prior_position=sum((number(f['size']) for f in state['fills'] if f['received_ms']<scheduled),Decimal(0))
        same_slot=[stamp for stamp in settlements if reported_clock and int(stamp)!=exchange
                   and int(stamp)//spec['execution']['funding_observation_interval_ms']==exchange//spec['execution']['funding_observation_interval_ms']]
        last_report=max([exchange,*[int(stamp) for stamp in same_slot]])
        zero_interval=(not prior_position and not any(scheduled<=f['received_ms']<=last_report for f in state['fills']))
        def source_issue(kind):
            issue={'kind':kind,'scheduled_ms':scheduled,'reported_ms':exchange,'event_id':event_id}
            issues=state.setdefault('funding_source_diagnostics',[])
            if issue not in issues:issues.append(issue)
            if (not zero_interval and 'funding_sensitivity_scenario' not in spec['execution']
                    and kind not in state['diagnostics']):
                state['diagnostics'].append(kind)
        if same_slot:
            source_issue('multiple_reported_funding_times_in_slot')
            ambiguous=not zero_interval
        if ambiguous:source_issue('funding_inventory_at_settlement_ambiguous')
        if previous is not None:
            if number(previous['unit_funding_usdc'])!=coefficient:
                source_issue('conflicting_funding_settlement_coefficients')
        else:
            # Fill timestamps are OUR simulated execution/availability times,
            # not the source fill event times. A delayed receipt uses inventory
            # at settlement, including a position subsequently closed. Equal-ms
            # ordering is unknown and must never fabricate a funding payment.
            effective_position = sum((number(f["size"]) for f in state["fills"]
                                      if f["received_ms"] < exchange), Decimal(0))
            settlements[str(exchange)]={"unit_funding_usdc":str(coefficient),
                "received_ms":receipt,"available_ms":now,
                "scheduled_ms":scheduled,"reported_ms":exchange,"reported_offset_ms":exchange-scheduled,
                "settlement_clock":spec["execution"].get("funding_settlement_clock","exact_epoch_v1"),
                "provenance":event.get("provenance"),"evidence_ref":event.get("evidence_ref"),
                "archive_response_sha256":event.get("archive_response_sha256"),
                "source_period":event.get("source_period"),"source_address":event.get("source_address"),
                "inventory_at_settlement":None if ambiguous else str(effective_position)}
            settlements[str(exchange)]['observed_payment_component']=(None if ambiguous else str(effective_position*coefficient))
            if not ambiguous and 'funding_sensitivity_scenario' not in spec['execution']:
                payment=effective_position*coefficient
                state["cash"] = str(number(state["cash"]) + payment)
                state["funding"] = str(number(state["funding"]) + payment)
            state["funding_events"] += 1
    elif kind == "regime":
        if event["label"] not in state["regimes"]:
            state["regimes"].append(event["label"])
    if state["opened_ms"] is not None and now - state["opened_ms"] >= spec["horizon_ms"]:
        if spec.get('engine')=='single_perp_v3':
            _order(state,spec,Decimal(0),now,intent='horizon_exit')
        elif not state["pending"]:
            _order(state, spec, Decimal(0), now)
    if state["quote"]:
        q = state["quote"]
        # Liquidation-side mark includes spread; realized cash already includes
        # fees/slippage. Do not subtract spread again.
        pos = number(state["position"])
        exposure = abs(pos) * (number(q["bid"]) + number(q["ask"])) / 2
        state["max_exposure_notional_usdc"] = str(max(number(state.get("max_exposure_notional_usdc", 0)), exposure))
        mark = number(q["bid"] if pos >= 0 else q["ask"])
        unrealized = pos * (mark - number(state["average_price"]))
        equity = number(state["cash"]) + unrealized
        state["peak_equity"] = str(max(number(state["peak_equity"]), equity))
        state["equity_curve"].append([now, str(equity)])
        if number(state["peak_equity"]) - equity >= number(spec["max_exposure"]["max_drawdown_usdc"]) and not state["risk_halted"]:
            state["risk_halted"] = True
            state["diagnostics"].append("risk_drawdown_with_unknown_funding" if
                state.get("funding_cost_status")=="pending" else "risk_drawdown_limit")
            _order(state,spec,Decimal(0),now,intent='risk_exit' if spec.get('engine')=='single_perp_v3' else None)


def funding_coverage(state: dict[str, Any], spec: dict[str, Any],
                     observation_window: dict[str,int] | None = None) -> dict[str,Any]:
    """Audit every settlement at which OUR inventory needed a coefficient.

    Hourly venue settlements use UTC epoch boundaries. A known empty inventory
    establishes zero cost without inventing an observed settlement or rate.
    Missing interval/ledger ordering remains unknown, never zero funding.
    """
    interval=spec['execution'].get('funding_observation_interval_ms')
    result={'version':'funding-exposure-coverage-v1','interval_ms':interval,
            'state':'unknown','required_settlements':[], 'missing_settlements':[],
            'ambiguous_settlements':[],'observed_settlement_count':len(state.get('funding_settlements',{})),
            'zero_exposure_settlements':0}
    if type(interval) is not int or interval<=0:
        result['reason']='verified_funding_interval_missing';return result
    if observation_window is None:
        stamps=[point[0] for point in state['equity_curve']]
        if not stamps:
            result['reason']='observation_window_missing';return result
        observation_window={'start_ms':min(stamps),'end_ms':max(stamps)+1}
    start,end=observation_window['start_ms'],observation_window['end_ms']
    if type(start) is not int or type(end) is not int or not 0<=start<end:
        raise ValueError('Explicit half-open funding observation window required')
    result['observation_window']=dict(observation_window)
    reported_clock=spec['execution'].get('funding_settlement_clock')=='reported_hour_with_inventory_invariance_v1'
    first=(start//interval)*interval if reported_clock else ((start+interval-1)//interval)*interval
    result['settlement_clock']=spec['execution'].get('funding_settlement_clock','exact_epoch_v1')
    if max(0,(end-1-first)//interval+1)>100_000:
        result['reason']='funding_boundary_audit_resource_limit';return result
    fills=sorted(state['fills'],key=lambda f:f['received_ms'])
    fill_stamps=[fill['received_ms'] for fill in fills]
    position=Decimal(0);index=0
    settlements=state.get('funding_settlements',{})
    slots={}
    for stamp in settlements:
        actual=int(stamp);slot=actual//interval*interval if reported_clock else actual
        slots.setdefault(slot,[]).append(actual)
    result['reported_settlements']=[{'scheduled_ms':slot,'reported_ms':actual,'offset_ms':actual-slot}
        for slot,actuals in sorted(slots.items()) for actual in sorted(actuals)]
    result['multiple_reported_time_slots']=[]
    result['unresolved_report_time_slots']=[]
    result['source_data_diagnostics']=list(state.get('funding_source_diagnostics',[]))
    cost_diagnostics=[]
    for boundary in range(first,end,interval):
        while index<len(fills) and fills[index]['received_ms']<boundary:
            position+=number(fills[index]['size']);index+=1
        actuals=slots.get(boundary,[])
        issues=[issue['kind'] for issue in state.get('funding_source_diagnostics',[])
                if issue['scheduled_ms']==boundary]
        if reported_clock and len(actuals)>1:result['multiple_reported_time_slots'].append(boundary)
        zero_interval=(not position and actuals and
            bisect_left(fill_stamps,boundary)==bisect_right(fill_stamps,max(actuals)))
        if zero_interval:
            # Any coefficient, including conflicting/unidentified ones, has
            # exactly zero effect when our inventory was provably zero across
            # every reported clock possibility. Keep source issues separate.
            result['zero_exposure_settlements']+=1
            continue
        cost_diagnostics.extend(issues)
        if reported_clock and len(actuals)>1:
            result['ambiguous_settlements'].append(boundary)
        elif reported_clock and actuals and bisect_left(fill_stamps,boundary)<bisect_right(fill_stamps,actuals[0]):
            result['ambiguous_settlements'].append(boundary)
        elif index<len(fills) and fills[index]['received_ms']==boundary:
            result['ambiguous_settlements'].append(boundary)
        elif position:
            result['required_settlements'].append(boundary)
            if not actuals:result['missing_settlements'].append(boundary)
        elif reported_clock and not actuals and bisect_left(fill_stamps,boundary)<bisect_left(fill_stamps,min(end,boundary+interval)):
            # Without a reported time, a later trade in the bucket might
            # overlap settlement. Scheduled-time flatness is not proof of zero.
            result['unresolved_report_time_slots'].append(boundary)
        else:result['zero_exposure_settlements']+=1
    malformed=[] if reported_clock else [int(stamp) for stamp in settlements if int(stamp)%interval]
    result['off_boundary_settlements']=sorted(malformed)
    result['diagnostics']=sorted(set(cost_diagnostics))
    result['state']=('incomplete' if result['missing_settlements'] or result['ambiguous_settlements']
                     or result['unresolved_report_time_slots'] or malformed or cost_diagnostics else 'complete')
    result['cost_basis']=('funding_cost_incomplete_or_ambiguous' if result['state']!='complete' else
                          'observed_coefficients_for_every_exposed_boundary' if result['required_settlements'] else
                          'no_inventory_at_any_settlement_boundary')
    return result


def metrics(state: dict[str, Any], spec: dict[str, Any], block_ms: int, *, confidence_alpha: float = 0.05) -> dict[str, Any]:
    if block_ms <= 0:
        raise ValueError("Positive independent block duration required")
    capital = number(state.get("session_starting_capital_usdc",spec["starting_capital_usdc"]))
    curve = state["equity_curve"]
    final = number(curve[-1][1]) if curve else capital
    peak, drawdown = capital, Decimal(0)
    blocks: dict[int, Decimal] = {}
    previous = capital
    for stamp, value in curve:
        equity = number(value)
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        blocks[stamp // block_ms] = blocks.get(stamp // block_ms, Decimal(0)) + equity - previous
        previous = equity
    values = [float(v) for v in blocks.values()]
    positive = sorted([v for v in values if v > 0], reverse=True)
    # Descriptive uncertainty only; blocks are not asserted IID. Configured
    # block duration must be justified against episode dependence.
    if not 0 < confidence_alpha < 1:
        raise ValueError("Invalid confidence alpha")
    quantile = NormalDist().inv_cdf(1-confidence_alpha/2)
    lower = mean(values) - quantile * stdev(values) / math.sqrt(len(values)) if len(values) >= 2 else None
    return {"starting_capital_usdc":str(capital),"net_pnl": str(final - capital), "realized_pnl": state["realized_pnl"],
            "unrealized_pnl": str(final - number(state["cash"])), "fees": state["fees"],
            "funding": state["funding"], "drawdown_usdc": str(drawdown),
            "block_count": len(values), "block_mean_lower_95_descriptive": lower,
            "largest_positive_block_share": positive[0] / sum(positive) if positive else None,
            "regimes": state["regimes"], "fills": len(state["fills"]),
            "signals_received": state.get("signals_received",0),
            "max_exposure_notional_usdc": state.get("max_exposure_notional_usdc","0"),
            "missed_orders": state["missed_orders"], "partial_orders": state["partial_orders"],
            "flat_end": number(state["position"]) == 0, "pending_end": len(state["pending"]),
            "funding_events": state["funding_events"], "diagnostics": sorted(set(state["diagnostics"])),
            "funding_source_diagnostics":state.get("funding_source_diagnostics",[]),
            "processing_lag_max_ms": max(state["processing_lags_ms"],default=0),
            "confidence_alpha": confidence_alpha,
            "uncertainty_assumption": "descriptive block estimate; independence is not established",
            "benchmark_cash_net_pnl": "0"}


def hold_benchmark(spec: dict[str,Any], events: list[dict[str,Any]], stress: Decimal) -> str | None:
    """Descriptive long market exposure with matched initial strategy size.

    It is liquidated at the final bid with both sides' fees/slippage; public
    displayed size bounds the initial quantity. This is not a passive fill.
    """
    ordered = sorted(events,key=lambda e:(e.get("available_ms",e["received_ms"]),e["received_ms"],str(e["id"])))
    quotes = [e for e in ordered if e["kind"] == "bbo"]
    if not quotes:
        return None
    first,last = quotes[0],quotes[-1]
    if spec["type"] == "follower":
        signals = [e for e in ordered if e["kind"] == "leader_fill" and e.get("is_snapshot") is False]
        if not signals:
            return None
        signal = signals[0]
        prior = [q for q in quotes if q.get("available_ms",q["received_ms"]) < signal.get("available_ms",signal["received_ms"])]
        if not prior:
            return None
        first = prior[-1]
        units = abs(number(signal["delta"]))*number(spec["sizing"]["scale"])
    else:
        units = number(spec["sizing"]["units"])*number(spec["sizing"]["scale"])
    slip = number(spec["slippage"]["bps"])*stress/10000
    entry = number(first["ask"])*(1+slip)
    exit_price = number(last["bid"])*(1-slip)
    units = min(units,number(first["ask_size"])*number(spec["execution"]["displayed_size_fraction"])/stress,number(spec["max_exposure"]["notional_usdc"])/entry)
    pnl = units*(exit_price-entry) - units*(entry+exit_price)*number(spec["fees"]["taker_bps"])*stress/10000
    sensitivity=spec['execution'].get('funding_sensitivity_scenario')
    if sensitivity is not None:
        count=max(0,last['event_ms']//3_600_000-first['event_ms']//3_600_000)
        return str(pnl-abs(units)*number(sensitivity['debit_usdc_per_base_unit'])*stress*count)
    coefficients={}
    reported_clock=spec['execution'].get('funding_settlement_clock')=='reported_hour_with_inventory_invariance_v1'
    for event in ordered:
        if event['kind']!='funding':continue
        if not reported_clock and not first['event_ms']<event['event_ms']<=last['event_ms']:continue
        stamp=int(event['event_ms'])
        coefficient=(number(event['unit_funding_usdc']) if 'unit_funding_usdc' in event
                     else -number(event['mark'])*number(event['rate']))
        if stamp in coefficients and coefficients[stamp]!=coefficient:return None
        coefficients[stamp]=coefficient
    interval=spec['execution'].get('funding_observation_interval_ms')
    if interval is not None and units:
        first_boundary=(first['event_ms']//interval)*interval if reported_clock else (first['event_ms']//interval+1)*interval
        if max(0,(last['event_ms']-first_boundary)//interval+1)>100_000:return None
        if reported_clock:
            slots={}
            for actual in coefficients:slots.setdefault(actual//interval*interval,[]).append(actual)
            for boundary in range(first_boundary,last['event_ms']+1,interval):
                actuals=slots.get(boundary,[])
                if len(actuals)!=1:return None
                if any(boundary<=stamp<=actuals[0] for stamp in (first['event_ms'],last['event_ms'])):
                    return None
        elif any(boundary not in coefficients for boundary in range(first_boundary,last['event_ms']+1,interval)):
            return None
    pnl+=units*sum((coefficient for stamp,coefficient in coefficients.items()
                    if first['event_ms']<stamp<=last['event_ms']),Decimal(0))
    return str(pnl)


def replay(spec: dict[str, Any], events: list[dict[str, Any]], *, block_ms: int, stress: Any = 1, confidence_alpha: float = 0.05, observation_window: dict[str,int] | None = None) -> dict[str, Any]:
    state = initial_state(spec)
    # Transient membership index; the persisted, ordered history is unchanged.
    # A linear-list lookup per quote made multi-day replay quadratic.
    seen_ids: set[str] = set()
    if 'funding_sensitivity_scenario' in spec['execution']:
        state['funding_sensitivity_window']=observation_window or {
            'start_ms':min((e.get('available_ms',e['received_ms']) for e in events),default=0),
            'end_ms':max((e.get('available_ms',e['received_ms']) for e in events),default=0)+1}
    for event in sorted(events, key=lambda e: (e.get("available_ms",e["received_ms"]), e["received_ms"], str(e["id"]))):
        reduce_event(state, spec, event, stress=number(stress), _seen_ids=seen_ids)
    sensitivity=spec['execution'].get('funding_sensitivity_scenario')
    if sensitivity is not None:
        from .funding_sensitivity import apply_through
        apply_through(state,spec,state['funding_sensitivity_window']['end_ms']-1,number(stress))
    summary = metrics(state,spec,block_ms,confidence_alpha=confidence_alpha)
    summary["funding_coverage"] = funding_coverage(state,spec,observation_window)
    if sensitivity is not None:
        summary['observed_funding_coverage']=summary['funding_coverage']
        summary['observed_funding_components']=state.get('funding_settlements',{})
        summary['funding_coverage']={'version':'funding-sensitivity-accounting-v1','state':'complete',
            'classification':'chosen_model_cost_complete_not_observed_venue_cost',
            'model_only':True,'observed_costs_complete':False,
            'settlement_clock':sensitivity['settlement_clock'],
            'contract_fingerprint':sensitivity['fingerprint'],
            'required_settlements':[r['scheduled_ms'] for r in state.get('funding_sensitivity_ledger',[]) if number(r['inventory_before_boundary'])]}
        summary['funding_sensitivity_ledger']=state.get('funding_sensitivity_ledger',[])
        summary['observed_funding_not_booked_into_scenario_cash']=True
    summary["benchmark_matched_size_buy_hold_pnl"] = hold_benchmark(spec,events,number(stress))
    return {"state":state,"metrics":summary,"input_fingerprint":fingerprint(events)}
