"""Deterministic paper outcome -> persistent research task handoff."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .engine import canonical, fingerprint
from .hype_diagnostics import fee_crossed_summary, live_fills, ms, quantiles
from .paper_adaptation import initialize as initialize_adaptation
from .paper_research import initialize as initialize_research
from .research_memory import authorized_period

TERMINAL_EXPERIMENTS = {"completed", "abandoned"}
TERMINAL_SESSIONS = {"suspended", "retired"}
COLLECTION_CODES = {
    "connection_interrupted", "market_subscription_missing",
    "connection_changed_without_reconciliation", "missing_live_heartbeat",
}


def choose_route(experiment_status: str, report: dict) -> dict:
    """Choose a deterministic next task from evidence, never from duration alone."""
    if experiment_status not in TERMINAL_EXPERIMENTS:
        return {"route": "wait", "state": "waiting", "reason": "final report not terminal",
                "wake": {"kind": "terminal_report_available"}}
    feed = report.get("feed") or {}
    diagnostics = set(feed.get("diagnostics", []))
    if feed.get("connected") is False or diagnostics & COLLECTION_CODES:
        return {"route": "targeted_collection", "state": "collection_required",
                "reason": "report contains a concrete feed/coverage failure",
                "wake": {"kind": "named_collection_evidence_available"}}
    diagnosis = report.get("execution_diagnosis") or {}
    if diagnosis.get("category") in {"execution_invariant_failure", "execution_model_error", "priority_exit_failure"}:
        return {"route": "execution_correction", "state": "correction_required",
                "reason": "report records a deterministic execution invariant failure",
                "wake": {"kind": "correction_reviewed_and_tested"}}
    if experiment_status == "abandoned":
        return {"route": "abandon", "state": "archived", "reason": "experiment explicitly abandoned",
                "wake": {"kind": "new_independent_evidence"}}
    results = report.get("results_after_simulated_costs") or {}
    signals = report.get("signals") or {}
    if results.get("economic_result_complete") is False:
        return {"route":"wait","state":"waiting","reason":"funding costs remain unknown; observed components are not after-cost results",
                "wake":{"kind":"observed_funding_costs_required"}}
    required = {"net_pnl_observed_usdc", "fees_usdc", "funding_events_observed"}
    if required <= results.keys() and "live_non_snapshot_fills" in signals:
        return {"route": "strategic_analysis", "state": "budget_required",
                "reason": "terminal after-cost results and signal coverage exist; interpretation remains unproven",
                "wake": {"kind": "explicit_shared_budget_available"}}
    return {"route": "wait", "state": "waiting", "reason": "final report lacks required result fields",
            "wake": {"kind": "report_evidence_completed"}}


def reconstruct_lineage(signals: list[dict], opportunities: list[dict], fills: list[dict], *,
                        max_receipt_lag_ms: int) -> dict:
    """Keep causal candidates distinct from persisted joins and exact fill joins."""
    grouped: dict[int, list[dict]] = {}
    for index, opportunity in enumerate(opportunities):
        decision_ms = opportunity.get("signal_decision_ms")
        if type(decision_ms) is int:
            grouped.setdefault(decision_ms, []).append(opportunity | {"_index": index})
    decisions = sorted(grouped)
    signal_links = []
    for signal in signals:
        received = signal.get("received_ms")
        candidates = ([d for d in decisions if type(received) is int
                      and 0 <= d-received <= max_receipt_lag_ms])
        signal_links.append({
            "source_tid": signal.get("tid"),
            "status": "unknown" if not candidates else "temporal_candidate" if len(candidates) == 1 else "multiple_candidates",
            "decision_candidates_ms": candidates,
            "exact_source_decision_key_persisted": False,
        })
    used_fills: set[int] = set()
    order_links = []
    decision_links = []
    for decision_ms in decisions:
        group = grouped[decision_ms]
        order_refs = []
        for item in group:
            opportunity_id = fingerprint({"report_record_index": item["_index"],
                **{k: v for k, v in item.items() if k != "_index"}})
            order_refs.append(opportunity_id)
            matches = [i for i, fill in enumerate(fills) if i not in used_fills
                       and fill.get("received_ms") == item.get("execution_decision_ms")
                       and fill.get("size") == item.get("fill_size")]
            if item.get("outcome") not in {"executed", "partial"}:
                link = {"status": "no_fill", "paper_fill_indices": []}
            elif len(matches) == 1:
                used_fills.add(matches[0])
                link = {"status": "unique_exact_timestamp_and_size", "paper_fill_indices": matches}
            elif len(matches) > 1:
                link = {"status": "multiple_exact_attribute_matches", "paper_fill_indices": matches}
            else:
                link = {"status": "unknown", "paper_fill_indices": []}
            order_links.append({"order_ref": opportunity_id,
                "decision_ms": decision_ms, "intent": item.get("intent"),
                "outcome": item.get("outcome"), "fill_link": link})
        decision_links.append({"decision_ms": decision_ms, "order_refs": order_refs,
                               "relation": "one_to_many" if len(order_refs) > 1 else "one_to_one"})
    return {
        "source_signal_to_decision": signal_links,
        "decision_to_order": decision_links,
        "order_to_paper_fill": order_links,
        "limits": ["Signal decision timestamps are stored, but the triggering source TID is not.",
                   "Temporal candidates use the observed maximum receive-to-process lag and are not exact joins.",
                   "Order-to-fill matches require a unique exact execution timestamp and fill size; other links remain unknown or multiple."],
    }


def _decode(row):
    from .storage import decode_observation_payload
    return decode_observation_payload(row)


def _iso(ms_value: int) -> str:
    return datetime.fromtimestamp(ms_value/1000, timezone.utc).isoformat(timespec="milliseconds")


def build_packet(store, session_id: str, report_id: str, *, available_ms: int,
                 max_chars: int = 225_000) -> dict:
    if type(available_ms) is not int or available_ms < 0 or type(max_chars) is not int or max_chars < 1:
        raise ValueError("Explicit packet availability and size required")
    session = store.connection.execute("SELECT * FROM paper_sessions WHERE session_id=?", (session_id,)).fetchone()
    experiment = store.connection.execute("SELECT * FROM paper_experimental_sessions WHERE session_id=?", (session_id,)).fetchone()
    report_row = store.connection.execute("SELECT * FROM paper_experimental_reports WHERE report_id=? AND session_id=?",
                                           (report_id, session_id)).fetchone()
    suspension = store.connection.execute("SELECT suspended_ms,diagnostics_json FROM paper_suspensions WHERE session_id=?",
                                           (session_id,)).fetchone()
    if (not session or not experiment or not report_row or not suspension
            or session["status"] not in TERMINAL_SESSIONS
            or experiment["status"] not in TERMINAL_EXPERIMENTS
            or report_row["review_index"] != experiment["review_index"]
            or report_row["observed_through_ms"] > available_ms
            or suspension["suspended_ms"] > available_ms):
        raise ValueError("Available terminal paper report and suspension required")
    period = {"network": session["network"], "address": session["address"],
              "market": session["coin"], "start_ms": session["started_ms"],
              "end_ms": report_row["observed_through_ms"]}
    # Protect the source period before reading any raw observations.
    if not authorized_period(store, period, available_ms, end_inclusive=True):
        raise ValueError("Paper outcome period intersects an unreleased reserve")

    report = json.loads(report_row["report_json"])
    state = json.loads(session["state_json"])
    spec_row = store.connection.execute("SELECT spec_json,frozen_ms FROM strategy_variants WHERE variant_id=?",
                                        (session["variant_id"],)).fetchone()
    if not spec_row or spec_row["frozen_ms"] > session["started_ms"]:
        raise ValueError("Frozen simulation parameters unavailable before paper start")
    spec = json.loads(spec_row["spec_json"])

    start_cursor = store.connection.execute("SELECT coalesce(max(observation_id),0) FROM raw_observations "
        "WHERE network=? AND observed_at<?", (session["network"], _iso(session["started_ms"]))).fetchone()[0]
    end_cursor = int(session["last_observation_id"])
    coverage = {}
    for row in store.connection.execute("""SELECT source,endpoint,entity_type,entity_id,count(*) AS observations,
            min(observation_id) AS first_id,max(observation_id) AS last_id,sum(coalesce(record_count,0)) AS records
        FROM raw_observations WHERE network=? AND observation_id>? AND observation_id<=?
          AND observed_at>=? AND observed_at<=?
          AND ((entity_type='account' AND entity_id=? AND endpoint IN ('userFills','userFundings'))
            OR (entity_type='market' AND entity_id=? AND endpoint IN ('bbo','l2Book')))
        GROUP BY source,endpoint,entity_type,entity_id""",
        (session["network"], start_cursor, end_cursor, _iso(session["started_ms"]), _iso(report_row["observed_through_ms"]),
         session["address"], session["coin"])):
        key = f"{row['source']}:{row['endpoint']}"
        coverage[key] = {"observations": row["observations"], "record_count_sum": row["records"],
                         "observation_id_span": [row["first_id"], row["last_id"]]}

    source_signals = []
    event_to_receipt, receipt_to_archive = [], []
    ws_rows = store.connection.execute("""SELECT * FROM raw_observations WHERE source='hyperliquid-websocket-v1'
        AND network=? AND entity_type='account' AND entity_id=? AND endpoint='userFills'
        AND observation_id>? AND observation_id<=? AND observed_at>=? AND observed_at<=?
        ORDER BY observation_id""",
        (session["network"], session["address"], start_cursor, end_cursor,
         _iso(session["started_ms"]), _iso(report_row["observed_through_ms"]))).fetchall()
    for raw in ws_rows:
        payload = _decode(raw)
        request = json.loads(raw["request_json"])
        received_ms = ms(raw["requested_at"])
        archived_ms = ms(raw["observed_at"])
        receipt_to_archive.append(archived_ms-received_ms)
        for fill in live_fills(payload, request, session["coin"]):
            event_ms = int(fill["time"])
            if not session["started_ms"] <= event_ms <= received_ms or received_ms > report_row["observed_through_ms"]:
                continue
            delta = float(fill["sz"]) * (1 if fill.get("side") == "B" else -1)
            source_signals.append({"tid": str(fill["tid"]), "event_ms": event_ms,
                "received_ms": received_ms, "archived_ms": archived_ms,
                "delta": fill["sz"] if fill.get("side") == "B" else "-"+fill["sz"],
                "crossed": fill.get("crossed"), "fee": fill.get("fee"),
                "fee_token": fill.get("feeToken"), "builderFee": fill.get("builderFee"),
                "observation_id": raw["observation_id"]})
            event_to_receipt.append(received_ms-event_ms)

    opportunities = report.get("execution_opportunities", {}).get("records", [])
    fills = state.get("fills", [])
    max_receipt_lag = int(report.get("scheduler", {}).get("max_receipt_lag_ms_since_start", 0))
    lineage = reconstruct_lineage(source_signals, opportunities, fills,
                                  max_receipt_lag_ms=max_receipt_lag)
    successful = [x for x in opportunities if x.get("outcome") in {"executed", "partial"}]
    execution_decision_lags = [int(x["execution_decision_ms"])-int(x["signal_decision_ms"]) for x in successful]
    due_lags = [int(x["execution_decision_ms"])-int(x["due_ms"]) for x in successful]
    quote_ages = [int(x["quote_age_ms"]) for x in successful if x.get("quote_age_ms") is not None]
    snapshot = store.connection.execute("SELECT snapshot_id FROM paper_snapshots WHERE session_id=? AND available_ms<=? "
        "ORDER BY available_ms DESC,snapshot_id LIMIT 1", (session_id, report_row["observed_through_ms"])).fetchone()
    if not snapshot:
        raise ValueError("Immutable paper snapshot for final report required")
    metrics = report.get("results_after_simulated_costs", {})
    route = choose_route(experiment["status"], report)
    pending = state.get("pending", [])
    packet = {
        "schema_version": "paper-outcome-research-v1",
        "session_id": session_id, "variant_id": session["variant_id"], "report_id": report_id,
        "available_ms": int(report_row["observed_through_ms"]),
        "source_periods": [period], "source_period_membership": "paper report observed-through boundary",
        "results": metrics,
        "coverage": {"window_start_ms": session["started_ms"], "observed_through_ms": report_row["observed_through_ms"],
            "observation_cursor_start": start_cursor, "observation_cursor_start_is_reconstructed": True,
            "observation_cursor_end": end_cursor, "observations_by_source_endpoint": coverage,
            "report_feed": report.get("feed"), "signal_counts": report.get("signals"),
            "coverage_limits": report.get("observations_limits", [])},
        "simulated_parameters": {"variant_id": session["variant_id"], "frozen_ms": spec_row["frozen_ms"], "spec": spec},
        "measured_delays_ms": {"event_to_receipt": quantiles(event_to_receipt),
            "receipt_to_archive": quantiles(receipt_to_archive),
            "archive_to_decision": {"status": "not_persisted_per_event", "maximum_receipt_to_processing_ms": max_receipt_lag},
            "decision_to_simulated_execution": quantiles(execution_decision_lags),
            "due_to_simulated_execution": quantiles(due_lags), "quote_age_at_simulated_fill": quantiles(quote_ages),
            "paper_runtime": report.get("scheduler", {})},
        "costs": {"reported_after_simulated_costs": metrics,
            "source_fee_crossed_summary": fee_crossed_summary(source_signals),
            "configured_fee_model": spec.get("fees"), "configured_slippage_model": spec.get("slippage"),
            "funding_absence_is_not_zero": True},
        "refusal_reasons": report.get("execution_opportunities", {}).get("miss_reasons", {}),
        "lineage": lineage,
        "residual": {"position": state.get("position"), "pending_orders": pending,
            "round_trip_result": "unknown while residual or pending order remains" if state.get("position") not in ("0", 0) or pending else "bounded session ledger complete",
            "no_closure_inferred": True},
        "route": route,
        "evidence_refs": ["paper_sessions:"+session_id, "paper_experimental_sessions:"+session_id,
            "paper_experimental_reports:"+report_id, "paper_snapshots:"+snapshot["snapshot_id"],
            f"raw_observations:{start_cursor}..{end_cursor}"],
        "research_contract": {"model_calls_authorized": 0, "profitability_proven": False,
            "strategy_promotion_authorized": False, "new_version_authorized": False,
            "existing_session_or_position_mutation_authorized": False},
    }
    packet["fingerprint"] = fingerprint(packet)
    if len(canonical(packet)) > max_chars:
        # Keep the task ready even when individual historical links cannot fit.
        packet["lineage"] = {"source_signal_count": len(source_signals),
            "decision_count": len(lineage["decision_to_order"]), "order_count": len(opportunities),
            "paper_fill_count": len(fills), "source_signal_to_decision": "unknown: compacted to packet budget",
            "decision_to_order": "see automatic paper report evidence ref",
            "order_to_paper_fill": "see automatic paper report evidence ref",
            "limits": lineage["limits"]}
        packet.pop("fingerprint", None)
        packet["fingerprint"] = fingerprint(packet)
    if len(canonical(packet)) > max_chars:
        raise ValueError("Paper outcome summary exceeds configured packet bound")
    return packet


def present_report(store, session_id: str, report_id: str, *, clock_ms: int,
                   policy: dict | None = None, max_packet_chars: int = 225_000) -> dict:
    """Persist one outcome task and bounded packet; no model call or version start."""
    if type(clock_ms) is not int or clock_ms < 0:
        raise ValueError("Explicit task availability required")
    initialize_adaptation(store)
    initialize_research(store)
    existing_task = store.connection.execute("SELECT adaptation_request_id,task_id,source_fingerprint,packet_json,route_json "
        "FROM paper_outcome_packets WHERE session_id=? AND report_id=?", (session_id, report_id)).fetchone()
    if existing_task:
        saved_packet = json.loads(existing_task["packet_json"])
        return {"status": "unchanged", "request_id": existing_task["adaptation_request_id"],
            "job_id": existing_task["task_id"], "route": json.loads(existing_task["route_json"]),
            "packet_fingerprint": existing_task["source_fingerprint"],
            "packet_chars": len(canonical(saved_packet)), "model_calls": 0}
    packet = build_packet(store, session_id, report_id, available_ms=clock_ms, max_chars=max_packet_chars)
    route = packet["route"]
    if route["state"] != "budget_required":
        status = route["state"]
    else:
        status = "budget_required"
    request_id = fingerprint({"kind": "paper-outcome-task", "session_id": session_id,
                              "report_id": report_id, "packet_fingerprint": packet["fingerprint"]})
    suspension = store.connection.execute("SELECT suspended_ms FROM paper_suspensions WHERE session_id=?",
                                          (session_id,)).fetchone()
    diagnostic = {"schema_version": "paper-outcome-task-v1", "request_id": request_id,
        "session_id": session_id, "source_report_id": report_id, "created_ms": clock_ms,
        "suspension_ms": suspension["suspended_ms"], "state": "research_budget_required" if status == "budget_required" else status,
        "route": route["route"], "next_action": route["reason"], "wake": route["wake"],
        "paper_snapshot_available_ms": packet["available_ms"],
        "observed_paper_metrics": packet["results"], "evidence_refs": packet["evidence_refs"],
        "input_fingerprint": packet["fingerprint"],
        "model_calls_authorized": 0, "promotion_authorized": False, "new_version_authorized": False}
    adaptation_id = request_id
    job_id = fingerprint({"adaptation_request_id": adaptation_id, "packet": packet["fingerprint"]})
    route_json = {"route": route["route"], "state": status, "reason": route["reason"],
        "wake": route["wake"], "source_report_id": report_id, "packet_fingerprint": packet["fingerprint"],
        "model_calls_authorized": 0, "promotion_authorized": False, "new_version_authorized": False}
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        existing = store.connection.execute("SELECT request_id,diagnostic_json FROM paper_adaptation_requests WHERE session_id=?",
                                             (session_id,)).fetchone()
        if existing:
            saved = json.loads(existing["diagnostic_json"])
            adaptation_id = saved["request_id"]
            job_id = fingerprint({"adaptation_request_id": adaptation_id, "packet": packet["fingerprint"]})
            saved_task = store.connection.execute("SELECT task_id,report_id,source_fingerprint,packet_json FROM paper_outcome_packets WHERE adaptation_request_id=?",
                                                   (adaptation_id,)).fetchone()
            if saved_task:
                if (saved_task["report_id"] != report_id or saved_task["source_fingerprint"] != packet["fingerprint"]
                        or saved_task["packet_json"] != canonical(packet)):
                    raise ValueError("Session already has a different immutable report handoff")
                store.connection.commit()
                return {"status": "unchanged", "request_id": adaptation_id, "job_id": saved_task["task_id"],
                    "route": route_json, "packet_fingerprint": packet["fingerprint"],
                    "packet_chars": len(canonical(packet)), "model_calls": 0}
        else:
            store.connection.execute("INSERT INTO paper_adaptation_requests VALUES(?,?,?,?,?)",
                (request_id, session_id, clock_ms, suspension["suspended_ms"], canonical(diagnostic)))
        frozen_policy = policy or {"state": "budget_required", "model_calls_authorized": 0,
                                   "shared_budget_required": True}
        store.connection.execute("INSERT OR IGNORE INTO paper_research_jobs "
            "(request_id,adaptation_request_id,session_id,created_ms,packet_json,policy_json,status,network,address,updated_ms,result_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, adaptation_id, session_id, clock_ms, canonical(packet), canonical(frozen_policy),
             status, packet["source_periods"][0]["network"], packet["source_periods"][0]["address"],
             clock_ms, canonical(route_json)))
        store.connection.execute("INSERT OR IGNORE INTO paper_outcome_packets "
            "(adaptation_request_id,session_id,report_id,created_ms,source_fingerprint,packet_json,route_json,task_id) "
            "VALUES(?,?,?,?,?,?,?,?)", (adaptation_id, session_id, report_id, clock_ms,
                packet["fingerprint"], canonical(packet), canonical(route_json), job_id))
        saved_job = store.connection.execute("SELECT request_id,packet_json,status,result_json FROM paper_research_jobs "
            "WHERE request_id=? AND parent_request_id IS NULL", (job_id,)).fetchone()
        if not saved_job or saved_job["request_id"] != job_id or saved_job["packet_json"] != canonical(packet):
            raise ValueError("Persisted paper task differs from prepared evidence")
        store.connection.commit()
    except BaseException:
        store.connection.rollback()
        raise
    return {"status": "unchanged" if existing else status, "request_id": adaptation_id,
        "job_id": job_id, "route": route_json, "packet_fingerprint": packet["fingerprint"],
        "packet_chars": len(canonical(packet)), "model_calls": 0}


def recover_completed_reports(store, *, clock_ms: int, max_tasks: int = 8) -> list[dict]:
    if type(max_tasks) is not int or not 1 <= max_tasks <= 64:
        raise ValueError("Bounded completed-report recovery required")
    if not store.connection.execute("SELECT 1 FROM sqlite_master WHERE name='paper_experimental_reports'").fetchone():
        return []
    initialize_adaptation(store)
    initialize_research(store)
    rows = store.connection.execute("""SELECT e.session_id,r.report_id FROM paper_experimental_sessions e
        JOIN paper_sessions s USING(session_id)
        JOIN paper_experimental_reports r ON r.session_id=e.session_id AND r.review_index=e.review_index
        WHERE e.status IN ('completed','abandoned') AND s.status IN ('suspended','retired')
          AND NOT EXISTS (SELECT 1 FROM paper_outcome_packets p WHERE p.session_id=e.session_id)
        ORDER BY r.observed_through_ms,e.session_id LIMIT ?""", (max_tasks,)).fetchall()
    output = []
    for row in rows:
        try:
            output.append(present_report(store, row["session_id"], row["report_id"], clock_ms=clock_ms))
        except ValueError as exc:
            output.append({"session_id": row["session_id"], "report_id": row["report_id"],
                           "status": "waiting", "reason": str(exc), "model_calls": 0})
    return output
