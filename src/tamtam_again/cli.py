from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .analysis import (_fills_from_observation, cohort_research_status,
                       observed_account_summary)
from .providers.hyperliquid import NETWORKS, HyperliquidInfo, ProviderError, validate_address
from .providers.hyperliquid_stats import HyperliquidLeaderboard
from .markets import STREAM_MARKET_COUNT, TOP_MARKET_COUNT, top_markets
from .storage import Store, decode_observation_payload, utc_now
from .workflow import (claim_run, complete_paper, complete_research,
                       workflow_tick, write_research_evidence)
from .whales import rank_leaderboard
from .websocket import run_websocket_collector, tracked_market_symbols


DEFAULT_DB = Path("data/tamtam.sqlite3")
NETWORK_NAME = "hyperliquid-mainnet"
TRACKING_ACTIVITY_DAYS = 7


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tamtam-again",
        description="Collecte publique en lecture seule pour le projet tamtam_again.",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Base SQLite locale (défaut: data/tamtam.sqlite3).")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="Créer le schéma SQLite local.")

    add = commands.add_parser("add-candidate", help="Ajouter un compte candidat découvert publiquement.")
    add.add_argument("address")
    add.add_argument("--source", required=True, help="Source publique de découverte ou référence interne.")
    add.add_argument("--label", default="")
    add.add_argument("--network", choices=NETWORKS, default=NETWORK_NAME)

    listing = commands.add_parser("candidates", help="Lister le registre local de candidats.")
    listing.add_argument("--network", choices=NETWORKS)

    top_markets_cmd = commands.add_parser("top-markets", help="Afficher le dernier top 5 de marchés collecté.")
    top_markets_cmd.add_argument("--network", choices=NETWORKS, default=NETWORK_NAME)

    top_whales_cmd = commands.add_parser("top-whales", help="Afficher les derniers rangs PnL/ROI des comptes découverts.")
    top_whales_cmd.add_argument("--limit", default=25, type=int)

    research_status = commands.add_parser(
        "research-status",
        help="Résumer la cohorte suivie, ses marchés et la couverture utile au paper replay.",
    )
    research_status.add_argument("--network", choices=NETWORKS, default=NETWORK_NAME)
    research_status.add_argument("--output", type=Path,
                                  help="Écrire aussi le rapport JSON dans ce fichier.")

    wf_tick = commands.add_parser(
        "workflow-tick", help="Détecter les paliers atteints et exposer les tâches Hermes en attente."
    )
    wf_tick.add_argument("--network", choices=NETWORKS, default=NETWORK_NAME)
    wf_tick.add_argument("--stage", choices=("research", "paper"), default="research")
    wf_claim = commands.add_parser("workflow-claim", help="Prendre un bail idempotent sur un run Hermes.")
    wf_claim.add_argument("run_id")
    wf_evidence = commands.add_parser("research-evidence", help="Exporter les cycles et leur contexte marché pour Hermes.")
    wf_evidence.add_argument("run_id")
    wf_evidence.add_argument("--output", type=Path, required=True)
    wf_complete = commands.add_parser("workflow-complete", help="Enregistrer un artifact Hermes validé.")
    wf_complete.add_argument("run_id")
    wf_complete.add_argument("result_json", type=Path)

    markets = commands.add_parser("collect-markets", help="Collecter les métadonnées et indicateurs de marché publics.")
    markets.add_argument("--network", choices=NETWORKS, default=NETWORK_NAME)
    markets.add_argument("--candle-interval", default="1m")
    markets.add_argument("--candle-lookback-minutes", default=5, type=int)

    whales = commands.add_parser("collect-whales", help="Découvrir les comptes les mieux classés et collecter leurs données publiques.")
    whales.add_argument("--limit-per-window", default=25, type=int,
                        help="Nombre de comptes retenus par fenêtre et métrique PnL/ROI.")
    whales.add_argument("--max-accounts", default=10, type=int,
                        help="Plafond de comptes à approfondir pendant ce cycle.")
    whales.add_argument("--lookback-days", default=30, type=int,
                        help="Historique initial; les cycles suivants reprennent au curseur.")

    run = commands.add_parser("run-collectors", help="Lancer les collecteurs continus marché et baleines.")
    run.add_argument("--market-every-seconds", default=60, type=int)
    run.add_argument("--ranking-refresh-seconds", default=900, type=int)
    run.add_argument("--whale-every-seconds", default=3600, type=int)
    run.add_argument("--whale-limit-per-window", default=25, type=int)
    run.add_argument("--max-whale-accounts", default=10, type=int)
    run.add_argument("--max-stream-markets", default=STREAM_MARKET_COUNT, type=int)
    run.add_argument("--max-depth-markets", default=2, type=int)
    run.add_argument("--lookback-days", default=30, type=int)

    collect = commands.add_parser("collect", help="Collecter les données publiques d’un candidat connu.")
    collect.add_argument("address")
    collect.add_argument("--start-ms", required=True, type=int, help="Début UTC inclus, en millisecondes Unix.")
    collect.add_argument("--end-ms", type=int, help="Fin UTC incluse; défaut : maintenant.")
    collect.add_argument("--network", choices=NETWORKS, default=NETWORK_NAME)

    report = commands.add_parser("report", help="Produire un résumé descriptif des observations collectées.")
    report.add_argument("address")
    report.add_argument("--start-ms", required=True, type=int)
    report.add_argument("--end-ms", required=True, type=int)
    report.add_argument("--network", choices=NETWORKS, default=NETWORK_NAME)
    report.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            with Store(args.db):
                pass
            print(f"Base initialisée : {args.db}")
        elif args.command == "add-candidate":
            validate_address(args.address)
            if not args.source.strip():
                raise ValueError("La source de découverte est obligatoire.")
            with Store(args.db) as store:
                inserted = store.add_candidate(args.network, args.address,
                                               args.source.strip(), args.label.strip())
            print("Candidat ajouté." if inserted else "Candidat déjà enregistré; aucune modification.")
        elif args.command == "candidates":
            with Store(args.db) as store:
                result = [dict(row) for row in store.candidates(args.network)]
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "top-markets":
            with Store(args.db) as store:
                result = store.latest_market_selection(args.network)
            print(json.dumps(result or {}, ensure_ascii=False, indent=2))
        elif args.command == "top-whales":
            if args.limit < 1:
                raise ValueError("limit doit être positif.")
            with Store(args.db) as store:
                result = [dict(row) for row in store.latest_whale_rankings(NETWORK_NAME, args.limit)]
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "research-status":
            with Store(args.db) as store:
                result = cohort_research_status(store, args.network)
            serialized = json.dumps(result, ensure_ascii=False, indent=2)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(serialized + "\n", encoding="utf-8")
            print(serialized)
        elif args.command == "workflow-tick":
            with Store(args.db) as store:
                result = workflow_tick(store, args.network, args.stage)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "workflow-claim":
            with Store(args.db) as store:
                run = claim_run(store, args.run_id)
            request = json.loads(Path(run["request_path"]).read_text(encoding="utf-8"))
            print(json.dumps({"run": run, "request": request}, ensure_ascii=False, indent=2))
        elif args.command == "research-evidence":
            with Store(args.db) as store:
                result = write_research_evidence(store, args.run_id, args.output)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "workflow-complete":
            with Store(args.db) as store:
                row = store.connection.execute(
                    "SELECT stage FROM automation_runs WHERE run_id=?", (args.run_id,),
                ).fetchone()
                if not row:
                    raise ValueError("Run inconnu.")
                result = (complete_research(store, args.run_id, args.result_json)
                          if row["stage"] == "research"
                          else complete_paper(store, args.run_id, args.result_json))
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "collect-markets":
            _collect_markets(args)
        elif args.command == "collect-whales":
            _collect_whales(args)
        elif args.command == "run-collectors":
            _run_collectors(args)
        elif args.command == "collect":
            _collect(args)
        elif args.command == "report":
            validate_address(args.address)
            with Store(args.db) as store:
                result = observed_account_summary(store, args.network, args.address,
                                                  args.start_ms, args.end_ms)
            serialized = json.dumps(result, ensure_ascii=False, indent=2)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(serialized + "\n", encoding="utf-8")
            print(serialized)
        return 0
    except (ValueError, ProviderError, OSError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2


def _collect(args: argparse.Namespace) -> None:
    validate_address(args.address)
    end_ms = args.end_ms if args.end_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    if args.start_ms < 0 or end_ms < args.start_ms:
        raise ValueError("Fenêtre temporelle invalide.")
    address = args.address.lower()
    with Store(args.db) as store:
        if not store.get_candidate(args.network, address):
            raise ValueError("Compte absent du registre. Ajoute d’abord son adresse et sa source publique.")
        client = HyperliquidInfo(args.network)
        market = client.collect_market_snapshot()
        store.save_observation(network=args.network, source="hyperliquid-info-v1",
                               entity_type="market", entity_id="perpetuals",
                               endpoint="metaAndAssetCtxs", payload=market,
                               request_payload={"type": "metaAndAssetCtxs"})

        for endpoint in ("userFillsByTime", "userFunding", "userNonFundingLedgerUpdates"):
            pages = client.collect_time_range(endpoint, address, args.start_ms, end_ms)
            for page in pages:
                store.save_observation(
                    network=args.network, source="hyperliquid-info-v1",
                    entity_type="account", entity_id=address,
                    endpoint=endpoint, payload=page.rows,
                    request_payload=page.request,
                    requested_at=utc_now(), window_start_ms=page.start_ms,
                    window_end_ms=page.end_ms, record_count=len(page.rows),
                    complete=page.complete,
                )
            if pages and not pages[-1].complete:
                print(f"Couverture à vérifier : pagination incomplète pour {endpoint}.", file=sys.stderr)

        snapshots = client.collect_account_snapshots(address)
        for endpoint, payload in snapshots.items():
            store.save_observation(network=args.network, source="hyperliquid-info-v1",
                                   entity_type="account", entity_id=address,
                                   endpoint=endpoint, payload=payload,
                                   request_payload={"type": endpoint, "user": address})
        print(json.dumps({"network": args.network, "address": address,
                          "window_start_ms": args.start_ms, "window_end_ms": end_ms,
                          "market_snapshot_saved": True,
                          "history_endpoints": ["userFillsByTime", "userFunding",
                                                "userNonFundingLedgerUpdates"],
                          "account_snapshots": list(snapshots)}, indent=2))


def _collect_markets(args: argparse.Namespace) -> None:
    summary = _collect_market_cycle(args.db, args.network,
                                    args.candle_interval,
                                    args.candle_lookback_minutes)
    print(json.dumps(summary, indent=2))


def _collect_market_cycle(db_path: Path, network: str, candle_interval: str,
                          candle_lookback_minutes: int,
                          refresh_ranking: bool = True,
                          market_context_count: int = STREAM_MARKET_COUNT
                          ) -> dict[str, Any]:
    if candle_lookback_minutes < 1:
        raise ValueError("candle-lookback-minutes doit être positif.")
    client = HyperliquidInfo(network)
    observed_at = utc_now()
    payload = None
    with Store(db_path) as store:
        selection = store.latest_market_selection(network)
        candle_markets = tracked_market_symbols(store, network, market_context_count)
    should_refresh = refresh_ranking or selection is None
    if should_refresh:
        payload = client.collect_market_universes()
        ranked = top_markets(payload, TOP_MARKET_COUNT)
        snapshot_id = uuid4().hex
    else:
        ranked = selection["markets"]
        snapshot_id = selection["snapshot_id"]
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - candle_lookback_minutes * 60_000
    errors = []
    with Store(db_path) as store:
        if should_refresh:
            store.save_observation(
                network=network, source="hyperliquid-info-v1",
                entity_type="market", entity_id="perpetuals", endpoint="perpDexs",
                payload=payload["perpDexs"], request_payload={"type": "perpDexs"},
                requested_at=observed_at,
            )
            for dex_index, (dex, pair) in enumerate(zip(
                    payload["perpDexs"], payload["perpUniverses"])):
                dex_name = dex.get("name") if isinstance(dex, dict) else None
                venue = "perps-main" if dex_index == 0 else (
                    f"perps:{dex_name}" if dex_name else f"perps-dex-{dex_index}"
                )
                request = {"type": "metaAndAssetCtxs"}
                if dex_name:
                    request["dex"] = dex_name
                store.save_observation(
                    network=network, source="hyperliquid-info-v1",
                    entity_type="market", entity_id=f"perpetuals:{venue}",
                    endpoint="metaAndAssetCtxs", payload=pair,
                    request_payload=request, requested_at=observed_at,
                )
            store.save_observation(
                network=network, source="hyperliquid-info-v1",
                entity_type="market", entity_id="spot",
                endpoint="spotMetaAndAssetCtxs",
                payload=payload["spotMetaAndAssetCtxs"],
                request_payload={"type": "spotMetaAndAssetCtxs"},
                requested_at=observed_at,
            )
            store.save_market_rankings(snapshot_id, network, observed_at, ranked)
        for coin in candle_markets or [market["coin"] for market in ranked]:
            try:
                candles = client.collect_candles(coin, candle_interval, start_ms, end_ms)
                store.save_observation(
                    network=network, source="hyperliquid-info-v1",
                    entity_type="market", entity_id=coin,
                    endpoint=f"candleSnapshot:{candle_interval}", payload=candles,
                    request_payload={"type": "candleSnapshot", "coin": coin,
                                    "interval": candle_interval,
                                    "startTime": start_ms, "endTime": end_ms},
                    requested_at=observed_at, window_start_ms=start_ms,
                    window_end_ms=end_ms,
                    record_count=len(candles) if isinstance(candles, list) else None,
                )
            except (ProviderError, ValueError) as exc:
                errors.append({"coin": coin, "endpoint": "candleSnapshot", "error": str(exc)})
    perp_count = (sum(len(pair[0]["universe"]) for pair in payload["perpUniverses"])
                  if payload else None)
    spot_count = (len(payload["spotMetaAndAssetCtxs"][0]["universe"])
                  if payload else None)
    return {"network": network, "source": "hyperliquid-info-v1",
            "ranking_refreshed": should_refresh,
            "ranking_observed_at": observed_at if should_refresh else selection["observed_at"],
            "ranking": "dayNtlVlm_desc",
            "perp_markets_in_universe": perp_count,
            "spot_markets_in_universe": spot_count,
            "markets_in_universe": (perp_count + spot_count
                                    if perp_count is not None and spot_count is not None
                                    else None),
            "candle_markets": candle_markets or [market["coin"] for market in ranked],
            "top_markets": [{"rank": row["rank"], "coin": row["coin"],
                             "market_type": row["market_type"], "venue": row["venue"],
                             "day_notional_volume": row["day_notional_volume"]}
                            for row in ranked],
            "candle_interval": candle_interval, "errors": errors}


def _discover_whales(store: Store, limit_per_window: int) -> tuple[str, list[dict[str, Any]], int]:
    payload = HyperliquidLeaderboard().fetch()
    rankings, candidates = rank_leaderboard(payload, limit_per_window)
    observed_at = utc_now()
    snapshot_id = uuid4().hex
    archive_endpoint = "leaderboard-daily-raw"
    archived_at = store.latest_observation_at(
        NETWORK_NAME, "hyperliquid-official-web-stats-v1", "discovery",
        "leaderboard", archive_endpoint,
    )
    if archived_at is None:
        archived_at = store.latest_observation_at(
            NETWORK_NAME, "hyperliquid-official-web-stats-v1", "discovery",
            "leaderboard", "leaderboard",
        )
    should_archive = (archived_at is None or
                      datetime.fromisoformat(archived_at).date()
                      < datetime.now(timezone.utc).date())
    if should_archive:
        store.save_observation(
            network=NETWORK_NAME, source="hyperliquid-official-web-stats-v1",
            entity_type="discovery", entity_id="leaderboard",
            endpoint=archive_endpoint, payload=payload,
            request_payload={"url": "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"},
            requested_at=observed_at, record_count=len(payload["leaderboardRows"]),
        )
    store.save_whale_rankings(snapshot_id, NETWORK_NAME, observed_at, rankings)
    for candidate in candidates:
        store.add_candidate(NETWORK_NAME, candidate["address"],
                            "hyperliquid-official-web-stats:leaderboard",
                            candidate["display_name"])
    return snapshot_id, candidates, len(payload["leaderboardRows"])


def _collect_whale_accounts(store: Store, client: HyperliquidInfo,
                            addresses: list[str], lookback_days: int) -> list[dict[str, Any]]:
    if lookback_days < 1:
        raise ValueError("lookback-days doit être positif.")
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    result = []
    for address in addresses:
        endpoint_results = {}
        for endpoint in ("userFillsByTime", "userFunding", "userNonFundingLedgerUpdates"):
            prior = store.collection_cursor(NETWORK_NAME, address, endpoint)
            start_ms = max(0, prior - 1) if prior is not None else now_ms - lookback_days * 86_400_000
            pages = client.collect_time_range(endpoint, address, start_ms, now_ms)
            for page in pages:
                store.save_observation(
                    network=NETWORK_NAME, source="hyperliquid-info-v1",
                    entity_type="account", entity_id=address, endpoint=endpoint,
                    payload=page.rows, request_payload=page.request,
                    requested_at=utc_now(), window_start_ms=page.start_ms,
                    window_end_ms=page.end_ms, record_count=len(page.rows),
                    complete=page.complete,
                )
            complete = bool(pages) and all(page.complete for page in pages)
            resume_cursor = pages[-1].resume_cursor_ms if pages else None
            endpoint_results[endpoint] = {
                "pages": len(pages), "complete": complete,
                "resume_cursor_ms": resume_cursor,
            }
            if complete:
                store.mark_history_observations_complete(
                    NETWORK_NAME, address, endpoint, start_ms
                )
                store.set_collection_cursor(NETWORK_NAME, address, endpoint, now_ms)
            elif resume_cursor is not None and (prior is None or resume_cursor > prior):
                store.set_collection_cursor(NETWORK_NAME, address, endpoint,
                                           resume_cursor)
        snapshots = client.collect_account_snapshots(address)
        for endpoint, payload in snapshots.items():
            store.save_observation(
                network=NETWORK_NAME, source="hyperliquid-info-v1",
                entity_type="account", entity_id=address, endpoint=endpoint,
                payload=payload,
                request_payload={"type": endpoint, "user": address},
            )
        result.append({"address": address, "history": endpoint_results,
                       "snapshots": sorted(snapshots)})
    return result


def _collect_whales(args: argparse.Namespace, emit: bool = True) -> dict[str, Any]:
    if not 1 <= args.max_accounts <= 10 or args.limit_per_window < 1:
        raise ValueError("Le suivi WebSocket accepte 1 à 10 comptes; les autres limites doivent être positives.")
    client = HyperliquidInfo(NETWORK_NAME)
    with Store(args.db) as store:
        snapshot_id, _, source_count = _discover_whales(store, args.limit_per_window)
        cutoff_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - (
            TRACKING_ACTIVITY_DAYS * 86_400_000
        )
        inactive_addresses = []
        for row in store.candidates(NETWORK_NAME):
            if row["status"] != "tracked":
                continue
            last_fill_ms = _last_observed_fill_ms(store, row["address"], cutoff_ms)
            if last_fill_ms is None or last_fill_ms < cutoff_ms:
                inactive_addresses.append(row["address"])
        tracked = store.promote_top_whales(snapshot_id, NETWORK_NAME,
                                           args.max_accounts, inactive_addresses)
        candidates = store.whale_addresses(snapshot_id, args.max_accounts)
        addresses = [row["address"] for row in candidates]
        candidate_pool_size = len(store.candidates(NETWORK_NAME))
        collected = _collect_whale_accounts(store, client, addresses, args.lookback_days)
    summary = {"leaderboard_rows": source_count,
               "candidate_pool_size": candidate_pool_size,
               "tracked_accounts": tracked,
               "inactive_accounts_demoted": len(inactive_addresses),
               "selected_candidates": len(addresses),
               "collected_accounts": collected}
    if emit:
        print(json.dumps(summary, indent=2))
    return summary


def _last_observed_fill_ms(store: Store, address: str,
                           cutoff_ms: int) -> int | None:
    latest: int | None = None
    rows = store.observations(NETWORK_NAME, "account", address.lower(),
                              cutoff_ms, None)
    for observation in rows:
        if observation["endpoint"] not in {"userFillsByTime", "userFills"}:
            continue
        try:
            payload = decode_observation_payload(observation)
        except (ValueError, TypeError, OSError):
            continue
        for fill in _fills_from_observation(observation["endpoint"], payload):
            try:
                stamp = int(fill.get("time", 0))
            except (TypeError, ValueError):
                continue
            if stamp >= cutoff_ms and (latest is None or stamp > latest):
                latest = stamp
    return latest


def _run_collectors(args: argparse.Namespace) -> None:
    if args.market_every_seconds < 15 or args.whale_every_seconds < 300:
        raise ValueError("Cadence minimale : marché 15 s; baleines 300 s.")
    if args.ranking_refresh_seconds < 300:
        raise ValueError("Le classement de volume doit être rafraîchi au moins toutes les 5 minutes.")
    if (not 1 <= args.max_whale_accounts <= 10
            or args.whale_limit_per_window < 1
            or args.max_stream_markets < TOP_MARKET_COUNT
            or not 1 <= args.max_depth_markets <= args.max_stream_markets):
        raise ValueError("Le WebSocket accepte 1 à 10 comptes; limites de marchés invalides.")
    stop_event = threading.Event()

    def repeat(name: str, cadence: int, collect: Any) -> None:
        while not stop_event.is_set():
            started = time.monotonic()
            try:
                result = collect()
                print(json.dumps({"collector": name, "result": result,
                                  "cycle_at": utc_now()}, ensure_ascii=False), flush=True)
            except (ValueError, ProviderError, OSError) as exc:
                print(json.dumps({"collector": name, "error": str(exc),
                                  "cycle_at": utc_now()}, ensure_ascii=False),
                      file=sys.stderr, flush=True)
            except Exception as exc:
                print(json.dumps({"collector": name,
                                  "error": f"{type(exc).__name__}: {exc}",
                                  "cycle_at": utc_now()}, ensure_ascii=False),
                      file=sys.stderr, flush=True)
            stop_event.wait(max(0.0, cadence - (time.monotonic() - started)))

    whale_args = argparse.Namespace(
        db=args.db, limit_per_window=args.whale_limit_per_window,
        max_accounts=args.max_whale_accounts, lookback_days=args.lookback_days,
    )
    next_ranking_refresh = 0.0

    def collect_market_loop() -> dict[str, Any]:
        nonlocal next_ranking_refresh
        now = time.monotonic()
        refresh = now >= next_ranking_refresh
        summary = _collect_market_cycle(
            args.db, NETWORK_NAME, "1m", 5, refresh_ranking=refresh,
            market_context_count=args.max_stream_markets,
        )
        if refresh:
            next_ranking_refresh = now + args.ranking_refresh_seconds
        return summary

    print("Collecteurs actifs; Ctrl-C pour arrêter.", flush=True)
    market_thread = threading.Thread(
        target=repeat,
        args=("markets", args.market_every_seconds, collect_market_loop),
        name="tamtam-market-collector",
        daemon=True,
    )
    websocket_thread = threading.Thread(
        target=run_websocket_collector,
        args=(stop_event, args.db, NETWORK_NAME, args.max_stream_markets,
              args.max_depth_markets),
        name="tamtam-websocket-collector",
        daemon=True,
    )
    whale_thread = threading.Thread(
        target=repeat,
        args=("whales", args.whale_every_seconds,
              lambda: _collect_whales(whale_args, emit=False)),
        name="tamtam-whale-collector",
        daemon=True,
    )
    market_thread.start()
    whale_thread.start()
    websocket_thread.start()
    try:
        market_thread.join()
        whale_thread.join()
    except KeyboardInterrupt:
        print("Arrêt demandé; les requêtes en cours se terminent.", flush=True)
        stop_event.set()
        deadline = time.monotonic() + 30
        for worker in (market_thread, whale_thread, websocket_thread):
            worker.join(timeout=max(0.0, deadline - time.monotonic()))
        still_running = [worker.name for worker in (market_thread, whale_thread, websocket_thread)
                         if worker.is_alive()]
        if still_running:
            print(json.dumps({"stopping_workers": still_running,
                              "message": "Arrêt après la fenêtre de grâce; les observations validées sont conservées."}),
                  file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
