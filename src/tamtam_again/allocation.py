"""Prospective collection cohorts; economic/observation/execution statuses separate."""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib,json
from typing import Any
from .engine import canonical,fingerprint
from .discovery import protected_addresses

SCHEMA='''CREATE TABLE IF NOT EXISTS population_cohorts (
 cohort_id TEXT PRIMARY KEY,network TEXT NOT NULL,epoch INTEGER NOT NULL,
 created_ms INTEGER NOT NULL,policy_json TEXT NOT NULL,snapshot_json TEXT NOT NULL,
 UNIQUE(network,epoch,policy_json));'''
def validate_policy(policy):
    if not policy.get('version') or not policy.get('justification') or not policy.get('seed'):raise ValueError('Versioned allocation rationale required')
    for key in ('epoch_ms','max_deepen_epochs'):
        if type(policy.get(key)) is not int or policy[key]<1:raise ValueError('Invalid allocation duration budget')
    if set(policy.get('slots',{}))!={'explore','deepen','control_uniform','control_leaderboard'}:raise ValueError('Explicit research and control budgets required')
    if any(type(n) is not int or n<0 for n in policy['slots'].values()) or sum(policy['slots'].values())<1:raise ValueError('Invalid allocation slots')

def choose(rows:list[dict[str,Any]],policy:dict[str,Any], *,epoch:int) -> dict[str,Any]:
    validate_policy(policy)
    if len({r['address'] for r in rows})!=len(rows):raise ValueError('Unique candidate addresses required')
    eligible=[r for r in rows if not r.get('hard_blockers')]
    selected={};groups={};seed=policy['seed']+':'+str(epoch)
    def order(pool,group):return sorted(pool,key=lambda r:hashlib.sha256((seed+group+r['address']).encode()).hexdigest())
    def take(pool,group,ranked=False):
        available=[r for r in pool if r['address'] not in selected]
        if ranked:
            ordered=sorted(available,key=lambda r:(r['leaderboard_rank'],r['address']))
        elif group=='deepen':
            # Historical provider-curve evidence may prioritize further data
            # collection, but never affects controls, exploration, or validation.
            ordered=sorted(available,key=lambda r:(
                0 if r.get('historical_priority') else 1,
                r.get('historical_concentration') if r.get('historical_concentration') is not None else 2.0,
                -r.get('historical_positive_months',0),
                hashlib.sha256((seed+group+r['address']).encode()).hexdigest()))
        else:
            ordered=order(available,group)
        picked=ordered[:policy['slots'][group]]
        groups[group]=[r['address'] for r in picked]
        selected.update({r['address']:group for r in picked})
    # Controls assigned before adaptive prioritization; disjoint groups receive
    # the same REST profile. Public rank is a baseline, never trusted accounting.
    take([r for r in eligible if r.get('leaderboard_rank') is not None],'control_leaderboard',True)
    take(eligible,'control_uniform')
    take([r for r in eligible if (r.get('observed_scope') or r.get('historical_priority')) and r.get('consecutive_deepen_epochs',0)<policy['max_deepen_epochs']],'deepen')
    take(eligible,'explore')
    decisions=[]
    for r in sorted(rows,key=lambda r:r['address']):
        group=selected.get(r['address'])
        decisions.append({'address':r['address'],'group':group,'selected':group is not None,
            'performance':r.get('performance','unknown'),'observability':r.get('observability','unknown'),
            'reproducibility':r.get('reproducibility','unknown'),
            'hard_blockers':r.get('hard_blockers',[]),'adverse_results':r.get('adverse_results',[]),
            'unknowns':r.get('unknowns',[]),'evaluation_blockers':r.get('evaluation_blockers',[]),
            'evidence_refs':r.get('evidence_refs',[]),'leaderboard_rank':r.get('leaderboard_rank'),
            'consecutive_deepen_epochs':r.get('consecutive_deepen_epochs',0),
            'collection_question':'Can the observed account be reconciled over a complete comparable period?' if group=='deepen' else 'What public activity and account scope can be observed under the common REST policy?' if group else None,
            'wake_condition':{'next_allocation_epoch':epoch+1} if not group else {'next_rest_due_and_new_available_observations':True},
            'reason':('historical positive curve; prioritize coverage under bounded deepen budget' if group=='deepen' and r.get('historical_priority') else 'bounded '+group+' budget') if group else 'not allocated this epoch; evidence and identity retained',
            'historical_screen_status':r.get('historical_screen_status'),
            'historical_decision_ref':r.get('historical_decision_ref'),
            'next_action':('collect longer fills and ledger coverage; verify activity and flows' if group=='deepen' and r.get('historical_priority') else 'public REST inventory/accounting') if group else 'eligible at next epoch unless blocked',
            'economic_qualification':False})
    return {'epoch':epoch,'groups':groups,'decisions':decisions,
        'unfilled_slots':{g:policy['slots'][g]-len(groups[g]) for g in groups},
        'limits':['selection allocates collection, not profitability or AI promotion',
                  'uniform controls are conditional on the discovered population',
                  'leaderboard controls use the available selected ranking window',
                  'coverage and public fill count confer no permanent priority']}

def allocate_population(store,network:str,population_policy:dict[str,Any], *,now_ms:int):
    policy=population_policy['allocation'];validate_policy(policy)
    if sum(policy['slots'].values())>population_policy['max_rest_accounts']:raise ValueError('Allocation exceeds REST account budget')
    store.connection.executescript(SCHEMA);epoch=now_ms//policy['epoch_ms'];policy_json=canonical(policy)
    prior=store.connection.execute('select * from population_cohorts where network=? and epoch=? and policy_json=?',(network,epoch,policy_json)).fetchone()
    blocked=protected_addresses(store)
    blocked.update(r['address'] for r in store.candidates(network) if r['status']=='tracked')
    if prior:snapshot=json.loads(prior['snapshot_json']);cohort_id=prior['cohort_id']
    else:
        cutoff=datetime.fromtimestamp(now_ms/1000,timezone.utc).isoformat()
        reports={}
        for r in store.connection.execute('select report_id,address,available_ms from account_scope_reports where network=? and available_ms<=? order by available_ms',(network,now_ms)):reports[r['address']]=dict(r)
        ranks={}
        latest=store.connection.execute('select snapshot_id from whale_rankings where network=? and observed_at<=? and window=? and metric=? order by observed_at desc limit 1',(network,cutoff,policy.get('leaderboard_window','day'),'pnl')).fetchone()
        if latest:
            ranks={r['address']:r['rank'] for r in store.connection.execute('select address,rank from whale_rankings where snapshot_id=? and window=? and metric=?',(latest[0],policy.get('leaderboard_window','day'),'pnl'))}
        previous=[json.loads(r[0]) for r in store.connection.execute('select snapshot_json from population_cohorts where network=? and epoch<? and policy_json=? order by epoch desc limit ?',(network,epoch,policy_json,policy['max_deepen_epochs']))]
        history={}
        if store.connection.execute("select 1 from sqlite_master where type='table' and name='population_historical_decisions'").fetchone():
            for item in store.connection.execute(
                    'select decision_id,address,status,decision_json from population_historical_decisions '
                    'where network=? and as_of_ms<=? order by as_of_ms,decision_id',(network,now_ms)):
                # Keep the latest decision per address; every earlier decision remains archived.
                try: decision=json.loads(item['decision_json'])
                except (TypeError,ValueError): continue
                history[item['address'].lower()]={'decision_id':item['decision_id'],'status':item['status'],'decision':decision}
        rows=[]
        for candidate in store.candidates(network):
            if int(datetime.fromisoformat(candidate['added_at']).timestamp()*1000)>now_ms:continue
            address=candidate['address'];report=reports.get(address);consecutive=0
            for old in previous:
                if address not in old['groups']['deepen']:break
                consecutive+=1
            h=history.get(address.lower(),{});hd=h.get('decision',{})
            monthly=hd.get('weekly_monthly_consistency',{}).get('180',{}).get('month',{})
            historical_priority=h.get('status') in ('credible_deep_dive_candidate','reported_positive_pending_activity')
            rows.append({'address':address,'hard_blockers':['reserved pilot/direct subscription'] if address in blocked or candidate['status']=='tracked' else [],
                'observed_scope':bool(report),'consecutive_deepen_epochs':consecutive,'leaderboard_rank':ranks.get(address),
                'historical_priority':historical_priority,
                'historical_concentration':float(monthly['largest_positive_bucket_share_of_positive_delta']) if monthly.get('largest_positive_bucket_share_of_positive_delta') is not None else None,
                'historical_positive_months':monthly.get('positive_observed_buckets',0),
                'historical_screen_status':h.get('status'),
                'historical_decision_ref':'population_historical_decisions:'+h['decision_id'] if h else None,
                'evidence_refs':['candidates:'+network+':'+address]+(['account_scope_reports:'+report['report_id']] if report else [])+(['whale_rankings:'+latest[0]] if address in ranks else []),
                'performance':'unknown','observability':'inventory_observed' if report else 'unknown',
                'reproducibility':'unproven','unknowns':['economic performance','historical completeness','reproducibility'],
                'evaluation_blockers':['complete accounting and execution evidence required']})
        snapshot=choose(rows,policy,epoch=epoch);snapshot['created_ms']=now_ms
        snapshot['leaderboard_snapshot_id']=latest[0] if latest else None
        cohort_id=fingerprint({'network':network,'epoch':epoch,'policy':policy,'snapshot':snapshot})
        store.connection.execute('insert or ignore into population_cohorts values (?,?,?,?,?,?)',(cohort_id,network,epoch,now_ms,policy_json,canonical(snapshot)));store.connection.commit()
        winner=store.connection.execute('select cohort_id,snapshot_json from population_cohorts where network=? and epoch=? and policy_json=?',(network,epoch,policy_json)).fetchone()
        cohort_id=winner['cohort_id'];snapshot=json.loads(winner['snapshot_json'])
    desired={address for group in snapshot['groups'].values() for address in group}-blocked
    # Running leases finish normally. Newly admitted slots wait if these running
    # jobs would transiently exceed the fixed active-account budget.
    store.connection.execute('begin immediate')
    try:
        existing={r['address']:r for r in store.connection.execute('select * from population_accounts where network=?',(network,))}
        running_outside=sum(r['status']=='running' and a not in desired for a,r in existing.items())
        running={a for a,r in existing.items() if r['status']=='running'}
        admitted=sorted(desired&running)+sorted(desired-running)[:max(0,population_policy['max_rest_accounts']-len(running))]
        for address,row in existing.items():
            if address not in admitted and row['status']!='running':store.connection.execute("update population_accounts set status='retired' where network=? and address=?",(network,address))
        for address in admitted:
            if address in existing:
                store.connection.execute("update population_accounts set policy_json=?,status=case when status='retired' then 'scheduled' else status end,next_due_ms=case when status='retired' then ? else next_due_ms end where network=? and address=?",(canonical(population_policy),now_ms,network,address))
            else:
                store.connection.execute('insert into population_accounts values (?,?,?,?,?,?,NULL,NULL,NULL)',(network,address,canonical(population_policy),'scheduled',population_policy['default_poll_seconds'],now_ms))
        store.connection.commit()
    except BaseException:store.connection.rollback();raise
    return {'cohort_id':cohort_id,'groups':snapshot['groups'],'admitted_accounts':len(admitted),
            'running_outside_cohort':running_outside,'direct_slots_changed':False,
            'economic_qualification':False,'unfilled_slots':snapshot['unfilled_slots']}
