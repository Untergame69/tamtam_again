"""Whole-address observed accounting components, currency-separated, no capital sum."""
from .accounting import reconcile_period


def summarize(events,ledger_events,*,address,start_ms,end_ms,as_of_ms,account_mode):
    groups={};unassigned=[]
    for event in events+ledger_events:
        if not start_ms<event['event_ms']<=end_ms or event['available_ms']>as_of_ms:continue
        currency=event.get('pnl_currency') if event['kind']=='fill' else event.get('currency')
        if not currency or currency=='UNVERIFIED_DEX_CURRENCY':
            unassigned.append({'event_id':event['id'],'evidence_ref':event.get('evidence_ref'),
                               'reason':'event denomination unavailable'});continue
        scope='hypercore:'+address.lower()+':currency:'+currency
        groups.setdefault(currency,[]).append({**event,'origin_scope_id':event.get('scope_id'),'scope_id':scope})
    reports=[]
    for currency,rows in sorted(groups.items()):
        coverage={key:{'status':'unknown','evidence_refs':[],
                       'reason':'observed public components do not prove account-wide completeness'}
                  for key in ('fills','funding','flows','other_income','valuation_scope')}
        result=reconcile_period({'start_ms':start_ms,'end_ms':end_ms,'as_of_ms':as_of_ms,
            'scope':{'id':rows[0]['scope_id'],'currency':currency,'account_mode':account_mode,
                     'shared_collateral_model_verified':False},
            'coverage':coverage,'valuations':[],'events':rows})
        result['origin_scope_ids']=sorted({r['origin_scope_id'] for r in rows})
        result['observed_not_complete']=True
        reports.append(result)
    return {'version':'whole-address-observed-components-v1','address':address.lower(),
        'period':{'start_ms':start_ms,'end_ms':end_ms,'as_of_ms':as_of_ms},
        'currency_reports':reports,'unassigned_events':unassigned,
        'capital':None,'economic_pnl':None,'economic_qualification':False,
        'limits':['single address boundary; related subaccounts and vaults not merged',
                  'ledger flows counted once at address boundary, never once per DEX',
                  'currencies remain separate; no nominal stablecoin parity or invented FX',
                  'realized components omit missing events, spot cost basis, debt interest and latent change',
                  'zero observed sums are not zero true costs or zero economic PnL']}
