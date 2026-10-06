from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .storage import Store, utc_now


def write_tracked_cohort(store: Store, output: Path, network: str) -> dict[str, Any]:
    """Publish only the currently tracked public account identifiers."""
    candidates = [row for row in store.candidates(network)
                  if row["status"] == "tracked"]
    rankings = store.latest_whale_rankings(network, limit=500)
    names: dict[str, str] = {}
    for row in rankings:
        address = str(row["address"]).lower()
        display_name = str(row["display_name"] or "").strip()
        if display_name:
            names.setdefault(address, display_name)

    accounts = []
    for index, row in enumerate(candidates, start=1):
        address = str(row["address"]).lower()
        accounts.append({
            "label": names.get(address) or str(row["label"] or "").strip()
                     or f"Compte {index:02d}",
            "address": address,
            "tracked_since": str(row["added_at"]),
            "profile_url": f"https://hypurrscan.io/address/{address}",
            "selection_evidence": [{"window": r["window"], "rank": r["rank"],
                                    "pnl": r["pnl"]}
                                   for r in rankings
                                   if str(r["address"]).lower() == address
                                   and r["metric"] == "pnl"],
            "filter_status": "not_fully_verified",
        })

    payload = {
        "schema_version": 1,
        "network": network,
        "updated_at": utc_now(),
        "count": len(accounts),
        "qualification": "candidate",
        "accounts": accounts,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{output.name}.",
                                     suffix=".tmp", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, 0o644)
        os.replace(temp_name, output)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return payload
