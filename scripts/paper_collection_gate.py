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
from tamtam_again.validation import now_ms

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
    args=parser.parse_args()
    if args.duration_sec!=600:
        parser.error('the frozen gate duration is exactly 600 seconds')
    store=Store(DB)
    spec=json.loads(SPEC.read_text())
    spec_id=fingerprint(spec)
    started=now_ms()
    start_state=_paper_collection_runtime_state(store)
    start_iso=iso(started)
    print(json.dumps({"state":"measuring","window_start_utc":start_iso,
        "collector_pid":start_state["collector_pid"],
        "connection_id":start_state["current_connection_id"],
        "runtime_config":start_state["runtime_config"]}),flush=True)
    time.sleep(600)
    ended=now_ms();end_iso=iso(ended)
    # Include records flushed just after the end instant, while excluding their later receipt times.
    rows=store.connection.execute(
        "SELECT * FROM raw_observations WHERE source='hyperliquid-websocket-v1' AND "
        "((entity_type='market' AND entity_id='HYPE' AND endpoint='bbo') OR "
        "(entity_type='stream' AND endpoint='streamHealth')) AND observed_at>=? AND observed_at<=? "
        "ORDER BY observation_id",(start_iso,iso(ended+3000))).fetchall()
    frames=[];health=[]
    for row in rows:
        payload=decode_observation_payload(row)
        if row['endpoint']=='bbo':
            for frame in payload.get('events',[]):
                received=int(datetime.fromisoformat(frame['received_at'].replace('Z','+00:00')).timestamp()*1000)
                archived=int(datetime.fromisoformat(row['observed_at'].replace('Z','+00:00')).timestamp()*1000)
                msg=frame.get('message',{});data=msg.get('data',{})
                bbo=data.get('bbo',[])
                if start<=received<ended and len(bbo)==2:
                    frames.append({"observation_id":int(row['observation_id']),"received_ms":received,
                        "archived_ms":archived,"connection_id":msg.get('_stream',{}).get('connection_id'),
                        "bid":bbo[0].get('px'),"ask":bbo[1].get('px')})
        else:
            event=payload
            stamp=int(datetime.fromisoformat(row['requested_at'].replace('Z','+00:00')).timestamp()*1000)
            if start<=stamp<ended:health.append({"observation_id":int(row['observation_id']),
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
        and start_state['current_connection_id']==end_state['current_connection_id'])
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
        "raw_observation_refs":[f"raw_observations:{f['observation_id']}" for f in frames]}
    report=json.loads(REPORT.read_text());report['observation_windows'].append(window)
    report['launch_gate']['status']='passed' if gate['passed'] and runtime_stable else 'not_yet_passed'
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    result_path=ROOT/'docs/continuous-research'/f"PAPER-FRESHNESS-GATE-{started}-A880-HYPE.json"
    result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    store.close()
    print(json.dumps({"gate_id":gate['gate_id'],"passed":gate['passed'] and runtime_stable,
        "measurement_file":str(result_path.relative_to(ROOT)),"window":window},ensure_ascii=False),flush=True)
    return 0 if gate['passed'] and runtime_stable else 2

if __name__=='__main__':raise SystemExit(main())
