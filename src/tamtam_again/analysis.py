from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from .storage import Store, decode_observation_payload


def observed_account_summary(store: Store, network: str, address: str,
                             start_ms: int, end_ms: int) -> dict[str, Any]:
    """Summarize directly observed perp components without claiming total return."""
    rows = store.observations(network, "account", address.lower(), start_ms, end_ms)
    fills: dict[str, dict[str, Any]] = {}
    funding: dict[str, dict[str, Any]] = {}
    ledger_count = 0
    coverage_incomplete = False
    observed_endpoints: set[str] = set()

    for observation in rows:
        endpoint = observation["endpoint"]
        observed_endpoints.add(endpoint)
        coverage_incomplete |= not bool(observation["complete"])
        try:
            data = decode_observation_payload(observation)
        except ValueError:
            continue
        if endpoint == "userFillsByTime" and isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                tid = str(item.get("tid", item.get("hash", repr(item))))
                fills[f"{item.get('coin', '')}:{tid}"] = item
        elif endpoint == "userFunding" and isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                key = f"{item.get('time')}:{item.get('hash')}:{repr(item.get('delta'))}"
                funding[key] = item
        elif endpoint == "userNonFundingLedgerUpdates" and isinstance(data, list):
            ledger_count += len(data)

    fill_counts: Counter[str] = Counter()
    realized_by_kind: defaultdict[str, Decimal] = defaultdict(Decimal)
    fees_by_kind_token: defaultdict[str, Decimal] = defaultdict(Decimal)
    perp_fee_tokens: Counter[str] = Counter()
    for row in fills.values():
        kind = _market_kind(str(row.get("coin", "")))
        fill_counts[kind] += 1
        realized_by_kind[kind] += _decimal(row.get("closedPnl"))
        token = str(row.get("feeToken") or "unknown").strip().upper()
        fees_by_kind_token[f"{kind}:{token}"] += _decimal(row.get("fee"))
        if kind == "perp":
            perp_fee_tokens[token] += 1
    funding_usdc = Decimal(0)
    for item in funding.values():
        delta = item.get("delta") or {}
        if isinstance(delta, dict) and delta.get("usdc") is not None:
            funding_usdc += _decimal(delta["usdc"])

    expected_history = {"userFillsByTime", "userFunding",
                       "userNonFundingLedgerUpdates"}
    missing_history = sorted(expected_history - observed_endpoints)

    return {
        "network": network,
        "address": address.lower(),
        "window_start_ms": start_ms,
        "window_end_ms": end_ms,
        "unique_fill_count_observed": len(fills),
        "fill_count_by_market_kind": dict(sorted(fill_counts.items())),
        "realized_closed_pnl_by_market_kind_observed": {
            kind: _format(value) for kind, value in sorted(realized_by_kind.items())
        },
        "fees_by_market_kind_and_fee_token_observed": {
            key: _format(value) for key, value in sorted(fees_by_kind_token.items())
        },
        "perp_fee_tokens_observed": dict(sorted(perp_fee_tokens.items())),
        "perp_realized_closed_pnl_usdc_observed": _format(realized_by_kind["perp"]),
        "perp_fees_usdc_observed": _format(fees_by_kind_token["perp:USDC"]),
        "funding_usdc_observed": _format(funding_usdc),
        "perp_pnl_less_known_usdc_fees_plus_funding_observed_usdc": _format(
            realized_by_kind["perp"] - fees_by_kind_token["perp:USDC"] + funding_usdc
        ),
        "non_funding_ledger_event_count_observed": ledger_count,
        "history_endpoints_observed": sorted(expected_history & observed_endpoints),
        "history_endpoints_missing": missing_history,
        "history_coverage_complete": not coverage_incomplete and not missing_history,
        "coverage_incomplete": coverage_incomplete or bool(missing_history),
        "observation_data_present": bool(observed_endpoints),
        "limitations": [
            "Somme des fills effectivement collectés; elle ne prouve pas la couverture complète du compte.",
            "N’inclut pas le PnL latent, la valorisation spot, les comptes liés ni les flux de capital dans un rendement total.",
            "Les comptes maître, sous-comptes, wallets d’agent et éventuelles migrations peuvent fragmenter l’historique.",
            "Le résultat est un indicateur exploratoire, pas une validation de rentabilité reproductible.",
        ],
    }


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _format(value: Decimal) -> str:
    return format(value, "f")


def _market_kind(coin: str) -> str:
    # Spot symbols use names such as @107 or PURR/USDC; perp symbols may include
    # a HIP-3 dex prefix but do not contain a slash.
    return "spot" if coin.startswith("@") or "/" in coin else "perp"
