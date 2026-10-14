"""Bounded, public-only 67f7/ETH observation with durable, replayable reports."""
from __future__ import annotations

import bisect
import json
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .engine import canonical, fingerprint
from .population_local_join import _quote_values, _ms
from .providers.hyperliquid import HyperliquidInfo, MAX_PAGE_ROWS_BY_ENDPOINT
from .storage import Store, decode_observation_payload, utc_now
from .validation import now_ms

VERSION = "eth-public-observation-v1"
SOURCE = "hyperliquid-prospective-observation-v1"
POLL_INTERVAL_MS = 300_000
POLL_OVERLAP_MS = 60_000
PRIMARY_HORIZON_MS = 60_000
MAX_PREFILL_AGE_MS = 1_000
MAX_TARGET_OVERSHOOT_MS = 5_000
MAX_DECODED_QUOTES = 1_500_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS eth_observation_runs (
 protocol_id TEXT PRIMARY KEY, protocol_fingerprint TEXT NOT NULL, protocol_json TEXT NOT NULL,
 status TEXT NOT NULL, actual_started_ms INTEGER, finalised_ms INTEGER,
 last_poll_end_ms INTEGER, next_poll_ms INTEGER, diagnostic_json TEXT,
 created_ms INTEGER NOT NULL, updated_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS eth_observation_polls (
 poll_id TEXT PRIMARY KEY, protocol_id TEXT NOT NULL, start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
 status TEXT NOT NULL, requested_at TEXT NOT NULL, response_received_at TEXT,
 observation_id INTEGER, record_count INTEGER, complete INTEGER, error_code TEXT, error_detail TEXT,
 updated_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS eth_observation_reports (
 protocol_id TEXT NOT NULL, stage TEXT NOT NULL, input_fingerprint TEXT NOT NULL,
 report_json TEXT NOT NULL, created_ms INTEGER NOT NULL,
 PRIMARY KEY(protocol_id,stage));
CREATE TABLE IF NOT EXISTS eth_observation_routes (
 protocol_id TEXT NOT NULL, stage TEXT NOT NULL, route_json TEXT NOT NULL, updated_ms INTEGER NOT NULL,
 PRIMARY KEY(protocol_id,stage));
"""


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds")


def _to_ms(value: str) -> int:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def protocol_body(protocol: dict) -> dict:
    return {k: v for k, v in protocol.items() if k != "protocol_fingerprint"}


def validate_protocol(protocol: dict) -> None:
    if protocol.get("version") != VERSION or protocol.get("market") != "ETH":
        raise ValueError("This runner accepts only a versioned ETH public observation")
    if protocol.get("network") != "hyperliquid-mainnet" or protocol.get("address", "").lower() != "0x67f7aa8fb95c47e6ea9c517b623e0701cbf9d9ba":
        raise ValueError("Observation account scope does not match the sealed 67f7/ETH request")
    start, checkpoint, end = (protocol.get(k) for k in ("start_ms", "checkpoint_ms", "end_ms"))
    if any(type(x) is not int for x in (start, checkpoint, end)) or not start < checkpoint < end or end - start > 86_400_000:
        raise ValueError("Frozen observation must contain a 6-hour checkpoint and end within 24 hours")
    if protocol.get("poll_interval_ms") != POLL_INTERVAL_MS:
        raise ValueError("Poll cadence differs from the frozen low-rate protocol")
    if protocol.get("horizon_ms") != PRIMARY_HORIZON_MS or protocol.get("prefill_age_ms") != MAX_PREFILL_AGE_MS or protocol.get("target_overshoot_ms") != MAX_TARGET_OVERSHOOT_MS:
        raise ValueError("Frozen measurement thresholds differ from the pre-registered comparison")
    if protocol.get("protocol_fingerprint") and protocol["protocol_fingerprint"] != fingerprint(protocol_body(protocol)):
        raise ValueError("Frozen protocol fingerprint mismatch")


def init(store: Store, protocol: dict) -> str:
    validate_protocol(protocol)
    store.connection.executescript(SCHEMA)
    fp = fingerprint(protocol_body(protocol))
    row = store.connection.execute("select protocol_fingerprint,protocol_json from eth_observation_runs where protocol_id=?",
        (protocol["protocol_id"],)).fetchone()
    if row:
        if row["protocol_fingerprint"] != fp or json.loads(row["protocol_json"]) != protocol_body(protocol):
            raise ValueError("Existing observation ID is bound to another immutable protocol")
    else:
        now = now_ms()
        store.connection.execute("insert into eth_observation_runs values(?,?,?,'scheduled',NULL,NULL,NULL,?,NULL,?,?)",
            (protocol["protocol_id"], fp, canonical(protocol_body(protocol)), protocol["start_ms"], now, now))
        store.connection.commit()
    return fp


def _poll_id(protocol_id: str, start: int, end: int) -> str:
    return fingerprint({"protocol_id": protocol_id, "start_ms": start, "end_ms": end})


def _poll_fills(store: Store, protocol: dict, now: int, info=None) -> dict | None:
    run = store.connection.execute("select * from eth_observation_runs where protocol_id=?",
        (protocol["protocol_id"],)).fetchone()
    if run["finalised_ms"] is not None:
        return None
    is_final = now >= protocol["end_ms"]
    if not is_final and (run["next_poll_ms"] or protocol["start_ms"]) > now:
        return None
    last_end = run["last_poll_end_ms"]
    start = max(protocol["start_ms"], (last_end - POLL_OVERLAP_MS) if last_end else protocol["start_ms"])
    end = min(now, protocol["end_ms"])
    if end <= start:
        return None
    poll_id = _poll_id(protocol["protocol_id"], start, end)
    old = store.connection.execute("select * from eth_observation_polls where poll_id=?", (poll_id,)).fetchone()
    if old and old["status"] in ("complete", "saturated"):
        return {"status": "unchanged", "poll_id": poll_id, "observation_id": old["observation_id"]}
    requested = utc_now()
    store.connection.execute("insert or replace into eth_observation_polls "
        "(poll_id,protocol_id,start_ms,end_ms,status,requested_at,updated_ms) values(?,?,?,?, 'running',?,?)",
        (poll_id, protocol["protocol_id"], start, end, requested, now))
    store.connection.commit()
    payload = {"type": "userFillsByTime", "user": protocol["address"], "startTime": start, "endTime": end}
    request = {**payload, "observation_id": protocol["protocol_id"], "poll_id": poll_id,
        "collection_kind": "bounded_prospective_rest_page", "live_user_websocket": False}
    try:
        provider = info or HyperliquidInfo(protocol["network"])
        rows = provider.post_info(payload)
        received = utc_now()
        if not isinstance(rows, list):
            raise ValueError("userFillsByTime response is not a list")
        complete = len(rows) < MAX_PAGE_ROWS_BY_ENDPOINT["userFillsByTime"]
        inserted = store.save_observation(network=protocol["network"], source=SOURCE,
            entity_type="account", entity_id=protocol["address"].lower(), endpoint="userFillsByTime",
            payload=rows, request_payload=request, requested_at=requested,
            window_start_ms=start, window_end_ms=end, record_count=len(rows), complete=complete)
        obs = store.connection.execute("select observation_id,observed_at,response_sha256 from raw_observations "
            "where network=? and source=? and entity_type='account' and entity_id=? and endpoint=? "
            "and request_json=? order by observation_id desc limit 1",
            (protocol["network"], SOURCE, protocol["address"].lower(), "userFillsByTime", canonical(request))).fetchone()
        status = "complete" if complete else "saturated"
        store.connection.execute("update eth_observation_polls set status=?,response_received_at=?,observation_id=?,record_count=?,complete=?,updated_ms=? where poll_id=?",
            (status, received, obs["observation_id"], len(rows), int(complete), now_ms(), poll_id))
        store.connection.execute("update eth_observation_runs set last_poll_end_ms=max(coalesce(last_poll_end_ms,0),?),next_poll_ms=?,updated_ms=? where protocol_id=?",
            (end, end if is_final else min(protocol["end_ms"], now + POLL_INTERVAL_MS), now_ms(), protocol["protocol_id"]))
        store.connection.commit()
        return {"status": status, "poll_id": poll_id, "observation_id": obs["observation_id"],
            "response_sha256": obs["response_sha256"], "response_received_at": received,
            "archived_at": obs["observed_at"], "inserted": inserted, "records": len(rows)}
    except Exception as exc:
        store.connection.execute("update eth_observation_polls set status='error',error_code=?,error_detail=?,updated_ms=? where poll_id=?",
            (type(exc).__name__, str(exc)[:500], now_ms(), poll_id))
        store.connection.execute("update eth_observation_runs set diagnostic_json=?,next_poll_ms=?,updated_ms=? where protocol_id=?",
            (canonical({"stage": "fill_poll", "code": type(exc).__name__, "message": str(exc)[:500], "poll_id": poll_id}),
             min(protocol["end_ms"], now + POLL_INTERVAL_MS), now_ms(), protocol["protocol_id"]))
        store.connection.commit()
        return {"status": "error", "poll_id": poll_id, "code": type(exc).__name__, "message": str(exc)[:500]}


def _quotes(store: Store, protocol: dict, cutoff_ms: int):
    start_iso, end_iso = _iso(protocol["start_ms"]), _iso(cutoff_ms)
    rows = store.connection.execute("select * from raw_observations where network=? and source='hyperliquid-websocket-v1' "
        "and entity_type='market' and entity_id='ETH' and endpoint in ('bbo','l2Book') and observed_at>=? and observed_at<=? "
        "order by observed_at,observation_id", (protocol["network"], start_iso, end_iso))
    values, refs, rejects, events_by_channel = [], [], defaultdict(int), defaultdict(list)
    for row in rows:
        payload = decode_observation_payload(row)
        kind = row["endpoint"]
        received_lot = _to_ms(row["observed_at"])
        accepted, bad, count, batched = _quote_values(kind, payload, "ETH", lot_received_ms=received_lot, cutoff_ms=cutoff_ms)
        refs.append({"observation_id": row["observation_id"], "sha256": row["response_sha256"],
            "endpoint": kind, "archived_at": row["observed_at"], "frame_count": count, "batched": batched})
        for key, amount in bad.items(): rejects[key] += amount
        for q in accepted:
            data_frame = payload["events"][q["event_index"]] if batched else {"message": payload}
            message = data_frame.get("message", {})
            stream = message.get("_stream", {})
            item = {**q, "channel": kind, "received_ms": q["event_received_ms"], "archived_ms": received_lot,
                "connection_id": stream.get("connection_id"), "observation_id": row["observation_id"],
                "sha256": row["response_sha256"], "event_index": q["event_index"]}
            if item["event_ms"] < protocol["end_ms"]:
                values.append(item); events_by_channel[kind].append(item["received_ms"])
            if len(values) > MAX_DECODED_QUOTES:
                raise ValueError("decoded quote event bound exceeded")
    values.sort(key=lambda q: (q["event_ms"], q["received_ms"], 0 if q["channel"] == "bbo" else 1,
        q["observation_id"], q["event_index"]))
    manifest = {kind: {"event_count": len(events_by_channel[kind]),
        "max_received_gap_ms": max((b-a for a,b in zip(sorted(events_by_channel[kind]), sorted(events_by_channel[kind])[1:])), default=None),
        "received_first_ms": min(events_by_channel[kind], default=None), "received_last_ms": max(events_by_channel[kind], default=None)}
        for kind in ("bbo", "l2Book")}
    return values, {"quotes": manifest, "rejected_events": dict(sorted(rejects.items())),
        "source_refs": refs, "source_fingerprint": fingerprint(refs)}


def _fills(store: Store, protocol: dict, cutoff_ms: int):
    rows = store.connection.execute("select observation_id,observed_at,requested_at,request_json,record_count,complete,response_sha256,response_json,response_encoding "
        "from raw_observations where network=? and source=? and entity_type='account' and entity_id=? and endpoint='userFillsByTime' "
        "and observed_at>=? and observed_at<=? order by observed_at,observation_id",
        (protocol["network"], SOURCE, protocol["address"].lower(), _iso(protocol["start_ms"]), _iso(cutoff_ms))).fetchall()
    polls = {r["poll_id"]: r for r in store.connection.execute("select * from eth_observation_polls where protocol_id=?", (protocol["protocol_id"],))}
    by_tid, conflicts, page_refs = defaultdict(list), [], []
    for row in rows:
        request=json.loads(row["request_json"])
        page_refs.append({"observation_id": row["observation_id"], "sha256": row["response_sha256"],
            "requested_at": row["requested_at"], "archived_at": row["observed_at"],
            "record_count": row["record_count"], "complete": bool(row["complete"]),
            "poll_id": request.get("poll_id")})
        poll = polls.get(request.get("poll_id"))
        payload = decode_observation_payload(row)
        for fill in payload if isinstance(payload, list) else []:
            if not isinstance(fill, dict) or fill.get("coin") != "ETH" or not fill.get("tid"):
                continue
            if not protocol["start_ms"] <= int(fill.get("time", -1)) < min(cutoff_ms, protocol["end_ms"]):
                continue
            item = {**fill, "fill_page_observation_id": row["observation_id"],
                "fill_page_sha256": row["response_sha256"], "fill_page_requested_at": row["requested_at"],
                "fill_page_received_at": (poll["response_received_at"] if poll else None),
                "fill_page_archived_at": row["observed_at"], "poll_id": request.get("poll_id")}
            by_tid[str(fill["tid"])].append(item)
    fills = []
    for tid, variants in sorted(by_tid.items()):
        signatures = {canonical({k:v for k,v in v.items() if not k.startswith("fill_page_") and k!="poll_id"}) for v in variants}
        if len(signatures) > 1:
            conflicts.append({"tid": tid, "raw_refs": sorted({v["fill_page_observation_id"] for v in variants})})
            continue
        fills.append(min(variants, key=lambda x: (x["fill_page_received_at"] or x["fill_page_archived_at"], x["fill_page_observation_id"])))
    fills.sort(key=lambda f: (int(f["time"]), str(f["tid"])))
    return fills, {"pages": page_refs, "page_count": len(page_refs),
        "complete_page_count": sum(bool(r["complete"]) for r in page_refs),
        "incomplete_page_count": sum(not bool(r["complete"]) for r in page_refs),
        "unique_eth_fills": len(fills), "duplicate_fill_instances": sum(len(v)-1 for v in by_tid.values()),
        "conflicting_fill_ids": conflicts, "source_fingerprint": fingerprint(page_refs)}


def _action(fill):
    try:
        pre, qty = float(fill["startPosition"]), float(fill["sz"])
        signed = qty if fill["side"] == "B" else -qty if fill["side"] == "A" else None
        if signed is None or qty <= 0: return "unknown", None, None
        post = pre + signed
        if pre == 0 or pre * signed > 0: return "opens", 0.0, qty
        closing = min(abs(pre), qty); opening = qty - closing
        return ("inverts" if opening > 1e-12 else "reduces"), closing, opening
    except (KeyError, TypeError, ValueError):
        return "unknown", None, None


def _mid(q): return (float(q["bid"]) + float(q["ask"])) / 2


def _measure(fills, quotes, cutoff_ms):
    times = [q["event_ms"] for q in quotes]
    by_receive = sorted(quotes, key=lambda q: (q["received_ms"], q["archived_ms"], q["event_ms"], q["observation_id"]))
    receive_times = [q["received_ms"] for q in by_receive]
    rows=[]
    for fill in fills:
        t=int(fill["time"]); action,close_qty,open_qty=_action(fill)
        side=1 if fill.get("side")=="B" else -1 if fill.get("side")=="A" else 0
        item={"tid":str(fill["tid"]),"event_ms":t,"side":fill.get("side"),"crossed":fill.get("crossed"),
            "start_position":fill.get("startPosition"),"action":action,"close_quantity":close_qty,
            "open_quantity":open_qty,"size":fill.get("sz"),
            "price":fill.get("px"),"fee":fill.get("fee"),"fee_token":fill.get("feeToken"),
            "fill_page_observation_id":fill["fill_page_observation_id"],"fill_page_sha256":fill["fill_page_sha256"],
            "fill_page_received_at":fill["fill_page_received_at"],"fill_page_archived_at":fill["fill_page_archived_at"]}
        if fill.get("fill_page_received_at"):
            item["event_to_fill_page_receipt_ms"]=_to_ms(fill["fill_page_received_at"])-t
        prior_i=bisect.bisect_left(times,t)-1
        prior=quotes[prior_i] if prior_i>=0 else None
        if prior and t-prior["event_ms"] <= 30_000:
            mid=_mid(prior)
            item["prefill_quote"]={"event_ms":prior["event_ms"],"age_ms":t-prior["event_ms"],
                "bid":prior["bid"],"bid_size":prior["bid_size"],"ask":prior["ask"],"ask_size":prior["ask_size"],
                "channel":prior["channel"],"received_at":_iso(prior["received_ms"]),"archived_at":_iso(prior["archived_ms"]),
                "archived_before_fill_page_request":prior["archived_ms"]<=_to_ms(fill["fill_page_requested_at"]),
                "connection_id":prior["connection_id"],"ref":f"raw_observations:{prior['observation_id']}#sha256:{prior['sha256']}#{prior['event_index']}"}
            target=t+PRIMARY_HORIZON_MS
            future_i=bisect.bisect_left(times,target)
            future=quotes[future_i] if future_i<len(quotes) and quotes[future_i]["event_ms"]<=target+MAX_TARGET_OVERSHOOT_MS else None
            if future:
                item["event_time_markout_60s_bps"]=( _mid(future)-mid )/mid*10000*side if side else None
                item["future_quote"]={"event_ms":future["event_ms"],"overshoot_ms":future["event_ms"]-target,
                    "bid":future["bid"],"bid_size":future["bid_size"],"ask":future["ask"],"ask_size":future["ask_size"],
                    "channel":future["channel"],"received_at":_iso(future["received_ms"]),"archived_at":_iso(future["archived_ms"]),
                    "connection_id":future["connection_id"],"ref":f"raw_observations:{future['observation_id']}#sha256:{future['sha256']}#{future['event_index']}"}
            else:item["event_time_markout_60s_bps"]=None;item["future_quote"]=None
        else:
            item["prefill_quote"]=None;item["future_quote"]=None;item["event_time_markout_60s_bps"]=None
        # Complement: price movement remaining after the fill page was actually
        # received locally. This is explicitly a delayed REST-page observation.
        page_ms=_to_ms(fill["fill_page_received_at"]) if fill.get("fill_page_received_at") else None
        if page_ms is not None:
            base_i=bisect.bisect_right(receive_times,page_ms)-1
            base=by_receive[base_i] if base_i>=0 else None
            later_i=bisect.bisect_left(receive_times,page_ms+PRIMARY_HORIZON_MS)
            later=None
            while later_i<len(by_receive) and by_receive[later_i]["received_ms"]<=page_ms+PRIMARY_HORIZON_MS+MAX_TARGET_OVERSHOOT_MS:
                candidate=by_receive[later_i]
                if base and candidate["event_ms"]>base["event_ms"]:
                    later=candidate;break
                later_i+=1
            if base and later and side:
                base_mid=_mid(base)
                item["post_receipt_markout_60s_bps"]=(_mid(later)-base_mid)/base_mid*10000*side
                item["receipt_baseline_quote_ref"]=f"raw_observations:{base['observation_id']}#{base['event_index']}"
                item["receipt_future_quote_ref"]=f"raw_observations:{later['observation_id']}#{later['event_index']}"
                item["receipt_baseline_quote"]={"event_ms":base["event_ms"],"received_at":_iso(base["received_ms"]),"archived_at":_iso(base["archived_ms"]),
                    "bid":base["bid"],"bid_size":base["bid_size"],"ask":base["ask"],"ask_size":base["ask_size"],
                    "ref":f"raw_observations:{base['observation_id']}#sha256:{base['sha256']}#{base['event_index']}"}
                item["receipt_future_quote"]={"event_ms":later["event_ms"],"received_at":_iso(later["received_ms"]),"archived_at":_iso(later["archived_ms"]),
                    "bid":later["bid"],"bid_size":later["bid_size"],"ask":later["ask"],"ask_size":later["ask_size"],
                    "ref":f"raw_observations:{later['observation_id']}#sha256:{later['sha256']}#{later['event_index']}"}
                item["receipt_baseline_age_to_fill_ms"]=abs(page_ms-t)
                item["receipt_future_lag_ms"]=later["received_ms"]-(page_ms+PRIMARY_HORIZON_MS)
            else:item["post_receipt_markout_60s_bps"]=None;item["receipt_baseline_quote_ref"]=None;item["receipt_future_quote_ref"]=None;item["receipt_baseline_quote"]=None;item["receipt_future_quote"]=None
        else:
            item["post_receipt_markout_60s_bps"]=None;item["receipt_baseline_quote_ref"]=None;item["receipt_future_quote_ref"]=None;item["receipt_baseline_quote"]=None;item["receipt_future_quote"]=None
        rows.append(item)
    return rows


def _summarize(measured):
    def med(vals): return statistics.median(vals) if vals else None
    result={}
    for behavior, bval in (("taker",True),("maker",False),("unknown",None)):
        selected=[r for r in measured if r["crossed"] is bval]
        result[behavior]={}
        for action in ("opens","reduces","inverts","unknown"):
            group=[r for r in selected if r["action"]==action]
            primary=[r["event_time_markout_60s_bps"] for r in group if r["prefill_quote"] and r["prefill_quote"]["age_ms"]<=MAX_PREFILL_AGE_MS and r["event_time_markout_60s_bps"] is not None]
            receipt=[r["post_receipt_markout_60s_bps"] for r in group if r["post_receipt_markout_60s_bps"] is not None]
            prior=[r for r in group if r["prefill_quote"]]
            sensitivity={}
            for age in (100,1000,5000,30000):
                xs=[r["event_time_markout_60s_bps"] for r in group if r["prefill_quote"] and r["prefill_quote"]["age_ms"]<=age and r["event_time_markout_60s_bps"] is not None]
                sensitivity[str(age)]={"count":len(xs),"coverage_pct":round(100*len(xs)/len(group),2) if group else None,"median_bps":med(xs)}
            result[behavior][action]={"fills":len(group),"markout_60s_count":len(primary),
                "markout_60s_coverage_pct":round(100*len(primary)/len(group),2) if group else None,
                "directional_markout_60s_median_bps":med(primary),"freshness_sensitivity":sensitivity,
                "post_page_receipt_markout_60s_count":len(receipt),
                "post_page_receipt_markout_60s_median_bps":med(receipt),
                "prefill_quote_coverage_by_max_age":{str(age):sum(bool(r["prefill_quote"]) and r["prefill_quote"]["age_ms"]<=age for r in group) for age in (100,1000,5000,30000)},
                "observed_fees_by_token":_fee_sums(group),
                "size_sum":_sum_numeric(group,"size"),"close_quantity_sum":_sum_numeric(group,"close_quantity"),
                "open_quantity_sum":_sum_numeric(group,"open_quantity")}
    taker=result["taker"]
    red=taker["reduces"]["directional_markout_60s_median_bps"]
    opn=taker["opens"]["directional_markout_60s_median_bps"]
    red_n=taker["reduces"]["markout_60s_count"];open_n=taker["opens"]["markout_60s_count"]
    if not red_n or not open_n: decision="data_insufficient"
    elif red>0 and red>opn: decision="signal_exploratory_favorable"
    elif red<=0 and red<=opn: decision="signal_exploratory_unfavorable"
    else: decision="indeterminate"
    return result,decision


def _sum_numeric(rows,key):
    from decimal import Decimal, InvalidOperation
    values=[]
    for row in rows:
        try: values.append(Decimal(str(row.get(key))))
        except (InvalidOperation,TypeError): pass
    return str(sum(values,Decimal(0))) if values else "0"


def _fee_sums(rows):
    from decimal import Decimal, InvalidOperation
    sums=defaultdict(Decimal); missing=0
    for row in rows:
        if row.get("fee") is None: missing+=1; continue
        try:sums[str(row.get("fee_token") or "unknown")]+=Decimal(str(row["fee"]))
        except (InvalidOperation,TypeError):missing+=1
    return {"signed_amounts":{k:str(v) for k,v in sorted(sums.items())},"missing":missing}


def _report(store: Store, protocol: dict, stage: str, cutoff_ms: int):
    existing=store.connection.execute("select report_json from eth_observation_reports where protocol_id=? and stage=?",
        (protocol["protocol_id"],stage)).fetchone()
    if existing:return json.loads(existing[0]),"unchanged"
    fills,fillcov=_fills(store,protocol,cutoff_ms)
    quotes,quotecov=_quotes(store,protocol,cutoff_ms)
    poll_receipts={r["poll_id"]:r for r in store.connection.execute(
        "select poll_id,response_received_at from eth_observation_polls where protocol_id=?",(protocol["protocol_id"],))}
    for page in fillcov["pages"]:
        # Keep REST response receipt and SQLite archival availability distinct.
        response=poll_receipts.get(page.get("poll_id"))
        if response and response["response_received_at"]:
            page["response_received_at"] = response["response_received_at"]
            page["response_to_archive_ms"] = max(0,_to_ms(page["archived_at"])-_to_ms(page["response_received_at"]))
    measured=_measure(fills,quotes,cutoff_ms)
    summary,decision=_summarize(measured)
    quote_latency={}
    all_quotes=quotes
    for channel in ("bbo","l2Book"):
        group=[q for q in all_quotes if q["channel"]==channel]
        event_receive=[q["received_ms"]-q["event_ms"] for q in group]
        receive_archive=[q["archived_ms"]-q["received_ms"] for q in group]
        def quant(values,p):
            values=sorted(values)
            return values[min(len(values)-1,int((len(values)-1)*p))] if values else None
        quote_latency[channel]={"event_to_receive_ms":{"count":len(event_receive),"p50":quant(event_receive,.5),"p95":quant(event_receive,.95),"negative_count":sum(x<0 for x in event_receive)},
            "receive_to_archive_ms":{"count":len(receive_archive),"p50":quant(receive_archive,.5),"p95":quant(receive_archive,.95),"negative_count":sum(x<0 for x in receive_archive)}}
    health=[]
    health_rows=store.connection.execute("select observation_id,observed_at,response_sha256,response_json,response_encoding from raw_observations where network=? and source='hyperliquid-websocket-v1' and entity_type='stream' and endpoint='streamHealth' and observed_at>=? and observed_at<=? order by observation_id",
        (protocol["network"],_iso(protocol["start_ms"]),_iso(cutoff_ms))).fetchall()
    for row in health_rows:
        value=decode_observation_payload(row)
        health.append({"observation_id":row["observation_id"],"sha256":row["response_sha256"],"observed_at":row["observed_at"],
            "kind":value.get("kind"),"connected":value.get("connected"),"session":value.get("session"),"markets":value.get("markets",[])})
    telemetry=[]
    telemetry_path=store.path.with_suffix('.telemetry.sqlite3')
    if telemetry_path.exists():
        tc=sqlite3.connect(telemetry_path);tc.row_factory=sqlite3.Row
        has=tc.execute("select 1 from sqlite_master where type='table' and name='collector_measurements'").fetchone()
        if has:
            lo=protocol["start_ms"]/1000;hi=cutoff_ms/1000
            for row in tc.execute("select measurement_id,recorded_at,collector,metrics_json from collector_measurements where recorded_at>=? and recorded_at<=? and collector in ('websocket','websocket_error') order by measurement_id",(lo,hi)):
                metrics=json.loads(row["metrics_json"])
                telemetry.append({"ref":f"collector_measurements:{row['measurement_id']}","recorded_at":row["recorded_at"],
                    "collector":row["collector"],"session":metrics.get("session"),"frames":metrics.get("frames"),
                    "reconnections":metrics.get("reconnections"),"error_type":metrics.get("type"),
                    "acknowledged_bbo":metrics.get("acknowledged_bbo"),"max_flush_lag_seconds":metrics.get("max_flush_lag_seconds")})
        tc.close()
    poll_rows=[dict(r) for r in store.connection.execute("select poll_id,start_ms,end_ms,status,observation_id,record_count,complete,error_code,error_detail from eth_observation_polls where protocol_id=? order by start_ms,end_ms",(protocol["protocol_id"],))]
    source_bundle={"protocol_fingerprint":fingerprint(protocol_body(protocol)),"fills":fillcov["source_fingerprint"],
        "quotes":quotecov["source_fingerprint"],"polls":poll_rows,"health":health,"telemetry":telemetry,"cutoff_ms":cutoff_ms}
    input_fp=fingerprint(source_bundle)
    route={"decision":decision,"state":"observation_continues" if stage=="checkpoint_6h" else "review_required",
        "next_action":"continue to the frozen final deadline" if stage=="checkpoint_6h" else "human review of this exploratory result; no paper promotion",
        "paper_authorized":False,"model_calls":0,"collection_authorized":True if stage=="checkpoint_6h" else False}
    report={"schema_version":VERSION,"protocol_id":protocol["protocol_id"],"protocol_fingerprint":source_bundle["protocol_fingerprint"],
        "stage":stage,"planned_at_ms":protocol["checkpoint_ms"] if stage=="checkpoint_6h" else protocol["end_ms"],
        "generated_at_ms":now_ms(),"cutoff_ms":cutoff_ms,"input_fingerprint":input_fp,"decision":decision,
        "route":route,"coverage":{"fills":fillcov,"market":quotecov},"summary":summary,"fills":measured,
        "polls":poll_rows,"stream_health":health,"collector_telemetry":telemetry,"quote_latency_ms":quote_latency,
        "observation_start_ms":protocol["start_ms"],"observation_end_ms":protocol["end_ms"],
        "limits":["REST userFillsByTime pages are delayed account history, not live userFills WebSocket events.",
            "The account-level REST page can include other coins; only ETH fills enter this analysis and no other-market conclusion is drawn.",
            "Event, local receive, REST response receipt and SQLite archive clocks are retained separately and are not assumed synchronized.",
            "Event-time midpoint outcomes use a strict prior quote and future price only as an outcome; they do not define a historical signal.",
            "Post-page-receipt markout starts when our REST page arrived, not when the trader or venue first generated the fill.",
            "Fills are dependent and the 24-hour sample is short; medians are descriptive without confidence claims.",
            "Stream heartbeats and subscription acknowledgements are diagnostics only; quote events and their gaps determine observed market coverage.",
            "A favorable result is exploratory and never authorizes paper or live execution."]}
    encoded=canonical(report)
    store.connection.execute("insert or ignore into eth_observation_reports values(?,?,?,?,?)",
        (protocol["protocol_id"],stage,input_fp,encoded,now_ms()))
    report=json.loads(store.connection.execute("select report_json from eth_observation_reports where protocol_id=? and stage=?",
        (protocol["protocol_id"],stage)).fetchone()[0])
    store.connection.execute("insert or replace into eth_observation_routes values(?,?,?,?)",
        (protocol["protocol_id"],stage,canonical(route),now_ms()))
    store.connection.commit()
    return report,"prepared"


def _diagnostic_report(store: Store, protocol: dict, stage: str, exc: Exception):
    """Persist a terminally interpretable report if deterministic analysis fails."""
    old=store.connection.execute("select report_json from eth_observation_reports where protocol_id=? and stage=?",
        (protocol["protocol_id"],stage)).fetchone()
    if old:return json.loads(old[0]),"unchanged"
    diagnostic={"stage":"report_generation","code":type(exc).__name__,"message":str(exc)[:500]}
    route={"decision":"data_insufficient","state":"observation_continues" if stage=="checkpoint_6h" else "review_required",
        "next_action":"continue only to the frozen final deadline" if stage=="checkpoint_6h" else "human review of the diagnostic; no paper promotion",
        "paper_authorized":False,"model_calls":0,"collection_authorized":stage=="checkpoint_6h"}
    report={"schema_version":VERSION,"protocol_id":protocol["protocol_id"],
        "protocol_fingerprint":fingerprint(protocol_body(protocol)),"stage":stage,
        "planned_at_ms":protocol["checkpoint_ms"] if stage=="checkpoint_6h" else protocol["end_ms"],
        "generated_at_ms":now_ms(),"decision":"data_insufficient","route":route,
        "diagnostic":diagnostic,"coverage":"unknown because report generation failed",
        "limits":["No analytical coverage or result is inferred from the failed calculation.",
            "The frozen observation deadline remains in force; no extension or paper promotion is authorized."]}
    input_fp=fingerprint({"protocol":report["protocol_fingerprint"],"stage":stage,"diagnostic":diagnostic})
    report["input_fingerprint"]=input_fp
    store.connection.execute("insert or ignore into eth_observation_reports values(?,?,?,?,?)",
        (protocol["protocol_id"],stage,input_fp,canonical(report),now_ms()))
    store.connection.execute("insert or replace into eth_observation_routes values(?,?,?,?)",
        (protocol["protocol_id"],stage,canonical(route),now_ms()))
    store.connection.commit()
    return report,"diagnostic"


def tick(store: Store, protocol: dict, *, info=None, now: int | None = None) -> dict:
    now = now_ms() if now is None else now
    fp=init(store,protocol)
    # A killed/expired oneshot leaves a running poll. Preserve that failure as
    # an interruption; the next scheduled window remains separately identified.
    store.connection.execute("update eth_observation_polls set status='interrupted',error_code='worker_interrupted',"
        "error_detail='previous observer tick ended before persisting its response',updated_ms=? "
        "where protocol_id=? and status='running' and updated_ms<?",
        (now,protocol["protocol_id"],now-180_000))
    store.connection.commit()
    run=store.connection.execute("select * from eth_observation_runs where protocol_id=?",(protocol["protocol_id"],)).fetchone()
    if run["finalised_ms"] is not None:
        report,status=_report(store,protocol,"final_24h",protocol["end_ms"])
        return {"status":"finalised","poll":None,"report_status":status,"report":report}
    if now < protocol["start_ms"]:
        return {"status":"scheduled","next_due_ms":protocol["start_ms"],"protocol_fingerprint":fp}
    if run["actual_started_ms"] is None:
        store.connection.execute("update eth_observation_runs set status='observing',actual_started_ms=?,updated_ms=? where protocol_id=?",
            (now,now,protocol["protocol_id"]))
        store.connection.commit()
    poll=_poll_fills(store,protocol,now,info)
    if now>=protocol["end_ms"]:
        try:report,status=_report(store,protocol,"final_24h",now_ms())
        except Exception as exc:report,status=_diagnostic_report(store,protocol,"final_24h",exc)
        store.connection.execute("update eth_observation_runs set status='finalised',finalised_ms=?,updated_ms=? where protocol_id=?",
            (now_ms(),now_ms(),protocol["protocol_id"]))
        route=store.connection.execute("select route_json from eth_observation_routes where protocol_id=? and stage='final_24h'",(protocol["protocol_id"],)).fetchone()
        store.connection.commit()
        return {"status":"finalised","poll":poll,"report_status":status,"decision":report["decision"],"route":json.loads(route[0]) if route else None}
    stage=None
    if now>=protocol["checkpoint_ms"]:
        stage="checkpoint_6h"
    if stage:
        try:report,status=_report(store,protocol,stage,min(now,protocol["end_ms"]))
        except Exception as exc:report,status=_diagnostic_report(store,protocol,stage,exc)
        return {"status":"observing","poll":poll,"report_status":status,"decision":report["decision"],
            "next_due_ms":protocol["end_ms"]}
    return {"status":"observing","poll":poll,"next_due_ms":min(protocol["checkpoint_ms"],protocol["end_ms"])}


def load_protocol(path: Path) -> dict:
    protocol=json.loads(path.read_text(encoding="utf-8"));validate_protocol(protocol);return protocol

