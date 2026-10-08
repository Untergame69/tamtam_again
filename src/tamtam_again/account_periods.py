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
            'rejected_observations':rejected,
            'conflicting_timestamps':[t for t,v in points.items() if v['conflict']],
            'status':'periods_available' if periods else 'awaiting_two_timestamped_valuations',
            'limits':['periods differ across accounts; do not rank unaligned returns',
                      'observed boundaries do not prove event coverage or consolidated capital']}
