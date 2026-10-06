"""Deterministic, public-data-only strategy and virtual execution engine.

Same event reducer for replay and N2. Perpetual accounting: cash changes by
realized PnL, fees and funding; margin is not a spot purchase cash flow.
"""
from __future__ import annotations

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
            "leader_target": "0", "regimes": [], "funding_events": 0, "risk_halted": False, "peak_equity": str(spec["starting_capital_usdc"]), "processing_lags_ms": []}


def quote_status(state: dict[str, Any], now: int, execution: dict[str, Any]) -> str:
    q = state["quote"]
    if not state["connected"] and state["session"] is not None:
        return "interrupted"
    if not q or q["received_ms"] >= now or q["event_ms"] > now:
        return "unavailable"
    if (state["connected"] and q.get("session") == state["session"]
            and state["healthy_at_ms"] is not None
            and 0 <= now - state["healthy_at_ms"] <= execution["heartbeat_timeout_ms"]):
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


def _execute(state: dict[str, Any], spec: dict[str, Any], now: int, stress: Decimal) -> None:
    remaining = []
    for order in state["pending"]:
        if order["due_ms"] > now:
            remaining.append(order)
            continue
        if now > order["expires_ms"] or quote_status(state, now, spec["execution"]) != "continuous":
            state["missed_orders"] += 1
            continue
        q = state["quote"]
        target = number(order["target"])
        limit = number(spec["max_exposure"]["notional_usdc"])
        # Check exposure against the adverse side including simulated slippage.
        mark = max(number(q["bid"]), number(q["ask"])) * (1 + number(spec["slippage"]["bps"]) * stress / 10000)
        pos = number(state["position"])
        equity = number(state["cash"]) + pos * (number(q["bid"] if pos >= 0 else q["ask"]) - number(state["average_price"]))
        limit = min(limit, max(Decimal(0), equity) * number(spec["max_exposure"]["max_leverage"]))
        target = max(-limit / mark, min(limit / mark, target))
        delta = target - number(state["position"])
        if not delta:
            continue
        buy = delta > 0
        passive = spec["execution"]["kind"] == "passive_conservative"
        if passive:
            # Public depth does not establish queue priority. Default no fill,
            # including when the limit is touched. Explicit future queue models
            # must be implemented/versioned before they can change this rule.
            state["missed_orders"] += 1
            continue
        available_key = "ask_size" if buy else "bid_size"
        available = number(q.get(available_key, 0)) * number(spec["execution"]["displayed_size_fraction"]) / stress
        size = min(abs(delta), max(Decimal(0), available)) * (1 if buy else -1)
        if not size:
            state["missed_orders"] += 1
            continue
        if abs(size) < abs(delta):
            state["partial_orders"] += 1
        price = number(q["ask"] if buy else q["bid"])
        price *= 1 + number(spec["slippage"]["bps"]) * stress / 10000 * (1 if buy else -1)
        _fill(state, size, price, number(spec["fees"]["taker_bps"]) * stress, now)
    state["pending"] = remaining


def _order(state: dict[str, Any], spec: dict[str, Any], target: Decimal, now: int) -> None:
    if state["risk_halted"] and target != 0:
        return
    state["pending"] = [{"target": str(target), "due_ms": now + spec["latency_ms"],
                         "expires_ms": now + spec["latency_ms"] + spec["execution"]["order_ttl_ms"]}]


def reduce_event(state: dict[str, Any], spec: dict[str, Any], event: dict[str, Any], *, stress: Decimal = Decimal(1)) -> None:
    """Consume ordered local receipts. Equal-ms quotes cannot fill a decision.

    Timers execute before the incoming message, so the message being received
    cannot be used retrospectively to execute an older order.
    """
    receipt, exchange = int(event["received_ms"]), int(event["event_ms"])
    now = int(event.get("available_ms",receipt))
    if now < receipt:
        raise ValueError("Availability precedes local receipt")
    event_id = str(event["id"])
    if event_id in state["seen"]:
        return
    if now < state["last_ms"] or exchange > receipt:
        raise ValueError("Noncausal or out-of-order event")
    if stress < 1:
        raise ValueError("Stress multiplier must be >= 1")
    state["seen"].append(event_id)
    state["processing_lags_ms"].append(now-receipt)
    unavailable = (event["kind"] == "connection" and event.get("connected") is False) or (event["kind"] in {"heartbeat","subscriptions"} and "markets" in event and spec["market"] not in event["markets"])
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
            if state["session"] is not None:
                state["diagnostics"].append("connection_changed_without_reconciliation")
            state["session"], state["connected"] = event["session"], True
            state["quote"] = None
        if state["connected"] and event["session"] == state["session"]:
            state["healthy_at_ms"] = receipt
    elif kind == "bbo":
        bid, ask = number(event["bid"]), number(event["ask"])
        if not 0 < bid <= ask:
            raise ValueError("Invalid BBO")
        state["quote"] = {k: event[k] for k in ("received_ms", "event_ms", "bid", "ask", "bid_size", "ask_size", "session")}
        state["quote"]["source_received_ms"] = receipt
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
            state["leader_target"] = str(number(state["leader_target"]) + number(event["delta"]) * number(spec["sizing"]["scale"]))
            _order(state, spec, number(state["leader_target"]), now)
    elif kind == "funding":
        # Rate is applied to OUR position at this funding event; leader's USDC
        # funding payment is never reused. Event mark is an observed input.
        effective_position = sum((number(f["size"]) for f in state["fills"] if f["received_ms"] <= exchange), Decimal(0))
        payment = effective_position * number(event["unit_funding_usdc"]) if "unit_funding_usdc" in event else -effective_position * number(event["mark"]) * number(event["rate"])
        state["cash"] = str(number(state["cash"]) + payment)
        state["funding"] = str(number(state["funding"]) + payment)
        state["funding_events"] += 1
    elif kind == "regime":
        if event["label"] not in state["regimes"]:
            state["regimes"].append(event["label"])
    if state["opened_ms"] is not None and now - state["opened_ms"] >= spec["horizon_ms"] and not state["pending"]:
        _order(state, spec, Decimal(0), now)
    if state["quote"]:
        q = state["quote"]
        # Liquidation-side mark includes spread; realized cash already includes
        # fees/slippage. Do not subtract spread again.
        pos = number(state["position"])
        mark = number(q["bid"] if pos >= 0 else q["ask"])
        unrealized = pos * (mark - number(state["average_price"]))
        equity = number(state["cash"]) + unrealized
        state["peak_equity"] = str(max(number(state["peak_equity"]), equity))
        state["equity_curve"].append([now, str(equity)])
        if number(state["peak_equity"]) - equity >= number(spec["max_exposure"]["max_drawdown_usdc"]) and not state["risk_halted"]:
            state["risk_halted"] = True
            state["diagnostics"].append("risk_drawdown_limit")
            _order(state,spec,Decimal(0),now)


def metrics(state: dict[str, Any], spec: dict[str, Any], block_ms: int, *, confidence_alpha: float = 0.05) -> dict[str, Any]:
    if block_ms <= 0:
        raise ValueError("Positive independent block duration required")
    capital = number(spec["starting_capital_usdc"])
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
    return {"net_pnl": str(final - capital), "realized_pnl": state["realized_pnl"],
            "unrealized_pnl": str(final - number(state["cash"])), "fees": state["fees"],
            "funding": state["funding"], "drawdown_usdc": str(drawdown),
            "block_count": len(values), "block_mean_lower_95_descriptive": lower,
            "largest_positive_block_share": positive[0] / sum(positive) if positive else None,
            "regimes": state["regimes"], "fills": len(state["fills"]),
            "missed_orders": state["missed_orders"], "partial_orders": state["partial_orders"],
            "flat_end": number(state["position"]) == 0, "pending_end": len(state["pending"]),
            "funding_events": state["funding_events"], "diagnostics": sorted(set(state["diagnostics"])),
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
    for event in ordered:
        if event["kind"] == "funding" and first["event_ms"] < event["event_ms"] <= last["event_ms"]:
            pnl += units*number(event["unit_funding_usdc"]) if "unit_funding_usdc" in event else -units*number(event["mark"])*number(event["rate"])
    return str(pnl)


def replay(spec: dict[str, Any], events: list[dict[str, Any]], *, block_ms: int, stress: Any = 1, confidence_alpha: float = 0.05) -> dict[str, Any]:
    state = initial_state(spec)
    for event in sorted(events, key=lambda e: (e.get("available_ms",e["received_ms"]), e["received_ms"], str(e["id"]))):
        reduce_event(state, spec, event, stress=number(stress))
    summary = metrics(state,spec,block_ms,confidence_alpha=confidence_alpha)
    summary["benchmark_matched_size_buy_hold_pnl"] = hold_benchmark(spec,events,number(stress))
    return {"state":state,"metrics":summary,"input_fingerprint":fingerprint(events)}
