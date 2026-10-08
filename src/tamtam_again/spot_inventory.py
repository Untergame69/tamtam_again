"""Whole-account spot components; no pricing or duplicate collateral valuation."""
from .accounting import decimal


def inventory(payload):
    unknown=[];balances=[];seen=set()
    def amount(value):
        n=decimal(value)
        if n==0:return '0'
        text=format(n,'f')
        return text.rstrip('0').rstrip('.') if '.' in text else text
    rows=payload.get('balances') if isinstance(payload,dict) else None
    if not isinstance(rows,list):unknown.append('spot balances absent')
    else:
        for row in rows:
            try:
                token=row['token']
                if type(token) is not int or token<0 or token in seen or not isinstance(row.get('coin'),str) or not row['coin']:
                    raise ValueError('Invalid token identity')
                seen.add(token)
                entry={'token':token,'coin':row['coin']}
                for key in ('total','hold','entryNtl','borrowed','supplied','ltv'):
                    if key in row:entry[key]=amount(row[key])
                if 'total' not in entry:raise ValueError('Total absent')
                # Negative total/hold can occur under portfolio margin.
                for key in ('borrowed','supplied','ltv'):
                    if key in entry and decimal(entry[key])<0:raise ValueError('Negative magnitude')
                balances.append(entry)
            except (KeyError,ValueError,TypeError):unknown.append('malformed or duplicate spot token')
    ratio=None;enabled=None
    if isinstance(payload,dict):
        enabled=payload.get('portfolioMarginEnabled') if type(payload.get('portfolioMarginEnabled')) is bool else None
        if 'portfolioMarginRatio' in payload:
            try:
                ratio=amount(payload['portfolioMarginRatio'])
                if decimal(ratio)<0:raise ValueError('Negative ratio')
            except (ValueError,TypeError):ratio=None;unknown.append('portfolio margin ratio malformed')
    return {'version':'public-spot-inventory-v1','status':'observed_components' if not unknown else 'unknown',
            'balances':sorted(balances,key=lambda x:x['token']),
            'reported_portfolio_margin_enabled':enabled,'reported_portfolio_margin_ratio':ratio,
            'unknown_reasons':sorted(set(unknown)),
            'equity':None,'economic_qualification':False,
            'limits':['token-native total, hold, borrowed and supplied are reported components, not additive independent assets',
                      'negative totals and holds retained; hold never added to total',
                      'reported ratio is liquidation-risk telemetry, not return or independently reconstructed risk',
                      'no spot prices, economic alignment or debt/spot overlap inferred']}
