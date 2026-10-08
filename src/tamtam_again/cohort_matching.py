"""Prospective matched collection witnesses. No PnL input or qualification claim."""
from __future__ import annotations
import hashlib,json,math,time
from .discovery import fingerprint,protected_addresses


def validate_policy(policy):
    if policy.get('version')!='matched-collection-v1' or not policy.get('seed') or not policy.get('justification'):
        raise ValueError('Version, seed and matching rationale required')
    for key in ('max_age_ms','minimum_activity_window_seconds','max_pairs'):
        if type(policy.get(key)) is not int or policy[key]<=0:raise ValueError('Positive matching budget required')
    cuts=policy.get('activity_rate_cuts',[])
    if not cuts or any(type(x) not in (int,float) or not math.isfinite(x) or x<=0 for x in cuts) or cuts!=sorted(set(cuts)):
        raise ValueError('Explicit increasing activity rate strata required')
    ratio=policy.get('maximum_window_ratio')
    if type(ratio) not in (int,float) or not math.isfinite(ratio) or ratio<1:
        raise ValueError('Explicit activity-window comparability required')


def features(payload,policy):
    activity=payload.get('activity',{});rate=activity.get('fills_per_second');window=activity.get('window_seconds')
    if (type(rate) not in (int,float) or not math.isfinite(rate) or rate<0 or
        type(window) not in (int,float) or not math.isfinite(window) or window<policy['minimum_activity_window_seconds']):
        return None
    markets=payload.get('markets');mode=payload.get('mode');dexes=payload.get('perp_dexes_observed')
    cadence=payload.get('poll_interval_seconds');coverage=payload.get('fill_coverage')
    if not isinstance(markets,list) or not markets or not all(isinstance(m,str) and m for m in markets):return None
    if not isinstance(mode,str) or not mode or not isinstance(dexes,list) or not dexes:return None
    if type(cadence) is not int or cadence<=0 or not isinstance(coverage,str) or not coverage:return None
    if type(payload.get('spot_observed')) is not bool:return None
    # Unknown historical coverage stays unknown. Matching equal unknown coverage
    # compares observation conditions, never establishes economic completeness.
    return {'markets':sorted(set(markets)), 'mode':mode,'dexes':sorted(set(dexes)),
            'spot_observed':payload['spot_observed'],'poll_interval_seconds':cadence,
            'fill_coverage':coverage,'activity_rate_stratum':sum(rate>=cut for cut in policy['activity_rate_cuts']),
            'activity_window_seconds':window}


def compatible(left,right,policy):
    exact=('mode','dexes','spot_observed','poll_interval_seconds','fill_coverage','activity_rate_stratum')
    if any(left[k]!=right[k] for k in exact):return []
    a,b=left['activity_window_seconds'],right['activity_window_seconds']
    if max(a,b)/min(a,b)>policy['maximum_window_ratio']:return []
    return sorted(set(left['markets'])&set(right['markets']))


def match(rows,policy,*,cutoff_ms):
    validate_policy(policy)
    if type(cutoff_ms) is not int or cutoff_ms<0:raise ValueError('Explicit causal cutoff required')
    if len({r['address'] for r in rows})!=len(rows):raise ValueError('Unique matching accounts required')
    eligible={};excluded=[]
    for row in sorted(rows,key=lambda r:r['address']):
        available=row.get('available_ms')
        reason=None
        if type(available) is not int or not 0<=available<=cutoff_ms:reason='feature unavailable at cutoff'
        elif cutoff_ms-available>policy['max_age_ms']:reason='feature too old for policy'
        elif not row.get('evidence_ref'):reason='missing feature provenance'
        f=features(row.get('payload',{}),policy) if reason is None else None
        if f is None and reason is None:reason='missing comparable observation features'
        if row.get('group') not in ('explore','deepen','control_uniform','control_leaderboard'):reason='outside declared cohort groups'
        if reason:excluded.append({'address':row['address'],'reason':reason})
        else:eligible[row['address']]={**row,'features':f}
    targets=[a for a,r in eligible.items() if r['group'] in ('explore','deepen')]
    controls=[a for a,r in eligible.items() if r['group'].startswith('control_')]
    def order(values,kind):
        return sorted(values,key=lambda a:hashlib.sha256((policy['seed']+kind+a).encode()).hexdigest())
    targets=order(targets,'target');controls=order(controls,'control')
    edges={a:[b for b in controls if compatible(eligible[a]['features'],eligible[b]['features'],policy)] for a in targets}
    # Augmenting paths maximize the number of disjoint comparable pairs, then
    # apply the declared cap. A greedy first match could strand valid targets.
    assigned={}
    def augment(a,seen):
        for b in edges[a]:
            if b in seen:continue
            seen.add(b)
            if b not in assigned or augment(assigned[b],seen):
                assigned[b]=a;return True
        return False
    for a in targets:augment(a,set())
    pairs=[]
    for b,a in sorted(assigned.items(),key=lambda item:targets.index(item[1]))[:policy['max_pairs']]:
        markets=compatible(eligible[a]['features'],eligible[b]['features'],policy)
        pairs.append({'selected_address':a,'control_address':b,
          'selected_group':eligible[a]['group'],'control_group':eligible[b]['group'],
          'comparison_market':order(markets,'market')[0],
          'shared_markets':markets,'selected_features':eligible[a]['features'],
          'control_features':eligible[b]['features'],
          'evidence_refs':[eligible[a]['evidence_ref'],eligible[b]['evidence_ref']],
          'knowledge_available_ms':[eligible[a]['available_ms'],eligible[b]['available_ms']]})
    paired={p['selected_address'] for p in pairs}
    return {'cutoff_ms':cutoff_ms,'pairs':pairs,'excluded':excluded,
      'unmatched_selected':[{'address':a,'compatible_controls':len(edges[a]),
        'reason':'no compatible control' if not edges[a] else 'disjoint control or pair budget exhausted'} for a in targets if a not in paired],
      'economic_qualification':False,
      'limits':['matching uses observed activity, not true activity under incomplete retention',
        'equal unknown coverage does not prove complete histories',
        'market-level comparisons do not imply whole-account risk equivalence',
        'unobserved external hedges, capital, leverage and execution advantages remain uncontrolled',
        'not randomized account treatment or proof of a selection advantage']}


def register(store,network,cohort_id,policy,*,start_ms,end_ms):
    """Freeze current evidence and future comparison bounds using the real clock."""
    validate_policy(policy);stamp=int(time.time()*1000)
    identity=fingerprint({'network':network,'cohort_id':cohort_id,'policy':policy,
                          'start_ms':start_ms,'end_ms':end_ms})
    store.connection.execute('create table if not exists matched_collection_cohorts '
        '(matching_id text primary key,network text not null,cohort_id text not null,'
        'registered_ms integer not null,start_ms integer not null,end_ms integer not null,snapshot_json text not null)')
    prior=store.connection.execute('select snapshot_json from matched_collection_cohorts where matching_id=?',(identity,)).fetchone()
    if prior:return {'matching_id':identity,**json.loads(prior[0]),'replayed':True}
    if type(start_ms) is not int or type(end_ms) is not int or not stamp<start_ms<end_ms:
        raise ValueError('Matching must be registered before future comparison')
    cohort=store.connection.execute('select * from population_cohorts where cohort_id=? and network=?',(cohort_id,network)).fetchone()
    if not cohort or cohort['created_ms']>stamp:raise ValueError('Available dated cohort required')
    snapshot=json.loads(cohort['snapshot_json']);blocked=protected_addresses(store)
    rows=[]
    # Exclusion before any payload read; no protected archives or pilot results.
    for group,addresses in snapshot['groups'].items():
        for address in addresses:
            if address.lower() in blocked:continue
            r=store.connection.execute('select report_id,available_ms,payload_json from account_scope_reports where network=? and address=? and available_ms<=? order by available_ms desc,report_id limit 1',(network,address,stamp)).fetchone()
            rows.append({'address':address,'group':group,'available_ms':r['available_ms'] if r else None,
                'evidence_ref':'account_scope_reports:'+r['report_id'] if r else None,
                'payload':json.loads(r['payload_json']) if r else {}})
    result=match(rows,policy,cutoff_ms=stamp)
    result.update({'network':network,'cohort_id':cohort_id,'policy':policy,
        'start_ms':start_ms,'end_ms':end_ms,'registered_ms':stamp})
    store.connection.execute('insert or ignore into matched_collection_cohorts values(?,?,?,?,?,?,?)',
        (identity,network,cohort_id,stamp,start_ms,end_ms,json.dumps(result,sort_keys=True)))
    store.connection.commit()
    winner=store.connection.execute('select snapshot_json from matched_collection_cohorts where matching_id=?',(identity,)).fetchone()
    return {'matching_id':identity,**json.loads(winner[0]),'replayed':False}
