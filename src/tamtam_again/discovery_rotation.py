"""Deterministic catalog rotation, independent of account profitability/cohorts."""
from __future__ import annotations
import hashlib
from typing import Any


def select_markets(catalog: dict[str, Any], *, now_ms: int,
                   protected: set[str], limit: int = 5,
                   interval_ms: int = 900_000) -> dict[str, Any]:
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError('Discovery market budget must be between one and ten')
    if type(interval_ms) is not int or interval_ms < 60_000:
        raise ValueError('Discovery interval must be at least one minute')
    if type(now_ms) is not int or now_ms < 0:
        raise ValueError('Invalid decision time')
    if catalog['available_ms'] > now_ms:
        raise ValueError('Catalog not available at decision time')
    groups: dict[str, list[str]] = {}
    for name, asset in catalog['instruments'].items():
        if name in protected or asset.get('is_delisted', False):
            continue
        groups.setdefault(asset['dex'], []).append(name)
    # Round robin across DEXs, then across instruments within each DEX.
    # Catalog changes create a new schedule; every decision records its catalog.
    dexes = sorted(groups)
    schedule = []
    ordered = {dex: sorted(groups[dex], key=lambda name:
               hashlib.sha256(name.encode()).hexdigest()) for dex in dexes}
    for index in range(max((len(v) for v in ordered.values()), default=0)):
        for dex in dexes:
            if index < len(ordered[dex]):
                schedule.append(ordered[dex][index])
    epoch = now_ms // interval_ms
    count = min(limit, len(schedule))
    markets = [schedule[(epoch * limit + i) % len(schedule)]
               for i in range(count)]
    return {'version': 'catalog-round-robin-v1', 'epoch': epoch,
            'interval_ms': interval_ms, 'markets': markets,
            'eligible_markets': len(schedule),
            'catalog_available_ms': catalog['available_ms'],
            'catalog_evidence_refs': catalog.get('evidence_refs', []),
            'protected_markets': sorted(protected),
            'bias': 'equal scheduled market time; active participants remain easier to observe; DEX sizes differ'}
