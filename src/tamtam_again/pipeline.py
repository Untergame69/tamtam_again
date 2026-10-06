"""Bounded deterministic N1 -> N2 scheduler, no language-model promotions."""
from __future__ import annotations

from typing import Any
from .paper import archive_events, classify_regimes, paper_tick, start_paper
from .storage import Store
from .validation import decision, evaluate, get_variant, initialize, now_ms


def tick(store: Store) -> dict[str,Any]:
    initialize(store)
    reports = []
    for variant in store.connection.execute("SELECT variant_id FROM strategy_variants").fetchall():
        row,spec,plan = get_variant(store,variant[0])
        if row["synthetic"]:
            continue
        for stage in ("comparison","final"):
            if now_ms() < plan[stage]["end_ms"]:
                decision(store,row["network"],row["address"],row["coin"],"needs_data",f"{stage} window not complete",
                         {"received_until_ms":plan[stage]["end_ms"]},"evaluate_unchanged_variant",{"variant_id":variant[0]})
                break
            prior = store.connection.execute("SELECT status,result_json FROM validation_evaluations WHERE variant_id=? AND stage=? ORDER BY created_at DESC LIMIT 1",(variant[0],stage)).fetchone()
            if prior:
                if prior["status"] != "passed":
                    break
                if stage == "final":
                    reports.append(start_paper(store,variant[0]))
                continue
            try:
                window = plan[stage]
                events,_ = archive_events(store,row["network"],row["address"],row["coin"],window["start_ms"],window["end_ms"])
                result = evaluate(store,variant[0],stage,classify_regimes(events,plan["criteria"]),provenance="local_archive")
                reports.append(result)
                if result["status"] != "passed":
                    break
                if result["promotable"]:
                    reports.append(start_paper(store,variant[0]))
            except ValueError as exc:
                decision(store,row["network"],row["address"],row["coin"],"needs_data",str(exc),
                         {"archive_or_plan_correction_required":True},"inspect_validation_evidence",{"variant_id":variant[0],"stage":stage})
                reports.append({"variant_id":variant[0],"stage":stage,"status":"waiting","reason":str(exc)})
                break
    for session in store.connection.execute("SELECT session_id FROM paper_sessions WHERE status='active'").fetchall():
        try:
            reports.append(paper_tick(store,session[0]))
        except ValueError as exc:
            reports.append({"session_id":session[0],"status":"waiting","reason":str(exc)})
    return {"processed":reports,"live_orders_enabled":False}
