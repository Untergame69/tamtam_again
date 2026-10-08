"""One targeted public retention witness; no scheduler or budget rearm."""
from .discovery import protected_addresses
from .providers.hyperliquid import ADDRESS_RE
from .storage import utc_now
from .account_adapter import SOURCE


def collect_witness(store,client,network,address):
    address=address.lower()
    if not ADDRESS_RE.fullmatch(address):raise ValueError('Public address required')
    if address in protected_addresses(store):raise ValueError('Reserved account excluded before request')
    if client.network!=network:raise ValueError('Client network mismatch')
    query={'type':'userFills','user':address,'aggregateByTime':False}
    requested=utc_now();rows=client.post_info(query)
    if not isinstance(rows,list):raise ValueError('Latest fills must be an array')
    identity=store.save_observation(network=network,source=SOURCE,entity_type='account',
        entity_id=address,endpoint='userFills',payload=rows,requested_at=requested,
        request_payload={**query,'transport':'rest','phase':'targeted_retention_witness'},
        record_count=len(rows),complete=False)
    return {'address':address,'requested_at':requested,'observation_result':identity,
            'fills_returned':len(rows),'scope':'retention witness only; no economic qualification'}
