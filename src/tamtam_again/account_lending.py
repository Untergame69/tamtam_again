"""Observed borrow/supply balances, never implicitly added to spot equity."""
from .accounting import decimal


def summarize(payload, *, available_ms, as_of_ms, evidence_ref):
    if type(available_ms) is not int or type(as_of_ms) is not int or not 0<=available_ms<=as_of_ms or not evidence_ref:
        raise ValueError('Available lending evidence required')
    reasons=[];tokens=[];seen=set()
    rows=payload.get('tokenToState') if isinstance(payload,dict) else None
    if not isinstance(rows,list):reasons.append('tokenToState array absent')
    else:
        for row in rows:
            try:
                if not isinstance(row,list) or len(row)!=2 or type(row[0]) is not int or row[0]<0 or row[0] in seen:
                    raise ValueError('Invalid token entry')
                token,state=row;seen.add(token);components={}
                for kind in ('borrow','supply'):
                    basis=decimal(state[kind]['basis']);value=decimal(state[kind]['value'])
                    if basis<0 or value<0:raise ValueError('Negative lending magnitude')
                    components[kind]={'reported_basis':str(basis),'reported_value':str(value),
                                      'value_minus_basis':str(value-basis)}
                tokens.append({'token':token,**components})
            except (ValueError,TypeError,KeyError):
                reasons.append('malformed or duplicate lending token entry')
    return {'version':'reported-lending-components-v1','available_ms':available_ms,
        'event_ms':payload.get('time') if isinstance(payload,dict) and type(payload.get('time')) is int and 0<=payload['time']<=available_ms else None,
        'evidence_ref':evidence_ref,'status':'observed_components' if not reasons else 'unknown',
        'tokens':tokens,'unknown_reasons':sorted(set(reasons)),
        'reported_health':payload.get('health') if isinstance(payload,dict) else None,
        'equity':None,'economic_qualification':False,
        'limits':['amounts are token-native, never summed across tokens',
                  'value minus basis is an observed snapshot component, not period interest income',
                  'relation to spot balances and possible overlap requires verified accounting conventions',
                  'an empty response does not prove absence of debt outside this endpoint or address',
                  'local availability is not an economic timestamp'],
        'source_contract':'https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint'}


def collect_snapshot(store,client,network,address):
    from .discovery import protected_addresses
    from .providers.hyperliquid import ADDRESS_RE
    from .storage import utc_now
    from .account_adapter import SOURCE
    address=address.lower()
    if not ADDRESS_RE.fullmatch(address):raise ValueError('Public address required')
    if address in protected_addresses(store):raise ValueError('Reserved account excluded before request')
    if client.network!=network:raise ValueError('Client network mismatch')
    query={'type':'borrowLendUserState','user':address};requested=utc_now()
    payload=client.post_info(query)
    if not isinstance(payload,dict):raise ValueError('Lending state object required')
    inserted=store.save_observation(network=network,source=SOURCE,entity_type='account',
        entity_id=address,endpoint=query['type'],payload=payload,requested_at=requested,
        request_payload={**query,'transport':'rest','phase':'targeted_lending_inventory'},complete=False)
    return {'address':address,'observation_inserted':inserted,'economic_qualification':False}
