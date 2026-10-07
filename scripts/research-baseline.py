#!/usr/bin/env python3
"""Metadata-only baseline: never read raw payloads or evaluation results."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess

p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
c=sqlite3.connect(f'file:{a.db.resolve()}?mode=ro',uri=True);c.row_factory=sqlite3.Row
c.execute('pragma query_only=on')
def rows(sql,args=()): return [dict(r) for r in c.execute(sql,args)]
def digest(value): return hashlib.sha256(value.encode()).hexdigest()
plans=[]
for r in c.execute('select plan_id,network,address,coin,plan_json,created_ms,synthetic from validation_plans'):
 x=dict(r);data=json.loads(x.pop('plan_json'));x['immutable_plan_sha256']=digest(json.dumps(data,sort_keys=True,separators=(',',':')));x['windows']={k:data[k] for k in ('exploration','comparison','final')};plans.append(x)
variants=[]
for r in c.execute('select variant_id,plan_id,spec_json,criteria_json,frozen_ms,research_run_id from strategy_variants'):
 x=dict(r);x['spec_sha256']=digest(x.pop('spec_json'));x['criteria_sha256']=digest(x.pop('criteria_json'));variants.append(x)
services=subprocess.run(['systemctl','--user','show','tamtam-again-collectors.service','tamtam-again-research.timer','tamtam-again-paper.timer','-p','Id','-p','ActiveState','-p','MainPID','-p','MemoryCurrent','-p','CPUUsageNSec','-p','ExecStart'],capture_output=True,text=True,check=True).stdout
payload={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'raw_payloads_accessed':False,
'git_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
'database_bytes':a.db.stat().st_size,'wal_bytes':Path(str(a.db)+'-wal').stat().st_size if Path(str(a.db)+'-wal').exists() else 0,
'candidate_status':rows('select network,status,discovery_source,count(*) count from candidates group by network,status,discovery_source'),
'active_accounts':rows("select network,address,label,discovery_source,added_at from candidates where status='tracked' order by added_at,address"),
'endpoint_metadata':rows('select source,endpoint,count(*) observations,sum(record_count) reported_records,min(observed_at) first_available,max(observed_at) last_available from raw_observations group by source,endpoint'),
'last_day_ingestion':rows("select substr(observed_at,1,13) utc_hour,source,count(*) observations,sum(record_count) records from raw_observations where observed_at>=? group by utc_hour,source",((datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=1)).isoformat(),)),
'cursor_status':rows('select endpoint,count(*) count,min(last_successful_end_ms) earliest,max(last_successful_end_ms) latest from collection_cursors group by endpoint'),
'plans':plans,'variants':variants,
'evaluation_metadata':rows('select evaluation_id,variant_id,plan_id,stage,status,created_at from validation_evaluations'),
'paper_metadata':rows('select session_id,variant_id,status,started_ms,updated_at from paper_sessions'),
'research_metadata':rows('select run_id,plan_id,status,reserved_cost_usd,actual_cost_usd,created_at,updated_at from isolated_research_jobs'),
'services':services,'measurements_missing':['REST actual charged weight, retries, response items by attempt','WS input bytes, queue peak, flush latency','Process-isolated quota consumption from other tools sharing the IP'],
'note':'Reported record_count is archive metadata, not unique fills or independent episodes. Hashes preserve pilot identity; no results or raw reserved observations exported.'}
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n');print('Baseline written:',a.output,'plans',len(plans),'variants',len(variants))
