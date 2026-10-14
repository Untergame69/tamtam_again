"""Exploratory ETH fill economics and strictly forward BBO consequences.

All market features used for execution comparison are strict event-time
predecessors. Forward midpoints are outcome measurements only.
"""
from __future__ import annotations

import bisect
import gzip
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from .engine import canonical, fingerprint
from .population_descriptive import _load_fills, _load_funding, _position_flows
from .research_memory import authorized_account_history
from .population_local_join import _decode_verified as _decode_market, _quote_values, _source_specs, _ms
from .validation import now_ms

VERSION = "population-eth-execution-contribution-v1"
ADDRESS = "0x67f7aa8fb95c47e6ea9c517b623e0701cbf9d9ba"
MARKET = "ETH"
NETWORK = "hyperliquid-mainnet"
HORIZONS_MS = (1_000, 60_000, 300_000, 900_000)
FRESHNESS_MS = (100, 1_000, 5_000, 30_000, 300_000)
ARTIFACT_PATH = "docs/continuous-research/POPULATION-67F7-ETH-EXECUTION-CONTRIBUTION-20261014-v1.json.gz"


def _d(v):
    return Decimal(str(v))


def _mid(q):
    return (_d(q["bid"]) + _d(q["ask"])) / 2


def _side_sign(side):
    return Decimal(1) if side == "B" else Decimal(-1)


def persist_artifact(connection, request_id, base_join_fingerprint, artifact):
    """Idempotently store the immutable versioned result under its sealed base."""
    connection.execute("create table if not exists population_eth_execution_contributions (request_id text not null, analysis_version text not null, base_join_fingerprint text not null, analysis_fingerprint text not null, artifact_json text not null, created_ms integer not null, primary key(request_id,analysis_version,base_join_fingerprint))")
    row=connection.execute("select analysis_fingerprint,artifact_json from population_eth_execution_contributions where request_id=? and analysis_version=? and base_join_fingerprint=?",
        (request_id,VERSION,base_join_fingerprint)).fetchone()
    if row:return "unchanged",row["analysis_fingerprint"],json.loads(row["artifact_json"])
    encoded=canonical(artifact)
    connection.execute("insert into population_eth_execution_contributions values(?,?,?,?,?,?)",
        (request_id,VERSION,base_join_fingerprint,artifact["analysis_fingerprint"],encoded,now_ms()))
    connection.commit()
    return "prepared",artifact["analysis_fingerprint"],artifact


def _link_job_result(store, request_id, result, artifact):
    ref={"version":VERSION,"state":"completed","analysis_fingerprint":artifact["analysis_fingerprint"],
        "base_join_fingerprint":artifact["base_join_fingerprint"],"artifact_path":ARTIFACT_PATH,
        "model_calls":0,"collection_started":False}
    if result.get("local_eth_execution_contribution")!=ref:
        result["local_eth_execution_contribution"]=ref
        store.connection.execute("update population_research_jobs set result_json=?,updated_ms=? where request_id=? and status='needs_data'",
            (canonical(result),now_ms(),request_id));store.connection.commit()
    return ref


def _effect(fill):
    pre = _d(fill["startPosition"])
    qty = _d(fill["sz"])
    signed = qty if fill["side"] == "B" else -qty
    post = pre + signed
    if pre == 0 or pre * signed >= 0:
        return "opens", Decimal(0), qty
    close = min(abs(pre), qty)
    opened = qty - close
    return ("inverts" if opened > 0 else "reduces"), close, opened


def measure_fill_consequences(fills, quotes, *, horizons_ms=HORIZONS_MS):
    """Pure computation. Quotes are (event_ms, bid, ask, ref) rows."""
    quotes = sorted(quotes, key=lambda q: q[0])
    times = [q[0] for q in quotes]
    rows = []
    for fill in fills:
        t = int(fill["time"])
        i = bisect.bisect_left(times, t) - 1
        prior = quotes[i] if i >= 0 else None
        action, close_qty, open_qty = _effect(fill)
        row = {"tid": str(fill["tid"]), "time_ms": t, "segment": fill.get("segment"),
               "utc_day": fill.get("utc_day"), "crossed": fill.get("crossed"), "action": action,
               "close_quantity": str(close_qty), "open_quantity": str(open_qty),
               "fill_side": fill["side"], "fill_price": str(fill["px"]), "fill_quantity": str(fill["sz"]),
               "observed_fee": fill.get("fee"), "fee_token": fill.get("feeToken")}
        if prior:
            age = t-prior[0]
            mid = _mid({"bid": prior[1], "ask": prior[2]})
            px = _d(fill["px"])
            signed_shortfall = _side_sign(fill["side"])*(px-mid)
            row["strict_prior_quote"] = {"event_ms": prior[0], "age_ms": age, "ref": prior[3]}
            row["prior_mid"] = str(mid)
            row["execution_vs_mid_bps_signed_cost"] = str(signed_shortfall/mid*Decimal(10000))
            row["execution_vs_mid_usd_signed_cost"] = str(signed_shortfall*_d(fill["sz"]))
        else:
            row["strict_prior_quote"] = None
            row["prior_mid"] = None
            row["execution_vs_mid_bps_signed_cost"] = None
            row["execution_vs_mid_usd_signed_cost"] = None
        future = {}
        for h in horizons_ms:
            target = t + int(h)
            j = bisect.bisect_left(times, target)
            while j < len(times) and times[j] <= t:
                j += 1
            if j >= len(times):
                future[str(h)] = None
                continue
            q = quotes[j]
            future_mid = _mid({"bid": q[1], "ask": q[2]})
            if prior:
                delta_bps = (future_mid-_mid({"bid": prior[1], "ask": prior[2]}))/_mid({"bid": prior[1], "ask": prior[2]})*Decimal(10000)
                future[str(h)] = {"quote_event_ms": q[0], "target_overshoot_ms": q[0]-target,
                    "quote_ref": q[3], "mid": str(future_mid), "mid_change_bps": str(delta_bps),
                    "direction_adjusted_mid_change_bps": str(delta_bps*_side_sign(fill["side"]))}
            else:
                future[str(h)] = {"quote_event_ms": q[0], "target_overshoot_ms": q[0]-target,
                    "quote_ref": q[3], "mid": str(future_mid), "mid_change_bps": None,
                    "direction_adjusted_mid_change_bps": None}
        row["future_midpoints_outcome_only"] = future
        rows.append(row)
    return rows


def summarize_consequences(rows):
    groups = defaultdict(list)
    for row in rows:
        behavior = "taker" if row["crossed"] is True else "maker" if row["crossed"] is False else "unknown"
        for key, value in (("all", "all"), ("behavior", behavior), ("action", row["action"]),
                           ("day", row["utc_day"] or "unknown"), ("segment", str(row["segment"]))):
            groups[(key, value)].append(row)
        groups[("behavior_action", f"{behavior}/{row['action']}")].append(row)
    out = defaultdict(list)
    def quant(xs, p):
        if not xs: return None
        xs = sorted(xs); return xs[min(len(xs)-1, max(0, int((len(xs)-1)*p)))]
    for (kind, val), selected in sorted(groups.items()):
        priors = [r for r in selected if r["strict_prior_quote"]]
        costs = [_d(r["execution_vs_mid_bps_signed_cost"]) for r in priors]
        fee_groups=defaultdict(Decimal);fee_missing=0
        for r in selected:
            if r["observed_fee"] is None:fee_missing+=1
            else:fee_groups[str(r["fee_token"] or "unknown")]+=_d(r["observed_fee"])
        per = {"fills": len(selected), "strict_prior_matched": len(priors),
               "execution_quantity":str(sum((_d(r["fill_quantity"]) for r in selected),Decimal(0))),
               "position_close_quantity":str(sum((_d(r["close_quantity"]) for r in selected),Decimal(0))),
               "position_open_quantity":str(sum((_d(r["open_quantity"]) for r in selected),Decimal(0))),
               "observed_signed_fees_by_token":{k:str(v) for k,v in sorted(fee_groups.items())},"fills_missing_fee":fee_missing,
               "prior_age_ms": {"p50": quant([r["strict_prior_quote"]["age_ms"] for r in priors], .5),
                                "p95": quant([r["strict_prior_quote"]["age_ms"] for r in priors], .95)},
               "execution_vs_mid_signed_cost_bps": {"count": len(costs), "mean": str(sum(costs)/len(costs)) if costs else None,
                    "p50": str(quant(costs,.5)) if costs else None, "p95": str(quant(costs,.95)) if costs else None}}
        per["prior_coverage_by_max_age"] = {str(age): sum(r["strict_prior_quote"] is not None and r["strict_prior_quote"]["age_ms"] <= age for r in selected) for age in FRESHNESS_MS}
        age_buckets={"0_100ms":[],"100ms_1s":[],"1s_5s":[],"5s_30s":[],"30s_5m":[],"over_5m":[]}
        for r in priors:
            age=r["strict_prior_quote"]["age_ms"]
            key="0_100ms" if age<=100 else "100ms_1s" if age<=1000 else "1s_5s" if age<=5000 else "5s_30s" if age<=30000 else "30s_5m" if age<=300000 else "over_5m"
            age_buckets[key].append(_d(r["execution_vs_mid_bps_signed_cost"]))
        per["execution_cost_sensitivity_by_prior_age"]={k:{"fills":len(v),"median_bps":str(quant(v,.5)) if v else None,
            "p95_bps":str(quant(v,.95)) if v else None} for k,v in age_buckets.items()}
        per["future_mid_change_bps_by_horizon"] = {}
        available_horizons=sorted({int(h) for r in selected for h in r["future_midpoints_outcome_only"]})
        for h in available_horizons:
            vals = [_d(r["future_midpoints_outcome_only"][str(h)]["mid_change_bps"])
                    for r in selected if r["future_midpoints_outcome_only"][str(h)] and r["future_midpoints_outcome_only"][str(h)]["mid_change_bps"] is not None]
            overshoots=[r["future_midpoints_outcome_only"][str(h)]["target_overshoot_ms"] for r in selected if r["future_midpoints_outcome_only"][str(h)]]
            forward_freshness={}
            for max_overshoot in (1_000,5_000,30_000):
                eligible=[r["future_midpoints_outcome_only"][str(h)] for r in selected
                    if r["future_midpoints_outcome_only"][str(h)] and r["future_midpoints_outcome_only"][str(h)]["target_overshoot_ms"]<=max_overshoot]
                changes=[_d(x["mid_change_bps"]) for x in eligible if x["mid_change_bps"] is not None]
                adjusted=[_d(x["direction_adjusted_mid_change_bps"]) for x in eligible if x["direction_adjusted_mid_change_bps"] is not None]
                forward_freshness[str(max_overshoot)]={"count":len(changes),"coverage_pct":round(100*len(changes)/len(selected),4) if selected else None,
                    "median_mid_change_bps":str(quant(changes,.5)) if changes else None,
                    "direction_adjusted_median_bps":str(quant(adjusted,.5)) if adjusted else None}
            joint=[r["future_midpoints_outcome_only"][str(h)] for r in selected
                if r["strict_prior_quote"] is not None and r["strict_prior_quote"]["age_ms"]<=1_000
                and r["future_midpoints_outcome_only"][str(h)]
                and r["future_midpoints_outcome_only"][str(h)]["target_overshoot_ms"]<=5_000]
            joint_adjusted=[_d(x["direction_adjusted_mid_change_bps"]) for x in joint if x["direction_adjusted_mid_change_bps"] is not None]
            forward_freshness["joint_prefill_le_1s_target_le_5s"]={"count":len(joint),
                "coverage_pct":round(100*len(joint)/len(selected),4) if selected else None,
                "direction_adjusted_median_bps":str(quant(joint_adjusted,.5)) if joint_adjusted else None}
            per["future_mid_change_bps_by_horizon"][str(h)] = {"count": len(vals), "coverage_pct": round(100*len(vals)/len(selected),4) if selected else None,
                "median": str(quant(vals,.5)) if vals else None,
                "quote_target_overshoot_ms":{"p50":quant(overshoots,.5),"p95":quant(overshoots,.95)},
                "quote_within_overshoot_ms":{str(age):sum(x<=age for x in overshoots) for age in FRESHNESS_MS},
                "fresh_target_sensitivity":forward_freshness,
                "direction_adjusted_median": str(quant([_d(r["future_midpoints_outcome_only"][str(h)]["direction_adjusted_mid_change_bps"]) for r in selected if r["future_midpoints_outcome_only"][str(h)] and r["future_midpoints_outcome_only"][str(h)]["direction_adjusted_mid_change_bps"] is not None],.5)) if vals else None}
        out[kind].append({"key": val, **per})
    return dict(out)


def _episodes_and_daily(fills, funding):
    chain, episodes, censored = _position_flows(fills)
    timeline = sorted([(int(f["time"]), _d(f["startPosition"])+(_d(f["sz"]) if f["side"]=="B" else -_d(f["sz"]))) for f in fills])
    rows=[]
    for ep in episodes:
        times=[t for t,_ in timeline]
        attributed=[]
        for event in funding:
            if not (int(ep["start_ms"]) < event["time_ms"] < int(ep["end_ms"])): continue
            ix=bisect.bisect_left(times,event["time_ms"])-1
            if ix>=0 and timeline[ix][1]==_d(event["szi"]): attributed.append(event)
        row={"segment":ep.get("segment"),"entry_tid":ep["entry_tid"],"exit_tid":ep["exit_tid"],
             "start_ms":ep["start_ms"],"end_ms":ep["end_ms"],
             "duration_ms":int(ep["end_ms"])-int(ep["start_ms"]),"close_type":ep["close_type"],
             "price_result_quote_units":ep["price_result_quote_units"],
             "signed_fees_by_token":ep["signed_fees_by_token"],
             "fee_part_missing_count":ep.get("fee_part_missing_count",0),
             "strictly_attributed_funding_usdc":str(sum((_d(x["usdc"] or 0) for x in attributed),Decimal(0))),
             "funding_event_count":len(attributed)}
        rows.append(row)
    by_day=defaultdict(list);by_segment=defaultdict(list)
    from datetime import datetime,timezone
    for ep in rows:
        day=datetime.fromtimestamp(ep["end_ms"]/1000,timezone.utc).date().isoformat()
        by_day[day].append(ep);by_segment[str(ep["segment"])].append(ep)
    def agg(items):
        fees=defaultdict(Decimal)
        for e in items:
            for token,value in e["signed_fees_by_token"].items():fees[token]+=_d(value)
        prices=[_d(e["price_result_quote_units"]) for e in items]
        gross=sum((abs(x) for x in prices),Decimal(0));largest=sorted((abs(x) for x in prices),reverse=True)
        return {"episodes":len(items),"price_result_quote_units":str(sum(prices,Decimal(0))),
            "price_result_concentration":{"gross_abs_sum_quote_units":str(gross),
                "largest_episode_abs_share":str(largest[0]/gross) if largest and gross else None,
                "largest_5_episode_abs_share":str(sum(largest[:5],Decimal(0))/gross) if gross else None,
                "gross_positive_quote_units":str(sum((x for x in prices if x>0),Decimal(0))),
                "gross_negative_quote_units":str(sum((x for x in prices if x<0),Decimal(0)))},
            "signed_fees_by_token":{k:str(v) for k,v in sorted(fees.items())},
            "strictly_attributed_funding_usdc":str(sum((_d(e["strictly_attributed_funding_usdc"]) for e in items),Decimal(0)))}
    final_positions={}
    for seg in sorted({f.get("segment") for f in fills if f.get("segment") is not None}):
        group=sorted((f for f in fills if f.get("segment")==seg),key=lambda f:(int(f["time"]),str(f["tid"])))
        if group:
            f=group[-1];delta=_d(f["sz"]) if f["side"]=="B" else -_d(f["sz"])
            final_positions[str(seg)]=str(_d(f["startPosition"])+delta)
    return {"by_utc_exit_day":{k:agg(v) for k,v in sorted(by_day.items())},"by_segment":{k:agg(v) for k,v in sorted(by_segment.items())},
        "episodes":rows,"open_or_censored_positions":{"counts":censored,
            "segment_end_positions":final_positions},"ruptures":chain.get("position_chain_ruptures",[]),
        "unattributed_funding":{"event_count":max(0,len(funding)-sum(e["funding_event_count"] for e in rows)),
            "amount_usdc":str(sum((_d(x["usdc"] or 0) for x in funding),Decimal(0))-
                sum((_d(e["strictly_attributed_funding_usdc"]) for e in rows),Decimal(0)))}}


def _attach_episode_segments(episode_data, fills):
    segment_by_tid={str(f["tid"]):f.get("segment") for f in fills}
    for ep in episode_data["episodes"]:
        ep["segment"]=segment_by_tid.get(str(ep["entry_tid"]))
    from datetime import datetime,timezone
    by_day=defaultdict(list);by_segment=defaultdict(list)
    for ep in episode_data["episodes"]:
        day=datetime.fromtimestamp(ep["end_ms"]/1000,timezone.utc).date().isoformat()
        by_day[day].append(ep);by_segment[str(ep["segment"])].append(ep)
    def agg(items):
        fees=defaultdict(Decimal)
        for e in items:
            for token,value in e["signed_fees_by_token"].items():fees[token]+=_d(value)
        prices=[_d(e["price_result_quote_units"]) for e in items]
        gross=sum((abs(x) for x in prices),Decimal(0));largest=sorted((abs(x) for x in prices),reverse=True)
        return {"episodes":len(items),"price_result_quote_units":str(sum(prices,Decimal(0))),
            "price_result_concentration":{"gross_abs_sum_quote_units":str(gross),
                "largest_episode_abs_share":str(largest[0]/gross) if largest and gross else None,
                "largest_5_episode_abs_share":str(sum(largest[:5],Decimal(0))/gross) if gross else None,
                "gross_positive_quote_units":str(sum((x for x in prices if x>0),Decimal(0))),
                "gross_negative_quote_units":str(sum((x for x in prices if x<0),Decimal(0)))},
            "signed_fees_by_token":{k:str(v) for k,v in sorted(fees.items())},
            "strictly_attributed_funding_usdc":str(sum((_d(e["strictly_attributed_funding_usdc"]) for e in items),Decimal(0)))}
    episode_data["by_utc_exit_day"]={k:agg(v) for k,v in sorted(by_day.items())}
    episode_data["by_segment"]={k:agg(v) for k,v in sorted(by_segment.items())}
    return episode_data


def _enrich_economic_amounts(artifact):
    episodes=artifact["episode_economics"]["episodes"]
    for ep in episodes:
        fees=ep["signed_fees_by_token"]
        if ep.get("fee_part_missing_count",0)==0 and set(fees).issubset({"USDC"}):
            ep["net_observed_result_usdc"]=str(_d(ep["price_result_quote_units"])-_d(fees.get("USDC",0))+
                _d(ep["strictly_attributed_funding_usdc"]))
        else:ep["net_observed_result_usdc"]=None
    from datetime import datetime,timezone
    day_groups=defaultdict(list);segment_groups=defaultdict(list)
    for ep in episodes:
        day_groups[datetime.fromtimestamp(ep["end_ms"]/1000,timezone.utc).date().isoformat()].append(ep)
        segment_groups[str(ep["segment"])].append(ep)
    def aggregate(group):
        price=[_d(e["price_result_quote_units"]) for e in group]
        net=[_d(e["net_observed_result_usdc"]) for e in group if e["net_observed_result_usdc"] is not None]
        def concentration(values):
            gross=sum((abs(x) for x in values),Decimal(0));ordered=sorted((abs(x) for x in values),reverse=True)
            return {"gross_abs_sum":str(gross),"largest_episode_abs_share":str(ordered[0]/gross) if ordered and gross else None,
                "largest_5_episode_abs_share":str(sum(ordered[:5],Decimal(0))/gross) if gross else None,
                "gross_positive":str(sum((x for x in values if x>0),Decimal(0))),
                "gross_negative":str(sum((x for x in values if x<0),Decimal(0)))}
        fees={token:str(sum((_d(e["signed_fees_by_token"].get(token,0)) for e in group),Decimal(0)))
            for token in sorted({token for e in group for token in e["signed_fees_by_token"]})}
        return {"episodes":len(group),"price_result_quote_units":str(sum(price,Decimal(0))),
            "price_result_concentration":concentration(price),"signed_fees_by_token":fees,
            "strictly_attributed_funding_usdc":str(sum((_d(e["strictly_attributed_funding_usdc"]) for e in group),Decimal(0))),
            "net_observed_result_usdc":str(sum(net,Decimal(0))) if len(net)==len(group) else None,
            "net_result_concentration":concentration(net) if len(net)==len(group) else None}
    artifact["episode_economics"]["by_utc_exit_day"]={k:aggregate(v) for k,v in sorted(day_groups.items())}
    artifact["episode_economics"]["by_segment"]={k:aggregate(v) for k,v in sorted(segment_groups.items())}
    observed_fees=defaultdict(Decimal);missing=0
    for row in artifact["fill_consequences"]["fills"]:
        if row["observed_fee"] is None:missing+=1
        else:observed_fees[str(row["fee_token"] or "unknown")]+=_d(row["observed_fee"])
    bounded_fees=defaultdict(Decimal)
    for ep in episodes:
        for token,value in ep["signed_fees_by_token"].items():bounded_fees[token]+=_d(value)
    artifact["episode_economics"]["fee_accounting"]={"observed_signed_fill_fees_by_token":{k:str(v) for k,v in sorted(observed_fees.items())},
        "bounded_episode_part_fees_by_token":{k:str(v) for k,v in sorted(bounded_fees.items())},
        "outside_bounded_episode_parts_by_token":{k:str(v-bounded_fees.get(k,Decimal(0))) for k,v in sorted(observed_fees.items())},
        "fills_missing_fee":missing,"outside_bounded_note":"Residual includes censored/open episode parts, left-censored closures, and any fee parts not attributable to a bounded episode."}
    return artifact


def _load_quotes(store, cutoff_ms):
    where,params=_source_specs(NETWORK,ADDRESS,MARKET,cutoff_ms)["bbo"]
    quotes=[]; lots=events=0; refs={}; rejected=defaultdict(int)
    for obs in store.connection.execute("select * from raw_observations where "+where+" order by observation_id",params):
        lots+=1; payload,size=_decode_market(obs,max_decoded_bytes=16_000_000,with_size=True)
        refs[obs["observation_id"]]=obs["response_sha256"]
        vals,bad,count,_=_quote_values("bbo",payload,MARKET,lot_received_ms=_ms(obs["observed_at"]),cutoff_ms=cutoff_ms)
        events+=count
        for k,v in bad.items():rejected[k]+=v
        for v in vals: quotes.append((v["event_ms"],v["bid"],v["ask"],{"observation_id":obs["observation_id"],"event_index":v["event_index"],"sha256":obs["response_sha256"]}))
    quote_fp=fingerprint({"lots":sorted(refs.items()),"events":events,"rejected":dict(sorted(rejected.items()))})
    return quotes,{"lot_count":lots,"decoded_event_count":events,"usable_quotes":len(quotes),"rejected_events":dict(sorted(rejected.items())),"source_fingerprint":quote_fp}


def execute(store, *, request_id, output_path=None):
    job=store.connection.execute("select * from population_research_jobs where request_id=?",(request_id,)).fetchone()
    if not job or job["status"]!="needs_data": raise ValueError("Sealed needs-data task required")
    result=json.loads(job["result_json"] or "{}")
    join=result.get("local_archive_join",{})
    if join.get("state")!="completed" or join.get("version")!="population-offline-archive-join-v3": raise ValueError("Completed sealed v3 join required")
    packetrow=store.connection.execute("select artifact_json from population_local_archive_joins where request_id=? and artifact_fingerprint=?",(request_id,join.get("artifact_fingerprint"))).fetchone()
    if not packetrow: raise ValueError("Referenced local archive join missing")
    base=json.loads(packetrow["artifact_json"])
    if fingerprint(base)!=join["artifact_fingerprint"]: raise ValueError("Join fingerprint mismatch")
    cutoff=int(base["cutoff_ms"])
    if not authorized_account_history(store,NETWORK,ADDRESS,cutoff): raise PermissionError("Account history not authorized at sealed cutoff")
    store.connection.execute("create table if not exists population_eth_execution_contributions (request_id text not null, analysis_version text not null, base_join_fingerprint text not null, analysis_fingerprint text not null, artifact_json text not null, created_ms integer not null, primary key(request_id,analysis_version,base_join_fingerprint))")
    saved=store.connection.execute("select analysis_fingerprint,artifact_json from population_eth_execution_contributions where request_id=? and analysis_version=? and base_join_fingerprint=?",(request_id,VERSION,join["artifact_fingerprint"])).fetchone()
    if saved:
        artifact=json.loads(saved["artifact_json"])
        # Version v1 was first persisted before adding an explicit selected ETH
        # count. Upgrade that metadata from the already persisted fill rows.
        if ("selected_market_fill_count" not in artifact["coverage"]["fills"] or
                "net_observed_result_usdc" not in artifact["episode_economics"]["episodes"][0] or
                not artifact["episode_economics"]["by_utc_exit_day"].get(next(iter(artifact["episode_economics"]["by_utc_exit_day"]),""),{}).get("price_result_concentration") or
                "execution_cost_sensitivity_by_prior_age" not in artifact["fill_consequences"]["summary"].get("all",[{}])[0] or
                "position_close_quantity" not in artifact["fill_consequences"]["summary"].get("all",[{}])[0] or
                "joint_prefill_le_1s_target_le_5s" not in artifact["fill_consequences"]["summary"].get("all",[{}])[0].get("future_mid_change_bps_by_horizon",{}).get("1000",{}).get("fresh_target_sensitivity",{})):
            artifact["coverage"]["fills"]["selected_market_fill_count"]=len(artifact["fill_consequences"]["fills"])
            artifact["coverage"]["fills"]["other_markets_unique_fill_count"]=artifact["coverage"]["fills"]["unique_fill_id_count"]-len(artifact["fill_consequences"]["fills"])
            def aggregate(group):
                prices=[_d(e["price_result_quote_units"]) for e in group];gross=sum((abs(x) for x in prices),Decimal(0));ordered=sorted((abs(x) for x in prices),reverse=True)
                fees={k:str(sum((_d(e["signed_fees_by_token"].get(k,0)) for e in group),Decimal(0))) for k in sorted({k for e in group for k in e["signed_fees_by_token"]})}
                return {"episodes":len(group),"price_result_quote_units":str(sum(prices,Decimal(0))),
                    "price_result_concentration":{"gross_abs_sum_quote_units":str(gross),"largest_episode_abs_share":str(ordered[0]/gross) if ordered and gross else None,
                        "largest_5_episode_abs_share":str(sum(ordered[:5],Decimal(0))/gross) if gross else None,
                        "gross_positive_quote_units":str(sum((x for x in prices if x>0),Decimal(0))),"gross_negative_quote_units":str(sum((x for x in prices if x<0),Decimal(0)))},
                    "signed_fees_by_token":fees,"strictly_attributed_funding_usdc":str(sum((_d(e["strictly_attributed_funding_usdc"]) for e in group),Decimal(0)))}
            from datetime import datetime,timezone
            by_day=defaultdict(list);by_seg=defaultdict(list)
            for ep in artifact["episode_economics"]["episodes"]:
                by_day[datetime.fromtimestamp(ep["end_ms"]/1000,timezone.utc).date().isoformat()].append(ep);by_seg[str(ep["segment"])].append(ep)
            artifact["episode_economics"]["by_utc_exit_day"]={k:aggregate(v) for k,v in sorted(by_day.items())}
            artifact["episode_economics"]["by_segment"]={k:aggregate(v) for k,v in sorted(by_seg.items())}
            artifact["fill_consequences"]["summary"]=summarize_consequences(artifact["fill_consequences"]["fills"])
            artifact=_enrich_economic_amounts(artifact)
            artifact.pop("analysis_fingerprint",None);analysis_fp=fingerprint(artifact);artifact["analysis_fingerprint"]=analysis_fp
            store.connection.execute("update population_eth_execution_contributions set analysis_fingerprint=?,artifact_json=? where request_id=? and analysis_version=? and base_join_fingerprint=?",
                (analysis_fp,canonical(artifact),request_id,VERSION,join["artifact_fingerprint"]));store.connection.commit()
        if output_path:
            path=Path(output_path);path.parent.mkdir(parents=True,exist_ok=True)
            with gzip.open(path,"wt",encoding="utf-8") as f:json.dump(artifact,f,sort_keys=True,separators=(",",":"))
        _link_job_result(store,request_id,result,artifact)
        return {"status":"unchanged","analysis_fingerprint":artifact["analysis_fingerprint"],"artifact":artifact}
    fills,coverage,fill_refs=_load_fills(store,NETWORK,ADDRESS,cutoff)
    fills=[f for f in fills if f.get("coin")==MARKET]
    for f in fills:
        f["utc_day"]=(__import__('datetime').datetime.fromtimestamp(f["time"]/1000,__import__('datetime').timezone.utc).date().isoformat())
    # Position segment labels come from the sealed join; IDs are stable fill tids.
    segment_by_id={str(f["fill_id"]):f["segment"] for f in base["fills"]}
    for f in fills:f["segment"]=segment_by_id.get(str(f["tid"]))
    funding, funding_cov, funding_refs=_load_funding(store,NETWORK,ADDRESS,cutoff)
    funding=[f for f in funding if f["coin"]==MARKET]
    quotes,qcov=_load_quotes(store,cutoff)
    consequences=measure_fill_consequences(fills,quotes)
    episode_data=_attach_episode_segments(_episodes_and_daily(fills,funding),fills)
    # Keep the original source/fill/context refs and quote source manifest in the artifact.
    refs=[f"raw_observations:{r['id']}#sha256:{r['sha256']}" for r in fill_refs+funding_refs]
    artifact={"schema_version":VERSION,"request_id":request_id,"network":NETWORK,"address":ADDRESS,"market":MARKET,
        "cutoff_ms":cutoff,"base_join_fingerprint":join["artifact_fingerprint"],
        "prior_context_fingerprint":result.get("local_inventory_market_context",{}).get("analysis_fingerprint"),
        "definitions":{"prior_mid":"latest archived BBO event with event_ms < fill event_ms; same-ms is excluded.",
            "future_mid":"first archived BBO event at or after fill_ms+horizon and strictly after fill_ms. Outcome-only measurement; never a historical signal.",
            "fill_action":"opening/reducing/reversing derived from startPosition and signed fill size; inversion quantities split arithmetically.",
            "maker_taker":"archived crossed=false/true respectively; unknown remains separate.",
            "own_execution_cost":"not estimated; trader fees/quotes cannot be transferred to our hypothetical execution or passive fills."},
        "coverage":{"fills":{**coverage,"selected_market_fill_count":len(fills),
                "other_markets_unique_fill_count":coverage["unique_fill_id_count"]-len(fills)},"funding":funding_cov,"bbo":qcov},
        "episode_economics":episode_data,"fill_consequences":{"horizons_ms":list(HORIZONS_MS),"freshness_sensitivity_ms":list(FRESHNESS_MS),
            "summary":summarize_consequences(consequences),"fills":consequences},
        "evidence_refs":refs+[f"population_local_archive_joins:{request_id}#{join['artifact_fingerprint']}",
            f"population_inventory_market_contexts:{request_id}#{result.get('local_inventory_market_context',{}).get('analysis_fingerprint')}"],
        "limits":["Archives are bounded and incomplete; local position coherence is not history completeness.",
            "No fill-local receipt timestamp exists, and clocks are not calibrated; event-time predecessor does not prove live availability.",
            "Equal-millisecond book/fill order is unknown.","Future midpoints evaluate consequences only and do not imply a fill policy or passive-fill simulation.",
            "Episode cash-flow result, execution-vs-mid cost and future midpoint move overlap economically; they are separate views and must not be added.",
            "Funding attribution follows strict interior episode and exact prior position match; unassigned funding remains unknown."]}
    artifact=_enrich_economic_amounts(artifact)
    artifact["analysis_fingerprint"]=fingerprint(artifact)
    status,analysis_fp,artifact=persist_artifact(store.connection,request_id,join["artifact_fingerprint"],artifact)
    if output_path:
        path=Path(output_path);path.parent.mkdir(parents=True,exist_ok=True)
        with gzip.open(path,"wt",encoding="utf-8") as f: json.dump(artifact,f,sort_keys=True,separators=(",",":"))
    _link_job_result(store,request_id,result,artifact)
    return {"status":status,"analysis_fingerprint":analysis_fp,"artifact":artifact}
