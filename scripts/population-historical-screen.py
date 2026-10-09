#!/usr/bin/env python3
"""Build and persist a deterministic historical population screen (no API/AI)."""
import argparse
import csv
import json
import sqlite3
import time
from pathlib import Path
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from tamtam_again.historical_selection import build_report, persist_decisions

STATUS_FR = {
    "credible_deep_dive_candidate": "approfondissement crédible",
    "reported_positive_pending_activity": "PnL déclaré positif, activité à confirmer",
    "reported_positive_concentrated_or_sparse": "PnL déclaré positif, gains concentrés ou série trop courte",
    "insufficiently_documented": "documentation insuffisante",
    "non_prioritaire_performance_declared_negative": "non prioritaire : PnL déclaré négatif sur un horizon mesuré",
    "excluded_before_payload_read": "exclu avant lecture des observations",
}


def write_outputs(report, outdir, max_charts):
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    fields = ["address", "status", "performance_quality", "activity_quality", "account_mode",
              "allTime_pnl_samples", "allTime_max_gap_days", "fills_30d_observed", "active_days_30d_observed", "fill_query_days", "fill_pagination_statuses",
              "recovery_watch_status", "confidence", "horizons", "reasons"]
    with (outdir / "accounts.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for account in report["accounts"]:
            writer.writerow({"address": account.get("address"), "status": account.get("status"),
                             "performance_quality": account.get("performance_quality"),
                             "activity_quality": account.get("activity_quality"),
                             "account_mode": account.get("account_mode", "unknown"),
                             "allTime_pnl_samples": account.get("data_quality", {}).get("allTime_pnl_samples"),
                             "allTime_max_gap_days": account.get("data_quality", {}).get("allTime_max_gap_days"),
                             "fills_30d_observed": account.get("fill_activity", {}).get("fills_30d_observed"),
                             "active_days_30d_observed": account.get("fill_activity", {}).get("active_days_30d_observed"),
                             "fill_query_days": account.get("fill_activity", {}).get("query_span_days"),
                             "fill_pagination_statuses": json.dumps(account.get("fill_activity", {}).get("pagination_statuses", [])),
                             "recovery_watch_status": account.get("recovery_watch", {}).get("status"),
                             "confidence": account.get("confidence"),
                             "horizons": json.dumps(account.get("horizons", {}), sort_keys=True),
                             "reasons": " | ".join(account.get("reasons", []))})
    rows = report["accounts"]
    lines = [f"# Sélection historique — cutoff {report['as_of_utc']}", "",
             "Courbes déclarées Hyperliquid ; aucun résultat n'est une performance économique réconciliée ou une stratégie validée.", "",
             f"Comptes autorisés analysés : {report['population']['authorized_analyzed']} / {report['population']['inventory']}. Appels fournisseur : 0. Observations décodées : {report['raw_observation_payloads_read']}.", "",
             "États : " + "; ".join(f"{STATUS_FR.get(k,k)} : {v}" for k,v in sorted(report['status_counts'].items())), "",
             f"Comptes répondant aux critères de courbes et d'activité : {report['status_counts'].get('credible_deep_dive_candidate',0)}. Les positifs en attente sont des cibles de collecte ; ils ne sont pas qualifiés pour une RE.", "",
             "| Compte | État | PnL déclaré 30 j | PnL déclaré 90 j | PnL déclaré 180 j | fills observés dans 30 j | jours avec fills | jours de requête fills | qualité activité | baisse PnL échantillonnée 180 j |",
             "|---|---|---:|---:|---:|---:|---:|---:|---|---:|"]
    for d in rows:
        h30, h90, h180 = (d.get("horizons", {}).get(str(days), {}) for days in (30, 90, 180))
        f = d.get("fill_activity", {})
        lines.append(f"| `{d['address']}` | {STATUS_FR.get(d['status'],d['status'])} | {h30.get('delta') or 'inconnu'} | {h90.get('delta') or 'inconnu'} | {h180.get('delta') or 'inconnu'} | {f.get('fills_30d_observed', 0)} | {f.get('active_days_30d_observed', 0)} | {f.get('query_span_days', 0)} | {d.get('activity_quality', 'inconnue')} | {h180.get('max_sampled_pnl_peak_to_trough') or 'inconnu'} |")
    lines += ["", "## Règle de décision", "",
              "La coupure, les tolérances de bornes et les critères sont fixés dans `report.json`. Aucune interpolation n'est faite. Les valeurs de `pnlHistory` sont des variations déclarées par le fournisseur ; elles ne sont pas converties en rendement corrigé des dépôts/retraits.", "",
              "`vlm` reste un volume déclaré, jamais un nombre de transactions. Les fills et ordres observés sont incomplets et leurs fenêtres sont affichées dans le JSON/CSV. Les états d'exposition sont les derniers snapshots réellement reçus et ne décrivent pas le risque historique.", "",
              "## Courbes des comptes les plus prioritaires", ""]
    chart_accounts = list(rows[:max_charts])
    existing = {d["address"] for d in chart_accounts}
    chart_accounts.extend(d for d in report.get("recovery_watch_list", []) if d["address"] not in existing)
    for d in chart_accounts:
        points = d.get("evidence", {}).get("series", {}).get("allTime.pnlHistory", {}).get("points", [])
        if len(points) < 2:
            continue
        chart = outdir / ("curve-" + d["address"] + ".svg")
        draw_svg(points, chart, d["address"])
        lines.append(f"- `{d['address']}` — [{chart.name}]({chart.name}) ({STATUS_FR.get(d['status'],d['status'])}).")
    lines += ["", f"## Surveillance d'une reprise apparente ({report.get('recovery_watch_count', 0)})", "",
              "Règle fixée avant l'extraction : PnL déclaré positif sur 30 jours, puis négatif sur au moins un des horizons fixes 90 ou 180 jours. Il s'agit d'une liste de surveillance ; elle n'indique pas un changement de stratégie et ne modifie pas l'allocation prioritaire.", ""]
    for d in report.get("recovery_watch_list", []):
        h=d["horizons"]
        flows=d.get("recovery_watch",{}).get("observed_external_flows_30d",[])
        flow_note=("flux externes observés : "+", ".join(f"{x['observed_amount']} {x['currency']} ({x['event_count']} événements)" for x in flows)+"; couverture inconnue") if flows else "aucun flux externe classé observé dans ces pages; couverture inconnue"
        lines.append(f"- `{d['address']}` — 30 j {h['30'].get('delta') or 'inconnu'}, 90 j {h['90'].get('delta') or 'inconnu'}, 180 j {h['180'].get('delta') or 'inconnu'}; {flow_note}.")
    (outdir / "report.md").write_text("\n".join(lines) + "\n")


def draw_svg(points, path, title):
    cutoff = max(int(p[0]) for p in points)
    subset = [(int(t), float(v)) for t, v in points if int(t) >= cutoff - 180 * 86_400_000]
    if len(subset) < 2:
        subset = [(int(t), float(v)) for t, v in points]
    width, height, pad = 960, 420, 48
    xs = [t for t, _ in subset]
    ys = [v for _, v in subset]
    lo, hi = min(ys), max(ys)
    if hi == lo:
        hi += 1
    xspan, yspan = max(xs) - min(xs), hi - lo
    coords = [(pad + (x - min(xs)) / xspan * (width - 2 * pad),
               height - pad - (y - lo) / yspan * (height - 2 * pad)) for x, y in subset]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    labels = escape(title)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
           '<rect width="100%" height="100%" fill="white"/>'
           f'<text x="{pad}" y="26" font-family="sans-serif" font-size="14">{labels} — allTime pnlHistory, dernières observations (180 j affichés)</text>'
           f'<line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" stroke="#777"/>'
           f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height-pad}" stroke="#777"/>'
           f'<polyline fill="none" stroke="#155eef" stroke-width="2" points="{poly}"/>'
           f'<text x="{pad}" y="{height-12}" font-family="sans-serif" font-size="11">{_date_label(min(xs))}</text>'
           f'<text x="{width-pad-100}" y="{height-12}" font-family="sans-serif" font-size="11">{_date_label(max(xs))}</text>'
           f'<text x="{pad+8}" y="{pad+15}" font-family="sans-serif" font-size="11">{hi:.2f}</text>'
           f'<text x="{pad+8}" y="{height-pad-4}" font-family="sans-serif" font-size="11">{lo:.2f}</text></svg>')
    path.write_text(svg)


def _date_label(ms):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--network", default="hyperliquid-mainnet")
    p.add_argument("--as-of-ms", type=int, help="Fixed UTC cutoff in milliseconds; defaults to invocation time")
    p.add_argument("--daily-cutoff-utc", help="Use a deterministic daily HH:MM UTC decision cutoff")
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--max-charts", type=int, default=10)
    p.add_argument("--no-persist", action="store_true", help="Do not append immutable decisions to the DB")
    args = p.parse_args()
    if args.as_of_ms is not None and args.daily_cutoff_utc:
        p.error("choose --as-of-ms or --daily-cutoff-utc")
    if args.daily_cutoff_utc:
        try:
            hour, minute = (int(x) for x in args.daily_cutoff_utc.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59): raise ValueError
            now = datetime.now(timezone.utc)
            as_of_ms = int(datetime(now.year, now.month, now.day, hour, minute, tzinfo=timezone.utc).timestamp() * 1000)
        except (ValueError, TypeError):
            p.error("--daily-cutoff-utc must be HH:MM")
    else:
        as_of_ms = args.as_of_ms if args.as_of_ms is not None else int(time.time() * 1000)
    path = args.db.resolve()
    started = time.perf_counter()
    with sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=30) as connection:
        connection.row_factory = sqlite3.Row
        report = build_report(connection, network=args.network, as_of_ms=as_of_ms)
        inserted = 0 if args.no_persist else persist_decisions(connection, report)
    report["provider_calls"] = 0
    write_outputs(report, args.output_dir, args.max_charts)
    print(json.dumps({"as_of_ms": as_of_ms, "analyzed": report["population"]["authorized_analyzed"],
                      "status_counts": report["status_counts"], "persisted_decisions": inserted,
                      "provider_calls": 0, "provider_requests": 0,
                      "raw_observation_payloads_read": report["raw_observation_payloads_read"],
                      "duration_seconds": round(time.perf_counter()-started,3),
                      "output_dir": str(args.output_dir)}))


if __name__ == "__main__":
    main()
