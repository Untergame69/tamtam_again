"""Explicitly synthetic local acceptance recipe; cannot promote real strategy."""
from __future__ import annotations

from pathlib import Path
import json
import tempfile
from typing import Any

from .paper import start_paper, synthetic_recipe_tick
from .storage import Store
from .validation import create_plan, evaluate, register_variant


def synthetic_spec() -> dict[str,Any]:
    return {"schema_version":2,"type":"follower","market":"SYNTH","data_sources":["bbo","userFills","streamHealth","userFundings"],
            "signal":{"kind":"leader_delta"},"entry":{"kind":"target_position"},"exit":{"kind":"horizon_or_target"},
            "sizing":{"scale":"1"},"max_exposure":{"notional_usdc":"10000","max_drawdown_usdc":"100","max_leverage":"1"},
            "fees":{"maker_bps":"1","taker_bps":"2"},"slippage":{"bps":"1"},
            "latency_ms":1,"horizon_ms":500,"starting_capital_usdc":"10000",
            "execution":{"kind":"market_ioc","heartbeat_timeout_ms":65000,"unknown_quote_max_age_ms":1000,
                         "order_ttl_ms":500,"displayed_size_fraction":"0.5"},
            "invalidation_conditions":["nonpositive net edge", "uncertain continuity", "exposure exceeded"]}


def synthetic_plan() -> dict[str,Any]:
    return {"network":"synthetic","address":"fixture-only","coin":"SYNTH","synthetic":True,
            "exploration":{"start_ms":1000,"end_ms":6000},"comparison":{"start_ms":10000,"end_ms":16000},
            "final":{"start_ms":20000,"end_ms":26000},"embargo_ms":1000,"isolation":"unavailable",
            "criteria":{"block_ms":1000,"min_blocks":4,"min_regimes":2,"max_positive_block_share":"0.4",
                        "min_net_pnl":"0","max_drawdown_usdc":"10","min_block_lower_bound":"0",
                        "stress_multiplier":"2","min_stress_net_pnl":"0","require_funding":False,
                        "dependence_justification":"SYNTHETIC: independent scripted cycles, one cycle per block; not evidence for a real strategy",
                        "regime_threshold_bps":"10","regime_window_ms":100,"confidence_alpha":"0.05"},
            "budget":{"max_runs":10,"max_same_input_corrections":2,"max_duration_ms":86400000,"max_cost_usd":"1"}}


def synthetic_events(start_ms: int) -> list[dict[str,Any]]:
    events = [{"id":f"connection:{start_ms}","kind":"connection","received_ms":start_ms,"event_ms":start_ms,"session":"fixture-session","connected":True}]
    for i in range(4):
        base = start_ms + i*1000
        def event(kind: str, delay: int, **fields: Any) -> dict[str,Any]:
            return {"id":f"{base}:{kind}:{delay}","kind":kind,"received_ms":base+delay,"event_ms":base+delay,**fields}
        events += [event("bbo",10,session="fixture-session",bid="100",ask="100.1",bid_size="100",ask_size="100"),
                   event("regime",11,label="up" if i%2 else "quiet"),
                   event("leader_fill",20,is_snapshot=False,delta="1"),event("timer",30),
                   event("bbo",100,session="fixture-session",bid="102",ask="102.1",bid_size="100",ask_size="100"),
                   event("leader_fill",120,is_snapshot=False,delta="-1"),event("timer",130),event("timer",140)]
    return events


def run_recipe(output: Path) -> dict[str,Any]:
    output.mkdir(parents=True,exist_ok=True)
    # Dedicated temporary DB; never the collector DB, even if CLI --db is given.
    with tempfile.TemporaryDirectory(prefix="tamtam-synthetic-") as directory:
        with Store(Path(directory)/"recipe.sqlite3") as store:
            plan = create_plan(store,synthetic_plan())
            variant = register_variant(store,plan["plan_id"],synthetic_spec())
            stages = [evaluate(store,variant["variant_id"],stage,synthetic_events(synthetic_plan()[stage]["start_ms"]),provenance="synthetic") for stage in ("exploration","comparison","final")]
            from unittest.mock import patch
            with patch('tamtam_again.paper.now_ms',return_value=30000):
                session = start_paper(store,variant["variant_id"],synthetic_recipe=True)
            events = synthetic_events(30000)
            half = len(events)//2
            synthetic_recipe_tick(store,session["session_id"],events[:half])
            # A new SQLite connection must continue the same journal, rather
            # than initialize another portfolio when the process restarts.
            with Store(Path(directory)/"recipe.sqlite3") as resumed:
                continued = synthetic_recipe_tick(resumed,session["session_id"],events[half:])
                duplicate = synthetic_recipe_tick(resumed,session["session_id"],events)
                if continued["metrics"] != duplicate["metrics"]:
                    raise ValueError("Synthetic N2 restart/idempotence failed")
            report = {"synthetic":True,"real_strategy_validated":False,"stages":stages,"paper_recipe":session,
                      "paper_metrics":continued["metrics"],"paper_restart_and_idempotence_verified":True,"live_orders_enabled":False}
            (output/"recipe-result.json").write_text(json.dumps(report,indent=2)+"\n")
    return report
