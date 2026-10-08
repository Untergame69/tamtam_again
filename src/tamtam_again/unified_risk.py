"""Collateral-native unified-account maintenance ratio, never a portfolio valuation."""
from .accounting import decimal


def unified_ratio(*,mode,spot,dex_states,catalog,expected_dexes,event_ms,as_of_ms):
    missing=[];pools={};refs=[]
    if mode!='unifiedAccount':missing.append('ratio applies only to unifiedAccount, not portfolio margin or legacy modes')
    if type(event_ms) is not int or type(as_of_ms) is not int or not 0<=event_ms<=as_of_ms:
        raise ValueError('Explicit valuation timestamp/cutoff required')
    if not expected_dexes or len(set(expected_dexes))!=len(expected_dexes):raise ValueError('Distinct expected DEX scope required')
    def available(x,label):
        valid=(x.get('event_ms')==event_ms and type(x.get('available_ms')) is int and event_ms<=x['available_ms']<=as_of_ms and bool(x.get('evidence_ref')))
        if not valid:missing.append('unaligned or unavailable '+label)
        else:refs.append(x['evidence_ref'])
        return valid
    if not catalog or type(catalog.get('available_ms')) is not int or catalog['available_ms']>event_ms or not catalog.get('evidence_refs'):
        missing.append('collateral catalog unavailable at economic timestamp')
    balances={}
    if available(spot,'spot balances'):
        try:
            for b in spot['balances']:
                token=b['token'];total=decimal(b['total'])
                if type(token) is not int or token in balances:raise ValueError('Duplicate/invalid token')
                balances[token]=total  # total already includes hold; never add hold.
        except (KeyError,TypeError,ValueError):missing.append('spot balances malformed or conflicting')
    seen=set()
    for state in dex_states:
        dex=state.get('dex')
        if dex not in expected_dexes or dex in seen:
            missing.append('unexpected or duplicate DEX state');continue
        seen.add(dex)
        if not available(state,'DEX '+dex):continue
        mapping=(catalog or {}).get('dexes',{}).get(dex,{})
        token=mapping.get('collateral_token')
        if type(token) is not int or not mapping.get('evidence_refs'):
            missing.append('unknown collateral token: '+dex);continue
        try:
            cross=decimal(state['crossMaintenanceMarginUsed']);isolated=decimal(0)
            if cross<0:raise ValueError('Negative maintenance requirement')
            for p in state['positions']:
                if p['leverage']['type'] not in ('cross','isolated'):raise ValueError('Unknown margin mode')
                margin=decimal(p['marginUsed'])
                if margin<0:raise ValueError('Negative isolated allocation')
                if p['leverage']['type']=='isolated':isolated+=margin
            pool=pools.setdefault(token,{'cross':decimal(0),'isolated':decimal(0)})
            pool['cross']+=cross;pool['isolated']+=isolated
        except (KeyError,TypeError,ValueError):missing.append('margin components unknown: '+dex)
    if seen!=set(expected_dexes):missing.append('expected DEX states absent')
    ratios=[];details=[]
    for token,pool in sorted(pools.items()):
        total=balances.get(token)
        if total is None:
            missing.append('collateral balance absent: '+str(token));continue
        free=total-pool['isolated'];ratio=None
        if free<=0:
            if pool['cross']>0:missing.append('nonpositive cross collateral with maintenance requirement: '+str(token))
        else:ratio=pool['cross']/free;ratios.append(ratio)
        details.append({'collateral_token':token,'spot_total':str(total),'isolated_margin':str(pool['isolated']),
            'cross_available':str(free),'cross_maintenance':str(pool['cross']),'ratio':str(ratio) if ratio is not None else None})
    return {'version':'unified-maintenance-ratio-v1','status':'unknown' if missing else 'evidenced_inputs',
        'event_ms':event_ms,'as_of_ms':as_of_ms,'ratio':None if missing else str(max(ratios,default=decimal(0))),
        'collateral_pools':details,'unknown_reasons':sorted(set(missing)),'evidence_refs':refs,
        'limits':['caller must establish full DEX perimeter and timestamp alignment',
            'collateral-native maintenance ratio is not equity, PnL, portfolio margin ratio or profitability',
            'nonpositive available collateral is diagnostic, never silently interpreted as zero risk']}
