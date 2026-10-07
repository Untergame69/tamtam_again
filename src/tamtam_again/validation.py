"""Append-only plans, variants, consumed holdouts and machine promotion gates."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
from uuid import uuid4

from .engine import canonical, fingerprint, metrics, number, replay, validate_spec
from .storage import Store, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_plans (
 plan_id TEXT PRIMARY KEY, network TEXT NOT NULL, address TEXT NOT NULL, coin TEXT NOT NULL,
 plan_json TEXT NOT NULL, created_ms INTEGER NOT NULL, synthetic INTEGER NOT NULL,
 UNIQUE(network,address,coin,plan_id));
CREATE TABLE IF NOT EXISTS strategy_variants (
 variant_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES validation_plans(plan_id),
 spec_json TEXT NOT NULL, criteria_json TEXT NOT NULL, frozen_ms INTEGER NOT NULL,
 research_run_id TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS validation_evaluations (
 evaluation_id TEXT PRIMARY KEY, variant_id TEXT NOT NULL REFERENCES strategy_variants(variant_id),
 plan_id TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL,
 input_fingerprint TEXT NOT NULL, result_json TEXT, created_at TEXT NOT NULL,
 UNIQUE(variant_id,stage,input_fingerprint));
CREATE TABLE IF NOT EXISTS consumed_holdouts (
 evaluation_id TEXT PRIMARY KEY, network TEXT NOT NULL, address TEXT NOT NULL, coin TEXT NOT NULL,
 start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL, consumed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pipeline_decisions (
 decision_id INTEGER PRIMARY KEY, network TEXT NOT NULL,address TEXT NOT NULL,coin TEXT NOT NULL,
 state TEXT NOT NULL,diagnostic TEXT NOT NULL,wake_json TEXT NOT NULL,next_action TEXT NOT NULL,
 evidence_json TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS paper_sessions (
 session_id TEXT PRIMARY KEY,variant_id TEXT NOT NULL,network TEXT NOT NULL,address TEXT NOT NULL,
 coin TEXT NOT NULL,state_json TEXT NOT NULL,status TEXT NOT NULL,started_ms INTEGER NOT NULL,
 last_observation_id INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL);
"""
STATES = {"needs_data", "collector_correction", "redo_analysis", "ready_to_test", "rejected",
          "non_identifiable", "unsupported_mechanism", "paper_active", "suspended"}


def initialize(store: Store) -> None:
    if not store.connection.execute("SELECT 1 FROM sqlite_master WHERE name='validation_plans'").fetchone():
        store.connection.executescript(SCHEMA)


def now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def decision(store: Store, network: str, address: str, coin: str, state: str,
             diagnostic: str, wake: dict[str, Any], next_action: str, evidence: Any) -> None:
    if state not in STATES or not diagnostic.strip() or not isinstance(wake, dict) or not next_action:
        raise ValueError("Explicit transition diagnostic, wake condition and action required")
    initialize(store)
    latest = store.connection.execute(
        "SELECT state,diagnostic,wake_json,next_action,evidence_json FROM pipeline_decisions WHERE network=? AND address=? AND coin=? ORDER BY decision_id DESC LIMIT 1",
        (network,address,coin)).fetchone()
    values = (state,diagnostic,canonical(wake),next_action)
    if latest and tuple(latest) == (*values,canonical(evidence)):
        return
    store.connection.execute("INSERT INTO pipeline_decisions(network,address,coin,state,diagnostic,wake_json,next_action,evidence_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                             (network,address,coin,*values,canonical(evidence),utc_now()))
    store.connection.commit()


def record_evaluation_terminal(store: Store,evaluation_id: str,status: str) -> None:
    """Caller commits this metadata with the terminal evaluation result."""
    if status not in ('passed','failed','error'):raise ValueError('Terminal evaluation status required')
    source=store.connection.execute('select status from validation_evaluations where evaluation_id=?',(evaluation_id,)).fetchone()
    if not source or source[0]!=status:raise ValueError('Matching terminal evaluation evidence required')
    store.connection.execute('create table if not exists evaluation_terminal_events '
        '(evaluation_id text primary key,status text not null,available_ms integer not null)')
    prior=store.connection.execute('select status from evaluation_terminal_events where evaluation_id=?',(evaluation_id,)).fetchone()
    if prior and prior[0]!=status:raise ValueError('Terminal evaluation event is immutable')
    store.connection.execute('insert or ignore into evaluation_terminal_events values(?,?,?)',(evaluation_id,status,now_ms()))


def validate_criteria(criteria: dict[str, Any]) -> None:
    keys = {"block_ms", "min_blocks", "min_regimes", "max_positive_block_share", "min_net_pnl",
            "max_drawdown_usdc", "min_block_lower_bound", "stress_multiplier", "min_stress_net_pnl",
            "require_funding", "dependence_justification", "regime_threshold_bps", "regime_window_ms", "confidence_alpha"}
    if not keys <= criteria.keys():
        raise ValueError("Predefined complete promotion criteria required")
    for key in ("block_ms", "min_blocks", "min_regimes", "regime_window_ms"):
        if type(criteria[key]) is not int or criteria[key] < 1:
            raise ValueError(f"Positive criteria.{key} required")
    if not 0 < number(criteria["confidence_alpha"]) < 1:
        raise ValueError("Confidence alpha must be in (0,1)")
    if number(criteria["regime_threshold_bps"]) <= 0:
        raise ValueError("Positive regime threshold required")
    if not 0 < number(criteria["max_positive_block_share"]) <= 1 or number(criteria["stress_multiplier"]) <= 1:
        raise ValueError("Invalid concentration or stress policy")
    for key in ("min_net_pnl", "max_drawdown_usdc", "min_block_lower_bound", "min_stress_net_pnl"):
        number(criteria[key])
    if type(criteria["require_funding"]) is not bool or not str(criteria["dependence_justification"]).strip():
        raise ValueError("Explicit funding policy and block justification required")


def create_plan(store: Store, plan: dict[str, Any]) -> dict[str, Any]:
    initialize(store)
    required = {"network", "address", "coin", "exploration", "comparison", "final", "embargo_ms",
                "criteria", "budget", "synthetic", "isolation"}
    if not required <= plan.keys() or type(plan["synthetic"]) is not bool:
        raise ValueError("Incomplete validation plan")
    validate_criteria(plan["criteria"])
    if 'paper_monitoring' in plan:
        from .paper_monitor import validate_policy
        validate_policy(plan['paper_monitoring'])
    if 'paper_replacement' in plan:
        from .paper_handover import validate_policy
        validate_policy(plan['paper_replacement'])
        predecessor=store.connection.execute('select p.network,p.address,p.coin,p.synthetic from strategy_variants v join validation_plans p on p.plan_id=v.plan_id where v.variant_id=?',
            (plan['paper_replacement']['predecessor_variant_id'],)).fetchone()
        if not predecessor or any(predecessor[k]!=plan[k] for k in ('network','address','coin','synthetic')):
            raise ValueError('Replacement requires an existing predecessor in the same scope and provenance')
    if not plan["synthetic"]:
        from .providers.hyperliquid import NETWORKS, validate_address
        if plan["network"] not in NETWORKS:
            raise ValueError("Unknown real network")
        validate_address(plan["address"])
    if type(plan["embargo_ms"]) is not int or plan["embargo_ms"] < 1:
        raise ValueError("Positive embargo required")
    previous_end = None
    for stage in ("exploration", "comparison", "final"):
        interval = plan[stage]
        start, end = interval["start_ms"], interval["end_ms"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end or (previous_end is not None and start < previous_end + plan["embargo_ms"]):
            raise ValueError("Chronological disjoint half-open windows with embargo required")
        previous_end = end
    if type(plan["embargo_ms"]) is not int or plan["embargo_ms"] < 1:
        raise ValueError("Positive embargo required")
    if not plan["synthetic"] and not plan["criteria"]["require_funding"]:
        raise ValueError("Real perpetual validation requires funding observations")
    if not plan["synthetic"] and plan["comparison"]["start_ms"] < now_ms():
        raise ValueError("Comparison/final must be prospective; past exposed data is development data")
    for key in ("max_runs", "max_same_input_corrections", "max_duration_ms"):
        if type(plan["budget"].get(key)) is not int:
            raise ValueError("Integer run/correction/duration budgets required")
    for key in ("max_runs", "max_same_input_corrections", "max_duration_ms", "max_cost_usd"):
        if key not in plan["budget"] or number(plan["budget"][key]) <= 0:
            raise ValueError("Explicit positive iteration/time/cost budget required")
    if plan["isolation"] not in {"unavailable", "separate_principal"}:
        raise ValueError("Declare actual agent isolation availability")
    # A declaration cannot grant OS isolation. Production AI dispatch remains
    # suspended until a deployment supplies and verifies a separate principal.
    plan_id = fingerprint(plan)
    store.connection.execute("INSERT OR IGNORE INTO validation_plans VALUES (?,?,?,?,?,?,?)",
                             (plan_id,plan["network"],plan["address"],plan["coin"],canonical(plan),now_ms(),int(plan["synthetic"])))
    store.connection.commit()
    return {"plan_id":plan_id, "plan":plan}


def latest_plan(store: Store, network: str, address: str, coin: str) -> dict[str, Any] | None:
    initialize(store)
    row = store.connection.execute("SELECT * FROM validation_plans WHERE network=? AND address=? AND coin=? ORDER BY created_ms DESC,rowid DESC LIMIT 1", (network,address,coin)).fetchone()
    return {**dict(row), "plan":json.loads(row["plan_json"])} if row else None


def register_variant(store: Store, plan_id: str, spec: dict[str, Any], research_run_id: str | None = None, *, commit: bool = True) -> dict[str, Any]:
    initialize(store)
    validate_spec(spec)
    row = store.connection.execute("SELECT * FROM validation_plans WHERE plan_id=?",(plan_id,)).fetchone()
    if not row:
        raise ValueError("Unknown validation plan")
    plan = json.loads(row["plan_json"])
    if spec["market"] != row["coin"]:
        raise ValueError("Strategy market differs from plan")
    if max(spec["horizon_ms"],spec["signal"].get("lookback_ms",0)) + spec["latency_ms"] > plan["embargo_ms"]:
        raise ValueError("Embargo must cover horizon, lookback and latency")
    if not row["synthetic"] and now_ms() >= plan["final"]["start_ms"]:
        raise ValueError("Strategy must be frozen before final period begins")
    count = store.connection.execute("SELECT count(*) FROM strategy_variants WHERE plan_id=?",(plan_id,)).fetchone()[0]
    identity = fingerprint({"plan_id":plan_id,"spec":spec,"criteria":plan["criteria"]})
    existing = store.connection.execute("SELECT * FROM strategy_variants WHERE variant_id=?",(identity,)).fetchone()
    if not existing:
        if count >= plan["budget"]["max_runs"]:
            raise ValueError("Variant budget exhausted")
        store.connection.execute("INSERT INTO strategy_variants VALUES (?,?,?,?,?,?,?)",(identity,plan_id,canonical(spec),canonical(plan["criteria"]),now_ms(),research_run_id,utc_now()))
        if commit:
            store.connection.commit()
    return {"variant_id":identity,"plan_id":plan_id,"strategy_fingerprint":fingerprint(spec)}


def get_variant(store: Store, variant_id: str) -> tuple[Any,dict[str,Any],dict[str,Any]]:
    initialize(store)
    row = store.connection.execute("SELECT v.*,p.plan_json,p.network,p.address,p.coin,p.synthetic,p.created_ms FROM strategy_variants v JOIN validation_plans p USING(plan_id) WHERE variant_id=?",(variant_id,)).fetchone()
    if not row:
        raise ValueError("Unknown variant")
    return row,json.loads(row["spec_json"]),json.loads(row["plan_json"])


def promotion(metrics_normal: dict[str,Any], stressed: dict[str,Any], criteria: dict[str,Any]) -> list[str]:
    failures = []
    checks = {
        "net_edge_after_costs": number(metrics_normal["net_pnl"]) > max(number(criteria["min_net_pnl"]),number(metrics_normal["benchmark_cash_net_pnl"])),
        "market_reference": metrics_normal.get("benchmark_matched_size_buy_hold_pnl") is not None and number(metrics_normal["net_pnl"]) > number(metrics_normal["benchmark_matched_size_buy_hold_pnl"]),
        "drawdown_limit": number(metrics_normal["drawdown_usdc"]) <= number(criteria["max_drawdown_usdc"]),
        "independent_block_volume": metrics_normal["block_count"] >= criteria["min_blocks"],
        "regime_coverage": len(metrics_normal["regimes"]) >= criteria["min_regimes"],
        "gain_concentration": metrics_normal["largest_positive_block_share"] is not None and metrics_normal["largest_positive_block_share"] <= float(criteria["max_positive_block_share"]),
        "uncertainty": metrics_normal["block_mean_lower_95_descriptive"] is not None and metrics_normal["block_mean_lower_95_descriptive"] > float(criteria["min_block_lower_bound"]),
        "stress_edge": number(stressed["net_pnl"]) > number(criteria["min_stress_net_pnl"]),
        "flat_boundaries": metrics_normal["flat_end"] and stressed["flat_end"] and not metrics_normal["pending_end"] and not stressed["pending_end"],
        "funding_observed": not criteria["require_funding"] or metrics_normal["funding_events"] > 0,
        "uninterrupted_observation": not metrics_normal["diagnostics"],
    }
    failures.extend(key for key,passed in checks.items() if not passed)
    return failures


def evaluate(store: Store, variant_id: str, stage: str, events: list[dict[str,Any]], *, provenance: str) -> dict[str,Any]:
    row,spec,plan = get_variant(store,variant_id)
    if stage not in {"exploration","comparison","final"}:
        raise ValueError("Unknown validation stage")
    if bool(row["synthetic"]) != (provenance == "synthetic"):
        raise ValueError("Synthetic/real provenance mismatch")
    if provenance not in {"synthetic","local_archive"}:
        raise ValueError("Archived or explicitly synthetic evidence required")
    interval = plan[stage]
    if not events or any(not interval["start_ms"] <= e["event_ms"] <= e["received_ms"] <= e.get("available_ms",e["received_ms"]) < interval["end_ms"] for e in events):
        raise ValueError("Every event and receipt must be inside the selected window")
    if not row["synthetic"] and now_ms() < interval["end_ms"]:
        raise ValueError("Evaluation window has not finished")
    if stage == "final":
        from .experiments import require_final_selection
        require_final_selection(store,variant_id)
        comparison = store.connection.execute("SELECT 1 FROM validation_evaluations WHERE variant_id=? AND stage='comparison' AND status='passed'",(variant_id,)).fetchone()
        if not comparison:
            raise ValueError("Final requires a passed comparison for this exact frozen variant")
    criteria = json.loads(row["criteria_json"])
    data_fp = fingerprint(events)
    evaluation_id = fingerprint({"variant":variant_id,"stage":stage,"input":data_fp})
    prior = store.connection.execute("SELECT * FROM validation_evaluations WHERE evaluation_id=?",(evaluation_id,)).fetchone()
    if prior:
        return json.loads(prior["result_json"]) if prior["result_json"] else {"evaluation_id":evaluation_id,"status":prior["status"],"diagnostic":"Previously consumed; no rerun"}
    evaluations = store.connection.execute("SELECT count(*) FROM validation_evaluations WHERE plan_id=?", (row["plan_id"],)).fetchone()[0]
    if evaluations >= plan["budget"]["max_runs"] or now_ms() - row["created_ms"] > plan["budget"]["max_duration_ms"]:
        raise ValueError("Evaluation iteration/duration budget exhausted")
    if not row["synthetic"]:
        health = sorted([e for e in events if e["kind"] in {"connection", "heartbeat"} and e.get("connected",True)],key=lambda e:e["received_ms"])
        timeout = spec["execution"]["heartbeat_timeout_ms"]
        if not health or health[0]["received_ms"] - interval["start_ms"] > timeout or interval["end_ms"] - health[-1]["received_ms"] > timeout:
            raise ValueError("Archive does not establish observation coverage of this complete window")
        if any(b["received_ms"] - a["received_ms"] > timeout for a,b in zip(health,health[1:])):
            raise ValueError("Heartbeat gap inside validation window")
    # Burn the entire final window BEFORE execution. Errors/crashes never make
    # the holdout available again. Overlap is forbidden across plan revisions.
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        if stage == "final":
            overlap = store.connection.execute("SELECT 1 FROM consumed_holdouts WHERE network=? AND address=? AND coin=? AND start_ms<? AND end_ms>?",(row["network"],row["address"],row["coin"],interval["end_ms"],interval["start_ms"])).fetchone()
            if overlap:
                raise ValueError("Reserved period already consumed; collect a new future period")
            store.connection.execute("INSERT INTO consumed_holdouts VALUES (?,?,?,?,?,?,?)",(evaluation_id,row["network"],row["address"],row["coin"],interval["start_ms"],interval["end_ms"],utc_now()))
        store.connection.execute("INSERT INTO validation_evaluations VALUES (?,?,?,?,?,?,?,?)",(evaluation_id,variant_id,row["plan_id"],stage,"running",data_fp,None,utc_now()))
        store.connection.commit()
    except Exception:
        store.connection.rollback()
        raise
    try:
        # Bonferroni over the PREDECLARED maximum trial count, rather than the
        # number seen so far; later variants cannot weaken earlier decisions.
        adjusted_alpha = float(number(criteria["confidence_alpha"])) / plan["budget"]["max_runs"]
        normal = replay(spec,events,block_ms=criteria["block_ms"],confidence_alpha=adjusted_alpha)
        stress = replay(spec,events,block_ms=criteria["block_ms"],stress=criteria["stress_multiplier"],confidence_alpha=adjusted_alpha)
        failures = promotion(normal["metrics"],stress["metrics"],criteria)
        result = {"evaluation_id":evaluation_id,"variant_id":variant_id,"stage":stage,
                  "status":"failed" if failures else "passed", "synthetic":bool(row["synthetic"]),
                  "promotable":stage == "final" and not failures and not row["synthetic"],
                  "failures":failures,"metrics":normal["metrics"],"stress_metrics":stress["metrics"],
                  "input_fingerprint":data_fp,"criteria_fingerprint":fingerprint(criteria)}
    except Exception as exc:
        store.connection.execute("UPDATE validation_evaluations SET status='error',result_json=? WHERE evaluation_id=?",(canonical({"status":"error","error_type":type(exc).__name__}),evaluation_id))
        record_evaluation_terminal(store,evaluation_id,'error')
        store.connection.commit()
        raise
    store.connection.execute("UPDATE validation_evaluations SET status=?,result_json=? WHERE evaluation_id=?",(result["status"],canonical(result),evaluation_id))
    record_evaluation_terminal(store,evaluation_id,result["status"])
    store.connection.commit()
    decision(store,row["network"],row["address"],row["coin"],"ready_to_test" if result["promotable"] else "needs_data" if not failures else "rejected",
             f"{stage}: {result['status']}; synthetic={bool(row['synthetic'])}",
             {"new_prospective_plan_required":stage=="final","failures":failures},"start_n2" if result["promotable"] else "review_diagnostic",{"evaluation_id":evaluation_id})
    return result
