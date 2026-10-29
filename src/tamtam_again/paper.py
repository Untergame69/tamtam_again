"""Causal archive adapter and persistent N2 paper reducer; no order API."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from time import monotonic_ns
from typing import Any
from uuid import uuid4

from .engine import canonical, fingerprint, initial_state, metrics, number, reduce_event, funding_coverage
from .storage import Store, decode_observation_payload, utc_now
from .validation import decision, get_variant, now_ms
from . import paper_evidence


def timestamp(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def archive_events(store: Store, network: str, address: str, coin: str, start_ms: int, end_ms: int,
                   *, after_observation_id: int = 0,
                   include_l2book: bool = False,
                   funding_witnesses: dict[str,Any] | None = None,
                   include_evidence_refs: bool = False,
                   query_metrics: dict[str, Any] | None = None) -> tuple[list[dict[str,Any]], int]:
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
    upper_observation_id=store.connection.execute("select coalesce(max(observation_id),0) from raw_observations").fetchone()[0]
    common+=" AND observation_id<=?"
    params = (network,after_observation_id,start,end,end,upper_observation_id)
    rows = []
    clause_metrics = {}
    # Incremental live paper ticks must seek by the INTEGER PRIMARY KEY cursor.
    # Historical window reads (cursor 0) rely on the existing time/entity
    # indexes; forcing a table scan there would make pipeline evaluations scan
    # the entire multi-gigabyte live archive.
    observation_source = "raw_observations NOT INDEXED" if after_observation_id > 0 else "raw_observations"
    clauses=[("bbo","entity_type='market' AND entity_id=? AND endpoint='bbo'",(coin,))]
    if include_l2book:
        clauses.append(("l2Book","entity_type='market' AND entity_id=? AND endpoint='l2Book'",(coin,)))
    clauses.extend([("account","entity_type='account' AND entity_id=? AND endpoint IN ('userFills','userFundings')",(address,)),
                    ("health","entity_type='stream' AND endpoint='streamHealth'",())])
    for name,clause,extra in clauses:
        query_started = monotonic_ns()
        # Historical single-entity windows must not scan every market sharing
        # the same endpoint. Keep the primary-key cursor seek for live ticks.
        source=("raw_observations INDEXED BY idx_observations_entity_time"
                if after_observation_id==0 and name!='health' else observation_source)
        batch = store.connection.execute('SELECT * FROM '+source+' WHERE '+common+' AND '+clause,params+extra).fetchall()
        clause_metrics[name] = {"query_ms": round((monotonic_ns()-query_started)/1_000_000, 3),
                                "rows": len(batch)}
        rows.extend(batch)
    if query_metrics is not None:
        query_metrics.update({"clauses": clause_metrics,
                              "query_ms": round(sum(x["query_ms"] for x in clause_metrics.values()), 3),
                              "rows": sum(x["rows"] for x in clause_metrics.values())})
    rows.sort(key=lambda row:row['observation_id'])
    events = []
    cursor = after_observation_id
    seen = set()
    for row in rows:
        row_event_start=len(events)
        cursor = max(cursor,int(row["observation_id"]))
        archived_available = timestamp(row["observed_at"])
        if archived_available >= end_ms:
            continue
        if row["endpoint"]=="userFundings":
            from .population_local_join import _decode_verified
            payload=_decode_verified(row,max_decoded_bytes=2_000_000)
            data=payload.get("data",{}) if isinstance(payload,dict) else {}
            if (not isinstance(payload,dict) or payload.get("channel")!="userFundings"
                    or not isinstance(data,dict) or not isinstance(data.get("user"),str)
                    or data["user"].lower()!=address.lower()):
                raise ValueError("Primary funding envelope sender/channel mismatch")
        else:
            payload = decode_observation_payload(row)
        request = json.loads(row["request_json"])
        if row["endpoint"] == "streamHealth":
            receipt = timestamp(row["requested_at"])
            if start_ms <= receipt < end_ms:
                events.append({"id":f"health:{row['observation_id']}","received_ms":receipt,"event_ms":receipt,"available_ms":max(receipt,archived_available),**payload})
                if include_evidence_refs:
                    events[-1].update(evidence_ref=f"raw_observations:{row['observation_id']}",
                        archive_event_index=0,archive_available_ms=archived_available,
                        archive_response_sha256=row['response_sha256'])
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
                if not include_l2book and (exchange < start_ms or exchange > receipt):
                    continue
                event = {"kind":"bbo","event_ms":receipt if include_l2book else exchange,
                         "source_event_ms":exchange,"received_ms":receipt,"available_ms":max(receipt,archived_available),"session":session,
                         "source":"bbo","bid":bbo[0]["px"],"ask":bbo[1]["px"],"bid_size":bbo[0]["sz"],"ask_size":bbo[1]["sz"]}
                event["id"] = fingerprint(event)
                events.append(event)
            elif row["endpoint"] == "l2Book":
                levels=data.get('levels',[])
                if data.get('coin')!=coin or len(levels)!=2 or not levels[0] or not levels[1]:
                    continue
                bid,ask=levels[0][0],levels[1][0]
                exchange=int(data.get('time',0))
                if exchange<=0:
                    continue
                event={"kind":"l2book","event_ms":receipt,"source_event_ms":exchange,"received_ms":receipt,
                    "available_ms":max(receipt,archived_available),"session":session,"source":"l2Book",
                    "bid":bid['px'],"ask":ask['px'],'bid_size':bid['sz'],'ask_size':ask['sz']}
                event['id']=fingerprint(event)
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
                for funding_index,funding in enumerate(data.get("fundings",[])):
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
                        events.append({"id":(f"funding:{coin}:{exchange}:{row['observation_id']}:{funding_index}"
                                                if funding_witnesses is not None else f"funding:{coin}:{exchange}"),"kind":"funding","received_ms":receipt,
                                       "available_ms":max(receipt,archived_available),"event_ms":exchange,
                                       "unit_funding_usdc":str(unit),"provenance":"settled_user_funding_usdc_divided_by_signed_szi"})
        if include_evidence_refs:
            for index,event in enumerate(events[row_event_start:]):
                event.update(evidence_ref=f"raw_observations:{row['observation_id']}",
                    archive_event_index=index,archive_available_ms=archived_available,
                    archive_response_sha256=row['response_sha256'])
    if funding_witnesses is not None:
        from .funding_witnesses import archive_funding_events
        witness_events,witness_cursor=archive_funding_events(store,funding_witnesses,
            network=network,address=address,market=coin,start_ms=start_ms,end_ms=end_ms,
            after_observation_id=after_observation_id,through_observation_id=upper_observation_id)
        events.extend(witness_events);cursor=max(cursor,witness_cursor)
    return sorted(events,key=lambda e:(e.get("available_ms",e["received_ms"]),e["received_ms"],str(e["id"]))),cursor


def classify_regimes(events: list[dict[str,Any]], criteria: dict[str,Any]) -> list[dict[str,Any]]:
    """Causal trend/quiet proxy, explicitly not an exhaustive regime taxonomy."""
    threshold = number(criteria["regime_threshold_bps"])
    window = criteria["regime_window_ms"]
    from collections import deque
    history = deque()
    result = list(events)
    for e in sorted(events,key=lambda x:(x["received_ms"],str(x["id"]))):
        if e["kind"] != "bbo":
            continue
        mid = (number(e["bid"])+number(e["ask"]))/2
        cutoff=e['received_ms']-window
        while len(history)>1 and history[1][0]<=cutoff:
            history.popleft()
        prior=history[0] if history and history[0][0]<=cutoff else None
        if prior:
            change = (mid/prior[1]-1)*10000
            label = "up" if change > threshold else "down" if change < -threshold else "quiet"
            result.append({"id":"regime:"+e["id"],"kind":"regime","event_ms":e["event_ms"],"received_ms":e["received_ms"],"available_ms":e.get("available_ms",e["received_ms"]),"label":label})
        history.append((e["received_ms"],mid))
    return sorted(result,key=lambda e:(e.get("available_ms",e["received_ms"]),e["received_ms"],str(e["id"])))


def start_paper(store: Store, variant_id: str, *, synthetic_recipe: bool = False,
                restart_reason: str | None = None, reference_binding: dict | None = None,
                experimental_hypothesis: dict | None = None,
                independent_after_incomplete: bool = False,
                runtime_state: dict[str,Any] | None = None) -> dict[str,Any]:
    row,spec,plan = get_variant(store,variant_id)
    if 'funding_sensitivity_scenario' in spec['execution']:
        raise ValueError('Funding sensitivity evidence cannot authorize any paper session')
    if experimental_hypothesis is None:
        passed = store.connection.execute("SELECT result_json FROM validation_evaluations WHERE variant_id=? AND stage='final' AND status='passed'",(variant_id,)).fetchone()
        if not passed or (row["synthetic"] and not synthetic_recipe):
            raise ValueError("N2 requires real passed N1; synthetic recipe cannot activate real paper")
        if not row["synthetic"] and not json.loads(passed[0])["promotable"]:
            raise ValueError("N1 is not promotable")
    else:
        from .experimental_paper import initialize as initialize_experimental, validate_start
        validate_start(store,variant_id,experimental_hypothesis,runtime_state=runtime_state)
        initialize_experimental(store)
    if independent_after_incomplete and (experimental_hypothesis is None or reference_binding is not None
            or not restart_reason or not restart_reason.strip()):
        raise ValueError('Independent-after-incomplete restart requires an experimental version and explicit reason')
    # Start after the current archive watermark so the first tick scans only
    # newly received observations. Observation IDs are the incremental cursor.
    observation_cursor = store.connection.execute(
        "SELECT coalesce(max(observation_id),0) FROM raw_observations WHERE network=?", (row["network"],)
    ).fetchone()[0]
    session_id = uuid4().hex
    started = now_ms()
    state = initial_state(spec)
    if 'funding_observation_interval_ms' in spec['execution']:
        state['paper_funding_started_ms']=started
    if experimental_hypothesis is not None:
        # A collector restart may be needed to load the experiment's prioritized
        # account subscription. Until the first live signal there is no paper
        # position or decision whose stream continuity can be broken.
        state["experimental_initial_feed"] = True
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
        if independent_after_incomplete and replacement:
            raise ValueError('Independent-after-incomplete start cannot use portfolio replacement or handover')
        transferred=None
        capital_policy='independent_paper_session'
        capital_evidence=None
        used_incomplete_predecessor=False
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
            if independent_after_incomplete and prior['status']!='active' \
                    and number(previous['position'])!=0 and not previous['pending']:
                disposition_table=store.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='paper_experimental_dispositions'").fetchone()
                disposition_row=store.connection.execute(
                    "SELECT disposition_json FROM paper_experimental_dispositions WHERE session_id=? "
                    "ORDER BY created_at DESC LIMIT 1",(prior['session_id'],)
                ).fetchone() if disposition_table else None
                disposition=json.loads(disposition_row['disposition_json']) if disposition_row else {}
                if (prior['status']!='suspended' or disposition.get('status')!='administratively_incomplete'
                        or disposition.get('residual_position')!=str(previous['position'])
                        or disposition.get('final_round_trip_result')!='unknown'):
                    raise ValueError('Nonflat predecessor requires a matching immutable incomplete disposition')
                used_incomplete_predecessor=True
                capital_policy='independent_paper_after_incomplete'
                continue
            if prior['status']=='active' or number(previous['position'])!=0 or previous['pending']:
                raise ValueError('Paper handover requires retired flat prior sessions without pending orders')
            if prior['status']!='retired':
                raise ValueError('Explicit retirement required before paper replacement')
            if prior['variant_id']==variant_id and not (restart_reason and restart_reason.strip()):
                raise ValueError('Restart of a retired version requires an explicit reason')
        if replacement and transferred is None:
            raise ValueError('Predeclared replacement requires its suspended predecessor session')
        if independent_after_incomplete and not used_incomplete_predecessor:
            raise ValueError('No administratively incomplete predecessor was found for this independent start')
        store.connection.execute("INSERT INTO paper_sessions VALUES (?,?,?,?,?,?,?,?,?,?)",(session_id,variant_id,row["network"],row["address"],row["coin"],canonical(state),"active",started,observation_cursor,utc_now()))
        store.connection.execute('insert into paper_session_policy values(?,?,?)',
                                 (session_id,capital_policy,restart_reason))
        paper_evidence.record(store,session_id,started,observation_cursor,state,
            metrics(state,spec,plan['criteria']['block_ms']))
        if reference_binding is not None:
            store.connection.execute('insert into paper_reference_sessions values(?,?,?,?)',
                (session_id,reference_binding['procedure_id'],reference_binding['period_index'],reference_binding['role']))
        if transferred:
            store.connection.execute('insert into paper_handovers values(?,?,?,?)',
                (session_id,transferred,started,canonical({**replacement,'capital_snapshot_id':capital_evidence,'opening_capital_usdc':state['cash']})))
        if experimental_hypothesis is not None:
            from .engine import fingerprint
            store.connection.execute('insert into paper_experimental_sessions '
                '(session_id,hypothesis_id,hypothesis_json,frozen_fingerprint,review_interval_ms,max_duration_ms,'
                'next_review_ms,review_index,status,created_ms,loss_limit_usdc) '
                'values(?,?,?,?,?,?,?,0,\'active\',?,?)',
                (session_id,experimental_hypothesis['hypothesis_id'],canonical(experimental_hypothesis),
                 fingerprint({'spec':spec,'criteria':row['criteria_json']}),
                 experimental_hypothesis['review_interval_ms'],experimental_hypothesis['max_duration_ms'],
                 started+experimental_hypothesis['review_interval_ms'],started,
                 str(spec['max_exposure']['max_drawdown_usdc'])))
        store.connection.commit()
    except BaseException:
        store.connection.rollback()
        raise
    if not row["synthetic"] and reference_binding is None and experimental_hypothesis is None:
        decision(store,row["network"],row["address"],row["coin"],"paper_active","N1 final passed by deterministic engine",{"interruptions":"suspend"},"paper_tick",{"session_id":session_id})
    elif experimental_hypothesis is not None:
        decision(store,row["network"],row["address"],row["coin"],"experimental_paper",
                 "Frozen prospective paper experiment; no N1 evaluation or economic promotion",
                 {"next_review_ms":started+experimental_hypothesis['review_interval_ms']},
                 "paper_experimental_review",{"session_id":session_id,
                 "hypothesis_id":experimental_hypothesis['hypothesis_id']})
    return {"session_id":session_id,"synthetic":bool(row["synthetic"]),"started_ms":started,
            "capital_policy":capital_policy,"restart_reason":restart_reason,
            "experiment_status":"experimental_paper" if experimental_hypothesis is not None else None,
            "economic_validation":False if experimental_hypothesis is not None else None}


def retire_paper(store: Store, session_id: str, *, reason: str,
                 cancel_pending: bool = False) -> dict[str,Any]:
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
        if number(state['position'])!=0:
            raise ValueError('Open position remains attributed to the old session')
        pending=list(state['pending'])
        if pending and not cancel_pending:
            raise ValueError('Pending orders require explicit cancellation before retirement')
        if pending:
            cancelled=state.setdefault('retirement_cancellations',[])
            cancelled.extend({'at_ms':now_ms(),'order':order,'reason':reason.strip()} for order in pending)
            reasons=state.setdefault('nonexecution_reasons',{})
            reasons['pending_cancelled_for_version_retirement']=reasons.get('pending_cancelled_for_version_retirement',0)+len(pending)
            state['pending']=[]
            store.connection.execute('update paper_sessions set state_json=? where session_id=?',
                                     (canonical(state),session_id))
        if session['status']!='retired':
            store.connection.execute('insert into paper_retirements values(?,?,?)',(session_id,now_ms(),reason))
            store.connection.execute("update paper_sessions set status='retired',updated_at=?,state_json=? where session_id=?",(utc_now(),canonical(state),session_id))
        if store.connection.execute("select 1 from sqlite_master where type='table' and name='paper_experimental_sessions'").fetchone():
            store.connection.execute("update paper_experimental_sessions set status='retired' where session_id=?",(session_id,))
        store.connection.commit()
    except BaseException:
        store.connection.rollback();raise
    return {'session_id':session_id,'status':'retired','ledger_preserved':True,
            'cancelled_pending_orders':len(pending) if 'pending' in locals() else 0}


def monitored_metrics(state,spec,block_ms,*,start_ms=None,end_ms=None):
    """Observed ledger components never stand in for complete funding costs."""
    result=metrics(state,spec,block_ms)
    if 'funding_observation_interval_ms' not in spec['execution']:
        return result
    window=({'start_ms':start_ms,'end_ms':max(start_ms+1,end_ms+1)}
            if start_ms is not None and end_ms is not None else state.get('funding_observation_window'))
    coverage=funding_coverage(state,spec,window)
    result['funding_coverage']=coverage
    result['economic_result_complete']=coverage['state']=='complete'
    if not result['economic_result_complete']:
        result['net_pnl_observed_components']=result['net_pnl']
        result['net_pnl']=None
    return result


def _persist_monitored_tick(store,session,state,spec,plan,cursor,clock_ms,*,runtime_metrics=None):
    """Caller owns transaction; identical safety decisions for live and fixture feeds."""
    healthy=state['healthy_at_ms']
    if clock_ms-session['started_ms']>plan['budget']['max_duration_ms']:
        state['diagnostics'].append('paper_duration_budget_exhausted')
    experimental = store.connection.execute(
        "SELECT 1 FROM paper_experimental_sessions WHERE session_id=?",(session['session_id'],)
    ).fetchone() if store.connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_experimental_sessions'"
    ).fetchone() else None
    unhealthy = healthy is None or clock_ms-healthy>spec['execution']['heartbeat_timeout_ms']
    if unhealthy and experimental and clock_ms-session['started_ms']<=180_000:
        state['wait_conditions']=['awaiting_initial_live_websocket_heartbeat']
    elif unhealthy:
        state['wait_conditions']=[]
        state['diagnostics'].append('missing_live_heartbeat')
    else:
        state['wait_conditions']=[]
    state['funding_observation_window']={'start_ms':session['started_ms'],'end_ms':max(session['started_ms']+1,clock_ms+1)}
    observed_metrics=monitored_metrics(state,spec,plan['criteria']['block_ms'])
    if 'funding_coverage' in observed_metrics:
        state['funding_coverage']=observed_metrics['funding_coverage']
    if observed_metrics.get('economic_result_complete') is False:
        state['wait_conditions'].append('awaiting_observed_funding_settlements')
        state['funding_cost_status']='pending'
        if clock_ms-session['started_ms']>plan['budget']['max_duration_ms']:
            state['diagnostics'].append('funding_cost_unobserved_at_paper_budget_end')
    elif 'funding_coverage' in observed_metrics:
        state['funding_cost_status']='complete'
    if runtime_metrics is not None:
        state['paper_runtime']=dict(runtime_metrics)
    if 'paper_monitoring' in plan:
        from .paper_monitor import diagnose
        state['diagnostics'].extend(diagnose(plan['paper_monitoring'],observed_metrics))
        observed_metrics=monitored_metrics(state,spec,plan['criteria']['block_ms'])
    status='suspended' if state['diagnostics'] else 'active'
    if status=='suspended':
        store.connection.execute('insert into paper_suspensions values(?,?,?)',
            (session['session_id'],clock_ms,canonical(state['diagnostics'])))
    store.connection.execute('UPDATE paper_sessions SET state_json=?,status=?,last_observation_id=?,updated_at=? WHERE session_id=?',
        (canonical(state),status,cursor,utc_now(),session['session_id']))
    snapshot_ms=max(clock_ms,state['last_ms'])
    paper_evidence.record(store,session['session_id'],snapshot_ms,cursor,state,observed_metrics)
    if status=='suspended' and not experimental:
        from .paper_adaptation import record
        record(store,session['session_id'],clock_ms=snapshot_ms)
    return status,observed_metrics


def paper_tick(store: Store, session_id: str) -> dict[str,Any]:
    tick_started_ms=now_ms()
    tick_started_ns=monotonic_ns()
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
        if "funding_observation_interval_ms" in spec["execution"]:
            state["paper_funding_started_ms"]=session["started_ms"]
        archive_profile={}
        events,cursor = archive_events(store,row["network"],row["address"],row["coin"],session["started_ms"],now_ms(),
            after_observation_id=session["last_observation_id"],
            include_l2book=spec['execution'].get('quote_evidence_contract')=='bbo_or_l2book_v1',
            funding_witnesses=spec['execution'].get('funding_witnesses'),
            query_metrics=archive_profile)
        processed_ms = now_ms()
        max_receipt_lag_ms=max((max(0,processed_ms-int(event['received_ms'])) for event in events),default=0)
        for event in events:
            event["available_ms"] = max(processed_ms,state["last_ms"],event.get("available_ms",event["received_ms"]))
            reduce_event(state,spec,event)
        clock_ms = now_ms()
        reduce_event(state,spec,{"id":f"n2-timer:{clock_ms}","kind":"timer","received_ms":clock_ms,"event_ms":clock_ms})
        previous_runtime=state.get('paper_runtime',{})
        interval_ms=(max(0,tick_started_ms-int(previous_runtime['started_ms']))
                     if previous_runtime.get('started_ms') is not None else None)
        processing_ms=round((monotonic_ns()-tick_started_ns)/1_000_000,3)
        max_interval=max(int(previous_runtime.get('max_interval_ms',0)),int(interval_ms or 0))
        max_processing=max(float(previous_runtime.get('max_processing_ms',0)),processing_ms)
        max_receipt_lag=max(int(previous_runtime.get('max_receipt_lag_ms',0)),max_receipt_lag_ms)
        runtime_metrics={"target_interval_ms":int(spec['execution'].get('paper_tick_target_ms',5000)),
                         "started_ms":tick_started_ms,
                         "interval_ms":interval_ms,
                         "max_interval_ms":max_interval,
                         "archive_query_ms":archive_profile.get('query_ms',0),
                         "max_archive_query_ms":max(float(previous_runtime.get('max_archive_query_ms',0)),float(archive_profile.get('query_ms',0))),
                         "archive_rows":archive_profile.get('rows',0),
                         "archive_by_kind":archive_profile.get('clauses',{}),
                         "events_processed":len(events),
                         "max_receipt_lag_ms":max_receipt_lag_ms,
                         "max_receipt_lag_ms_since_start":max_receipt_lag,
                         "processing_ms":processing_ms,
                         "max_processing_ms":max_processing,
                         "finished_ms":clock_ms}
        status,observed_metrics = _persist_monitored_tick(store,session,state,spec,plan,cursor,clock_ms,
                                                          runtime_metrics=runtime_metrics)
        store.connection.commit()
    except Exception:
        store.connection.rollback()
        raise
    if status == "suspended":
        decision(store,row["network"],row["address"],row["coin"],"suspended","N2 deterministic monitoring stopped the session",{"requires_operator_review":True,"new_session_required":True},"inspect_paper_diagnostics",state["diagnostics"])
    result={"session_id":session_id,"status":status,"processed_events":len(events),"metrics":observed_metrics}
    if status=='active' and state.get('wait_conditions'):
        result['waiting_for']=state['wait_conditions']
    return result


def synthetic_recipe_tick(store: Store, session_id: str, events: list[dict[str,Any]], *, clock_ms: int | None = None) -> dict[str,Any]:
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
    store.connection.execute('create table if not exists paper_suspensions '
        '(session_id text primary key,suspended_ms integer not null,diagnostics_json text not null)')
    store.connection.commit()
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        session = store.connection.execute("SELECT * FROM paper_sessions WHERE session_id=?",(session_id,)).fetchone()
        if session['status'] != 'active':
            raise ValueError("Recipe session changed before the tick acquired its lock")
        state = json.loads(session["state_json"])
        for event in events:
            reduce_event(state,spec,event)
        tick_ms=state['last_ms'] if clock_ms is None else clock_ms
        if type(tick_ms) is not int or tick_ms<state['last_ms']:
            raise ValueError('Fixture clock must follow all available events')
        reduce_event(state,spec,{'id':f'n2-timer:{tick_ms}','kind':'timer','received_ms':tick_ms,'event_ms':tick_ms})
        status,observed_metrics=_persist_monitored_tick(store,session,state,spec,plan,session['last_observation_id'],tick_ms)
        store.connection.commit()
    except Exception:
        store.connection.rollback()
        raise
    return {"synthetic":True,"session_id":session_id,"status":status,"metrics":observed_metrics}
