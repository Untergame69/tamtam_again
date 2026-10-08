"""Measured public DEX capital changes, with API-contract uncertainty exposed.

This assessment never promotes a strategy or declares whole-account profit.
Capital-change measurement is separate from completeness of its attribution.
"""
from .accounting import decimal, ZERO, reconcile_period

REFERENCES=[
 'https://hyperliquid.gitbook.io/hyperliquid-docs/trading/account-abstraction-modes',
 'https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals',
 'https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint#send-asset']


def assess(*,address,scope,mode,mode_changed,start_ms,end_ms,valuations,
           component_report,ledger_events,unsupported,history_coverage,events=None,as_of_ms=None):
    reasons=[];flows=[];boundary={};refs=[]
    if mode not in ('disabled','default','standard') or mode_changed:
        reasons.append('independent DEX capital model unavailable for shared, unknown or changing mode')
    if scope!='perp:':
        reasons.append('this measurement implements validator USDC perp scope only')
    for v in valuations:
        if v['event_ms'] not in (start_ms,end_ms):continue
        key=v['event_ms'];previous=boundary.get(key)
        content={k:v[k] for k in ('equity','unrealized_pnl','positions','currency','scope_id')}
        if previous and previous[1]!=content:reasons.append('conflicting boundary valuations')
        boundary.setdefault(key,(v,content));refs.append(v['evidence_ref'])
    if len(boundary)!=2:reasons.append('exact initial and final valuations required')
    if any(v[0]['currency']!='USDC' for v in boundary.values()):reasons.append('scope currency is not USDC')
    ledger=history_coverage['userNonFundingLedgerUpdates']
    if ledger['pagination_status']!='covered':reasons.append('ledger pagination gap')
    refs.extend(ledger['evidence_refs'])
    relevant_unknown=[u for u in unsupported if u.get('endpoint')=='userNonFundingLedgerUpdates']
    if relevant_unknown:reasons.append('unclassified ledger events may change this scope capital')
    for e in ledger_events:
        if not start_ms<e['event_ms']<=end_ms:continue
        if 'source_dex' in e:
            source=e['source_account']==address and e['source_dex']==''
            destination=e['destination_account']==address and e['destination_dex']==''
            if not (source or destination):continue
            if e['currency']!='USDC':reasons.append('transfer asset does not match scope currency');continue
            amount=decimal(e['transfer_principal'])*(int(destination)-int(source))
        elif 'to_perp' in e:
            amount=decimal(e['reported_principal'])*(1 if e['to_perp'] else -1)
        else:
            reasons.append('ledger event has no evidenced validator perp assignment');continue
        flows.append({'event_ms':e['event_ms'],'amount':str(amount),'evidence_ref':e['evidence_ref'],'id':e['id'],'available_ms':e.get('available_ms',end_ms)})
        refs.append(e['evidence_ref'])
    # Whole-address duplicate reconciliation already checks conflicting identities.
    if any(u.get('kind')=='conflicting_ledger_duplicate' for u in unsupported):
        reasons.append('conflicting ledger duplicate')
    metrics={'capital_change':None,'net_capital_change':None,'external_flows':None,
             'modified_dietz_estimate':None,'observed_component_pnl':None,
             'observed_attribution_residual':None}
    if len(boundary)==2:
        first,last=boundary[start_ms][0],boundary[end_ms][0]
        metrics['capital_change']=str(decimal(last['equity'])-decimal(first['equity']))
    if not reasons:
        first,last=boundary[start_ms][0],boundary[end_ms][0]
        flow=sum((decimal(f['amount']) for f in flows),ZERO)
        change=decimal(last['equity'])-decimal(first['equity']);net=change-flow
        denominator=decimal(first['equity'])+sum((decimal(f['amount'])*decimal(end_ms-f['event_ms'])/decimal(end_ms-start_ms) for f in flows),ZERO)
        metrics.update(net_capital_change=str(net),external_flows=str(flow),
            modified_dietz_estimate=str(net/denominator) if denominator>0 else None)
        o=component_report['observed']
        components=decimal(o['realized_pnl'])+decimal(o['unrealized_change'])-decimal(o['fees_converted_observed'])+decimal(o['funding'])+decimal(o['other_income'])
        metrics.update(observed_component_pnl=str(components),observed_attribution_residual=str(net-components))
    contract_reconciliation=None
    if not reasons and events is not None and as_of_ms is not None:
        # Completeness is conditional on the documented public endpoint contract,
        # not a claim about external economic portfolios or provider correctness.
        funding=history_coverage['userFunding']
        funding_unknown=any(u.get('endpoint')=='userFunding' for u in unsupported)
        fill_coverage=dict(history_coverage['userFillsByTime'])
        if any(u.get('kind')=='malformed_fill' for u in unsupported):
            fill_coverage.update(status='unknown',reason='unparsed fill in archived interval')
        coverage={
            'fills':fill_coverage,
            'funding':{'status':'complete' if funding['pagination_status']=='covered' and not funding_unknown else 'unknown',
                'evidence_refs':funding['evidence_refs'],'basis':'public interval endpoint contract'},
            'flows':{'status':'complete','evidence_refs':ledger['evidence_refs'],'basis':'covered and classified public ledger'},
            'other_income':{'status':'complete','evidence_refs':ledger['evidence_refs'],
                'basis':'no unclassified non-funding ledger event in this public scope; omissions remain provider uncertainty'},
            'valuation_scope':{'status':'complete','evidence_refs':refs,'basis':'explicit independent validator-perp accountValue boundaries'}}
        normalized_flows=[{**f,'scope_id':scope,'currency':'USDC','kind':'flow',
            'boundary_classification':'external','boundary_evidence_ref':f['evidence_ref']} for f in flows]
        contract_reconciliation=reconcile_period({'start_ms':start_ms,'end_ms':end_ms,
            'as_of_ms':as_of_ms,'scope':{'id':scope,'currency':'USDC','account_mode':mode},
            'coverage':coverage,'valuations':valuations,
            'events':[e for e in events if e['scope_id']==scope]+normalized_flows})
        contract_reconciliation['coverage']=coverage
        contract_reconciliation['basis']='conditional public API contract; no account-wide or strategy qualification'
    return {'version':'public-validator-perp-capital-v1','scope_id':scope,'currency':'USDC',
        'status':'measured_public_scope' if not reasons else 'insufficient_scope_evidence',
        'metrics':metrics,'unknown_reasons':sorted(set(reasons)),'classified_flows':flows,
        'coverage':history_coverage,'evidence_refs':sorted(set(refs)),
        'account_economic_qualification':False,'strategy_validation':False,
        'attribution_complete':False,'contract_reconciliation':contract_reconciliation,
        'next_actions':sorted(set(reasons)) if reasons else [
            'establish fill retention and supported income semantics before declaring complete attribution',
            'evaluate reconciliation residual under a separately versioned materiality policy'],
        'assumptions':['reported independent DEX accountValue represents this public USDC perp scope',
            'covered ledger pages enumerate the requested public interval under the documented API contract',
            'no claim of independently audited provider completeness or continuous account-mode observation'],
        'limits':['scope excludes spot, other DEXs, vaults, loans and related accounts',
            'net capital change includes all income sources in scope; observed components may omit events',
            'attribution residual is diagnostic, never booked as trading profit or other income',
            'Modified Dietz is approximate; no unsampled drawdown or profitable-account verdict'],
        'official_references':REFERENCES}
