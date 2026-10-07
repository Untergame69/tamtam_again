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

SOURCE='hyperliquid-population-rest-v1'
def millis(stamp:str)->int:return int(datetime.fromisoformat(stamp).timestamp()*1000)
def report_account(store:Store,network:str,address:str,start_ms:int,end_ms:int, *,as_of_ms:int|None=None)->dict[str,Any]:
    address=address.lower();as_of_ms=int(time.time()*1000) if as_of_ms is None else as_of_ms
    if address in protected_addresses(store):raise ValueError('Reserved pilot account excluded from accounting development')
    if not 0<=start_ms<end_ms<=as_of_ms:raise ValueError('Explicit available period required')
    records=[]
    for r in store.connection.execute('select * from raw_observations where network=? and entity_type=\'account\' and entity_id=? and source=? and observed_at<=? order by observed_at,observation_id',(network,address,SOURCE,datetime.fromtimestamp(as_of_ms/1000,timezone.utc).isoformat())):
        if millis(r['observed_at'])<=as_of_ms:records.append((r,decode_observation_payload(r),json.loads(r['request_json'])))
    modes=[(millis(r['observed_at']),p,r['observation_id']) for r,p,q in records if r['endpoint']=='userAbstraction']
    mode=modes[-1][1] if modes else 'unknown';mode_changed=len({str(p) for _,p,_ in modes})>1
    boundaries={};events=[];unsupported=[];refs=[];ledger_events=[]
    for row,payload,query in records:
        available=millis(row['observed_at']);ref='raw_observations:'+str(row['observation_id']);refs.append(ref)
        endpoint=row['endpoint']
        if endpoint=='clearinghouseState' and isinstance(payload,dict):
            dex=query.get('dex','');scope='perp:'+dex;stamp=int(payload.get('time',available))
            positions=[p['position'] for p in payload.get('assetPositions',[]) if isinstance(p,dict) and isinstance(p.get('position'),dict)]
            equity=payload.get('marginSummary',{}).get('accountValue')
            if equity is None or any('unrealizedPnl' not in p for p in positions):continue
            # Equity is API-reported, not a consolidated cross-dex capital claim.
            boundaries.setdefault(scope,[]).append({'event_ms':stamp,'available_ms':available,'scope_id':scope,'currency':'USDC' if not dex else 'UNVERIFIED_DEX_CURRENCY','equity':str(equity),'unrealized_pnl':str(sum((decimal(p['unrealizedPnl']) for p in positions),decimal(0))),'positions':positions,'evidence_ref':ref})
        if endpoint=='userFillsByTime' and isinstance(payload,list):
            for fill in payload:
                if not isinstance(fill,dict) or not fill.get('coin'):continue
                coin=str(fill['coin'])
                if coin.startswith('@') or '/' in coin:unsupported.append({'kind':'spot_fill','evidence_ref':ref});continue
                dex=coin.split(':',1)[0] if ':' in coin else '';currency='USDC' if not dex else 'UNVERIFIED_DEX_CURRENCY'
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
                    if endpoint=='userFunding':events.append(event)
                    else:ledger_events.append(event)
                if normalized['status']!='normalized':unsupported.append(normalized)
    scopes=sorted(set(boundaries)|{e['scope_id'] for e in events})
    reports=[]
    for scope in scopes:
        currency='USDC' if scope=='perp:' else 'UNVERIFIED_DEX_CURRENCY'
        coverage={k:{'status':'unknown','evidence_refs':[],'reason':'presence of API responses does not establish period completeness'} for k in ('fills','funding','flows','other_income','valuation_scope')}
        report=reconcile_period({'start_ms':start_ms,'end_ms':end_ms,'as_of_ms':as_of_ms,'scope':{'id':scope,'currency':currency,'account_mode':mode,'shared_collateral_model_verified':False},'coverage':coverage,'valuations':boundaries.get(scope,[]),'events':[e for e in events if e['scope_id']==scope]})
        reports.append(report)
    # Deduplicate receptions without merging contradictory financial events.
    ledger_by_id={}
    for event in ledger_events:
        old=ledger_by_id.get(event['id'])
        if old and {k:v for k,v in old.items() if k not in ('available_ms','evidence_ref','boundary_evidence_ref')}!={k:v for k,v in event.items() if k not in ('available_ms','evidence_ref','boundary_evidence_ref')}:
            unsupported.append({'kind':'conflicting_ledger_duplicate','evidence_refs':[old['evidence_ref'],event['evidence_ref']],'event_id':event['id'],'reason':'same identity with different financial fields'})
        ledger_by_id.setdefault(event['id'],event)
    ledger_events=list(ledger_by_id.values())
    return {'schema_version':2,'network':network,'address':address,'period':{'start_ms':start_ms,'end_ms':end_ms,'as_of_ms':as_of_ms},'account_mode':mode,'mode_changed_in_observed_history':mode_changed,'perp_scope_reports':reports,'ledger_scope':{'id':'hypercore:'+address,'boundary':'single address across spot and perp; no related-account or vault consolidation','normalized_events':ledger_events,'coverage_status':'unknown','assignment_to_perp_dex':'not inferred'},'spot_status':'inventory collected; priced balances and trading-cost basis not reconciled','unsupported_events':unsupported,'evidence_refs':refs,'status':'unknown','next_actions':['establish full period funding/ledger coverage and unsupported mechanism semantics','verify account-mode collateral valuation and dex currencies','establish comparable boundary valuations and priced spot balances'],'economic_validation':False,'limits':['no summed cross-dex equity','only population REST source; no reserved pilot observations read']}
