"""Bounded deterministic N1 -> N2 scheduler, no language-model promotions."""
from __future__ import annotations

from typing import Any
from .engine import canonical
from .paper import archive_events, classify_regimes, paper_tick, start_paper
from .storage import Store
from .validation import decision, evaluate, get_variant, initialize, now_ms


def _coverage_failure_is_frozen(store: Store, network: str, address: str,
                                coin: str, variant_id: str, stage: str) -> bool:
    """A completed local receipt window cannot gain eligible late receipts.

    These exact coverage failures require a new prospective plan or an
    explicit archive correction. Re-reading and decompressing the same
    high-rate BBO window on every five-second paper tick cannot change them.
    """
    evidence = canonical({"variant_id": variant_id, "stage": stage})
    wake = canonical({"archive_or_plan_correction_required": True})
    row = store.connection.execute(
        "SELECT 1 FROM pipeline_decisions WHERE network=? AND address=? AND coin=? "
        "AND state='needs_data' AND wake_json=? AND evidence_json=? "
        "AND diagnostic IN ('Heartbeat gap inside validation window', "
        "'Archive does not establish observation coverage of this complete window') LIMIT 1",
        (network, address, coin, wake, evidence),
    ).fetchone()
    return row is not None


def tick(store: Store) -> dict[str,Any]:
    return _tick(store)


def synthetic_tick(store: Store, fixtures: dict[str,dict[str,list]], *, chronological: bool = False) -> dict[str,Any]:
    """Exercise the same scheduler in an exclusively synthetic recipe database."""
    initialize(store)
    if not isinstance(fixtures,dict) or not fixtures:raise ValueError('Explicit synthetic fixture mapping required')
    if store.connection.execute('select 1 from validation_plans where synthetic=0').fetchone():
        raise ValueError('Synthetic scheduler forbidden in any database containing real plans')
    return _tick(store,fixtures=fixtures,chronological=chronological)


def _tick(store: Store, *, fixtures=None, chronological=False) -> dict[str,Any]:
    initialize(store)
    reports = []
    if store.connection.execute("select 1 from sqlite_master where name='experiment_families'").fetchone():
        from .experiments import select_final
        from .reserve_cycle import abandoned_final
        for family,plan_id in store.connection.execute('select family_id,plan_id from experiment_families').fetchall():
            if abandoned_final(store,plan_id,now_ms()):continue
            try:select_final(store,family)
            except ValueError as exc:
                reports.append({'family_id':family,'stage':'selection','status':'waiting',
                                'reason':str(exc),'next_action':'complete comparisons before final opens; otherwise create a new prospective plan'})
    for variant in store.connection.execute("SELECT variant_id FROM strategy_variants").fetchall():
        row,spec,plan = get_variant(store,variant[0])
        if plan.get("experiment_mode") == "experimental_paper_only":
            # These versions run prospectively under paper monitoring only.
            # They are never evaluated or promoted by the N1 scheduler.
            continue
        from .reserve_cycle import abandoned_final
        if abandoned_final(store,row['plan_id'],now_ms()):
            reports.append({'variant_id':variant[0],'status':'abandoned_for_development','next_action':'new prospective plan required'})
            continue
        if row["synthetic"] and fixtures is None:
            continue
        for stage in ("comparison","final"):
            if stage=='final' and 'funding_sensitivity_scenario' in spec['execution']:
                reports.append({'variant_id':variant[0],'status':'exploratory_complete',
                    'diagnostic':'Chosen funding sensitivity cannot authorize a final reserve or paper'})
                break
            if (fixtures is None or chronological) and now_ms() < plan[stage]["end_ms"]:
                decision(store,row["network"],row["address"],row["coin"],"needs_data",f"{stage} window not complete",
                         {"received_until_ms":plan[stage]["end_ms"]},"evaluate_unchanged_variant",{"variant_id":variant[0]})
                break
            if (fixtures is None and now_ms() >= plan[stage]["end_ms"]
                    and _coverage_failure_is_frozen(store,row['network'],row['address'],
                                                    row['coin'],variant[0],stage)):
                reports.append({"variant_id": variant[0], "stage": stage,
                                "status": "waiting",
                                "reason": "Completed archive window already failed its immutable coverage check",
                                "next_action": "create a new prospective plan after any archive correction"})
                break
            prior = store.connection.execute("SELECT status,result_json FROM validation_evaluations WHERE variant_id=? AND stage=? ORDER BY created_at DESC LIMIT 1",(variant[0],stage)).fetchone()
            if prior:
                if prior["status"] != "passed":
                    break
                if stage == "final":
                    try:
                        reports.append(start_paper(store,variant[0],synthetic_recipe=fixtures is not None))
                    except ValueError as exc:
                        reports.append({'variant_id':variant[0],'stage':'paper_handover',
                                        'status':'waiting','reason':str(exc),
                                        'next_action':'review prior sessions and preserve position attribution'})
                continue
            try:
                if stage=='final':
                    from .experiments import require_final_selection
                    require_final_selection(store,variant[0])
                window = plan[stage]
                if fixtures is None:
                    events,_ = archive_events(store,row["network"],row["address"],row["coin"],window["start_ms"],window["end_ms"],
                            funding_witnesses=spec["execution"].get("funding_witnesses"))
                else:
                    events=fixtures.get(variant[0],{}).get(stage,[])
                result = evaluate(store,variant[0],stage,classify_regimes(events,plan["criteria"]),provenance="synthetic" if fixtures is not None else "local_archive")
                reports.append(result)
                if result["status"] != "passed":
                    break
                if result["promotable"] or (fixtures is not None and stage=="final" and result["status"]=="passed"):
                    reports.append(start_paper(store,variant[0],synthetic_recipe=fixtures is not None))
            except ValueError as exc:
                decision(store,row["network"],row["address"],row["coin"],"needs_data",str(exc),
                         {"archive_or_plan_correction_required":True},"inspect_validation_evidence",{"variant_id":variant[0],"stage":stage})
                reports.append({"variant_id":variant[0],"stage":stage,"status":"waiting","reason":str(exc)})
                break
    if fixtures is None:
        from .procedure_references import tick_references
        reports.extend(tick_references(store,max_starts=1))
    for session in store.connection.execute("SELECT session_id,variant_id FROM paper_sessions WHERE status='active'").fetchall():
        try:
            if fixtures is None:
                reports.append(paper_tick(store,session[0]))
                from .experimental_paper import report_due
                experimental_report = report_due(store,session[0])
                if experimental_report:
                    reports.append(experimental_report)
                    if experimental_report.get('experiment_status') in {'completed','abandoned','suspended'}:
                        request_row=store.connection.execute(
                            "SELECT request_id FROM execution_correction_requests WHERE target_session_id=?",
                            (session[0],)).fetchone() if store.connection.execute(
                                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_correction_requests'").fetchone() else None
                        if request_row:
                            from .execution_correction import complete_request
                            complete_request(store,request_row['request_id'],experimental_report['report_id'],
                                {'experiment_status':experimental_report['experiment_status'],
                                 'next_action':experimental_report['report']['next_action'],
                                 'report':experimental_report['report']})
            else:
                from .paper import synthetic_recipe_tick
                events=fixtures.get(session['variant_id'],{}).get('paper',[])
                if events:reports.append(synthetic_recipe_tick(store,session[0],events))
        except ValueError as exc:
            reports.append({"session_id":session[0],"status":"waiting","reason":str(exc)})
    from .paper_adaptation import recover as recover_adaptation
    reports.extend(recover_adaptation(store,clock_ms=now_ms(),max_requests=8))
    if fixtures is None:
        # A terminal paper outcome becomes the next persistent task inside the
        # normal pipeline tick. Recovery is bounded and idempotent by session.
        from .paper_followup import recover_completed_reports
        reports.extend(recover_completed_reports(store,clock_ms=now_ms(),max_tasks=8))
    result={"processed":reports,"live_orders_enabled":False}
    if fixtures is not None:result.update(synthetic_recipe=True,real_strategy_validated=False)
    return result
