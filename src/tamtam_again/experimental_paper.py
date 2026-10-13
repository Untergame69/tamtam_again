"""Prospective paper experiments that do not claim N1 validation or promotion."""
from __future__ import annotations

import json
from typing import Any

from .engine import canonical, fingerprint, metrics, number
from .storage import Store, utc_now
from .validation import get_variant, now_ms

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_experimental_sessions (
 session_id TEXT PRIMARY KEY REFERENCES paper_sessions(session_id),
 hypothesis_id TEXT NOT NULL,
 hypothesis_json TEXT NOT NULL,
 frozen_fingerprint TEXT NOT NULL,
 review_interval_ms INTEGER NOT NULL,
 max_duration_ms INTEGER NOT NULL,
 next_review_ms INTEGER NOT NULL,
 review_index INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL,
 created_ms INTEGER NOT NULL,
 loss_limit_usdc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_experimental_reports (
 report_id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL REFERENCES paper_experimental_sessions(session_id),
 review_index INTEGER NOT NULL,
 due_ms INTEGER NOT NULL,
 observed_through_ms INTEGER NOT NULL,
 report_json TEXT NOT NULL,
 next_action TEXT NOT NULL,
 action_detail TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(session_id,review_index)
);
CREATE TABLE IF NOT EXISTS paper_experimental_rectifications (
 rectification_id TEXT PRIMARY KEY,
 corrects_report_id TEXT NOT NULL REFERENCES paper_experimental_reports(report_id),
 session_id TEXT NOT NULL REFERENCES paper_experimental_sessions(session_id),
 rectification_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_experimental_dispositions (
 disposition_id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL REFERENCES paper_experimental_sessions(session_id),
 disposition_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_experimental_collection_gates (
 gate_id TEXT PRIMARY KEY,
 spec_fingerprint TEXT NOT NULL,
 passed INTEGER NOT NULL CHECK(passed IN (0,1)),
 measurement_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_paper_collection_gates_spec
 ON paper_experimental_collection_gates(spec_fingerprint,passed,created_at);
"""

REQUIRED_HYPOTHESIS = {
    "schema_version", "hypothesis_id", "observations", "interpretation",
    "claim", "signal", "entry", "exit", "execution", "risk",
    "decision_rules", "evidence_refs", "review_interval_ms", "max_duration_ms",
}
COLLECTION_GATE_RECENCY_MS = 600_000


def initialize(store: Store) -> None:
    store.connection.executescript(SCHEMA)


def validate_start(store: Store, variant_id: str, hypothesis: dict[str, Any], *,
                   runtime_state: dict[str, Any] | None = None) -> tuple[Any, dict, dict]:
    row, spec, plan = get_variant(store, variant_id)
    if row["synthetic"] or plan.get("experiment_mode") != "experimental_paper_only":
        raise ValueError("Experimental paper requires an explicitly marked real paper-only plan")
    if store.connection.execute(
        "SELECT 1 FROM validation_evaluations WHERE plan_id=? LIMIT 1", (row["plan_id"],)
    ).fetchone():
        raise ValueError("Paper-only experiment cannot reuse economic evaluation results")
    if not isinstance(hypothesis, dict) or not REQUIRED_HYPOTHESIS <= hypothesis.keys():
        raise ValueError("Complete frozen experimental hypothesis required")
    if hypothesis["schema_version"] != 1 or not str(hypothesis["hypothesis_id"]).strip():
        raise ValueError("Versioned experimental hypothesis required")
    for field in ("claim", "interpretation", "signal", "entry", "exit", "execution"):
        if not isinstance(hypothesis[field], str) or not hypothesis[field].strip():
            raise ValueError(f"Explicit hypothesis.{field} required")
    if not isinstance(hypothesis["observations"], list) or not hypothesis["observations"]:
        raise ValueError("Source observations required")
    if not isinstance(hypothesis["evidence_refs"], list) or not hypothesis["evidence_refs"]:
        raise ValueError("Hypothesis provenance required")
    if not isinstance(hypothesis["risk"], dict) or not isinstance(hypothesis["decision_rules"], dict):
        raise ValueError("Explicit risk and stopping rules required")
    interval, duration = hypothesis["review_interval_ms"], hypothesis["max_duration_ms"]
    if type(interval) is not int or interval < 60_000 or type(duration) is not int or duration <= interval:
        raise ValueError("Positive review interval and longer finite experiment duration required")
    if duration > plan["budget"]["max_duration_ms"]:
        raise ValueError("Experimental duration exceeds the frozen plan budget")
    required_sources = {"bbo", "userFills", "streamHealth", "userFundings"}
    if hypothesis.get('quote_evidence_contract')=='bbo_or_l2book_v1':
        required_sources.add('l2Book')
        if spec.get('execution',{}).get('quote_evidence_contract')!='bbo_or_l2book_v1':
            raise ValueError('Hypothesis and executable spec must freeze the same BBO/l2Book contract')
    if not required_sources <= set(spec["data_sources"]):
        raise ValueError("Experimental paper requires live fills, BBO, health and funding sources")
    funding_interval = spec.get("execution", {}).get("funding_interval_ms")
    if type(funding_interval) is not int or funding_interval < 1:
        raise ValueError("Explicit funding interval required to prevent positions crossing an unobserved funding boundary")
    if not isinstance(spec.get("execution", {}).get("market_rules"), dict):
        raise ValueError("Current versioned venue lot, price and minimum-order rules required")
    if spec["execution"]["market_rules"].get("available_ms", duration + 1) > now_ms():
        raise ValueError("Venue market rules are not yet available")
    if not hypothesis["risk"].get("no_live_orders") or hypothesis["risk"].get("economic_validation") is not False:
        raise ValueError("Experimental paper must explicitly disable live orders and economic validation")
    if number(hypothesis["risk"].get("max_exposure_usdc", -1)) != number(spec["max_exposure"]["notional_usdc"]):
        raise ValueError("Hypothesis exposure cap must match the frozen executable strategy")
    if number(hypothesis["risk"].get("max_loss_usdc", -1)) != number(spec["max_exposure"]["max_drawdown_usdc"]):
        raise ValueError("Hypothesis loss cap must match the frozen executable strategy")
    if hypothesis.get('runtime_health_required'):
        expected_runtime={"paper_timer_interval_ms":500,"paper_timer_accuracy_ms":50,
            "paper_start_limit_interval_ms":10_000,"paper_start_limit_burst":30,
            "bbo_flush_interval_ms":250,"quote_age_limit_ms":1000}
        if not runtime_state or runtime_state.get('runtime_config')!=expected_runtime:
            raise ValueError('Live paper timer and market collector runtime settings are not the configured values')
        if runtime_state.get('collector_active') is not True or runtime_state.get('paper_timer_active') is not True:
            raise ValueError('Market collector and paper engine timer must both be active before start')
        if not runtime_state.get('collector_pid') or not runtime_state.get('current_connection_id'):
            raise ValueError('A running collector PID and current WebSocket connection are required')
        if (runtime_state.get('current_connection_healthy') is not True or
            runtime_state.get('current_connection_health_age_ms',10**12)>spec['execution'].get('heartbeat_timeout_ms',65_000)):
            raise ValueError('Current WebSocket connection is not healthy for HYPE')
    if hypothesis.get("prestart_collection_gate_required"):
        spec_id=fingerprint(spec)
        gate=store.connection.execute(
            "SELECT * FROM paper_experimental_collection_gates WHERE spec_fingerprint=? "
            "ORDER BY rowid DESC LIMIT 1", (spec_id,),
        ).fetchone()
        if not gate or not gate["passed"]:
            raise ValueError("Freshness/cadence collection gate has not passed for this exact strategy spec")
        measured=json.loads(gate["measurement_json"])
        age=now_ms()-int(measured.get("window_end_ms",0))
        if age<0 or age>COLLECTION_GATE_RECENCY_MS:
            raise ValueError("Passed collection gate is stale; a new continuous measurement is required")
        expected_runtime={"paper_timer_interval_ms":500,"paper_timer_accuracy_ms":50,
            "paper_start_limit_interval_ms":10_000,"paper_start_limit_burst":30,
            "bbo_flush_interval_ms":250,"quote_age_limit_ms":1000}
        if measured.get("runtime_config") != expected_runtime:
            raise ValueError("Passed collection gate does not match the frozen v3 runtime configuration")
        if not runtime_state or runtime_state.get("runtime_config") != expected_runtime:
            raise ValueError("Live timer, collector, or service configuration differs from the measured v3 configuration")
        if runtime_state.get("collector_active") is not True or runtime_state.get("paper_timer_active") is not True:
            raise ValueError("Live collector and paper timer must both be active at v3 start")
        if runtime_state.get("collector_pid") != measured.get("collector_pid"):
            raise ValueError("Collector process changed after the measured window; repeat the gate on its current connection")
        if runtime_state.get("collector_active_enter") != measured.get("collector_active_enter"):
            raise ValueError("Collector process age changed after the measured window; repeat the gate")
        if runtime_state.get("code_revision") != measured.get("code_revision"):
            raise ValueError("Code revision changed after the measured window; repeat the gate")
        current_connection=runtime_state.get("current_connection_id")
        if not current_connection or current_connection != measured.get("connection_id"):
            raise ValueError("Current HYPE quote connection differs from the measured collection connection")
        if runtime_state.get("current_quote_age_ms", 10**12)>1000:
            raise ValueError("Current HYPE quote is older than the frozen 1-second bound")
        if (runtime_state.get("current_connection_healthy") is not True or
            runtime_state.get("current_connection_health_age_ms",10**12)>spec["execution"].get("heartbeat_timeout_ms",65_000)):
            raise ValueError("Current HYPE WebSocket session has no active health confirmation")
    return row, spec, plan


def record_collection_gate(store: Store, spec_fingerprint: str,
                           measurement: dict[str, Any]) -> dict[str, Any]:
    """Persist an immutable ten-minute quote/cadence gate result for one spec."""
    initialize(store)
    if len(spec_fingerprint)!=64 or any(c not in "0123456789abcdef" for c in spec_fingerprint):
        raise ValueError("SHA-256 strategy spec fingerprint required")
    required={"window_start_ms","window_end_ms","quote_age_limit_ms","checkpoints","fresh_quotes",
        "connection_ids","reconnects","start_limit_hits","tick_interval_p95_ms","tick_interval_max_ms",
        "receipt_to_archive_p95_ms","runtime_config","collector_pid","collector_active_enter",
        "code_revision","control_checkpoints"}
    if not isinstance(measurement,dict) or not required<=measurement.keys():
        raise ValueError("Complete prestart collection measurement required")
    start,end=measurement["window_start_ms"],measurement["window_end_ms"]
    count,fresh=measurement["checkpoints"],measurement["fresh_quotes"]
    if any(type(x) is not int for x in (start,end,count,fresh)) or end<start or count<0 or not 0<=fresh<=count:
        raise ValueError("Invalid collection window or quote counts")
    ids=measurement["connection_ids"]
    if not isinstance(ids,list) or not all(isinstance(x,str) and x for x in ids):
        raise ValueError("WebSocket connection ids required")
    proofs=measurement["control_checkpoints"]
    if (not isinstance(proofs,list) or len(proofs)!=count or
        any(not isinstance(p,dict) or type(p.get("control_at_ms")) is not int or
            type(p.get("tick_start_ms")) is not int or type(p.get("observation_id")) is not int
            for p in proofs)):
        raise ValueError("A timestamped observation reference is required for every measured control checkpoint")
    runtime=measurement["runtime_config"]
    expected_runtime={"paper_timer_interval_ms":500,"paper_timer_accuracy_ms":50,
        "paper_start_limit_interval_ms":10_000,"paper_start_limit_burst":30,
        "bbo_flush_interval_ms":250,"quote_age_limit_ms":1000}
    if not isinstance(runtime,dict):
        raise ValueError("Measured live runtime configuration required")
    if (type(measurement["collector_pid"]) is not int or measurement["collector_pid"]<=0 or
        not isinstance(measurement["collector_active_enter"],str) or
        not isinstance(measurement["code_revision"],str) or not measurement["code_revision"]):
        raise ValueError("Collector process identity and code revision required")
    connection_id=measurement.get("connection_id")
    if not isinstance(connection_id,str) or not connection_id:
        raise ValueError("Single measured WebSocket connection id required")
    for key in ("tick_interval_p95_ms","tick_interval_max_ms","receipt_to_archive_p95_ms"):
        if type(measurement[key]) not in (int,float) or not number(measurement[key]).is_finite() or number(measurement[key])<0:
            raise ValueError(f"Nonnegative finite {key} required")
    for key in ("quote_age_limit_ms","reconnects","start_limit_hits"):
        if type(measurement[key]) is not int or measurement[key]<0:
            raise ValueError(f"Nonnegative integer {key} required")
    passed=(end-start>=600_000 and count>=600 and measurement["quote_age_limit_ms"]==1000
        and fresh/count>=.95 and len(set(ids))==1 and ids[0]==connection_id and measurement["reconnects"]==0
        and runtime==expected_runtime and measurement.get("runtime_config_stable") is True
        and measurement["start_limit_hits"]==0 and measurement["tick_interval_p95_ms"]<=600
        and measurement["tick_interval_max_ms"]<=1000
        and measurement["receipt_to_archive_p95_ms"]<=300)
    payload={**measurement,"passed":bool(passed),"required_window_ms":600_000,
        "required_checkpoints":600,"required_fresh_fraction":0.95,"required_quote_age_limit_ms":1000,
        "required_tick_interval_p95_ms":600,"required_tick_interval_max_ms":1000,
        "required_receipt_to_archive_p95_ms":300}
    gate_id=fingerprint({"spec_fingerprint":spec_fingerprint,"measurement":payload})
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        store.connection.execute(
            "INSERT OR IGNORE INTO paper_experimental_collection_gates VALUES (?,?,?,?,?)",
            (gate_id,spec_fingerprint,int(passed),canonical(payload),utc_now()),
        )
        store.connection.commit()
    except BaseException:
        store.connection.rollback()
        raise
    return {"gate_id":gate_id,"spec_fingerprint":spec_fingerprint,"passed":bool(passed),
            "measurement":payload}


def start(store: Store, variant_id: str, hypothesis: dict[str, Any], *,
          restart_reason: str | None = None,
          independent_after_incomplete: bool = False,
          runtime_state: dict[str, Any] | None = None) -> dict[str, Any]:
    validate_start(store, variant_id, hypothesis, runtime_state=runtime_state)
    from .paper import start_paper
    return start_paper(store, variant_id, experimental_hypothesis=hypothesis,
                       restart_reason=restart_reason,
                       independent_after_incomplete=independent_after_incomplete,
                       runtime_state=runtime_state)


def execution_diagnosis(state: dict[str, Any], spec: dict[str, Any],
                        previous_report: dict[str, Any] | None = None,
                        *, now_ms: int | None = None) -> dict[str, Any]:
    """Classify progress since the last review without changing the session."""
    previous_report=previous_report or {}
    old=previous_report.get('progress',{})
    old_signals=int(old.get('signals',previous_report.get('signals',{}).get('live_non_snapshot_fills',0)))
    old_exec=int(old.get('executions',previous_report.get('signals',{}).get('executions',0)))
    old_missed=int(old.get('missed',previous_report.get('signals',{}).get('missed_executions',0)))
    old_reasons=old.get('nonexecution_reasons',previous_report.get('signals',{}).get('nonexecution_reasons',{}))
    signals=int(state.get('signals_received',0)); executions=len(state.get('fills',[]))
    missed=int(state.get('missed_orders',0)); reasons=state.get('nonexecution_reasons',{})
    delta_reasons={key:max(0,int(value)-int(old_reasons.get(key,0)))
                   for key,value in reasons.items() if int(value)>int(old_reasons.get(key,0))}
    progress={'signals':signals,'executions':executions,'missed':missed,
              'delta_signals':max(0,signals-old_signals),
              'delta_executions':max(0,executions-old_exec),
              'delta_missed':max(0,missed-old_missed),
              'nonexecution_reasons':dict(reasons),'delta_nonexecution_reasons':delta_reasons}
    runtime=state.get('paper_runtime',{})
    target=int(spec['execution'].get('paper_tick_target_ms',5000))
    # Diagnose the latest tick against the declared cadence. Lifetime maxima
    # remain visible for context but must not keep a repaired scheduler in a
    # permanent delay state.
    intervals=[int(runtime.get('interval_ms') or 0),
               int(runtime.get('processing_ms') or 0),
               int(runtime.get('max_receipt_lag_ms') or 0)]
    slow=any(value>target for value in intervals)
    if 'priority_exit_unresolved_position' in state.get('diagnostics',[]):
        category,action,detail=('priority_exit_unresolved_position','stop_and_reconcile',
            'A priority close expired without a simulated fill; the nonzero paper position is preserved and this session must be reconciled before any restart.')
    elif progress['delta_executions']>0:
        category,action,detail='execution_progress','continue','At least one virtual execution occurred since the previous review; continue this frozen version and keep measuring costs.'
    elif delta_reasons.get('order_ttl_expired',0):
        if slow:
            category,action,detail='processing_or_collection_delay','collect_data','Observed tick interval, processing time, or receipt lag exceeds the declared paper cadence; restore timely processing and collect a fresh quote/fill sequence before interpreting execution.'
        else:
            category,action,detail='execution_parameters_incompatible','propose_new_version','Signals were present and the observed tick cadence met its target, but orders still expired without execution; review the frozen execution assumptions and propose a separately frozen version using only later observations.'
    elif progress['delta_signals']==0:
        category,action,detail='no_admissible_opportunity','collect_data','No new non-snapshot HYPE signal arrived since the previous review; continue the live subscription and do not infer a signal from REST history.'
    elif delta_reasons:
        category,action,detail='no_admissible_opportunity','collect_data','Signals arrived, but the frozen size, venue minimum, funding window, or available liquidity admitted no execution; collect an admissible opportunity without relaxing the current version.'
    else:
        category,action,detail='execution_not_observed','collect_data','Signals arrived without a recorded execution or explicit execution miss; inspect the live BBO/health sequence and collect a fresh causal opportunity.'
    return {'category':category,'recommended_action':action,'detail':detail,
            'progress':progress,'scheduler':dict(runtime)}


def _action(session: Any, state: dict, summary: dict, run: Any, now: int,
            diagnosis: dict[str, Any]) -> tuple[str, str, str]:
    diagnostics = set(state.get("diagnostics", []))
    if "priority_exit_unresolved_position" in diagnostics:
        return "abandon", diagnosis["detail"], "abandoned"
    if (state.get("risk_halted") or number(summary["drawdown_usdc"]) >= number(run["loss_limit_usdc"])
            or "paper_net_loss_budget_exhausted" in diagnostics):
        return "abandon", "The predeclared paper loss or drawdown limit was reached; preserve the ledger and stop this version.", "abandoned"
    if session["status"] == "suspended":
        feed_markers = ("heartbeat", "connection", "stream", "market_subscription", "leader_signal")
        if any(any(marker in item for marker in feed_markers) for item in diagnostics):
            return "collect_data", "Reconcile a fresh continuous HYPE BBO, stream heartbeat and non-snapshot account fill before any new version.", "suspended"
        if "paper_duration_budget_exhausted" in diagnostics:
            return "propose_new_version", "The frozen paper duration ended; review the stored after-cost ledger before proposing a separately frozen future version.", "completed"
        return "abandon", "The session suspended on a predeclared diagnostic; retain the version and ledger for review.", "suspended"
    healthy = (state.get("connected") and state.get("healthy_at_ms") is not None
               and 0 <= now - int(state["healthy_at_ms"]) <= 65_000)
    if not healthy:
        return "collect_data", "Require a current connection heartbeat and same-session market quote; missing continuity remains unknown.", "active"
    if int(state.get("signals_received", 0)) == 0:
        return "collect_data", "Continue the bounded live subscription until a non-snapshot HYPE fill arrives; no signal has been inferred from REST history.", "active"
    if diagnosis['recommended_action']=='propose_new_version':
        return 'propose_new_version',diagnosis['detail'],'active'
    if diagnosis['recommended_action']=='collect_data':
        return 'collect_data',diagnosis['detail'],'active'
    return "continue", diagnosis['detail'], "active"


def report_due(store: Store, session_id: str, *, clock_ms: int | None = None) -> dict[str, Any] | None:
    initialize(store)
    now = now_ms() if clock_ms is None else clock_ms
    run = store.connection.execute(
        "SELECT * FROM paper_experimental_sessions WHERE session_id=?", (session_id,)
    ).fetchone()
    if not run or run["status"] in {"abandoned", "completed"}:
        return None
    session = store.connection.execute("SELECT * FROM paper_sessions WHERE session_id=?", (session_id,)).fetchone()
    state = json.loads(session["state_json"])
    forced_final = session["status"] == "suspended"
    if now < run["next_review_ms"] and not forced_final:
        return None
    _, spec, plan = get_variant(store, session["variant_id"])
    summary = metrics(state, spec, plan["criteria"]["block_ms"])
    prior_row=store.connection.execute(
        "SELECT report_json FROM paper_experimental_reports WHERE session_id=? ORDER BY review_index DESC LIMIT 1",
        (session_id,)).fetchone()
    prior_report=json.loads(prior_row['report_json']) if prior_row else None
    diagnosis=execution_diagnosis(state,spec,prior_report,now_ms=now)
    next_action, detail, status = _action(session, state, summary, run, now, diagnosis)
    quote = state.get("quote")
    exposure_now = "0"
    quote_age = None
    if quote:
        exposure_now = str(abs(number(state["position"])) * (number(quote["bid"]) + number(quote["ask"])) / 2)
        quote_age = now - int(quote.get("source_received_ms",quote["received_ms"]))
    report_index = int(run["review_index"]) + 1
    due_ms = int(run["next_review_ms"])
    payload = {
        "schema_version": 1,
        "experiment_status": "experimental_paper",
        "hypothesis_id": run["hypothesis_id"],
        "variant_id": session["variant_id"],
        "frozen_fingerprint": run["frozen_fingerprint"],
        "scheduled_review_ms": due_ms,
        "observed_through_ms": int(state.get("last_ms", -1)),
        "session_state": session["status"],
        "feed": {"connected": bool(state.get("connected")), "last_heartbeat_ms": state.get("healthy_at_ms"),
                 "quote_age_ms": quote_age, "wait_conditions": state.get("wait_conditions", []),
                 "quote_source":quote.get('source') if quote else None,
                 "quote_received_ms":quote.get('source_received_ms') if quote else None,
                 "quote_available_ms":quote.get('available_ms') if quote else None,
                 "quote_connection_id":quote.get('session') if quote else None,
                 "diagnostics": sorted(state.get("diagnostics", [])),
                 "exit_uncertainties":state.get('exit_uncertainties',[])},
        "signals": {"live_non_snapshot_fills": int(state.get("signals_received", 0)),
                    "executions": summary["fills"], "missed_executions": summary["missed_orders"],
                    "partial_executions": summary["partial_orders"],
                    "nonexecution_reasons": state.get("nonexecution_reasons", {})},
        "execution_opportunities": {
            "records":state.get("execution_opportunities",[]),
            "eligible":sum(1 for x in state.get("execution_opportunities",[]) if x.get("eligible")),
            "missed":sum(1 for x in state.get("execution_opportunities",[]) if x.get("outcome")=="missed"),
            "executed":sum(1 for x in state.get("execution_opportunities",[]) if x.get("outcome") in {"executed","partial"}),
            "miss_reasons":{key:value for key,value in state.get("nonexecution_reasons",{}).items()},
        },
        "progress": diagnosis['progress'],
        "execution_diagnosis": {key:value for key,value in diagnosis.items() if key not in {'progress','scheduler'}},
        "scheduler": diagnosis['scheduler'],
        "results_after_simulated_costs": {"net_pnl_observed_usdc": summary["net_pnl"],
                    "realized_pnl_usdc": summary["realized_pnl"], "unrealized_pnl_usdc": summary["unrealized_pnl"],
                    "fees_usdc": summary["fees"], "funding_usdc_observed": summary["funding"],
                    "funding_events_observed": summary["funding_events"], "drawdown_usdc": summary["drawdown_usdc"],
                    "funding_coverage": "observed events are included; absence does not prove zero funding"},
        "exposure": {"current_position": state["position"], "current_notional_usdc": exposure_now,
                     "max_observed_notional_usdc": state.get("max_exposure_notional_usdc", "0"),
                     "configured_max_notional_usdc": spec["max_exposure"]["notional_usdc"],
                     "configured_loss_limit_usdc": run["loss_limit_usdc"]},
        "observations_limits": ["experiment is paper only; no historical evaluation or promotion",
             "fill and quote archive may have interruptions; missing funding remains unknown",
             "block uncertainty is descriptive and fills are dependent observations",
             "simulated IOC prices include configured spread/slippage/fees and visible-size cap"],
        "next_action": next_action,
        "next_action_detail": detail,
    }
    next_review = now + int(run["review_interval_ms"]) if status == "active" else now
    report_id = fingerprint({"session_id": session_id, "review_index": report_index, "report": payload})
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        store.connection.execute(
            "INSERT INTO paper_experimental_reports VALUES (?,?,?,?,?,?,?,?,?)",
            (report_id, session_id, report_index, due_ms, int(state.get("last_ms", -1)), canonical(payload),
             next_action, detail, utc_now()),
        )
        store.connection.execute(
            "UPDATE paper_experimental_sessions SET review_index=?, next_review_ms=?, status=? WHERE session_id=?",
            (report_index, next_review, status, session_id),
        )
        store.connection.commit()
    except BaseException:
        store.connection.rollback()
        raise
    return {"session_id": session_id, "report_id": report_id, "report": payload,
            "next_review_ms": next_review, "experiment_status": status}


def add_rectification(store: Store, report_id: str, correction: dict[str, Any]) -> dict[str, Any]:
    """Append a linked correction while leaving the original report immutable."""
    initialize(store)
    original=store.connection.execute(
        "SELECT session_id FROM paper_experimental_reports WHERE report_id=?",(report_id,)
    ).fetchone()
    if not original:
        raise ValueError("Original experimental report not found")
    if not isinstance(correction,dict) or not correction:
        raise ValueError("Structured rectification required")
    rectification_id=fingerprint({"corrects_report_id":report_id,"correction":correction})
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        store.connection.execute(
            "INSERT OR IGNORE INTO paper_experimental_rectifications VALUES (?,?,?,?,?)",
            (rectification_id,report_id,original["session_id"],canonical(correction),utc_now()),
        )
        store.connection.commit()
    except BaseException:
        store.connection.rollback()
        raise
    row=store.connection.execute(
        "SELECT rectification_id,corrects_report_id,session_id,rectification_json,created_at "
        "FROM paper_experimental_rectifications WHERE rectification_id=?",(rectification_id,)
    ).fetchone()
    return {"rectification_id":row["rectification_id"],"corrects_report_id":row["corrects_report_id"],
            "session_id":row["session_id"],"rectification":json.loads(row["rectification_json"]),
            "created_at":row["created_at"]}


def record_incomplete_disposition(store: Store, session_id: str, *, reason: str,
                                 administrative_action_id: str | None = None) -> dict[str, Any]:
    """Record administrative incompleteness without flattening or rewriting a ledger."""
    initialize(store)
    if not reason.strip():
        raise ValueError("Explicit incomplete-disposition reason required")
    session=store.connection.execute(
        "SELECT status,state_json FROM paper_sessions WHERE session_id=?",(session_id,)
    ).fetchone()
    if not session:
        raise ValueError("Unknown paper session")
    state=json.loads(session["state_json"])
    position=str(state["position"])
    if number(position)==0:
        raise ValueError("Incomplete residual disposition requires a preserved nonzero position")
    if state.get("pending"):
        raise ValueError("Incomplete residual disposition requires no pending paper orders")
    disposition={"schema_version":1,"status":"administratively_incomplete",
        "paper_session_status":session["status"],"residual_position":position,
        "closing_fill":None,"final_round_trip_result":"unknown","reason":reason.strip(),
        "administrative_action_id":administrative_action_id}
    disposition_id=fingerprint({"session_id":session_id,"disposition":disposition})
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        store.connection.execute(
            "INSERT OR IGNORE INTO paper_experimental_dispositions VALUES (?,?,?,?)",
            (disposition_id,session_id,canonical(disposition),utc_now()),
        )
        store.connection.commit()
    except BaseException:
        store.connection.rollback()
        raise
    row=store.connection.execute(
        "SELECT disposition_id,session_id,disposition_json,created_at "
        "FROM paper_experimental_dispositions WHERE disposition_id=?",(disposition_id,)
    ).fetchone()
    return {"disposition_id":row["disposition_id"],"session_id":row["session_id"],
            "disposition":json.loads(row["disposition_json"]),"created_at":row["created_at"]}


def status(store: Store, session_id: str | None = None) -> list[dict[str, Any]]:
    initialize(store)
    where, args = (" WHERE e.session_id=?", (session_id,)) if session_id else ("", ())
    rows = store.connection.execute(
        "SELECT e.*,p.variant_id,p.network,p.address,p.coin,p.status AS paper_status "
        "FROM paper_experimental_sessions e JOIN paper_sessions p USING(session_id)" + where +
        " ORDER BY e.created_ms", args
    ).fetchall()
    output = []
    for row in rows:
        latest = store.connection.execute(
            "SELECT report_id,review_index,next_action,action_detail,report_json,created_at "
            "FROM paper_experimental_reports WHERE session_id=? ORDER BY review_index DESC LIMIT 1",
            (row["session_id"],),
        ).fetchone()
        output.append({"session_id": row["session_id"], "variant_id": row["variant_id"],
            "network": row["network"], "address": row["address"], "coin": row["coin"],
            "hypothesis_id": row["hypothesis_id"], "status": row["status"],
            "paper_status": row["paper_status"], "review_interval_ms": row["review_interval_ms"],
            "next_review_ms": row["next_review_ms"], "review_index": row["review_index"],
            "latest_report": json.loads(latest["report_json"]) if latest else None})
    return output
