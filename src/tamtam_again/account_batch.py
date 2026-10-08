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
