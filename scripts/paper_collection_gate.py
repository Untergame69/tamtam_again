#!/usr/bin/env python3
"""Measure the frozen v3 paper collection gate at real systemd tick starts."""
from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tamtam_again.cli import _paper_collection_runtime_state
from tamtam_again.engine import fingerprint
from tamtam_again.experimental_paper import record_collection_gate
from tamtam_again.storage import Store, decode_observation_payload
from tamtam_again.validation import create_plan, now_ms, register_variant

DB=ROOT/'data/tamtam.sqlite3'
SPEC=ROOT/'config/experiments/a880-hype-live-delta-v3.json'
REPORT=ROOT/'docs/continuous-research/PAPER-FRESHNESS-GATE-20261012-A880-HYPE.json'
EXPECTED={"paper_timer_interval_ms":500,"paper_timer_accuracy_ms":50,
    "paper_start_limit_interval_ms":10_000,"paper_start_limit_burst":30,
    "bbo_flush_interval_ms":250,"quote_age_limit_ms":1000}

def pct(values:list[int|float],p:float)->int:
    if not values:return 0
    ordered=sorted(values);return int(ordered[min(len(ordered)-1,math.ceil(p*len(ordered))-1)])

def iso(ms:int)->str:
    return datetime.fromtimestamp(ms/1000,timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')

def main()->int:
    parser=argparse.ArgumentParser()
    parser.add_argument('--duration-sec',type=int,default=600)
    parser.add_argument('--replay-start-ms',type=int,
        help='Reconstruct a completed uninterrupted window from journal and archive timestamps.')
    parser.add_argument('--launch-on-pass',action='store_true',
        help='After a passing gate, register a fresh paper-only plan and start the independent v3 ledger.')
    args=parser.parse_args()
    if args.duration_sec!=600:
        parser.error('the frozen gate duration is exactly 600 seconds')
    store=Store(DB)
    spec=json.loads(SPEC.read_text())
    spec_id=fingerprint(spec)
    started=args.replay_start_ms or now_ms()
    start_state=_paper_collection_runtime_state(store)
    if args.replay_start_ms:
        prior=store.connection.execute(
            "SELECT response_json,response_encoding FROM raw_observations WHERE source='hyperliquid-websocket-v1' "
            "AND entity_type='market' AND entity_id='HYPE' AND endpoint='bbo' AND observed_at<=? "
            "ORDER BY observation_id DESC LIMIT 1",(iso(started),)).fetchone()
        if prior:
            payload=decode_observation_payload(prior)
            frame=max(payload.get('events',[]),key=lambda x:x['received_at'],default=None)
            if frame:
                start_state['current_connection_id']=frame.get('message',{}).get('_stream',{}).get('connection_id')
        session_row=store.connection.execute(
            "SELECT response_json,response_encoding FROM raw_observations WHERE source='hyperliquid-websocket-v1' "
            "AND entity_type='stream' AND endpoint='streamHealth' AND requested_at<=? "
            "ORDER BY observation_id DESC LIMIT 1",(iso(started),)).fetchone()
        if session_row:
            health=decode_observation_payload(session_row)
            start_state['current_connection_id']=health.get('session',start_state['current_connection_id'])
    start_iso=iso(started)
    print(json.dumps({"state":"measuring","window_start_utc":start_iso,
        "collector_pid":start_state["collector_pid"],
        "connection_id":start_state["current_connection_id"],
        "runtime_config":start_state["runtime_config"]}),flush=True)
    if not args.replay_start_ms:time.sleep(600)
    ended=(started+600_000) if args.replay_start_ms else now_ms();end_iso=iso(ended)
    # Include records flushed just after the end instant, while excluding their later receipt times.
    rows=store.connection.execute(
        "SELECT * FROM raw_observations WHERE source='hyperliquid-websocket-v1' AND "
        "((entity_type='market' AND entity_id='HYPE' AND endpoint='bbo') OR "
        "(entity_type='stream' AND endpoint='streamHealth')) AND observed_at>=? AND observed_at<=? "
        "ORDER BY observation_id",(iso(max(0,started-1000)),iso(ended+3000))).fetchall()
    frames=[];health=[]
    for row in rows:
        payload=decode_observation_payload(row)
        if row['endpoint']=='bbo':
            for frame in payload.get('events',[]):
                received=int(datetime.fromisoformat(frame['received_at'].replace('Z','+00:00')).timestamp()*1000)
                archived=int(datetime.fromisoformat(row['observed_at'].replace('Z','+00:00')).timestamp()*1000)
                msg=frame.get('message',{});data=msg.get('data',{})
                bbo=data.get('bbo',[])
                if started-1000<=received<ended and len(bbo)==2:
                    frames.append({"observation_id":int(row['observation_id']),"received_ms":received,
                        "archived_ms":archived,"connection_id":msg.get('_stream',{}).get('connection_id'),
                        "bid":bbo[0].get('px'),"ask":bbo[1].get('px')})
        else:
            event=payload
            stamp=int(datetime.fromisoformat(row['requested_at'].replace('Z','+00:00')).timestamp()*1000)
            if started<=stamp<ended:health.append({"observation_id":int(row['observation_id']),
                "stamp_ms":stamp,"connection_id":event.get('session'),"kind":event.get('kind'),
                "connected":event.get('connected')})
    # Use actual systemd service start records as decision instants.
    journal=subprocess.run(['journalctl','--user','-u','tamtam-again-paper.service',
        '--since',f'@{started/1000:.3f}','--until',f'@{ended/1000:.3f}','--no-pager','-o','json'],
        check=True,capture_output=True,text=True)
    tick_ms=[];start_limit_hits=0
    for line in journal.stdout.splitlines():
        try:entry=json.loads(line)
        except json.JSONDecodeError:continue
        message=str(entry.get('MESSAGE',''))
        if 'start-limit-hit' in message.lower() or 'start request repeated too quickly' in message.lower():
            start_limit_hits+=1
        if message.startswith('Starting tamtam-again-paper.service'):
            tick_ms.append(int(entry['__REALTIME_TIMESTAMP'])//1000)
    frames.sort(key=lambda f:(f['received_ms'],f['observation_id']))
    checkpoints=[];fresh=0;cursor=0;latest=[]
    for tick in tick_ms:
        while cursor<len(frames) and frames[cursor]['archived_ms']<=tick and frames[cursor]['received_ms']<=tick:
            latest.append(frames[cursor]);cursor+=1
        quote=latest[-1] if latest else None
        age=tick-quote['received_ms'] if quote else 10**12
        ok=bool(quote and age<=1000 and quote['connection_id']==start_state['current_connection_id'])
        fresh+=int(ok)
        checkpoints.append({"control_at_ms":tick,"control_at_utc":iso(tick),
            "tick_start_ms":tick,"tick_start_utc":iso(tick),
            "observation_id":quote['observation_id'] if quote else 0,
            "observation_ref":f"raw_observations:{quote['observation_id']}" if quote else None,
            "connection_id":quote['connection_id'] if quote else None,
            "quote_received_at_ms":quote['received_ms'] if quote else None,
            "quote_archived_at_ms":quote['archived_ms'] if quote else None,
            "quote_age_ms":age if quote else None,"admissible":ok})
    ids={h['connection_id'] for h in health if h['connection_id']}
    ids.update(f['connection_id'] for f in frames if f['connection_id'])
    if start_state['current_connection_id']:ids.add(start_state['current_connection_id'])
    reconnects=sum(1 for h in health if h['connected'] is False)+max(0,len(ids)-1)
    intervals=[b-a for a,b in zip(tick_ms,tick_ms[1:])]
    receipt_lag=[max(0,f['archived_ms']-f['received_ms']) for f in frames]
    end_state=_paper_collection_runtime_state(store)
    runtime_stable=(start_state['runtime_config']==end_state['runtime_config']==EXPECTED
        and start_state['collector_pid']==end_state['collector_pid']
        and start_state['collector_active_enter']==end_state['collector_active_enter']
        and start_state['code_revision']==end_state['code_revision']
        and start_state['current_connection_id']==end_state['current_connection_id']
        and start_state['collector_active'] and end_state['collector_active']
        and start_state['paper_timer_active'] and end_state['paper_timer_active']
        and start_state['current_connection_healthy'] and end_state['current_connection_healthy'])
    measurement={"window_start_ms":started,"window_end_ms":ended,"window_start_utc":start_iso,
        "window_end_utc":end_iso,"quote_age_limit_ms":1000,"checkpoints":len(checkpoints),
        "fresh_quotes":fresh,"connection_ids":sorted(ids),"connection_id":start_state['current_connection_id'],
        "reconnects":reconnects,"start_limit_hits":start_limit_hits,
        "tick_interval_p95_ms":pct(intervals,.95),"tick_interval_max_ms":max(intervals,default=0),
        "receipt_to_archive_p95_ms":pct(receipt_lag,.95),"runtime_config":start_state['runtime_config'],
        "runtime_config_stable":runtime_stable,"collector_pid":start_state['collector_pid'],
        "collector_active_enter":start_state['collector_active_enter'],"code_revision":start_state['code_revision'],
        "bbo_frames":len(frames),"health_observations":[h['observation_id'] for h in health],
        "control_checkpoints":checkpoints,
        "quote_age_ms":{"p50":pct([x['quote_age_ms'] for x in checkpoints if x['quote_age_ms'] is not None],.5),
            "p95":pct([x['quote_age_ms'] for x in checkpoints if x['quote_age_ms'] is not None],.95),
            "max":max([x['quote_age_ms'] for x in checkpoints if x['quote_age_ms'] is not None],default=0)},
        "targeted_runtime_config":EXPECTED}
    gate=record_collection_gate(store,spec_id,measurement)
    result={**gate,"measurement":measurement,"spec_fingerprint":spec_id}
    window={"phase":"ten_minute_live_gate","start_utc":start_iso,"end_utc":end_iso,
        "duration_ms":ended-started,"collector_connection_id":start_state['current_connection_id'],
        "bbo_frames":len(frames),"decision_checkpoints":len(tick_ms),"admissible_quotes":fresh,
        "admissible_fraction":fresh/len(tick_ms) if tick_ms else 0,
        "tick_interval_ms":{"p95":measurement['tick_interval_p95_ms'],"max":measurement['tick_interval_max_ms']},
        "receipt_to_archive_p95_ms":measurement['receipt_to_archive_p95_ms'],
        "quote_age_ms":measurement['quote_age_ms'],"reconnects":reconnects,
        "start_limit_hits":start_limit_hits,"runtime_config_stable":runtime_stable,
        "gate_id":gate['gate_id'],"passed":gate['passed'],"window_ref":f"paper_experimental_collection_gates:{gate['gate_id']}",
        "raw_observation_refs":sorted({f"raw_observations:{f['observation_id']}" for f in frames})}
    failures=[]
    if not tick_ms or fresh/len(tick_ms)<.95:
        failures.append(f"Eligible quotes {fresh}/{len(tick_ms)} ({fresh/len(tick_ms) if tick_ms else 0:.2%}) were below the frozen 95% requirement with max_quote_age_ms=1000.")
    if len(set(ids))!=1 or reconnects:
        failures.append(f"Connection continuity failed: connection_ids={sorted(ids)}, reconnects={reconnects}.")
    if start_limit_hits:
        failures.append(f"Systemd start-limit hits: {start_limit_hits}.")
    if pct(intervals,.95)>600 or max(intervals,default=0)>1000:
        failures.append(f"Tick cadence exceeded the frozen p95/max limits: p95={pct(intervals,.95)} ms, max={max(intervals,default=0)} ms.")
    if pct(receipt_lag,.95)>300:
        failures.append(f"Receipt-to-archive p95 exceeded 300 ms: {pct(receipt_lag,.95)} ms.")
    if not runtime_stable:
        failures.append("Collector process/session or active collection runtime configuration changed during the window.")
    if failures:window['failure_reasons']=failures
    report=json.loads(REPORT.read_text());report['observation_windows'].append(window)
    report['launch_gate']['status']='passed' if gate['passed'] and runtime_stable else 'failed_latest_window'
    report['last_decision']={"result":"start_v3" if gate['passed'] and runtime_stable else "do_not_start_v3",
        "gate_id":gate['gate_id'],"reason":"All predeclared gate criteria passed." if gate['passed'] and runtime_stable
            else "; ".join(failures)}
    report['next_control']={"status":"complete_no_further_retry" if args.launch_on_pass else "not_applicable",
        "one_shot_recheck":True,"recursive_retries":False}
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    result_path=ROOT/'docs/continuous-research'/f"PAPER-FRESHNESS-GATE-{started}-A880-HYPE.json"
    result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    passed=gate['passed'] and runtime_stable
    launch_result=None
    if passed and args.launch_on_pass:
        from tamtam_again.experimental_paper import start as start_experimental
        runtime=None
        for _ in range(120):
            runtime=_paper_collection_runtime_state(store)
            if (runtime['current_connection_id']==measurement['connection_id']
                and runtime['current_quote_age_ms']<=1000
                and runtime['current_connection_healthy']):
                break
            time.sleep(.5)
        else:
            launch_result={"started":False,"reason":"No current quote within the frozen 1000 ms limit on the measured connection within 60 seconds."}
        if launch_result is None:
            plan=json.loads((ROOT/'config/experiments/a880-hype-live-delta-plan-v2.json').read_text())
            base=now_ms()+60_000;gap=plan['embargo_ms'];width=3_600_000
            plan['exploration']={"start_ms":base,"end_ms":base+width}
            plan['comparison']={"start_ms":base+width+gap,"end_ms":base+2*width+gap}
            plan['final']={"start_ms":base+2*width+2*gap,"end_ms":base+3*width+2*gap}
            created_plan=create_plan(store,plan)
            variant=register_variant(store,created_plan['plan_id'],spec)
            hypothesis=json.loads((ROOT/'config/experiments/a880-hype-live-delta-hypothesis-v3.json').read_text())
            launch_deadline=time.monotonic()+60
            while time.monotonic()<launch_deadline:
                runtime=_paper_collection_runtime_state(store)
                if (runtime['current_connection_id']==measurement['connection_id']
                    and runtime['current_quote_age_ms']<=1000
                    and runtime['current_connection_healthy']):
                    break
                time.sleep(.25)
            else:
                launch_result={"started":False,"reason":"Current quote freshness on the measured connection was unavailable at start within 60 seconds."}
            if launch_result is None:
                started_paper=start_experimental(store,variant['variant_id'],hypothesis,
                    restart_reason="Independent v3 after administratively incomplete v2; no residual, cash or result transferred.",
                    independent_after_incomplete=True,runtime_state=runtime)
                session_id=started_paper['session_id'];initial_cursor=started_paper['last_observation_id']
                deadline=time.monotonic()+30;processed=None
                while time.monotonic()<deadline:
                    row=store.connection.execute("SELECT last_observation_id,state_json,status FROM paper_sessions WHERE session_id=?",
                        (session_id,)).fetchone()
                    state=json.loads(row['state_json'])
                    if int(row['last_observation_id'])>int(initial_cursor) and state.get('paper_runtime',{}).get('started_ms'):
                        processed={"last_observation_id":int(row['last_observation_id']),"paper_runtime":state['paper_runtime']}
                        break
                    time.sleep(.5)
                exp_row=store.connection.execute("SELECT next_review_ms,review_interval_ms FROM paper_experimental_sessions WHERE session_id=?",
                    (session_id,)).fetchone()
                launch_result={"started":True,"session_id":session_id,"variant_id":variant['variant_id'],
                    "plan_id":created_plan['plan_id'],"initial_observation_cursor":initial_cursor,
                    "first_processed_observations":processed,"scheduled_review_ms":exp_row['next_review_ms'],
                    "review_interval_ms":exp_row['review_interval_ms'],"gate_id":gate['gate_id']}
                started_path=ROOT/'docs/continuous-research'/f"PAPER-V3-START-{session_id}.json"
                started_path.write_text(json.dumps({"artifact_type":"v3_independent_paper_start_evidence",
                    "gate_id":gate['gate_id'],"spec_fingerprint":spec_id,"start":launch_result,
                    "start_runtime_state":runtime},ensure_ascii=False,indent=2)+'\n')
    run_success=passed and (not args.launch_on_pass or bool(launch_result and launch_result.get('started')))
    if args.launch_on_pass:
        window['launch_result']=launch_result
        report=json.loads(REPORT.read_text());report['observation_windows'][-1]=window
        if run_success:
            report['launch_gate']['status']='v3_started'
            report['last_decision']={"result":"start_v3","gate_id":gate['gate_id'],
                "session_id":launch_result['session_id'],"reason":"Ten-minute gate passed and current connection/configuration/fresh quote were verified at start."}
        elif passed:
            report['launch_gate']['status']='passed_start_blocked'
            report['last_decision']={"result":"do_not_start_v3","gate_id":gate['gate_id'],
                "reason":launch_result['reason'] if launch_result else "No start result was recorded."}
        REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    store.close()
    store.close()
    print(json.dumps({"gate_id":gate['gate_id'],"passed":passed,
        "measurement_file":str(result_path.relative_to(ROOT)),"checkpoints":len(tick_ms),
        "fresh_quotes":fresh,"fresh_fraction":fresh/len(tick_ms) if tick_ms else 0,
        "launch_result":launch_result},ensure_ascii=False),flush=True)
    return 0 if run_success else 2

if __name__=='__main__':raise SystemExit(main())
