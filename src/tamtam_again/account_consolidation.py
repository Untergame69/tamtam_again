"""Consolidate evidenced independent capital pools at one economic timestamp."""
from __future__ import annotations
from .accounting import decimal


def consolidate_equity(valuations, *, event_ms, as_of_ms, currency,
                       expected_scope_ids, perimeter_evidence_refs):
    if not 0<=event_ms<=as_of_ms or not currency:
        raise ValueError('Explicit available valuation time and currency required')
    if not expected_scope_ids or len(set(expected_scope_ids))!=len(expected_scope_ids):
        raise ValueError('Distinct expected capital scopes required')
    missing=[];scopes={};groups={};total=decimal(0)
    if not perimeter_evidence_refs:missing.append('whole-account perimeter unproven')
    for value in valuations:
        scope=value.get('scope_id')
        if scope not in expected_scope_ids:
            missing.append('unexpected valuation scope');continue
        if scope in scopes:
            missing.append('duplicate valuation scope');continue
        scopes[scope]=value
        if value.get('event_ms')!=event_ms:
            missing.append('valuation timestamps not aligned: '+scope);continue
        available=value.get('available_ms')
        if type(available) is not int or not event_ms<=available<=as_of_ms:
            missing.append('valuation unavailable: '+scope);continue
        group=value.get('capital_pool_id')
        if not group or not value.get('capital_pool_evidence_ref') or not value.get('evidence_ref'):
            missing.append('capital pool or valuation provenance unproven: '+scope);continue
        if group in groups:
            missing.append('overlapping capital pool: '+str(group));continue
        groups[group]=scope
        try:
            equity=decimal(value['equity'])
            if value.get('currency')!=currency:
                fx=value.get('conversion',{})
                quote=fx.get('quote_ms');received=fx.get('available_ms')
                rate=decimal(fx['rate'])
                if (fx.get('currency')!=currency or not fx.get('evidence_ref')
                    or type(quote) is not int or quote!=event_ms
                    or type(received) is not int or not quote<=received<=as_of_ms or rate<=0):
                    raise ValueError('Invalid conversion')
                equity*=rate
            total+=equity
        except (KeyError,ValueError,TypeError):
            missing.append('equity or contemporaneous conversion unknown: '+scope)
    for scope in expected_scope_ids:
        if scope not in scopes:missing.append('valuation absent: '+scope)
    return {'version':'independent-capital-pools-v1','event_ms':event_ms,
            'as_of_ms':as_of_ms,'currency':currency,
            'status':'evidenced_inputs' if not missing else 'unknown',
            'equity':str(total) if not missing else None,
            'unknown_reasons':sorted(set(missing)),
            'scope_ids':list(expected_scope_ids),
            'perimeter_evidence_refs':perimeter_evidence_refs,
            'limits':['caller must substantiate independent capital-pool assignments',
                      'shared collateral requires one authoritative pool valuation, not per-DEX sums',
                      'this valuation does not establish period returns or off-platform completeness']}
