"""Causal archive adapter and persistent N2 paper reducer; no order API."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
from uuid import uuid4

from .engine import canonical, fingerprint, initial_state, metrics, number, reduce_event
from .storage import Store, decode_observation_payload, utc_now
from .validation import decision, get_variant, now_ms


def timestamp(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def archive_events(store: Store, network: str, address: str, coin: str, start_ms: int, end_ms: int,
                   *, after_observation_id: int = 0) -> tuple[list[dict[str,Any]], int]:
    """Only archived local receipts, live fills, and observed funding rates.

    Historical HTTP fills are never follower signals. No invented connection
    continuity or funding zeroes. Old streams lack session evidence and remain
    unavailable for promotion.
    """
    start = datetime.fromtimestamp(start_ms/1000,timezone.utc).isoformat(timespec="milliseconds")
    end = datetime.fromtimestamp(end_ms/1000,timezone.utc).isoformat(timespec="milliseconds")
    rows = store.connection.execute("""SELECT * FROM raw_observations
       WHERE network=? AND observation_id>? AND source='hyperliquid-websocket-v1'
       AND observed_at>=? AND requested_at<?
       AND ((entity_type='market' AND entity_id=? AND endpoint='bbo')
         OR (entity_type='account' AND entity_id=? AND endpoint IN ('userFills','userFundings'))
         OR (entity_type='stream' AND endpoint='streamHealth')) ORDER BY observation_id""",
       (network,after_observation_id,start,end,coin,address)).fetchall()
    events = []
    cursor = after_observation_id
    seen = set()
    for row in rows:
        cursor = max(cursor,int(row["observation_id"]))
        archived_available = timestamp(row["observed_at"])
        if archived_available >= end_ms:
            continue
        payload = decode_observation_payload(row)
        request = json.loads(row["request_json"])
        if row["endpoint"] == "streamHealth":
            receipt = timestamp(row["requested_at"])
            if start_ms <= receipt < end_ms:
                events.append({"id":f"health:{row['observation_id']}","received_ms":receipt,"event_ms":receipt,"available_ms":max(receipt,archived_available),**payload})
            continue
        frames = payload.get("events",[]) if row["entity_type"] == "market" else [{"received_at":row["requested_at"],"message":payload}]
        for frame in frames:
            receipt = timestamp(frame["received_at"])
            if not start_ms <= receipt < end_ms:
                continue
            message = frame["message"]
            data = message.get("data",{})
            stream = {**request.get("user_fills_stream",{}), **message.get("_stream",{})}
            session = stream.get("connection_id")
            if row["endpoint"] == "bbo":
                bbo = data.get("bbo",[])
                if len(bbo) != 2 or not all(isinstance(x,dict) for x in bbo):
                    continue
                exchange = int(data["time"])
                if exchange < start_ms or exchange > receipt:
                    continue
                event = {"kind":"bbo","event_ms":exchange,"received_ms":receipt,"available_ms":max(receipt,archived_available),"session":session,
                         "bid":bbo[0]["px"],"ask":bbo[1]["px"],"bid_size":bbo[0]["sz"],"ask_size":bbo[1]["sz"]}
                event["id"] = fingerprint(event)
                events.append(event)
            elif row["endpoint"] == "userFills":
                flag = data.get("isSnapshot")
                live = flag is False or ("isSnapshot" not in data and isinstance(stream.get("sequence"),int) and stream["sequence"] > 1 and session)
                if not live:
                    continue
                for fill in data.get("fills",[]):
                    if fill.get("coin") != coin:
                        continue
                    exchange = int(fill["time"])
                    if exchange < start_ms or exchange > receipt:
                        continue
                    identity = f"leader:{coin}:{exchange}:{fill['tid']}"
                    if identity in seen:
                        continue
                    seen.add(identity)
                    events.append({"id":identity,"kind":"leader_fill","event_ms":exchange,"received_ms":receipt,
                                   "available_ms":max(receipt,archived_available),"session":session,"is_snapshot":False,"delta":str(number(fill["sz"]) * (1 if fill["side"] == "B" else -1))})
            elif row["endpoint"] == "userFundings" and data.get("isSnapshot") is False:
                for funding in data.get("fundings",[]):
                    if funding.get("coin") != coin:
                        continue
                    exchange = int(funding["time"])
                    if (start_ms <= exchange <= receipt and "szi" in funding and "usdc" in funding
                            and number(funding["szi"]) != 0):
                        # A settled payment per signed unit determines the
                        # common funding coefficient without inventing a mark.
                        # Apply it to OUR effective position, never copy the
                        # leader's total payment or size.
                        unit = number(funding["usdc"])/number(funding["szi"])
                        events.append({"id":f"funding:{coin}:{exchange}","kind":"funding","received_ms":receipt,
                                       "available_ms":max(receipt,archived_available),"event_ms":exchange,
                                       "unit_funding_usdc":str(unit),"provenance":"settled_user_funding_usdc_divided_by_signed_szi"})
    return sorted(events,key=lambda e:(e.get("available_ms",e["received_ms"]),e["received_ms"],str(e["id"]))),cursor


def classify_regimes(events: list[dict[str,Any]], criteria: dict[str,Any]) -> list[dict[str,Any]]:
    """Causal trend/quiet proxy, explicitly not an exhaustive regime taxonomy."""
    threshold = number(criteria["regime_threshold_bps"])
    window = criteria["regime_window_ms"]
    history = []
    result = list(events)
    for e in sorted(events,key=lambda x:(x["received_ms"],str(x["id"]))):
        if e["kind"] != "bbo":
            continue
        mid = (number(e["bid"])+number(e["ask"]))/2
        prior = [p for p in history if p[0] <= e["received_ms"] - window]
        if prior:
            change = (mid/prior[-1][1]-1)*10000
            label = "up" if change > threshold else "down" if change < -threshold else "quiet"
            result.append({"id":"regime:"+e["id"],"kind":"regime","event_ms":e["event_ms"],"received_ms":e["received_ms"],"available_ms":e.get("available_ms",e["received_ms"]),"label":label})
        history.append((e["received_ms"],mid))
        older = [p for p in history if p[0] <= e["received_ms"]-window]
        history = older[-1:]+[p for p in history if p[0]>e["received_ms"]-window]
    return sorted(result,key=lambda e:(e.get("available_ms",e["received_ms"]),e["received_ms"],str(e["id"])))


def start_paper(store: Store, variant_id: str, *, synthetic_recipe: bool = False) -> dict[str,Any]:
    row,spec,plan = get_variant(store,variant_id)
    passed = store.connection.execute("SELECT result_json FROM validation_evaluations WHERE variant_id=? AND stage='final' AND status='passed'",(variant_id,)).fetchone()
    if not passed or (row["synthetic"] and not synthetic_recipe):
        raise ValueError("N2 requires real passed N1; synthetic recipe cannot activate real paper")
    if not row["synthetic"] and not json.loads(passed[0])["promotable"]:
        raise ValueError("N1 is not promotable")
    existing = store.connection.execute("SELECT session_id FROM paper_sessions WHERE variant_id=? AND status='active'",(variant_id,)).fetchone()
    if existing:
        return {"session_id":existing[0],"synthetic":bool(row["synthetic"])}
    session_id = uuid4().hex
    started = now_ms()
    state = initial_state(spec)
    store.connection.execute("INSERT INTO paper_sessions VALUES (?,?,?,?,?,?,?,?,?,?)",(session_id,variant_id,row["network"],row["address"],row["coin"],canonical(state),"active",started,0,utc_now()))
    store.connection.commit()
    if not row["synthetic"]:
        decision(store,row["network"],row["address"],row["coin"],"paper_active","N1 final passed by deterministic engine",{"interruptions":"suspend"},"paper_tick",{"session_id":session_id})
    return {"session_id":session_id,"synthetic":bool(row["synthetic"]),"started_ms":started}


def paper_tick(store: Store, session_id: str) -> dict[str,Any]:
    session = store.connection.execute("SELECT * FROM paper_sessions WHERE session_id=?",(session_id,)).fetchone()
    if not session or session["status"] != "active":
        raise ValueError("Paper session unknown or suspended")
    row,spec,plan = get_variant(store,session["variant_id"])
    if row["synthetic"]:
        raise ValueError("Synthetic session must never consume a real archive")
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        session = store.connection.execute("SELECT * FROM paper_sessions WHERE session_id=?",(session_id,)).fetchone()
        state = json.loads(session["state_json"])
        events,cursor = archive_events(store,row["network"],row["address"],row["coin"],session["started_ms"],now_ms(),after_observation_id=session["last_observation_id"])
        processed_ms = now_ms()
        for event in events:
            event["available_ms"] = max(processed_ms,state["last_ms"],event.get("available_ms",event["received_ms"]))
            reduce_event(state,spec,event)
        clock_ms = now_ms()
        reduce_event(state,spec,{"id":f"n2-timer:{clock_ms}","kind":"timer","received_ms":clock_ms,"event_ms":clock_ms})
        healthy = state["healthy_at_ms"]
        if now_ms() - session["started_ms"] > plan["budget"]["max_duration_ms"]:
            state["diagnostics"].append("paper_duration_budget_exhausted")
        if healthy is None or now_ms()-healthy > spec["execution"]["heartbeat_timeout_ms"]:
            state["diagnostics"].append("missing_live_heartbeat")
        status = "suspended" if state["diagnostics"] else "active"
        store.connection.execute("UPDATE paper_sessions SET state_json=?,status=?,last_observation_id=?,updated_at=? WHERE session_id=?",(canonical(state),status,cursor,utc_now(),session_id))
        store.connection.commit()
    except Exception:
        store.connection.rollback()
        raise
    if status == "suspended":
        decision(store,row["network"],row["address"],row["coin"],"suspended","N2 observation continuity failed",{"requires_operator_review":True,"new_session_required":True},"inspect_collector",state["diagnostics"])
    return {"session_id":session_id,"status":status,"processed_events":len(events),"metrics":metrics(state,spec,plan["criteria"]["block_ms"])}


def synthetic_recipe_tick(store: Store, session_id: str, events: list[dict[str,Any]]) -> dict[str,Any]:
    """Exercise persistent N2 state with fixture events in a synthetic session.

    Not exposed as a real feed: this function explicitly rejects real variants.
    """
    session = store.connection.execute("SELECT * FROM paper_sessions WHERE session_id=?",(session_id,)).fetchone()
    if not session:
        raise ValueError("Unknown recipe session")
    row,spec,plan = get_variant(store,session["variant_id"])
    if not row["synthetic"]:
        raise ValueError("Fixture feed forbidden for real variants")
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        session = store.connection.execute("SELECT * FROM paper_sessions WHERE session_id=?",(session_id,)).fetchone()
        state = json.loads(session["state_json"])
        for event in events:
            reduce_event(state,spec,event)
        store.connection.execute("UPDATE paper_sessions SET state_json=?,updated_at=? WHERE session_id=?",(canonical(state),utc_now(),session_id))
        store.connection.commit()
    except Exception:
        store.connection.rollback()
        raise
    return {"synthetic":True,"session_id":session_id,"metrics":metrics(state,spec,plan["criteria"]["block_ms"])}
