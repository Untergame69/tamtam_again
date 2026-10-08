"""Causal archive adapter and persistent N2 paper reducer; no order API."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
from uuid import uuid4

from .engine import canonical, fingerprint, initial_state, metrics, number, reduce_event
from .storage import Store, decode_observation_payload, utc_now
from .validation import decision, get_variant, now_ms
from . import paper_evidence


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
    # Separate indexed entity/time scans instead of a multi-entity OR scan over
    # the whole archive. Availability is bounded at BOTH ends of the window.
    common = "network=? AND observation_id>? AND source='hyperliquid-websocket-v1' AND observed_at>=? AND observed_at<? AND requested_at<?"
    params = (network,after_observation_id,start,end,end)
    rows = []
    for clause,extra in [("entity_type='market' AND entity_id=? AND endpoint='bbo'",(coin,)),
                         ("entity_type='account' AND entity_id=? AND endpoint IN ('userFills','userFundings')",(address,)),
                         ("entity_type='stream' AND endpoint='streamHealth'",())]:
        rows.extend(store.connection.execute('SELECT * FROM raw_observations WHERE '+common+' AND '+clause,params+extra).fetchall())
    rows.sort(key=lambda row:row['observation_id'])
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
                                   "available_ms":max(receipt,archived_available),"session":session,"is_snapshot":False,
                                   "leader_start_position":fill.get("startPosition"),
                                   "delta":str(number(fill["sz"]) * (1 if fill["side"] == "B" else -1))})
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


def start_paper(store: Store, variant_id: str, *, synthetic_recipe: bool = False,
                restart_reason: str | None = None, reference_binding: dict | None = None) -> dict[str,Any]:
    row,spec,plan = get_variant(store,variant_id)
    passed = store.connection.execute("SELECT result_json FROM validation_evaluations WHERE variant_id=? AND stage='final' AND status='passed'",(variant_id,)).fetchone()
    if not passed or (row["synthetic"] and not synthetic_recipe):
        raise ValueError("N2 requires real passed N1; synthetic recipe cannot activate real paper")
    if not row["synthetic"] and not json.loads(passed[0])["promotable"]:
        raise ValueError("N1 is not promotable")
    session_id = uuid4().hex
    started = now_ms()
    state = initial_state(spec)
    if reference_binding is not None:
        from .procedure_references import validate_reference_start
        validate_reference_start(store,variant_id,reference_binding,started)
    paper_evidence.initialize(store)
    store.connection.execute('create table if not exists paper_reference_sessions '
        '(session_id text primary key,procedure_id text not null,period_index integer not null,role text not null,'
        'unique(procedure_id,period_index,role))')
    store.connection.execute('create table if not exists paper_session_policy '
        '(session_id text primary key,capital_policy text not null,restart_reason text)')
    store.connection.execute('create table if not exists paper_retirements '
        '(session_id text primary key,retired_ms integer not null,reason text not null)')
    store.connection.execute('create table if not exists paper_handovers '
        '(new_session_id text primary key,prior_session_id text not null unique,'
        'available_ms integer not null,policy_json text not null)')
    store.connection.commit()
    store.connection.execute('BEGIN IMMEDIATE')
    try:
        if reference_binding is None:
            existing = store.connection.execute("SELECT session_id FROM paper_sessions WHERE variant_id=? AND status='active' and session_id not in (select session_id from paper_reference_sessions)",(variant_id,)).fetchone()
        else:
            existing=store.connection.execute('select r.session_id from paper_reference_sessions r join paper_sessions s using(session_id) where procedure_id=? and period_index=? and role=?',
                (reference_binding['procedure_id'],reference_binding['period_index'],reference_binding['role'])).fetchone()
        if existing:
            store.connection.commit()
            return {"session_id":existing[0],"synthetic":bool(row["synthetic"])}
        priors=store.connection.execute(
            'select session_id,variant_id,status,state_json,started_ms from paper_sessions where network=? and address=? and coin=? and session_id not in (select session_id from paper_reference_sessions)',
            (row['network'],row['address'],row['coin'])).fetchall()
        if reference_binding is not None:priors=[]
        replacement=plan.get('paper_replacement') if reference_binding is None else None
        transferred=None
        capital_policy='independent_paper_session'
        capital_evidence=None
        for prior in priors:
            if replacement and prior['status']!='retired':
                from .paper_handover import eligible
                if transferred is not None or not eligible(replacement,prior,started):
                    raise ValueError('Predeclared replacement waits for a suspended flat predecessor and cooldown')
                if replacement.get('capital_policy')=='carry_flat_cash':
                    from .paper_handover import carry_flat_cash
                    carried,capital_evidence=carry_flat_cash(store,prior,started)
                    state.update(cash=carried,peak_equity=carried,session_starting_capital_usdc=carried)
                    capital_policy='carry_flat_cash'
                store.connection.execute('insert into paper_retirements values(?,?,?)',
                    (prior['session_id'],started,'predeclared replacement: '+replacement['justification']))
                store.connection.execute("update paper_sessions set status='retired',updated_at=? where session_id=?",
                    (utc_now(),prior['session_id']))
                transferred=prior['session_id']
                continue
            previous=json.loads(prior['state_json'])
            if prior['status']=='active' or number(previous['position'])!=0 or previous['pending']:
                raise ValueError('Paper handover requires retired flat prior sessions without pending orders')
            if prior['status']!='retired':
                raise ValueError('Explicit retirement required before paper replacement')
            if prior['variant_id']==variant_id and not (restart_reason and restart_reason.strip()):
                raise ValueError('Restart of a retired version requires an explicit reason')
        if replacement and transferred is None:
            raise ValueError('Predeclared replacement requires its suspended predecessor session')
        store.connection.execute("INSERT INTO paper_sessions VALUES (?,?,?,?,?,?,?,?,?,?)",(session_id,variant_id,row["network"],row["address"],row["coin"],canonical(state),"active",started,0,utc_now()))
        store.connection.execute('insert into paper_session_policy values(?,?,?)',
                                 (session_id,capital_policy,restart_reason))
        paper_evidence.record(store,session_id,started,0,state,
            metrics(state,spec,plan['criteria']['block_ms']))
        if reference_binding is not None:
            store.connection.execute('insert into paper_reference_sessions values(?,?,?,?)',
                (session_id,reference_binding['procedure_id'],reference_binding['period_index'],reference_binding['role']))
        if transferred:
            store.connection.execute('insert into paper_handovers values(?,?,?,?)',
                (session_id,transferred,started,canonical({**replacement,'capital_snapshot_id':capital_evidence,'opening_capital_usdc':state['cash']})))
        store.connection.commit()
    except BaseException:
        store.connection.rollback()
        raise
    if not row["synthetic"] and reference_binding is None:
        decision(store,row["network"],row["address"],row["coin"],"paper_active","N1 final passed by deterministic engine",{"interruptions":"suspend"},"paper_tick",{"session_id":session_id})
    return {"session_id":session_id,"synthetic":bool(row["synthetic"]),"started_ms":started,
            "capital_policy":capital_policy,"restart_reason":restart_reason}


def retire_paper(store: Store, session_id: str, *, reason: str) -> dict[str,Any]:
    """Retire only flat sessions; preserve state, ledger and version attribution."""
    if not reason.strip():raise ValueError('Explicit retirement reason required')
    store.connection.execute('create table if not exists paper_retirements '
        '(session_id text primary key,retired_ms integer not null,reason text not null)')
    store.connection.commit()
    store.connection.execute('BEGIN IMMEDIATE')
    try:
        session=store.connection.execute('select * from paper_sessions where session_id=?',(session_id,)).fetchone()
        if not session:raise ValueError('Unknown paper session')
        state=json.loads(session['state_json'])
        if number(state['position'])!=0 or state['pending']:
            raise ValueError('Open positions or pending orders remain attributed to the old session')
        if session['status']!='retired':
            store.connection.execute('insert into paper_retirements values(?,?,?)',(session_id,now_ms(),reason))
            store.connection.execute("update paper_sessions set status='retired',updated_at=? where session_id=?",(utc_now(),session_id))
        store.connection.commit()
    except BaseException:
        store.connection.rollback();raise
    return {'session_id':session_id,'status':'retired','ledger_preserved':True}


def paper_tick(store: Store, session_id: str) -> dict[str,Any]:
    session = store.connection.execute("SELECT * FROM paper_sessions WHERE session_id=?",(session_id,)).fetchone()
    if not session or session["status"] != "active":
        raise ValueError("Paper session unknown or suspended")
    row,spec,plan = get_variant(store,session["variant_id"])
    if row["synthetic"]:
        raise ValueError("Synthetic session must never consume a real archive")
    paper_evidence.initialize(store)
    store.connection.execute('create table if not exists paper_suspensions '
        '(session_id text primary key,suspended_ms integer not null,diagnostics_json text not null)')
    store.connection.commit()
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        session = store.connection.execute("SELECT * FROM paper_sessions WHERE session_id=?",(session_id,)).fetchone()
        if session["status"] != "active":
            raise ValueError("Paper session changed before the tick acquired its lock")
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
        if 'paper_monitoring' in plan:
            from .paper_monitor import diagnose
            state['diagnostics'].extend(diagnose(plan['paper_monitoring'],
                metrics(state,spec,plan['criteria']['block_ms'])))
        status = "suspended" if state["diagnostics"] else "active"
        if status == "suspended":
            store.connection.execute('insert into paper_suspensions values(?,?,?)',
                (session_id,now_ms(),canonical(state['diagnostics'])))
        store.connection.execute("UPDATE paper_sessions SET state_json=?,status=?,last_observation_id=?,updated_at=? WHERE session_id=?",(canonical(state),status,cursor,utc_now(),session_id))
        observed_metrics=metrics(state,spec,plan['criteria']['block_ms'])
        snapshot_ms=max(now_ms(),state['last_ms'])
        paper_evidence.record(store,session_id,snapshot_ms,cursor,state,observed_metrics)
        if status == 'suspended':
            from .paper_adaptation import record as record_adaptation
            record_adaptation(store,session_id,clock_ms=max(now_ms(),snapshot_ms))
        store.connection.commit()
    except Exception:
        store.connection.rollback()
        raise
    if status == "suspended":
        decision(store,row["network"],row["address"],row["coin"],"suspended","N2 deterministic monitoring stopped the session",{"requires_operator_review":True,"new_session_required":True},"inspect_paper_diagnostics",state["diagnostics"])
    return {"session_id":session_id,"status":status,"processed_events":len(events),"metrics":observed_metrics}


def synthetic_recipe_tick(store: Store, session_id: str, events: list[dict[str,Any]]) -> dict[str,Any]:
    """Exercise persistent N2 state with fixture events in a synthetic session.

    Not exposed as a real feed: this function explicitly rejects real variants.
    """
    session = store.connection.execute("SELECT * FROM paper_sessions WHERE session_id=?",(session_id,)).fetchone()
    if not session or session['status'] != 'active':
        raise ValueError("Recipe session unknown or inactive")
    row,spec,plan = get_variant(store,session["variant_id"])
    if not row["synthetic"]:
        raise ValueError("Fixture feed forbidden for real variants")
    paper_evidence.initialize(store)
    store.connection.commit()
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        session = store.connection.execute("SELECT * FROM paper_sessions WHERE session_id=?",(session_id,)).fetchone()
        if session['status'] != 'active':
            raise ValueError("Recipe session changed before the tick acquired its lock")
        state = json.loads(session["state_json"])
        for event in events:
            reduce_event(state,spec,event)
        store.connection.execute("UPDATE paper_sessions SET state_json=?,updated_at=? WHERE session_id=?",(canonical(state),utc_now(),session_id))
        observed_metrics=metrics(state,spec,plan['criteria']['block_ms'])
        paper_evidence.record(store,session_id,max(now_ms(),state['last_ms']),session['last_observation_id'],state,observed_metrics)
        store.connection.commit()
    except Exception:
        store.connection.rollback()
        raise
    return {"synthetic":True,"session_id":session_id,"metrics":observed_metrics}
