"""Select observed valuation periods without ranking their economic results."""
from __future__ import annotations
from datetime import datetime, timezone
import json
from .account_adapter import SOURCE, millis
from .discovery import protected_addresses
from .storage import decode_observation_payload


def observed_periods(store, network, address, *, as_of_ms, scope_id='perp:'):
    address=address.lower()
    if address in protected_addresses(store):
        raise ValueError('Reserved pilot account excluded before raw query')
    if type(as_of_ms) is not int or as_of_ms<0 or not scope_id.startswith('perp:'):
        raise ValueError('Explicit available decision time and perp scope required')
    from .research_memory import authorized_account_history
    if not authorized_account_history(store,network,address,as_of_ms):raise ValueError('Account history reserved at requested cutoff')
    points={}; rejected=[]
    for row in store.connection.execute(
        'select * from raw_observations where network=? and entity_type=\'account\' '
        'and entity_id=? and source=? and endpoint=\'clearinghouseState\' '
        'and observed_at<=? order by observed_at,observation_id',
        (network,address,SOURCE,datetime.fromtimestamp(as_of_ms/1000,timezone.utc).isoformat())):
        received=millis(row['observed_at'])
        if received>as_of_ms:continue
        query=json.loads(row['request_json'])
        if 'perp:'+query.get('dex','')!=scope_id:continue
        payload=decode_observation_payload(row);ref='raw_observations:'+str(row['observation_id'])
        stamp=payload.get('time') if isinstance(payload,dict) else None
        if type(stamp) is not int or not 0<=stamp<=received:
            rejected.append({'evidence_ref':ref,'reason':'valuation event time unknown or inconsistent'})
            continue
        if not isinstance(payload.get('assetPositions'),list) or 'accountValue' not in payload.get('marginSummary',{}):
            rejected.append({'evidence_ref':ref,'reason':'valuation or positions absent'})
            continue
        # Retain conflicts as unusable boundaries; never pick the nicer valuation.
        canonical=json.dumps(payload,sort_keys=True)
        if stamp in points and points[stamp]['payload']!=canonical:
            points[stamp]['conflict']=True
        else:
            points.setdefault(stamp,{'payload':canonical,'conflict':False,'evidence_ref':ref,'available_ms':received})
    usable=sorted(t for t,v in points.items() if not v['conflict'])
    periods=[{'start_ms':left,'end_ms':right,'duration_ms':right-left,
              'boundary_evidence_refs':[points[left]['evidence_ref'],points[right]['evidence_ref']],
              'available_ms':max(points[left]['available_ms'],points[right]['available_ms']),
              'coverage_status':'unknown'} for left,right in zip(usable,usable[1:])]
    return {'version':'adjacent-observed-valuations-v1','address':address,
            'scope_id':scope_id,'as_of_ms':as_of_ms,'periods':periods,
            'valuation_boundaries':[{'event_ms':t,'evidence_ref':points[t]['evidence_ref'],
                'available_ms':points[t]['available_ms']} for t in usable],
            'rejected_observations':rejected,
            'conflicting_timestamps':[t for t,v in points.items() if v['conflict']],
            'status':'periods_available' if periods else 'awaiting_two_timestamped_valuations',
            'limits':['periods differ across accounts; do not rank unaligned returns',
                      'observed boundaries do not prove event coverage or consolidated capital']}


def validate_period_policy(policy):
    fields={'version','policy_id','justification','target_duration_ms',
            'start_tolerance_ms','max_end_age_ms'}
    if (not isinstance(policy,dict) or set(policy)!=fields
            or policy['version']!='observed-period-policy-v1'
            or any(not isinstance(policy[k],str) or not policy[k].strip()
                   for k in ('policy_id','justification'))):
        raise ValueError('Explicit justified observed-period policy required')
    for key in ('target_duration_ms','start_tolerance_ms','max_end_age_ms'):
        if type(policy[key]) is not int or policy[key]<0:
            raise ValueError('Explicit nonnegative period parameter required: '+key)
    if policy['target_duration_ms']<1 or policy['start_tolerance_ms']>=policy['target_duration_ms']:
        raise ValueError('Positive target duration and smaller boundary tolerance required')


def select_observed_period(observed,policy):
    """Choose exact observed boundaries by time only, before any PnL calculation."""
    from .engine import fingerprint
    validate_period_policy(policy)
    points={p['event_ms']:p for p in observed['valuation_boundaries']}
    result={'rule':'nearest-observed-duration-v1','policy':policy,
        'policy_fingerprint':fingerprint(policy),'as_of_ms':observed['as_of_ms'],
        'chosen_period':None,'interpolation_applied':False,
        'conflicting_timestamps':observed['conflicting_timestamps'],
        'limits':['time-only selection; no PnL or coverage-based fallback',
                  'exact observed boundaries; individual event periods remain different',
                  'duration similarity does not make returns comparable or prove completeness']}
    if len(points)<2:
        return {**result,'status':'awaiting_two_timestamped_valuations',
            'next_action':'collect two coherent timestamped valuations; do not use receipt times as valuations'}
    end=max(points)
    if observed['as_of_ms']-end>policy['max_end_age_ms']:
        return {**result,'status':'awaiting_recent_valuation','latest_event_ms':end,
            'next_action':'collect a timestamped valuation within the policy end-age budget'}
    target=end-policy['target_duration_ms']
    candidates=[stamp for stamp in points if stamp<end and abs(stamp-target)<=policy['start_tolerance_ms']]
    if not candidates:
        return {**result,'status':'awaiting_duration_boundary','target_start_ms':target,
            'latest_event_ms':end,'next_action':'accumulate timestamped valuations spanning the declared duration; do not substitute a shorter profitable interval'}
    # Ties choose the earlier bound; never examine financial results.
    start=min(candidates,key=lambda stamp:(abs(stamp-target),stamp))
    chosen={'start_ms':start,'end_ms':end,'duration_ms':end-start,
        'target_start_ms':target,'start_distance_ms':abs(start-target),
        'boundary_evidence_refs':[points[start]['evidence_ref'],points[end]['evidence_ref']],
        'available_ms':max(points[start]['available_ms'],points[end]['available_ms']),
        'coverage_status':'unknown'}
    return {**result,'status':'period_selected','chosen_period':chosen,'next_action':'reconcile the selected period without changing its boundaries after inspecting results'}
