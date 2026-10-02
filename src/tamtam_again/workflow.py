"""Idempotent queue and version ledger for Hermes RE and Paper N1 jobs."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from .analysis import _fills_from_observation, cohort_research_status
from .storage import Store, decode_observation_payload, utc_now


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGET = 30
NEXT_TARGET_AFTER_ACCEPT = 100
LEASE_MINUTES = 45


def workflow_tick(store: Store, network: str, stage: str = "research") -> dict[str, Any]:
    """Create eligible research runs, then return queued/expired tasks for Hermes."""
    if stage not in {"research", "paper"}:
        raise ValueError("stage doit être research ou paper")
    now = utc_now()
    if stage == "research":
        status = cohort_research_status(store, network)
        _queue_research_runs(store, status, network)
    pending = list(store.connection.execute(
        """SELECT run_id,stage,network,address,coin,threshold_cycles,attempt,
                  cycle_count,status,request_path,artifact_path,lease_until
           FROM automation_runs WHERE stage=? AND network=?
             AND (status='queued' OR (status='running' AND lease_until < ?))
           ORDER BY created_at,run_id""",
        (stage, network, now),
    ))
    return {"stage": stage, "pending": [dict(row) for row in pending]}


def _queue_research_runs(store: Store, status: dict[str, Any], network: str) -> None:
    now = utc_now()
    tracked = [row["address"] for row in store.candidates(network)
               if row["status"] == "tracked"]
    alias_to_address = {f"compte-{index:02d}": address
                        for index, address in enumerate(tracked, 1)}
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        for account in status["accounts"]:
            address = alias_to_address.get(account["account"])
            if not address:
                continue
            for pair in account["data_maturity_by_market"]:
                coin = pair["coin"]
                store.connection.execute(
                    """INSERT OR IGNORE INTO research_targets
                       (network,address,coin,required_cycles,attempt,status,updated_at)
                       VALUES (?,?,?, ?,1,'collecting',?)""",
                    (network,address,coin,DEFAULT_TARGET,now),
                )
                target = store.connection.execute(
                    """SELECT required_cycles,attempt,status FROM research_targets
                       WHERE network=? AND address=? AND coin=?""",
                    (network,address,coin),
                ).fetchone()
                threshold = int(target["required_cycles"])
                if target["status"] in {"rejected", "paused"}:
                    continue
                cycle_ids = pair.get("exploitable_cycle_ids", [])
                if (len(cycle_ids) < threshold or not pair.get("hypothesis_gate_ready")):
                    continue
                sample_ids = cycle_ids[:threshold]
                fingerprint = hashlib.sha256("\n".join(sample_ids).encode()).hexdigest()
                active = store.connection.execute(
                    """SELECT 1 FROM automation_runs WHERE stage='research'
                       AND network=? AND address=? AND coin=?
                       AND status IN ('queued','running') LIMIT 1""",
                    (network,address,coin),
                ).fetchone()
                exists = store.connection.execute(
                    """SELECT 1 FROM automation_runs WHERE stage='research'
                       AND network=? AND address=? AND coin=? AND threshold_cycles=?
                       AND input_fingerprint=? AND attempt=? LIMIT 1""",
                    (network,address,coin,threshold,fingerprint,int(target["attempt"])),
                ).fetchone()
                if active or exists:
                    continue
                run_id = uuid4().hex
                path = ROOT / "data" / "automation" / "requests" / f"research-{run_id}.json"
                request = {
                    "schema_version": 1,
                    "run_id": run_id,
                    "stage": "research",
                    "network": network,
                    "account": address,
                    "coin": coin,
                    "cycle_definition": (
                        "A complete perp position excursion: flat-to-flat, or an observed-baseline opening excursion "
                        "that returns to its pre-open net position. Reductions of inventory that predates the observed "
                        "excursion do not count."
                    ),
                    "required_exploitable_cycles": threshold,
                    "cycle_count_at_dispatch": len(cycle_ids),
                    "cycle_sample_ids": sample_ids,
                    "input_fingerprint": fingerprint,
                    "created_at": now,
                    "context": pair,
                    "guardrails": [
                        "Use only locally archived public observations and explicit sources.",
                        "Do not sign, create, or send any live order; all outputs are research only.",
                        "Keep the analysis immutable and write a separate result artifact.",
                        "If evidence is insufficient, return needs_more_data with a strictly higher required cycle count.",
                    ],
                }
                _atomic_json(path, request)
                store.connection.execute(
                    """INSERT INTO automation_runs
                       (run_id,stage,network,address,coin,threshold_cycles,attempt,
                        input_fingerprint,cycle_count,status,request_path,created_at,updated_at)
                       VALUES (?,'research',?,?,?,?,?,?,?,'queued',?,?,?)""",
                    (run_id,network,address,coin,threshold,int(target["attempt"]),
                     fingerprint,len(cycle_ids),str(path),now,now),
                )
        store.connection.commit()
    except Exception:
        store.connection.rollback()
        raise

def claim_run(store: Store, run_id: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    lease_until = (now + timedelta(minutes=LEASE_MINUTES)).isoformat(timespec="milliseconds")
    cursor = store.connection.execute(
        """UPDATE automation_runs SET status='running',lease_until=?,updated_at=?
           WHERE run_id=? AND (status='queued' OR (status='running' AND lease_until < ?))""",
        (lease_until, now.isoformat(timespec="milliseconds"), run_id,
         now.isoformat(timespec="milliseconds")),
    )
    store.connection.commit()
    if cursor.rowcount != 1:
        raise ValueError("Le run n'est pas en attente ou son bail est encore actif.")
    row = store.connection.execute(
        "SELECT * FROM automation_runs WHERE run_id=?", (run_id,),
    ).fetchone()
    return dict(row)


def write_research_evidence(store: Store, run_id: str, output_path: Path) -> dict[str, Any]:
    run = store.connection.execute(
        "SELECT * FROM automation_runs WHERE run_id=? AND stage='research'", (run_id,),
    ).fetchone()
    if not run:
        raise ValueError("Run de rétro inconnu.")
    request = json.loads(Path(run["request_path"]).read_text(encoding="utf-8"))
    wanted = set(request["cycle_sample_ids"])
    cycle_summaries = request["context"].get("exploitable_cycle_summaries", [])
    selected_cycles = [cycle for cycle in cycle_summaries if cycle.get("cycle_id") in wanted]
    fill_ids = {tid for cycle in selected_cycles for tid in cycle.get("fill_ids", [])}
    fills: dict[str, dict[str, Any]] = {}
    for observation in store.observations(run["network"], "account", run["address"]):
        if observation["endpoint"] not in {"userFillsByTime", "userFills"}:
            continue
        try:
            payload = decode_observation_payload(observation)
        except (ValueError, TypeError, OSError):
            continue
        for fill in _fills_from_observation(observation["endpoint"], payload):
            identifier = str(fill.get("tid", fill.get("hash", "")))
            if identifier in fill_ids:
                fills[identifier] = fill
    missing = sorted(fill_ids - set(fills))
    if not selected_cycles or missing:
        raise ValueError("Les fills complets des cycles retenus ne sont plus tous disponibles.")

    sorted_fills = sorted(fills.values(), key=lambda item: (
        _integer(item.get("time")), str(item.get("tid", "")),
    ))
    first_ms = _integer(sorted_fills[0].get("time")) - 1_000
    last_ms = _integer(sorted_fills[-1].get("time")) + 1_000
    first_iso = datetime.fromtimestamp(first_ms / 1000, timezone.utc).isoformat(timespec="milliseconds")
    last_iso = datetime.fromtimestamp(last_ms / 1000, timezone.utc).isoformat(timespec="milliseconds")
    market_events: dict[str, list[dict[str, Any]]] = {"bbo": [], "trades": [], "l2Book": []}
    observations = store.connection.execute(
        """SELECT * FROM raw_observations WHERE network=? AND entity_type='market'
           AND entity_id=? AND endpoint IN ('bbo','trades','l2Book')
           AND observed_at>=? AND observed_at<=? ORDER BY observed_at""",
        (run["network"],run["coin"],first_iso,last_iso),
    )
    for observation in observations:
        try:
            payload = decode_observation_payload(observation)
        except (ValueError, TypeError, OSError):
            continue
        events = payload.get("events", []) if isinstance(payload, dict) else []
        for event in events:
            message = event.get("message", {}) if isinstance(event, dict) else {}
            data = message.get("data") if isinstance(message, dict) else None
            values = data if isinstance(data, list) else [data]
            for value in values:
                if not isinstance(value, dict):
                    continue
                stamp = _integer(value.get("time", value.get("t")))
                if first_ms <= stamp <= last_ms:
                    market_events[observation["endpoint"]].append({
                        "time": stamp,
                        "received_at": event.get("received_at"),
                        "data": value,
                    })
    market_events["bbo"].sort(key=lambda item: item["time"])
    market_events["trades"].sort(key=lambda item: item["time"])
    market_events["l2Book"].sort(key=lambda item: item["time"])

    aligned_fills = []
    for fill in sorted_fills:
        stamp = _integer(fill.get("time"))
        preceding_bbo = [event for event in market_events["bbo"]
                         if 0 <= stamp - event["time"] <= 1_000]
        preceding_l2 = [event for event in market_events["l2Book"]
                        if 0 <= stamp - event["time"] <= 250]
        adjacent_trades = [event for event in market_events["trades"]
                           if abs(stamp - event["time"]) <= 250]
        aligned_fills.append({
            "fill": fill,
            "market_context": {
                "preceding_bbo": preceding_bbo[-1] if preceding_bbo else None,
                "preceding_l2": preceding_l2[-1] if preceding_l2 else None,
                "trades_within_250ms": adjacent_trades[:100],
                "trade_count_within_250ms": len(adjacent_trades),
            },
        })
    evidence = {
        "schema_version": 1,
        "run_id": run_id,
        "network": run["network"],
        "account": run["address"],
        "coin": run["coin"],
        "cycle_definition": request["cycle_definition"],
        "threshold_cycles": run["threshold_cycles"],
        "input_fingerprint": run["input_fingerprint"],
        "cycles": selected_cycles,
        "fills_with_market_context": aligned_fills,
        "market_event_counts_in_cycle_windows": {
            key: len(value) for key, value in market_events.items()
        },
        "limitations": [
            "The evidence joins only archived public feeds; missing events remain missing.",
            "BBO and L2 context are snapshots near each leader fill, not a full exchange queue reconstruction.",
            "A strategy hypothesis needs out-of-sample validation and explicit fees, slippage, and latency assumptions.",
        ],
    }
    _atomic_json(output_path, evidence)
    return {"run_id": run_id, "path": str(output_path.resolve()),
            "cycles": len(selected_cycles), "fills": len(aligned_fills)}


def complete_research(store: Store, run_id: str, result_path: Path) -> dict[str, Any]:
    draft = _read_result(result_path)
    row = store.connection.execute(
        "SELECT * FROM automation_runs WHERE run_id=? AND stage='research'", (run_id,),
    ).fetchone()
    if not row or row["status"] != "running":
        raise ValueError("Run de rétro inconnu, non réclamé ou déjà terminé.")
    request = json.loads(Path(row["request_path"]).read_text(encoding="utf-8"))
    draft_path = result_path.resolve()
    required_result_dir = (ROOT / "data" / "automation" / "results" / "research").resolve()
    if draft_path.parent != required_result_dir or draft_path.name != f"{run_id}-draft.json":
        raise ValueError("Le draft de rétro doit être rangé dans le répertoire immuable prévu pour ce run.")
    if (draft.get("schema_version") != 1 or draft.get("run_id") != run_id
            or draft.get("input_fingerprint") != row["input_fingerprint"]):
        raise ValueError("Draft de rétro non rattaché à la requête et aux données du run.")
    hermes_decision = str(draft.get("decision", ""))
    if hermes_decision not in {"accepted", "needs_more_data", "redo_re", "rejected"}:
        raise ValueError("Le draft Hermes doit contenir une décision reconnue.")
    evidence_path = ROOT / "data" / "automation" / "evidence" / "research" / f"{run_id}.json"
    if not evidence_path.exists():
        write_research_evidence(store, run_id, evidence_path)
    else:
        evidence = _read_result(evidence_path)
        if (evidence.get("run_id") != run_id
                or evidence.get("input_fingerprint") != row["input_fingerprint"]):
            evidence_path.unlink()
            write_research_evidence(store, run_id, evidence_path)
    draft_path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    expected_review_path = required_result_dir / f"{run_id}-codex-review.json"
    review = None
    if expected_review_path.exists():
        try:
            existing_review = _read_result(expected_review_path)
        except ValueError:
            expected_review_path.unlink()
        else:
            if (existing_review.get("run_id") == run_id
                    and existing_review.get("input_fingerprint") == row["input_fingerprint"]
                    and existing_review.get("schema_version") == 1):
                review = existing_review
            else:
                expected_review_path.unlink()
    if review is None:
        review = _run_codex_review(
            run_id, row["input_fingerprint"], draft_path, evidence_path,
            expected_review_path,
        )
    if (review.get("schema_version") != 1 or review.get("run_id") != run_id
            or review.get("input_fingerprint") != row["input_fingerprint"]):
        raise ValueError("L'artifact de revue Codex ne correspond pas au run courant.")
    review_decision = str(review.get("decision", ""))
    if review_decision not in {"approve", "needs_more_data", "redo_re", "reject"}:
        raise ValueError("Décision de revue Codex invalide.")
    if hermes_decision == "accepted" and review_decision == "approve":
        decision = "accepted"
    elif hermes_decision == "rejected" and review_decision == "reject":
        decision = "rejected"
    elif hermes_decision == "needs_more_data" or review_decision == "needs_more_data":
        decision = "needs_more_data"
    elif hermes_decision == "redo_re" or review_decision == "redo_re":
        decision = "redo_re"
    else:
        decision = "redo_re"
    result = dict(draft)
    result["hermes_decision"] = hermes_decision
    result["decision"] = decision
    result["codex_review_path"] = str(expected_review_path.relative_to(ROOT))
    result["codex_review_decision"] = review_decision
    if decision == "needs_more_data":
        result["reason"] = str(draft.get("reason") or review.get("reason") or "Cycle échantillon insuffisant.")
        threshold_now = int(row["threshold_cycles"])
        suggested = [int(value) for value in (
            draft.get("next_required_cycles"), review.get("next_required_cycles")
        ) if isinstance(value, int) and value > threshold_now]
        result["next_required_cycles"] = max(
            suggested or [max(NEXT_TARGET_AFTER_ACCEPT, threshold_now * 2)]
        )
    elif decision == "redo_re":
        result["reason"] = str(draft.get("reason") or review.get("reason") or "Revue indépendante non concordante.")
    elif decision == "rejected":
        result["reason"] = str(draft.get("reason") or review.get("reason") or "Les deux revues rejettent l'hypothèse.")
    result_path = required_result_dir / f"{run_id}.json"
    threshold = int(row["threshold_cycles"])
    now = utc_now()
    paper_request_path: Path | None = None
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        store.connection.execute(
            """UPDATE automation_runs SET status=?,decision=?,artifact_path=?,
               strategy_fingerprint=?,updated_at=?,lease_until=NULL WHERE run_id=?""",
            (decision,str(result.get("decision")),str(result_path.resolve()),
             result.get("strategy_fingerprint"),now,run_id),
        )
        if decision == "needs_more_data":
            if not str(result.get("reason", "")).strip():
                raise ValueError("needs_more_data exige une raison exploitable.")
            next_target = int(result.get("next_required_cycles", 0))
            if next_target <= threshold:
                raise ValueError("needs_more_data exige un seuil supérieur au seuil actuel.")
            review_target = int(review.get("next_required_cycles", threshold))
            if review_decision == "needs_more_data" and next_target < review_target:
                raise ValueError("Le nouveau seuil ne peut pas être inférieur au seuil recommandé par Codex.")
            store.connection.execute(
                """UPDATE research_targets SET required_cycles=?,attempt=1,
                   status='collecting',updated_at=? WHERE network=? AND address=? AND coin=?""",
                (next_target,now,row["network"],row["address"],row["coin"]),
            )
            store.connection.execute(
                "UPDATE automation_runs SET next_threshold_cycles=? WHERE run_id=?",
                (next_target,run_id),
            )
        elif decision == "redo_re" or decision == "insufficient_concordance":
            if not str(result.get("reason", "")).strip():
                raise ValueError("redo_re exige une raison exploitable.")
            store.connection.execute(
                """UPDATE research_targets SET attempt=attempt+1,status='collecting',updated_at=?
                   WHERE network=? AND address=? AND coin=?""",
                (now,row["network"],row["address"],row["coin"]),
            )
        elif decision == "accepted":
            if (not str(result.get("hypothesis", "")).strip()
                    or not isinstance(result.get("evidence"), list)
                    or not isinstance(result.get("limitations"), list)):
                raise ValueError("Une rétro acceptée doit contenir hypothèse, preuves et limites.")
            strategy_fingerprint = result.get("strategy_fingerprint")
            strategy_spec = result.get("strategy_spec")
            if not isinstance(strategy_spec, dict) or not strategy_spec:
                raise ValueError("Une rétro acceptée doit fournir strategy_spec structuré.")
            required_spec = {"schema_version", "signal", "entry", "exit", "sizing",
                             "max_exposure", "fees", "slippage", "latency_ms",
                             "invalidation_conditions"}
            if (not required_spec <= set(strategy_spec)
                    or strategy_spec.get("schema_version") != 1
                    or not isinstance(strategy_spec.get("signal"), dict)
                    or not isinstance(strategy_spec.get("entry"), dict)
                    or not isinstance(strategy_spec.get("exit"), dict)
                    or not isinstance(strategy_spec.get("sizing"), dict)
                    or not isinstance(strategy_spec.get("max_exposure"), dict)
                    or not isinstance(strategy_spec.get("fees"), dict)
                    or not isinstance(strategy_spec.get("slippage"), dict)
                    or not isinstance(strategy_spec.get("invalidation_conditions"), list)
                    or not isinstance(strategy_spec.get("latency_ms"), int)
                    or strategy_spec["latency_ms"] < 0):
                raise ValueError("strategy_spec ne respecte pas le contrat N1 version 1.")
            calculated_fingerprint = hashlib.sha256(
                json.dumps(strategy_spec, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":")).encode()
            ).hexdigest()
            if strategy_fingerprint != calculated_fingerprint:
                raise ValueError("strategy_fingerprint ne correspond pas à strategy_spec.")
            # Every accepted RE gets its own Paper N1 revision, including when
            # the executable strategy is unchanged. This RE is the current
            # source of truth; retaining a revision
            # makes that progression auditable instead of silently pinning N1
            # to an older research artifact.
            revision = store.connection.execute(
                """SELECT COALESCE(MAX(revision),0)+1 FROM paper_n1_revisions
                   WHERE network=? AND address=? AND coin=?""",
                (row["network"],row["address"],row["coin"]),
            ).fetchone()[0]
            artifact_dir = ROOT / "data" / "paper" / "n1" / row["address"] / row["coin"] / f"rev-{revision:03d}"
            paper_id = uuid4().hex
            paper_request_path = ROOT / "data" / "automation" / "requests" / f"paper-{paper_id}.json"
            request = {
                "schema_version": 1,
                "run_id": paper_id,
                "stage": "paper_n1",
                "network": row["network"],
                "account": row["address"],
                "coin": row["coin"],
                "research_run_id": run_id,
                "research_artifact": str(result_path.resolve()),
                "strategy_fingerprint": strategy_fingerprint,
                "revision": revision,
                "artifact_directory": str(artifact_dir),
                "guardrails": [
                    "Produce a local virtual-trading N1 only; do not use a wallet, signer, exchange order API, or VPS.",
                    "Preserve every earlier research and paper revision; promote this one only after validation.",
                    "Write a structured paper specification and an initialized virtual ledger.",
                ],
            }
            _atomic_json(paper_request_path, request)
            store.connection.execute(
                """INSERT INTO automation_runs
                   (run_id,stage,network,address,coin,threshold_cycles,attempt,
                    input_fingerprint,cycle_count,status,request_path,created_at,updated_at)
                   VALUES (?,'paper',?,?,?,?,1,?,?,'queued',?,?,?)""",
                (paper_id,row["network"],row["address"],row["coin"],threshold,
                 strategy_fingerprint,int(row["cycle_count"]),str(paper_request_path),now,now),
            )
            store.connection.execute(
                """INSERT INTO paper_n1_revisions
                   (network,address,coin,revision,research_run_id,strategy_fingerprint,
                    artifact_path,status,is_active,created_at)
                   VALUES (?,?,?,?,?,?,?,'queued',0,?)""",
                (row["network"],row["address"],row["coin"],revision,run_id,
                 strategy_fingerprint,str(artifact_dir),now),
            )
            store.connection.execute(
                """UPDATE research_targets SET required_cycles=?,attempt=1,
                   status='collecting',updated_at=? WHERE network=? AND address=? AND coin=?""",
                (max(NEXT_TARGET_AFTER_ACCEPT,threshold * 2),now,
                 row["network"],row["address"],row["coin"]),
            )
        elif decision == "rejected":
            if not str(result.get("reason", "")).strip():
                raise ValueError("rejected exige une raison exploitable.")
            store.connection.execute(
                """UPDATE research_targets SET status='rejected',updated_at=?
                   WHERE network=? AND address=? AND coin=?""",
                (now,row["network"],row["address"],row["coin"]),
            )
        else:
            raise ValueError("decision doit être accepted, needs_more_data, redo_re ou rejected")
        _atomic_json(result_path, result)
        for path in (draft_path, expected_review_path, result_path):
            path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        store.connection.commit()
    except Exception:
        store.connection.rollback()
        result_path.unlink(missing_ok=True)
        if paper_request_path:
            paper_request_path.unlink(missing_ok=True)
        raise
    return {"run_id": run_id, "decision": decision,
            "next_required_cycles": _target(store, row["network"], row["address"], row["coin"])}


def complete_paper(store: Store, run_id: str, result_path: Path) -> dict[str, Any]:
    result = _read_result(result_path)
    run = store.connection.execute(
        "SELECT * FROM automation_runs WHERE run_id=? AND stage='paper'", (run_id,),
    ).fetchone()
    if not run or run["status"] != "running":
        raise ValueError("Run Paper N1 inconnu, non réclamé ou déjà terminé.")
    # The paper request stores the source research run id in its JSON. Resolve it
    # from the request file rather than trusting a caller-supplied identifier.
    request = json.loads(Path(run["request_path"]).read_text(encoding="utf-8"))
    revision = store.connection.execute(
        "SELECT * FROM paper_n1_revisions WHERE research_run_id=?",
        (request["research_run_id"],),
    ).fetchone()
    expected_fp = request["strategy_fingerprint"]
    strategy_spec = result.get("strategy_spec")
    strategy_hash = hashlib.sha256(
        json.dumps(strategy_spec, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":")).encode()
    ).hexdigest() if isinstance(strategy_spec, dict) else ""
    if (not revision or result.get("schema_version") != 1
            or result.get("run_id") != run_id
            or result.get("research_run_id") != request["research_run_id"]
            or result.get("mode") != "paper_n1"
            or result.get("strategy_fingerprint") != expected_fp
            or strategy_hash != expected_fp
            or result.get("live_orders_enabled") is not False
            or result.get("wallet_or_signer_configured") is not False
            or not isinstance(result.get("paper_spec"), dict)
            or result["paper_spec"].get("market") != run["coin"]
            or result["paper_spec"].get("research_run_id") != request["research_run_id"]
            or result["paper_spec"].get("revision") != revision["revision"]
            or not isinstance(result["paper_spec"].get("fee_assumptions"), dict)
            or not result["paper_spec"].get("fee_assumptions")
            or not isinstance(result["paper_spec"].get("slippage_assumptions"), dict)
            or not result["paper_spec"].get("slippage_assumptions")
            or not isinstance(result.get("virtual_ledger"), dict)
            or "cash" not in result["virtual_ledger"]
            or not isinstance(result["virtual_ledger"].get("positions"), dict)
            or result["virtual_ledger"].get("positions") != {}
            or not isinstance(result["virtual_ledger"].get("orders"), list)
            or result["virtual_ledger"].get("orders") != []
            or not isinstance(result["virtual_ledger"].get("fills"), list)):
        raise ValueError("Artifact N1 invalide : mode virtuel ou empreinte incompatible.")
    if result["virtual_ledger"].get("fills") != []:
        raise ValueError("Le ledger initial N1 doit démarrer sans exécution.")
    try:
        starting_capital = Decimal(str(result["paper_spec"].get("starting_capital_usdc")))
        ledger_cash = Decimal(str(result["virtual_ledger"]["cash"]))
    except (InvalidOperation, ValueError):
        raise ValueError("Le capital initial et le cash du ledger doivent être numériques.")
    if (not starting_capital.is_finite() or starting_capital <= 0
            or not ledger_cash.is_finite() or ledger_cash != starting_capital):
        raise ValueError("Le cash initial doit correspondre au capital virtuel positif en USDC.")
    artifact_path = result_path.resolve()
    if not artifact_path.is_file():
        raise ValueError("Artifact Paper N1 absent.")
    artifact_dir = Path(revision["artifact_path"]).resolve()
    if artifact_dir not in artifact_path.parents:
        raise ValueError("L'artifact Paper N1 doit rester dans son répertoire de révision.")
    artifact_path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    now = utc_now()
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        store.connection.execute(
            """UPDATE automation_runs SET status='accepted',decision='created',artifact_path=?,
               updated_at=?,lease_until=NULL WHERE run_id=?""",
            (str(artifact_path),now,run_id),
        )
        latest_research = store.connection.execute(
            """SELECT run_id FROM automation_runs WHERE stage='research'
               AND network=? AND address=? AND coin=? AND decision='accepted'
               ORDER BY created_at DESC LIMIT 1""",
            (run["network"],run["address"],run["coin"]),
        ).fetchone()
        is_latest = bool(latest_research and latest_research["run_id"] == request["research_run_id"])
        if is_latest:
            store.connection.execute(
                """UPDATE paper_n1_revisions SET is_active=0,status='superseded'
                   WHERE network=? AND address=? AND coin=? AND is_active=1""",
                (run["network"],run["address"],run["coin"]),
            )
        store.connection.execute(
            """UPDATE paper_n1_revisions SET is_active=?,status=?,artifact_path=?
               WHERE revision_id=?""",
            (int(is_latest),"active" if is_latest else "superseded",
             str(artifact_path),revision["revision_id"]),
        )
        store.connection.commit()
    except Exception:
        store.connection.rollback()
        raise
    return {"run_id": run_id, "paper_revision": revision["revision"],
            "active": is_latest, "artifact": str(artifact_path)}


def _read_result(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("Fichier de résultat absent.")
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Fichier de résultat JSON invalide : {exc}") from exc
    if not isinstance(result, dict):
        raise ValueError("Le résultat doit être un objet JSON.")
    return result


def _run_codex_review(run_id: str, fingerprint: str, draft_path: Path,
                     evidence_path: Path, output_path: Path) -> dict[str, Any]:
    schema_path = ROOT / "docs" / "schemas" / "codex-research-review.schema.json"
    prompt = (
        "Review the Hermes reverse-engineering draft and its selected public evidence. "
        "Check that its claims follow from the included cycles, fills, BBO, trades and L2; "
        "interpret cycle_kind=baseline_excursion as a completed return to the observed pre-open net position, "
        "not as a flat-to-zero trade; "
        "look for timestamp/position reconstruction errors, survivorship, omitted fees, "
        "latency or unsupported profitability claims. Read only: do not edit files, "
        "run tests, or execute any order. Return only schema-valid JSON. Use decision "
        "approve only if the hypothesis and machine-readable strategy are reproducible; "
        "needs_more_data when the evidence sample is too small and choose a strictly "
        "higher cycle threshold; redo_re when the method or conclusion needs another "
        "analysis pass; reject only if the evidence directly contradicts the hypothesis.\n"
        f"run_id={run_id}\ninput_fingerprint={fingerprint}\n"
        f"draft={draft_path}\nevidence={evidence_path}"
    )
    command = [
        "/home/Untergame/.local/bin/codex", "exec", "--sandbox", "read-only",
        "--cd", str(ROOT), "--output-schema", str(schema_path),
        "--output-last-message", str(output_path), prompt,
    ]
    try:
        completed = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True,
            timeout=900, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        output_path.unlink(missing_ok=True)
        raise ValueError(f"Revue Codex impossible pour ce run : {exc}") from exc
    if completed.returncode != 0:
        output_path.unlink(missing_ok=True)
        raise ValueError(f"Revue Codex échouée (code {completed.returncode}); le run sera retenté après expiration de son bail.")
    try:
        review = _read_result(output_path)
    except ValueError:
        output_path.unlink(missing_ok=True)
        raise
    if (review.get("schema_version") != 1 or review.get("run_id") != run_id
            or review.get("input_fingerprint") != fingerprint):
        output_path.unlink(missing_ok=True)
        raise ValueError("La sortie Codex n'est pas rattachée au run courant.")
    output_path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    return review


def _integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Artifact immuable déjà présent : {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(data)
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _target(store: Store, network: str, address: str, coin: str) -> int:
    row = store.connection.execute(
        "SELECT required_cycles FROM research_targets WHERE network=? AND address=? AND coin=?",
        (network,address,coin),
    ).fetchone()
    return int(row[0]) if row else DEFAULT_TARGET
