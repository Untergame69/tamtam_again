"""Evidence-preserving adapter for public population REST accounting reports.

Only newly collected population source is read. Reserved pilot accounts are
excluded before any raw query. Missing period/scope coverage remains unknown.
"""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib,json,time
from typing import Any
from .storage import Store,decode_observation_payload
from .discovery import protected_addresses
from .accounting import reconcile_period,decimal
from .account_events import normalize_event
from .collateral import resolve_currency
from .account_coverage import pagination_coverage,retained_fill_coverage
from .observation_windows import acquisition_window

SOURCE='hyperliquid-population-rest-v1'
def millis(stamp:str)->int:return int(datetime.fromisoformat(stamp).timestamp()*1000)
def report_account(store:Store,network:str,address:str,start_ms:int,end_ms:int, *,as_of_ms:int|None=None)->dict[str,Any]:
    address=address.lower();as_of_ms=int(time.time()*1000) if as_of_ms is None else as_of_ms
    if address in protected_addresses(store):raise ValueError('Reserved pilot account excluded from accounting development')
    from .research_memory import authorized_account_history
    if not authorized_account_history(store,network,address,as_of_ms):raise ValueError('Account history reserved at requested cutoff')
    if not 0<=start_ms<end_ms<=as_of_ms:raise ValueError('Explicit available period required')
    catalogs=[]
    if store.connection.execute("select 1 from sqlite_master where type='table' and name='collateral_catalogs'").fetchone():
        catalogs=[json.loads(r[0]) for r in store.connection.execute('select payload_json from collateral_catalogs where network=? and available_ms<=? order by available_ms',(network,as_of_ms))]
    def currency_for(stamp, *,coin=None,dex=None):
        proof=resolve_currency(catalogs,event_ms=stamp,instrument=coin,dex=dex)
        if proof:return proof['currency']
        return 'USDC' if dex=='' or coin is not None and ':' not in coin else 'UNVERIFIED_DEX_CURRENCY'
    records=[]
    for r in store.connection.execute('select * from raw_observations where network=? and entity_type=\'account\' and entity_id=? and source=? and observed_at<=? order by observed_at,observation_id',(network,address,SOURCE,datetime.fromtimestamp(as_of_ms/1000,timezone.utc).isoformat())):
        if millis(r['observed_at'])<=as_of_ms:records.append((r,decode_observation_payload(r),json.loads(r['request_json'])))
    from .account_acquisitions import group_acquisitions
    acquisitions=group_acquisitions(records)
    from .portfolio_evidence import summarize as summarize_portfolio
    portfolio_observations=[summarize_portfolio(p,available_ms=millis(r['observed_at']),
        as_of_ms=as_of_ms,start_ms=start_ms,end_ms=end_ms,
        evidence_ref='raw_observations:'+str(r['observation_id']))
        for r,p,q in records if r['endpoint']=='portfolio']
    from .account_lending import summarize as summarize_lending
    lending_observations=[summarize_lending(p,available_ms=millis(r["observed_at"]),as_of_ms=as_of_ms,
        evidence_ref="raw_observations:"+str(r["observation_id"]))
        for r,p,q in records if r["endpoint"]=="borrowLendUserState" and q.get("user", "").lower()==address]
    modes=[(millis(r['observed_at']),p,r['observation_id']) for r,p,q in records if r['endpoint']=='userAbstraction']
    mode=modes[-1][1] if modes else 'unknown';mode_changed=len({str(p) for _,p,_ in modes})>1
    boundaries={};events=[];unsupported=[];refs=[];ledger_events=[];boundary_diagnostics=[];spot_snapshots=[];margin_snapshots=[]
    for row,payload,query in records:
        available=millis(row['observed_at']);ref='raw_observations:'+str(row['observation_id']);refs.append(ref)
        endpoint=row['endpoint']
        if endpoint=='spotClearinghouseState' and isinstance(payload,dict):
            spot_snapshots.append({'available_ms':available,'evidence_ref':ref,
                'balances':payload.get('balances'),'event_ms':payload.get('time'),
                'acquisition_window':acquisition_window(row['requested_at'],row['observed_at']),
                'status':'observed_balances_not_priced_equity'})
        if endpoint=='clearinghouseState' and isinstance(payload,dict):
            dex=query.get('dex','');scope='perp:'+dex
            margin_snapshots.append({'dex':dex,'event_ms':payload.get('time'),'available_ms':available,'evidence_ref':ref,
                'acquisition_window':acquisition_window(row['requested_at'],row['observed_at']),
                'crossMaintenanceMarginUsed':payload.get('crossMaintenanceMarginUsed'),
                'positions':[p.get('position',{}) for p in payload.get('assetPositions',[]) if isinstance(p,dict)]})
            if mode in ('unifiedAccount','portfolioMargin','dexAbstraction') or mode_changed:
                boundary_diagnostics.append({'scope_id':scope,'evidence_ref':ref,
                    'available_ms':available,'status':'per_dex_capital_not_usable',
                    'reason':'shared or changing account mode requires account-wide collateral valuation'})
                continue
            stamp=payload.get('time')
            if type(stamp) is not int or not 0<=stamp<=available:
                boundary_diagnostics.append({'scope_id':scope,'evidence_ref':ref,
                    'available_ms':available,'status':'valuation_event_time_unknown',
                    'reason':'receipt time cannot substitute for valuation event time'})
                continue
            raw_positions=payload.get('assetPositions')
            if not isinstance(raw_positions,list) or any(not isinstance(p,dict) or not isinstance(p.get('position'),dict) for p in raw_positions):
                boundary_diagnostics.append({'scope_id':scope,'evidence_ref':ref,'status':'malformed_positions','reason':'do not replace malformed positions with empty inventory'})
                continue
            positions=[p['position'] for p in raw_positions]
            equity=payload.get('marginSummary',{}).get('accountValue')
            if equity is None or any('unrealizedPnl' not in p for p in positions):continue
            # Equity is API-reported, not a consolidated cross-dex capital claim.
            boundaries.setdefault(scope,[]).append({'event_ms':stamp,'available_ms':available,'scope_id':scope,'currency':currency_for(stamp,dex=dex),'equity':str(equity),'unrealized_pnl':str(sum((decimal(p['unrealizedPnl']) for p in positions),decimal(0))),'positions':positions,'evidence_ref':ref})
        if endpoint=='userFillsByTime' and isinstance(payload,list):
            for fill in payload:
                if (not isinstance(fill,dict) or not fill.get('coin') or type(fill.get('time')) is not int
                    or (fill.get('tid') is None and not fill.get('hash'))):
                    unsupported.append({'kind':'malformed_fill','endpoint':'userFillsByTime','evidence_ref':ref,'reason':'fill timestamp, instrument or identity absent'})
                    continue
                coin=str(fill['coin'])
                if coin.startswith('@') or '/' in coin:unsupported.append({'kind':'spot_fill','evidence_ref':ref});continue
                dex=coin.split(':',1)[0] if ':' in coin else '';currency=currency_for(int(fill['time']),coin=coin)
                e={'id':str((fill.get('coin'),fill.get('time'),fill.get('tid',fill.get('hash')))),'kind':'fill','scope_id':'perp:'+dex,'event_ms':int(fill['time']),'available_ms':available,'evidence_ref':ref,'coin':coin,'pnl_currency':currency}
                if 'closedPnl' in fill:e['closed_pnl']=fill['closedPnl']
                if 'fee' in fill:e['fee']=fill['fee']
                if fill.get('feeToken'):e['fee_currency']=fill['feeToken'].strip()
                events.append(e)
        if endpoint in ('userFunding','userNonFundingLedgerUpdates'):
            if not isinstance(payload,list):
                unsupported.append({'kind':endpoint,'evidence_ref':ref,'reason':'history response is not an array'})
                continue
            for raw_event in payload:
                normalized=normalize_event(endpoint,raw_event,address=address,available_ms=available,evidence_ref=ref)
                if 'event_ms' in normalized and not start_ms<normalized['event_ms']<=end_ms:continue
                event=normalized.get('event')
                if event:
                    if endpoint=='userFunding':
                        event['currency']=currency_for(event['event_ms'],coin=event['coin'])
                        if event['currency']!='UNVERIFIED_DEX_CURRENCY':normalized['status']='normalized'
                        events.append(event)
                    else:ledger_events.append(event)
                if normalized['status']!='normalized':unsupported.append(normalized)
    history_coverage={}
    for endpoint in ('userFillsByTime','userFunding','userNonFundingLedgerUpdates'):
        pages=[{'start_ms':r['window_start_ms'],'end_ms':r['window_end_ms'],
                'available_ms':millis(r['observed_at']),
                'pagination_status':q.get('pagination_status','unknown'),
                'covered_until_ms':q.get('covered_until_ms',
                    max((x['time'] for x in p),default=None)
                    if isinstance(p,list) and p and all(isinstance(x,dict) and type(x.get('time')) is int
                        and r['window_start_ms'] is not None and r['window_end_ms'] is not None
                        and r['window_start_ms']<=x['time']<=r['window_end_ms'] for x in p) else None),
                'evidence_ref':'raw_observations:'+str(r['observation_id'])}
               for r,p,q in records if r['endpoint']==endpoint]
        history_coverage[endpoint]=pagination_coverage(pages,start_ms=start_ms,
            end_ms=end_ms,as_of_ms=as_of_ms)
    witnesses=[{'request':q,'requested_ms':millis(r['requested_at']),
                'available_ms':millis(r['observed_at']),'fills':p,
                'evidence_ref':'raw_observations:'+str(r['observation_id'])}
               for r,p,q in records if r['endpoint']=='userFills' and q.get('user','').lower()==address]
    history_coverage['userFillsByTime']=retained_fill_coverage(
        history_coverage['userFillsByTime'],witnesses,start_ms=start_ms,
        end_ms=end_ms,as_of_ms=as_of_ms)
    scopes=sorted(set(boundaries)|{e['scope_id'] for e in events})
    reports=[]
    for scope in scopes:
        currency=currency_for(end_ms,dex=scope.removeprefix('perp:'))
        coverage={k:{'status':'unknown','evidence_refs':[],'reason':'presence of API responses does not establish period completeness'} for k in ('fills','funding','flows','other_income','valuation_scope')}
        coverage['fills']=history_coverage['userFillsByTime']
        report=reconcile_period({'start_ms':start_ms,'end_ms':end_ms,'as_of_ms':as_of_ms,'scope':{'id':scope,'currency':currency,'account_mode':mode,'shared_collateral_model_verified':False},'coverage':coverage,'valuations':boundaries.get(scope,[]),'events':[e for e in events if e['scope_id']==scope]})
        reports.append(report)
        values=boundaries.get(scope,[])
        for name,target in (('start',start_ms),('end',end_ms)):
            before=[v for v in values if v['event_ms']<=target]
            after=[v for v in values if v['event_ms']>=target]
            nearest_before=max(before,key=lambda v:v['event_ms']) if before else None
            nearest_after=min(after,key=lambda v:v['event_ms']) if after else None
            def describe(v):
                return {'event_ms':v['event_ms'],'available_ms':v['available_ms'],
                        'distance_ms':abs(v['event_ms']-target),
                        'evidence_ref':v['evidence_ref']} if v else None
            exact=any(v['event_ms']==target for v in values)
            boundary_diagnostics.append({'scope_id':scope,'boundary':name,
                'target_ms':target,'status':'exact_observation' if exact else 'missing_exact_observation',
                'nearest_before':describe(nearest_before),'nearest_after':describe(nearest_after),
                'interpolation_applied':False,
                'next_action':None if exact else 'choose explicit observed boundaries or obtain timestamped valuations; do not interpolate equity'})
    # Deduplicate receptions without merging contradictory financial events.
    ledger_by_id={}
    for event in ledger_events:
        old=ledger_by_id.get(event['id'])
        if old and {k:v for k,v in old.items() if k not in ('available_ms','evidence_ref','boundary_evidence_ref')}!={k:v for k,v in event.items() if k not in ('available_ms','evidence_ref','boundary_evidence_ref')}:
            unsupported.append({'kind':'conflicting_ledger_duplicate','evidence_refs':[old['evidence_ref'],event['evidence_ref']],'event_id':event['id'],'reason':'same identity with different financial fields'})
        ledger_by_id.setdefault(event['id'],event)
    ledger_events=list(ledger_by_id.values())
    from .public_scope_accounting import assess as assess_public_scope
    for report in reports:
        scope=report['scope']['id']
        report['public_scope_assessment']=assess_public_scope(address=address,scope=scope,mode=mode,
            mode_changed=mode_changed,start_ms=start_ms,end_ms=end_ms,valuations=boundaries.get(scope,[]),
            component_report=report,ledger_events=ledger_events,unsupported=unsupported,
            history_coverage=history_coverage,events=events,as_of_ms=as_of_ms)
    from .account_cashflows import summarize as summarize_cashflows
    whole_account_components=summarize_cashflows(events,ledger_events,address=address,
        start_ms=start_ms,end_ms=end_ms,as_of_ms=as_of_ms,account_mode=mode)
    from .unified_risk import unified_ratio
    risk=[]
    for spot in spot_snapshots:
        stamp=spot['event_ms']
        eligible=[c for c in catalogs if type(stamp) is int and c['available_ms']<=stamp]
        if mode!='unifiedAccount' or mode_changed or type(stamp) is not int or not eligible or not eligible[-1].get('dexes'):
            reasons=[];actions=[]
            if mode!='unifiedAccount':
                reasons.append('maintenance formula not applicable to observed mode: '+str(mode))
                actions.append('use the mode-specific collateral and risk model; do not relabel the mode')
            if mode_changed:
                reasons.append('account mode changed within observed history')
                actions.append('establish mode at each valuation boundary before comparing risk')
            if type(stamp) is not int:
                reasons.append('spot response lacks an economic timestamp')
                actions.append('establish a timestamped coherent valuation source or explicitly model observation intervals; additional fills do not supply this timestamp')
            elif not eligible or not eligible[-1].get('dexes'):
                reasons.append('collateral perimeter not evidenced before economic timestamp')
                actions.append('obtain historical DEX/collateral mapping available at the valuation timestamp')
            risk.append({'status':'unknown','ratio':None,'evidence_refs':[spot['evidence_ref']],
                'unknown_reasons':reasons,'next_actions':actions})
            continue
        catalog=eligible[-1]
        risk.append(unified_ratio(mode=mode,spot=spot,catalog=catalog,
            dex_states=[x for x in margin_snapshots if x['event_ms']==stamp],
            expected_dexes=list(catalog['dexes']),event_ms=stamp,as_of_ms=as_of_ms))
    return {'schema_version':2,'network':network,'address':address,'period':{'start_ms':start_ms,'end_ms':end_ms,'as_of_ms':as_of_ms},'account_mode':mode,'mode_changed_in_observed_history':mode_changed,'perp_scope_reports':reports,'boundary_diagnostics':boundary_diagnostics,'history_coverage':history_coverage,'collateral_catalog_evidence':[{'available_ms':c['available_ms'],'evidence_refs':c.get('evidence_refs',[])} for c in catalogs],'ledger_scope':{'id':'hypercore:'+address,'boundary':'single address across spot and perp; no related-account or vault consolidation','normalized_events':ledger_events,'coverage_status':'unknown','assignment_to_perp_dex':'not inferred'},'whole_account_observed_components':whole_account_components,'reported_portfolio_observations':portfolio_observations,'account_acquisitions':acquisitions,'spot_balance_snapshots':spot_snapshots,'lending_observations':lending_observations,'margin_component_snapshots':margin_snapshots,'unified_maintenance_ratio_observations':risk,'capital_model':{'mode':mode,'status':'unverified','balance_source':'spotClearinghouseState' if mode in ('unifiedAccount','portfolioMargin') else 'mode-specific inventory','reference':'https://hyperliquid.gitbook.io/hyperliquid-docs/trading/account-abstraction-modes'},'spot_status':'inventory collected; priced balances and trading-cost basis not reconciled','unsupported_events':unsupported,'evidence_refs':refs,'status':'public_scope_measured' if any(r['public_scope_assessment']['status']=='measured_public_scope' for r in reports) else 'unknown','next_actions':['establish full period funding/ledger coverage and unsupported mechanism semantics','verify account-mode collateral valuation and dex currencies','establish comparable boundary valuations and priced spot balances'],'economic_validation':False,'limits':['no summed cross-dex equity','only population REST source; no reserved pilot observations read']}
