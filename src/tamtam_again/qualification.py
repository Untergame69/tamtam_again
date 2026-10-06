"""Three separate account assessments and immutable selection snapshots."""
from __future__ import annotations

from collections import defaultdict
import json
from typing import Any

from .analysis import _fills_from_observation
from .engine import canonical, fingerprint, number
from .storage import Store, decode_observation_payload, utc_now

METRICS = ("realized_pnl", "unrealized_pnl", "fees", "funding", "account_value", "exposure_usdc",
           "leverage", "drawdown", "deposit_adjusted_return", "gain_concentration", "market_dependence")


def qualify(store: Store, network: str, address: str) -> dict[str,Any]:
    observed = {key:None for key in METRICS}
    snapshots = {}
    fills = {}
    funding = {}
    ledger_present = False
    last_receipt = None
    for row in store.observations(network,"account",address):
        payload = decode_observation_payload(row)
        endpoint = row["endpoint"]
        last_receipt = max(last_receipt or row["requested_at"],row["requested_at"])
        if endpoint == "clearinghouseState":
            snapshots[endpoint] = payload
        if endpoint in {"userFills","userFillsByTime"}:
            for fill in _fills_from_observation(endpoint,payload):
                identity = (fill.get("coin"),fill.get("time"),fill.get("tid",fill.get("hash")))
                fills[identity] = fill
        if endpoint == "userFunding" and isinstance(payload,list):
            for item in payload:
                delta = item.get("delta",item)
                if "usdc" in delta:
                    funding[(item.get("time"),delta.get("coin"))] = number(delta["usdc"])
        if endpoint == "userNonFundingLedgerUpdates":
            ledger_present = True
    if fills:
        if all("closedPnl" in f for f in fills.values()):
            observed["realized_pnl"] = str(sum(number(f["closedPnl"]) for f in fills.values()))
        if all("fee" in f and f.get("feeToken") == "USDC" for f in fills.values()):
            observed["fees"] = str(sum(number(f["fee"]) for f in fills.values()))
        # builderFee is included in fee according to the API; never add twice.
        positive_by_day = defaultdict(lambda:number(0))
        for f in fills.values():
            pnl = number(f.get("closedPnl",0))
            if pnl > 0:
                positive_by_day[int(f["time"])//86400000] += pnl
        if positive_by_day:
            observed["gain_concentration"] = str(max(positive_by_day.values())/sum(positive_by_day.values()))
    if funding:
        observed["funding"] = str(sum(funding.values()))
    state = snapshots.get("clearinghouseState")
    if isinstance(state,dict):
        margin = state.get("marginSummary",{})
        positions = [x["position"] for x in state.get("assetPositions",[]) if isinstance(x.get("position"),dict)]
        if "accountValue" in margin:
            observed["account_value"] = str(number(margin["accountValue"]))
        if "totalNtlPos" in margin:
            observed["exposure_usdc"] = str(number(margin["totalNtlPos"]))
        if positions and all("unrealizedPnl" in p for p in positions):
            observed["unrealized_pnl"] = str(sum(number(p["unrealizedPnl"]) for p in positions))
        elif "assetPositions" in state and not positions:
            observed["unrealized_pnl"] = "0"
        if observed["account_value"] and observed["exposure_usdc"] and number(observed["account_value"]) > 0:
            observed["leverage"] = str(number(observed["exposure_usdc"])/number(observed["account_value"]))
    candidate = store.get_candidate(network,address)
    selected_at = None
    if store.connection.execute("SELECT 1 FROM sqlite_master WHERE name='cohort_membership_decisions'").fetchone():
        selected_at = store.connection.execute("SELECT min(created_at) FROM cohort_membership_decisions WHERE network=? AND address=? AND status='tracked'",(network,address)).fetchone()[0]
    return {"network":network,"address":address,"selected_status":candidate["status"] if candidate else "unknown",
            "discovered_at":candidate["added_at"] if candidate else None,"selection_first_recorded_at":selected_at,"as_of":last_receipt,
            "performance":{"status":"descriptive_only","observed":observed,"unknown":[k for k,v in observed.items() if v is None],
                           "scope":"observed perpetual fills and latest perp state; not lifetime/whole-platform return"},
            "observability":{"status":"partially_observable" if fills else "unknown","fills":len(fills),
                             "ledger_present":ledger_present,"external_hedges":"unknown","queue_priority":"unknown"},
            "reproducibility":{"status":"unproven","requires":"frozen strategy with passed real N1 and measured N2"}}


def snapshot_cohort(store: Store, network: str, *, reason: str) -> dict[str,Any]:
    if not reason.strip():
        raise ValueError("Selection decision reason required")
    store.connection.execute("""CREATE TABLE IF NOT EXISTS qualification_cohorts (
      cohort_id TEXT PRIMARY KEY,network TEXT NOT NULL,created_at TEXT NOT NULL,reason TEXT NOT NULL,payload_json TEXT NOT NULL)""")
    accounts = [qualify(store,network,row["address"]) for row in store.candidates(network)]
    payload = {"created_at":utc_now(),"network":network,"reason":reason,"accounts":accounts}
    identity = fingerprint(payload)
    store.connection.execute("INSERT INTO qualification_cohorts VALUES (?,?,?,?,?)",(identity,network,payload["created_at"],reason,canonical(payload)))
    store.connection.commit()
    return {"cohort_id":identity,"accounts":len(accounts),"reason":reason}
