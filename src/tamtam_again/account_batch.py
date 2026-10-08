"""Population accounting at a shared decision cutoff, excluding reserved accounts."""
from .account_adapter import report_account
from .discovery import protected_addresses


def report_population(store, network, start_ms, end_ms, *, as_of_ms):
    if any(type(x) is not int for x in (start_ms, end_ms, as_of_ms)) or not 0 <= start_ms < end_ms <= as_of_ms:
        raise ValueError('Explicit available accounting period required')
    blocked = {address.lower() for address in protected_addresses(store)}
    addresses = [row[0] for row in store.connection.execute(
        'select distinct lower(address) from account_scope_reports '
        'where network=? and available_ms<=? order by lower(address)', (network, as_of_ms))]
    reports, exclusions, failures = [], [], []
    for address in addresses:
        if address in blocked:
            exclusions.append({'address': address, 'reason': 'reserved pilot account; no raw query'})
            continue
        try:
            reports.append(report_account(store, network, address, start_ms, end_ms, as_of_ms=as_of_ms))
        except (ValueError, TypeError, KeyError) as exc:
            # Do not expose malformed payload contents through exception messages.
            failures.append({'address': address, 'status': 'evidence_error',
                             'error_type': type(exc).__name__,
                             'next_action': 'inspect and correct accounting evidence; no economic qualification'})
    return {'schema_version': 1, 'network': network, 'as_of_ms': as_of_ms,
            'period': {'start_ms': start_ms, 'end_ms': end_ms}, 'accounts': reports,
            'accounts_inventoried': len(addresses), 'accounts_reported': len(reports),
            'excluded_accounts': exclusions, 'failed_accounts': failures,
            'economically_validated': sum(r.get('economic_validation') is True for r in reports),
            'synthetic': False,
            'scope': 'population REST evidence; common period and cutoff; incomplete coverage remains unknown'}


def qualify_observed_population(store,network,*,as_of_ms,period_policy=None):
    """Apply the same latest-adjacent-period rule to every inventoried candidate.

    Selection is by availability and mode, never by measured PnL. Per-account
    periods are announced explicitly and must not be ranked as aligned returns.
    """
    import json
    from .account_periods import observed_periods,select_observed_period,validate_period_policy
    if period_policy is not None:validate_period_policy(period_policy)
    if type(as_of_ms) is not int or as_of_ms<0:raise ValueError('Explicit decision cutoff required')
    blocked=protected_addresses(store);latest={}
    for r in store.connection.execute('select address,available_ms,payload_json from account_scope_reports '
            'where network=? and available_ms<=? order by available_ms,address',(network,as_of_ms)):
        if r['address'] in blocked:continue
        latest[r['address']]=r
    reports=[];failures=[];representatives={}
    for address,row in sorted(latest.items()):
        mode=json.loads(row['payload_json']).get('mode','unknown')
        try:
            periods=observed_periods(store,network,address,as_of_ms=as_of_ms)
            if not periods['periods']:
                reports.append({'address':address,'account_mode':mode,'status':periods['status'],
                    'period_selection':periods,'economic_validation':False})
                continue
            selection=select_observed_period(periods,period_policy) if period_policy is not None else None
            if selection is not None and selection['status']!='period_selected':
                reports.append({'address':address,'account_mode':mode,'status':selection['status'],
                    'period_selection':selection,'economic_validation':False})
                continue
            chosen=selection['chosen_period'] if selection is not None else periods['periods'][-1]
            report=report_account(store,network,address,chosen['start_ms'],chosen['end_ms'],as_of_ms=as_of_ms)
            report['period_selection']=selection if selection is not None else {'rule':'latest-adjacent-observed-valuations-v1',**chosen}
            reports.append(report)
            # Contrast cases remain sample descriptors, never a population cap.
            previous=representatives.get(mode)
            if previous is None or (row['available_ms'],address)>(previous['inventory_available_ms'],previous['address']):
                representatives[mode]={'address':address,'inventory_available_ms':row['available_ms']}
        except (ValueError,TypeError,KeyError):
            failures.append({'address':address,'status':'evidence_error','next_action':'correct unsupported or malformed evidence; do not qualify'})
    return {'version':'observed-population-qualification-v1','network':network,'as_of_ms':as_of_ms,
        'period_rule':'latest adjacent timestamped validator-perp valuations available at cutoff' if period_policy is None else 'latest usable end and start closest to the declared target duration, using exact observed boundaries',
        **({'period_policy':period_policy} if period_policy is not None else {}),
        'accounts':reports,'failed_accounts':failures,'contrast_cases':representatives,
        'accounts_considered':len(latest),
        'public_scopes_measured':sum(r.get('status')=='public_scope_measured' for r in reports),
        'economically_validated':sum(r.get('economic_validation') is True for r in reports),
        'limits':['individual periods differ; no cross-account return ranking',
            'contrast cases selected by mode and inventory availability, never financial result',
            'public scope measurements do not qualify whole accounts or validate strategies'],
        'synthetic':False}
