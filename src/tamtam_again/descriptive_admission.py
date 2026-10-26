"""Deterministic admission proposals for bounded descriptive account studies.

This reader consumes one exact, already persisted historical-screen snapshot.
It never opens raw account observations, mutates the database, authorizes a
resource, or changes the economic-validation gate.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

SCREEN_POLICY = "historical-curves-v2.0"
EXCLUDED_STATUS = "excluded_before_payload_read"
BASE_MIN_FILLS = 10
BASE_MIN_DAYS = 2
LEGACY_MIN_FILLS = 20
LEGACY_MIN_DAYS = 4
DAY_MS = 86_400_000


def _alias(address: str, addresses: list[str]) -> str:
    """Return the shortest deterministic address suffix unique in this inventory."""
    lowered = [str(item).lower() for item in addresses]
    target = str(address).lower()
    for width in range(4, max((len(item) for item in lowered), default=40) + 1, 2):
        suffix = target[-width:]
        if sum(item.endswith(suffix) for item in lowered) == 1:
            return suffix
    return target


def _valid_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _market_list(decision: dict[str, Any]) -> list[str]:
    fill = decision.get("fill_activity")
    # Scope must match the 30-day activity window; an all-time market list
    # cannot establish the instrument scope of this particular study.
    markets = fill.get("markets_30d_observed") if isinstance(fill, dict) else []
    if not isinstance(markets, list):
        return []
    return sorted({item.strip() for item in markets if isinstance(item, str) and item.strip()})


def _coverage_summary(decision: dict[str, Any]) -> dict[str, Any]:
    quality = decision.get("data_quality") if isinstance(decision.get("data_quality"), dict) else {}
    fill = decision.get("fill_activity") if isinstance(decision.get("fill_activity"), dict) else {}
    request_fields = (
        "query_coverage_30d_days", "query_coverage_30d_segments_days",
        "query_coverage_30d_at_least_25d", "latest_query_coverage_age_30d_days",
        "query_coverage_30d_segments_days", "pagination_statuses",
        "truncated_or_retention_unknown", "query_start_ms", "query_end_ms",
    )
    return {
        "historical_curve_samples": quality.get("allTime_pnl_samples"),
        "historical_curve_first_ms": quality.get("allTime_first_ms"),
        "historical_curve_last_ms": quality.get("allTime_last_ms"),
        "historical_curve_max_gap_days": quality.get("allTime_max_gap_days"),
        "curve_economic_reconciliation": quality.get("economic_reconciliation", "unknown"),
        "fills_30d_request_coverage": {key: fill[key] for key in request_fields if key in fill},
        "fills_are_lower_bound": True,
    }


def _performance_summary(decision: dict[str, Any]) -> dict[str, Any]:
    horizons = decision.get("horizons") if isinstance(decision.get("horizons"), dict) else {}
    result: dict[str, Any] = {
        "status": decision.get("performance_quality", "unknown"),
        "source": "provider-reported portfolio curve; not reconciled return",
        "economic_validation": False,
        "horizons": {},
    }
    for horizon in ("30", "90", "180", "365"):
        item = horizons.get(horizon)
        if not isinstance(item, dict):
            result["horizons"][horizon] = None
            continue
        result["horizons"][horizon] = {
            key: item.get(key) for key in (
                "status", "delta", "actual_days", "start_ms", "end_ms",
                "end_age_days", "max_sampled_pnl_peak_to_trough",
            ) if key in item
        }
    return result


def _risk_summary(decision: dict[str, Any]) -> dict[str, Any]:
    horizon = (decision.get("horizons") or {}).get("180", {})
    if not isinstance(horizon, dict):
        horizon = {}
    snapshots = decision.get("current_exposure_observations")
    snapshots = snapshots if isinstance(snapshots, list) else []
    with_positions = 0
    for snapshot in snapshots:
        if isinstance(snapshot, dict) and snapshot.get("positions"):
            with_positions += 1
    unknowns = decision.get("risk_unknowns")
    if not isinstance(unknowns, list):
        unknowns = []
    return {
        "account_mode_observed": decision.get("account_mode", "unknown"),
        "sampled_pnl_peak_to_trough_180d_nominal": horizon.get("max_sampled_pnl_peak_to_trough"),
        "exposure_snapshots_with_positions": with_positions,
        "exposure_snapshot_count": len(snapshots),
        "unresolved_risk": [item for item in unknowns if isinstance(item, str)],
        "interpretation": "sampled or current observations only; not consolidated historical risk",
    }


def _priority(disposition: str, active_days: int, fills: int, market_count: int) -> tuple[str, int]:
    # Priority measures temporal evidence density and scope readiness only.
    if disposition == "admissible_descriptive":
        return ("P1" if active_days >= LEGACY_MIN_DAYS else "P2", active_days * 100 + min(fills, 99))
    if disposition == "needs_more_evidence" and market_count > 1:
        return ("P2" if active_days >= BASE_MIN_DAYS and fills >= BASE_MIN_FILLS else "P3",
                active_days * 100 + min(fills, 99))
    return "P3", active_days * 100 + min(fills, 99)


def _evaluate_record(meta: dict[str, Any], decision: dict[str, Any] | None,
                     aliases: list[str], cutoff_ms: int) -> dict[str, Any]:
    source_status = meta["status"]
    if source_status == EXCLUDED_STATUS:
        return {
            "candidate_id": None,
            "candidate_alias": "excluded-before-read",
            "source_status": source_status,
            "disposition": "excluded",
            "priority": "P3",
            "priority_rationale": "P3 : excluded before payload read; no evaluable evidence.",
            "priority_score": 0,
            "reason": "Le screening a exclu ce compte avant la lecture des preuves protégées.",
            "missing_evidence": [],
            "research_question": None,
            "scope": {"network": meta["network"], "period_start_ms": cutoff_ms - 30 * DAY_MS,
                      "cutoff_ms": cutoff_ms, "markets": []},
            "declared_performance": None,
            "known_risk": None,
            "coverage": None,
            "activity": None,
            "execution_compatibility": {"status": "not_assessed", "reason": "Aucune spécification exécutable n'est proposée."},
            "economic_validation": False,
            "resource_authorized": False,
        }

    address = str(meta["address"])
    alias = _alias(address, aliases)

    if decision is None:
        return {
            "candidate_id": address, "candidate_alias": alias, "source_status": source_status,
            "disposition": "deferred", "priority": "P3", "priority_score": 0,
            "priority_rationale": "P3 : la preuve structurée est indisponible.",
            "reason": "La décision historique n'est pas lisible comme preuve structurée.",
            "missing_evidence": ["Réparer ou republier la décision historique versionnée."],
            "research_question": None,
            "scope": {"network": meta["network"], "period_start_ms": cutoff_ms - 30 * DAY_MS,
                      "cutoff_ms": cutoff_ms, "markets": []},
            "declared_performance": None, "known_risk": None, "coverage": None, "activity": None,
            "execution_compatibility": {"status": "not_assessed", "reason": "No strategy or engine profile."},
            "economic_validation": False, "resource_authorized": False,
            "source_ref": f"population_historical_decisions:{meta['decision_id']}",
        }

    markets = _market_list(decision)
    fill = decision.get("fill_activity") if isinstance(decision.get("fill_activity"), dict) else {}
    fills = _valid_count(fill.get("fills_30d_observed"))
    active_days = _valid_count(fill.get("active_days_30d_observed"))
    market_count = len(markets)
    activity_ready = fills >= BASE_MIN_FILLS and active_days >= BASE_MIN_DAYS
    missing: list[str] = []
    question: str
    if market_count == 1 and activity_ready:
        disposition = "admissible_descriptive"
        market = markets[0]
        reason = (f"Un instrument observé ({market}), {fills} fills observés et {active_days} jours UTC actifs "
                  "dans la fenêtre de 30 jours satisfont le seuil descriptif proposé.")
        question = (f"Pour {market}, quelle est la distribution par jour UTC des {fills} fills observés pendant "
                    f"les 30 jours avant le cutoff {cutoff_ms}, et quelle couverture des requêtes est réellement "
                    "documentée ? Garder les limites de pages visibles et ne pas attribuer la courbe du compte à ce marché.")
    elif market_count > 1:
        disposition = "needs_more_evidence"
        shown = ", ".join(markets[:5])
        suffix = f" et {market_count - 5} autre(s)" if market_count > 5 else ""
        reason = (f"{market_count} marchés sont observés, mais le snapshot ne fournit pas les comptes et jours actifs "
                  "par marché nécessaires pour justifier une étude bornée par instrument.")
        missing = ["Fills observés et jours UTC actifs ventilés par marché sur la fenêtre de 30 jours.",
                   "Couverture/pagination des requêtes rattachée à chaque marché avant toute sélection d'un marché."]
        question = (f"Pour le compte {alias}, parmi les marchés observés ({shown}{suffix}), lesquels disposent d'une "
                    "couverture par marché suffisante pour une description séparée sur 30 jours ? Ne pas agréger les marchés.")
    elif market_count == 1:
        disposition = "needs_more_evidence" if fills > 0 else "deferred"
        market = markets[0]
        reason = (f"Le marché {market} est identifiable, mais les observations disponibles sont sous le seuil descriptif "
                  f"({fills} fills / {active_days} jours UTC actifs ; seuil {BASE_MIN_FILLS}/{BASE_MIN_DAYS}).")
        missing = [f"Au moins {BASE_MIN_FILLS} fills observés sur au moins {BASE_MIN_DAYS} jours UTC distincts, "
                   "ou une couverture autorisée démontrant que le volume inférieur est réellement complet."]
        question = (f"Pour {market}, la fenêtre de 30 jours reflète-t-elle une activité faible ou une couverture de collecte "
                    "partielle ? Comparer le nombre observé par jour aux états de pagination avant de résumer le comportement.")
    else:
        disposition = "needs_more_evidence" if fills > 0 else "deferred"
        reason = "Aucun instrument de fill n'est relié au snapshot utilisable pour borner la question par marché."
        missing = ["Identifiants d'instrument présents dans les pages de fills autorisées.",
                   "Nombre de fills et jours UTC actifs par instrument, avec état de couverture des requêtes."]
        question = (f"Pour le compte {alias}, quels instruments figurent dans les fills autorisés des 30 jours avant le cutoff "
                    f"{cutoff_ms}, et quel est leur nombre de jours actifs ? Aucune question d'exécution ne peut encore être posée.")

    priority, score = _priority(disposition, active_days, fills, market_count)
    if disposition == "admissible_descriptive":
        priority_rationale = (f"{priority} : {active_days} jours actifs; le rang tient compte de la répétition observée, "
                              "pas du PnL.")
    elif market_count > 1 and activity_ready:
        priority_rationale = (f"P2 : {active_days} jours actifs et {fills} fills justifient de résoudre la ventilation "
                              "par marché avant une admission.")
    else:
        priority_rationale = (f"P3 : {active_days} jours actifs / {fills} fills ou instrument insuffisamment établi; "
                              "preuve supplémentaire d'abord.")
    source_econ = decision.get("economic_research_readiness")
    source_econ_status = source_econ.get("status") if isinstance(source_econ, dict) else "unknown"
    return {
        "candidate_id": address,
        "candidate_alias": alias,
        "source_status": source_status,
        "source_input_fingerprint": meta.get("input_fingerprint"),
        "disposition": disposition,
        "priority": priority,
        "priority_rationale": priority_rationale,
        "priority_score": score,
        "reason": reason,
        "missing_evidence": missing,
        "research_question": question,
        "scope": {"network": meta["network"], "period_start_ms": cutoff_ms - 30 * DAY_MS,
                  "cutoff_ms": cutoff_ms, "markets": markets if market_count <= 5 else markets[:5],
                  "market_count": market_count, "additional_markets_omitted": max(0, market_count - 5)},
        "declared_performance": _performance_summary(decision),
        "known_risk": _risk_summary(decision),
        "coverage": _coverage_summary(decision),
        "activity": {
            "fills_30d_observed_lower_bound": fills,
            "active_days_30d_observed_lower_bound": active_days,
            "quality": decision.get("activity_quality", "unknown"),
            "observed_markets": market_count,
        },
        "execution_compatibility": {
            "status": "not_assessed",
            "reason": "A descriptive question does not specify a strategy or execution profile; compatibility must be reviewed separately.",
        },
        "economic_validation": False,
        "economic_gate_status": source_econ_status,
        "resource_authorized": False,
        "source_ref": f"population_historical_decisions:{meta['decision_id']}",
    }


def _readonly_connection(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Database path does not exist: {path}")
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    return conn


def evaluate_inventory(*, db_path: str | Path, cutoff_ms: int, network: str = "hyperliquid-mainnet",
                       max_candidates: int = 5000, queue_size: int = 8) -> dict[str, Any]:
    """Evaluate one exact historical screen in read-only mode, with a row cap."""
    if type(cutoff_ms) is not int or cutoff_ms <= 0:
        raise ValueError("An explicit positive cutoff in milliseconds is required")
    if not network or max_candidates <= 0 or queue_size < 0:
        raise ValueError("Network, positive candidate cap and nonnegative queue size are required")
    instant = datetime.fromtimestamp(cutoff_ms / 1000, timezone.utc)
    decision_day = instant.date().isoformat()
    conn = _readonly_connection(db_path)
    try:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='population_historical_decisions'").fetchone()
        if not exists:
            raise ValueError("The database has no historical screen inventory")
        meta_rows = conn.execute(
            "SELECT decision_id,network,CASE WHEN status=? THEN NULL ELSE address END AS address, "
            "decision_day_utc,as_of_ms,policy_version,input_fingerprint,status "
            "FROM population_historical_decisions "
            "WHERE network=? AND decision_day_utc=? AND as_of_ms=? AND policy_version=? ORDER BY address LIMIT ?",
            (EXCLUDED_STATUS, network, decision_day, cutoff_ms, SCREEN_POLICY, max_candidates + 1),
        ).fetchall()
        if len(meta_rows) > max_candidates:
            raise ValueError(f"Inventory exceeds explicit cap of {max_candidates} candidates")
        if not meta_rows:
            raise LookupError(f"No {SCREEN_POLICY} inventory found for {network} at cutoff {cutoff_ms}")
        meta = [dict(row) for row in meta_rows]
        visible_addresses = [str(row["address"]).lower() for row in meta if row["address"] is not None]
        if len(set(visible_addresses)) != len(visible_addresses):
            raise ValueError("The exact historical-screen cutoff contains duplicate account decisions")
        if any(row["as_of_ms"] != cutoff_ms or row["decision_day_utc"] != decision_day for row in meta):
            raise ValueError("The selected inventory does not share the explicit cutoff")
        decisions: dict[str, dict[str, Any] | None] = {}
        if any(row["status"] != EXCLUDED_STATUS for row in meta):
            # Fetch structured snapshots only after filtering protected pre-read exclusions.
            rows = conn.execute(
                "SELECT decision_id,decision_json FROM population_historical_decisions "
                "WHERE network=? AND decision_day_utc=? AND as_of_ms=? AND policy_version=? "
                "AND status<>? ORDER BY address",
                (network, decision_day, cutoff_ms, SCREEN_POLICY, EXCLUDED_STATUS),
            ).fetchall()
            for row in rows:
                try:
                    parsed = json.loads(row["decision_json"])
                    decisions[row["decision_id"]] = parsed if isinstance(parsed, dict) else None
                except (TypeError, json.JSONDecodeError):
                    decisions[row["decision_id"]] = None
    finally:
        conn.close()

    addresses = [str(row["address"]) for row in meta if row["address"] is not None]
    evaluations = [_evaluate_record(row, decisions.get(row["decision_id"]), addresses, cutoff_ms) for row in meta]
    evaluations.sort(key=lambda item: (item["candidate_id"] is None, item["candidate_id"] or ""))
    by_status: dict[str, int] = {}
    by_disposition: dict[str, int] = {}
    for row in evaluations:
        by_status[row["source_status"]] = by_status.get(row["source_status"], 0) + 1
        by_disposition[row["disposition"]] = by_disposition.get(row["disposition"], 0) + 1

    def count_at(min_fills: int, min_days: int) -> int:
        total = 0
        for row in evaluations:
            activity = row.get("activity") or {}
            market_count = (row.get("scope") or {}).get("market_count", 0)
            if market_count == 1 and activity.get("fills_30d_observed_lower_bound", 0) >= min_fills \
                    and activity.get("active_days_30d_observed_lower_bound", 0) >= min_days:
                total += 1
        return total

    ranked_admissible = sorted(
        (row for row in evaluations if row["disposition"] == "admissible_descriptive"),
        key=lambda row: (row["priority"], -row["activity"]["active_days_30d_observed_lower_bound"],
                         -row["activity"]["fills_30d_observed_lower_bound"], row["candidate_id"]),
    )

    def market_namespace(row: dict[str, Any]) -> str:
        markets = (row.get("scope") or {}).get("markets") or []
        market = markets[0] if markets else ""
        return market.split(":", 1)[0] if ":" in market else "unprefixed"

    # Preserve the evidence-ranked leading tier, then include the best
    # candidate from each additional venue namespace before filling remaining
    # slots. This keeps HIP-3/DEX-tagged instruments visible in a short queue.
    queue: list[dict[str, Any]] = []
    seen_namespaces: set[str] = set()
    for row in ranked_admissible:
        if row["priority"] == "P1" and len(queue) < queue_size:
            queue.append(row)
            seen_namespaces.add(market_namespace(row))
    for namespace in sorted({market_namespace(row) for row in ranked_admissible} - seen_namespaces):
        candidate = next(row for row in ranked_admissible if market_namespace(row) == namespace)
        if len(queue) < queue_size:
            queue.append(candidate)
            seen_namespaces.add(namespace)
    for row in ranked_admissible:
        if len(queue) >= queue_size:
            break
        if row not in queue:
            queue.append(row)

    scope_followup = sorted(
        (row for row in evaluations if row["disposition"] == "needs_more_evidence"
         and (row.get("scope") or {}).get("market_count", 0) > 1
         and row["activity"]["fills_30d_observed_lower_bound"] >= BASE_MIN_FILLS
         and row["activity"]["active_days_30d_observed_lower_bound"] >= BASE_MIN_DAYS),
        key=lambda row: (-row["activity"]["active_days_30d_observed_lower_bound"],
                         -row["activity"]["fills_30d_observed_lower_bound"], row["candidate_id"]),
    )[:4]
    multiactive = sum(1 for row in evaluations
                      if (row.get("scope") or {}).get("market_count", 0) > 1
                      and (row.get("activity") or {}).get("fills_30d_observed_lower_bound", 0) >= BASE_MIN_FILLS
                      and (row.get("activity") or {}).get("active_days_30d_observed_lower_bound", 0) >= BASE_MIN_DAYS)
    return {
        "schema_version": "descriptive-research-admission-v1",
        "network": network,
        "cutoff_ms": cutoff_ms,
        "cutoff_utc": instant.isoformat(),
        "scope_start_ms": cutoff_ms - 30 * DAY_MS,
        "source_policy": SCREEN_POLICY,
        "source": "population_historical_decisions; decision snapshots only; read-only; no raw observation payloads",
        "policy": {
            "base_minimum_observed_fills_30d": BASE_MIN_FILLS,
            "base_minimum_active_utc_days_30d": BASE_MIN_DAYS,
            "base_scope": "exactly one instrument observed in fills during the same 30-day activity window",
            "threshold_basis": "new descriptive minimum for a minimally repeated day-level tabulation; not statistical power",
            "historical_comparator": {"fills": LEGACY_MIN_FILLS, "active_days": LEGACY_MIN_DAYS,
                                      "meaning": "existing frequent_activity_observed_lower_bound criterion"},
            "no_admission_inputs": ["declared PnL sign or size", "economic_validation", "account mode", "execution-engine compatibility"],
            "multimarket_handling": "needs_more_evidence until per-market fills, active days and coverage justify an explicit bounded scope; never excluded solely for multi-market mode",
            "priority_queue_rule": "P1 first; then include the highest-evidence candidate from each additional market namespace; fill remaining slots by active days, observed fills and address",
            "resource_authorization": "separate; evaluator grants none",
        },
        "inventory": {"candidate_count": len(evaluations), "source_status_counts": dict(sorted(by_status.items())),
                      "disposition_counts": dict(sorted(by_disposition.items())),
                      "multimarket_active_needing_scope": multiactive},
        "threshold_sensitivity": {
            "single_market_admitted_at_5_fills_1_day": count_at(5, 1),
            "single_market_admitted_at_10_fills_2_days": count_at(BASE_MIN_FILLS, BASE_MIN_DAYS),
            "single_market_admitted_at_20_fills_4_days_existing_criterion": count_at(LEGACY_MIN_FILLS, LEGACY_MIN_DAYS),
            "single_market_admitted_at_40_fills_6_days_strict_sensitivity": count_at(40, 6),
        },
        "priority_queue": queue,
        "scope_followup_queue": scope_followup,
        "candidate_evaluations": evaluations,
        "limits": [
            "Provider-reported curves are not reconciled returns or economic validation.",
            "Observed fills and active days are lower bounds where source pagination is incomplete.",
            "Market lists do not provide per-market fill counts; multi-market candidates need that proof before admission.",
            "Execution compatibility and resource authorization remain separate and are not granted here.",
            "The cutoff is a historical snapshot, not a new or virgin validation period; reserved periods are not released by this evaluator.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    inventory = report["inventory"]
    sens = report["threshold_sensitivity"]
    out = [
        "# Proposition d’admission à la recherche descriptive — 26 octobre 2026",
        "",
        f"Cutoff commun : `{report['cutoff_ms']}` ms (`{report['cutoff_utc']}`). "
        f"Période de question : `[cutoff − 30 jours, cutoff]`. Réseau : `{report['network']}`.",
        "",
        "## Décision de portée",
        "",
        f"Inventaire du screening historique `{report['source_policy']}` : **{inventory['candidate_count']}** décisions. "
        f"Admissibles à une étude descriptive : **{inventory['disposition_counts'].get('admissible_descriptive', 0)}** ; "
        f"à approfondir : **{inventory['disposition_counts'].get('needs_more_evidence', 0)}** ; "
        f"différés : **{inventory['disposition_counts'].get('deferred', 0)}** ; "
        f"exclus avant lecture : **{inventory['disposition_counts'].get('excluded', 0)}**.",
        "",
        "Cette proposition évalue une question descriptive, pas une rentabilité. Elle ne change aucun état historique, "
        "n’attribue jamais `economic_validation=true` et n’autorise ni IA, collecte, paper, moteur, quota ou capital. "
        "L’autorisation de ressources reste une décision distincte.",
        "",
        "## Contexte de décision",
        "",
        "La clôture ETH du 16 octobre a terminé cette tâche sur son périmètre borné ; elle n’a ni défini de règle "
        "autonome ni démontré un avantage exploitable. Le recontrôle du 26 octobre garde ETH terminale et confirme "
        "que la voie générale ne dispose toujours pas d’une préparation descriptive distincte. Le scheduler courant "
        "continue d’exiger `economic_validation=true`, une readiness économique approuvée et des preuves avant la "
        "recherche IA. Cette proposition ne contourne pas ce gate et ne raccorde rien au scheduler.",
        "",
        "Les tickets [TAMTAM_AGAIN-6](https://manhattam.com/work/issue/TAMTAM_AGAIN-6) (qualification/découverte) "
        "et [TAMTAM_AGAIN-12](https://manhattam.com/work/issue/TAMTAM_AGAIN-12) (boucle de recherche jusqu’au paper N1) "
        "restent les registres de décisions opérationnelles ; le code reste la référence des règles exécutables.",
        "",
        "## Règle explicite",
        "",
        f"Base : un seul instrument observé dans les fills de la même fenêtre de 30 jours, au moins {BASE_MIN_FILLS} fills observés et "
        f"{BASE_MIN_DAYS} jours UTC actifs dans les 30 jours avant cutoff. Le seuil 10/2 est une proposition "
        "minimale de répétition pour une tabulation descriptive par jour ; il ne signifie ni puissance statistique "
        "ni activité complète. Le seuil historique 20/4 décrivait déjà une activité fréquente observée. Les PnL, "
        "le mode du compte, les risques et la compatibilité d’exécution sont affichés séparément et ne filtrent pas l’admission.",
        "",
        "| Seuil de fills/jours actifs | Comptes mono-marché admissibles |",
        "|---|---:|",
        f"| 5 / 1 (sensibilité basse) | {sens['single_market_admitted_at_5_fills_1_day']} |",
        f"| 10 / 2 (proposé) | {sens['single_market_admitted_at_10_fills_2_days']} |",
        f"| 20 / 4 (critère historique fréquent) | {sens['single_market_admitted_at_20_fills_4_days_existing_criterion']} |",
        f"| 40 / 6 (sensibilité stricte) | {sens['single_market_admitted_at_40_fills_6_days_strict_sensitivity']} |",
        "",
        f"**Cas sensible :** `{next((r['candidate_alias'] for r in report['candidate_evaluations'] if r['candidate_id'].endswith('5bcf')), 'non présent')}` "
        "est admis à 10/2 malgré un screening de PnL déclaré négatif ; il passe à approfondir sous 20/4. "
        "Cette règle retient donc aussi une question non gagnante économiquement.",
        "",
        f"**Comptes multi-marchés :** {inventory['multimarket_active_needing_scope']} satisfont déjà le volume/jours 10/2, "
        "mais restent à approfondir parce que le snapshot ne ventile pas activité et couverture par instrument. "
        "Ils ne sont pas exclus ; leur question demande cette preuve avant de choisir ou agréger un marché.",
        "",
        "## File prioritaire",
        "",
        "P1 en premier ; la file courte réserve ensuite une place au candidat le mieux documenté de chaque namespace "
        "de marché supplémentaire, puis trie par jours actifs, fills observés et adresse. Cette rotation garde visibles "
        "les marchés préfixés tels que `xyz:`. Aucune mesure de performance ne participe au tri. Les comptes sont des sujets d’étude, pas des gagnants.",
        "",
        "| Rang | Compte / marché | Activité observée | Performance déclarée | Risque connu / inconnu | Couverture | Compatibilité |",
        "|---:|---|---|---|---|---|---|",
    ]
    for index, row in enumerate(report["priority_queue"], 1):
        market = (row.get("scope") or {}).get("markets") or []
        market_label = ", ".join(market) if market else "non établi"
        act = row["activity"]
        perf = row["declared_performance"]
        risk = row["known_risk"]
        cov = row["coverage"]
        req = cov.get("fills_30d_request_coverage", {}) if isinstance(cov, dict) else {}
        h90 = perf["horizons"].get("90")
        h90_delta = h90.get("delta") if isinstance(h90, dict) else None
        perf_label = f"{perf['status']}; delta déclaré 90 j {h90_delta if h90_delta is not None else 'inconnu'}"
        risk_label = (f"mode {risk['account_mode_observed']}; drawdown PnL 180 j "
                      f"{risk['sampled_pnl_peak_to_trough_180d_nominal'] or 'inconnu'}; risques non résolus {len(risk['unresolved_risk'])}")
        coverage_label = (f"{cov.get('historical_curve_samples')} points courbe; "
                          f"{req.get('query_coverage_30d_days', 'inconnue')} j de requêtes; "
                          f"troncature inconnue={req.get('truncated_or_retention_unknown', 'inconnue')}")
        out.append(f"| {index} | `{row['candidate_alias']}` / {market_label} | "
                   f"{act['fills_30d_observed_lower_bound']} fills / {act['active_days_30d_observed_lower_bound']} jours | "
                   f"{perf_label} | {risk_label} | {coverage_label} | not_assessed |")
        out.append(f"|  | Question | {row['research_question']} |  |  |  |  |")
    out.extend([
        "",
        "## Comptes multi-marchés à approfondir",
        "",
        "Ces comptes ont déjà au moins 10 fills observés sur au moins 2 jours, mais restent distincts de la file admise "
        "jusqu’à preuve d’activité et de couverture par marché. La sélection ci-dessous sert à résoudre cette lacune ; "
        "elle ne constitue pas une exclusion scientifique.",
        "",
        "| Compte | Marchés observés | Fills 30 j / jours actifs | Question proposée | Preuve manquante |",
        "|---|---|---:|---|---|",
    ])
    for row in report["scope_followup_queue"]:
        scope = row["scope"]
        markets = ", ".join(scope["markets"])
        if scope.get("additional_markets_omitted"):
            markets += f" et {scope['additional_markets_omitted']} autres"
        activity = row["activity"]
        out.append(f"| `{row['candidate_alias']}` ({scope['market_count']}) | {markets} | "
                   f"{activity['fills_30d_observed_lower_bound']} / {activity['active_days_30d_observed_lower_bound']} | "
                   f"{row['research_question']} | {'; '.join(row['missing_evidence'])} |")
    out.extend([
        "",
        "## Séparation des dimensions",
        "",
        "Le JSON contient, candidat par candidat : performance déclarée par horizon ; risque connu/risque non résolu ; "
        "couverture des courbes et requêtes ; activité observée par jours et marchés ; compatibilité d’exécution. "
        "Cette dernière reste `not_assessed` car aucune stratégie ou spécification de moteur n’est proposée.",
        "",
        "Les comptes multi-marchés ayant assez d’activité sont `needs_more_evidence`, avec la preuve manquante "
        "par marché explicitée. Les candidats sans instrument visible sont différés ; l’unique compte marqué "
        "`excluded_before_payload_read` reste exclu sans décoder son snapshot.",
        "",
        "## Sources et limites",
        "",
        "Source : lignes `population_historical_decisions` à cutoff exact, produites par le screening historique "
        "autorisé ; aucune observation brute ni archive n’a été relue. Le cutoff n’est pas une période vierge et "
        "ne libère aucune période réservée. Le fichier JSON adjacent conserve les décisions détaillées des 2 533 comptes.",
        "",
        "Références locales : `docs/continuous-research/ETH-DECISION-CLOSURE-20261016.md`, "
        "`docs/continuous-research/ETH-LOOP-RECHECK-20261026.md`, `docs/continuous-research/HISTORICAL-SELECTION.md`, "
        "`src/tamtam_again/population_scheduler.py`.",
        "",
    ])
    return "\n".join(out)


def write_report(report: dict[str, Any], json_path: str | Path, markdown_path: str | Path) -> None:
    target = Path(json_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md = Path(markdown_path)
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(render_markdown(report), encoding="utf-8")
