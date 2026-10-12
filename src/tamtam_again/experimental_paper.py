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
"""

REQUIRED_HYPOTHESIS = {
    "schema_version", "hypothesis_id", "observations", "interpretation",
    "claim", "signal", "entry", "exit", "execution", "risk",
    "decision_rules", "evidence_refs", "review_interval_ms", "max_duration_ms",
}


def initialize(store: Store) -> None:
    store.connection.executescript(SCHEMA)


def validate_start(store: Store, variant_id: str, hypothesis: dict[str, Any]) -> tuple[Any, dict, dict]:
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
    return row, spec, plan


def start(store: Store, variant_id: str, hypothesis: dict[str, Any], *,
          restart_reason: str | None = None) -> dict[str, Any]:
    validate_start(store, variant_id, hypothesis)
    from .paper import start_paper
    return start_paper(store, variant_id, experimental_hypothesis=hypothesis,
                       restart_reason=restart_reason)


def _action(session: Any, state: dict, summary: dict, run: Any, now: int) -> tuple[str, str, str]:
    diagnostics = set(state.get("diagnostics", []))
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
    return "continue", "Feed and causal signals are present and limits remain clear; continue this frozen version to its next scheduled review.", "active"


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
    next_action, detail, status = _action(session, state, summary, run, now)
    quote = state.get("quote")
    exposure_now = "0"
    quote_age = None
    if quote:
        exposure_now = str(abs(number(state["position"])) * (number(quote["bid"]) + number(quote["ask"])) / 2)
        quote_age = now - int(quote["received_ms"])
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
                 "diagnostics": sorted(state.get("diagnostics", []))},
        "signals": {"live_non_snapshot_fills": int(state.get("signals_received", 0)),
                    "executions": summary["fills"], "missed_executions": summary["missed_orders"],
                    "partial_executions": summary["partial_orders"],
                    "nonexecution_reasons": state.get("nonexecution_reasons", {})},
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
