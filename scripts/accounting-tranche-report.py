#!/usr/bin/env python3
"""Readonly replay of a predeclared accounting tranche; never calls a provider."""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from tamtam_again.account_adapter import report_account
from tamtam_again.account_batch import qualify_observed_population
from tamtam_again.account_periods import observed_periods

p=argparse.ArgumentParser()
p.add_argument('--db',type=Path,required=True)
p.add_argument('--plan',type=Path,required=True)
p.add_argument('--period-policy',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
plan=json.loads(a.plan.read_text());policy=json.loads(a.period_policy.read_text())
cutoff=plan['archive_cutoff_ms'];network='hyperliquid-mainnet'
def project(r):
    return {k:r[k] for k in ('address','account_mode','status','economic_validation',
        'period','period_selection','history_coverage','unsupported_events','capital_model','next_actions') if k in r} | {
        'scopes':[{'scope':s['scope'],'status':s['status'],
            'observed':{k:v for k,v in s['observed'].items()
                if k not in ('initial_positions','final_positions')},
            'public_scope_assessment':s['public_scope_assessment']}
            for s in r.get('perp_scope_reports',[]) if s['scope']['id']=='perp:']}
with sqlite3.connect(a.db.resolve().as_uri()+'?mode=ro',uri=True) as c:
    c.row_factory=sqlite3.Row;c.execute('begin');store=SimpleNamespace(connection=c)
    population=qualify_observed_population(store,network,as_of_ms=cutoff,period_policy=policy)
    cases=[project(report_account(store,network,case['address'],case['start_ms'],
        case['end_ms'],as_of_ms=cutoff)) for case in plan['cases']]
    cohort=c.execute('select * from population_cohorts where network=? and created_ms<=? '
        'order by created_ms desc limit 1',(network,cutoff)).fetchone()
    snapshot=json.loads(cohort['snapshot_json']);allocation=json.loads(cohort['policy_json'])
    cadence=[]
    for group,members in sorted(snapshot['groups'].items()):
        for address in sorted(members):
            # Authorization is enforced before raw access by observed_periods.
            observed=observed_periods(store,network,address,as_of_ms=cutoff)
            ts=[v['event_ms'] for v in observed['valuation_boundaries']]
            gaps=[right-left for left,right in zip(ts,ts[1:])]
            cadence.append({'address':address,'group':group,'valuation_event_times_ms':ts,
                'last_interval_ms':gaps[-1] if gaps else None,
                'end_age_ms':cutoff-max(ts) if ts else None,
                'next_observation_required':'fresh exact valuation with a coherent start within target duration tolerance; no shorter-period fallback',
                'deadline_ms':plan['deadline_ms']})
    population['accounts']=[project(r) for r in population['accounts']]
    result={'version':'targeted-accounting-checkpoint-v1','plan':plan,
        'plan_sha256':hashlib.sha256(a.plan.read_bytes()).hexdigest(),
        'population':population,'historical_diagnostic_cases':cases,
        'cohort':{'cohort_id':cohort['cohort_id'],'created_ms':cohort['created_ms'],
            'epoch_end_ms':(cohort['epoch']+1)*allocation['epoch_ms'],
            'group_counts':{g:len(v) for g,v in snapshot['groups'].items()},'cadence':cadence},
        'real_account_qualified':False,'real_strategy_validated':False,
        'limits':['historical diagnostic periods are separate from current population selection',
            'all reports use actual evidence availability at the announced cutoff',
            'scope measurement does not establish account profitability or complete attribution']}
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({'accounts':population['accounts_considered'],
    'current_scopes_measured':population['public_scopes_measured'],
    'historical_case_statuses':[r['status'] for r in cases]}))
