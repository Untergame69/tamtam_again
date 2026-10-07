"""Period accounting on normalized, evidenced account valuations and events.

This module never infers completeness from an API response or sums shared
collateral dex snapshots. Adapters must supply explicit scope and provenance.
"""
from __future__ import annotations
from decimal import Decimal,InvalidOperation
import hashlib,json
from typing import Any

ZERO=Decimal(0)
def decimal(value:Any)->Decimal:
    try:r=Decimal(str(value))
    except InvalidOperation as exc:raise ValueError('Invalid accounting number') from exc
    if not r.is_finite():raise ValueError('Nonfinite accounting number')
    return r

def reconcile_period(data:dict[str,Any])->dict[str,Any]:
    start,end,available=(int(data[k]) for k in ('start_ms','end_ms','as_of_ms'))
    if not 0<=start<end<=available:raise ValueError('Accounting interval not available')
    scope=data['scope'];coverage=data.get('coverage',{})
    missing=[];observed={};events={};conflicts=[]
    if not scope.get('id') or not scope.get('currency'):raise ValueError('Explicit valuation scope and currency required')
    currency=scope['currency']
    required=('fills','funding','flows','other_income','valuation_scope')
    for kind in required:
        proof=coverage.get(kind,{})
        if proof.get('status')!='complete' or not proof.get('evidence_refs'):
            missing.append(kind+' coverage not proven')
    if scope.get('account_mode') in ('unifiedAccount','portfolioMargin','dexAbstraction') and not scope.get('shared_collateral_model_verified'):
        missing.append('shared collateral valuation model not verified')
    for event in data.get('events',[]):
        if int(event.get('available_ms',available+1))>available:
            if start<int(event['event_ms'])<=end:missing.append('period event not yet available')
            continue
        stamp=int(event['event_ms'])
        if not start<stamp<=end:continue
        identity=(event['kind'],event.get('scope_id'),event['id'])
        canonical=json.dumps(event,sort_keys=True,separators=(',',':'))
        if identity in events and events[identity][0]!=canonical:conflicts.append(str(identity))
        events.setdefault(identity,(canonical,event))
    if conflicts:missing.append('conflicting duplicate events')
    rows=[e[1] for e in events.values()]
    if any(e.get('scope_id')!=scope['id'] for e in rows):missing.append('event outside accounting scope')
    fills=[e for e in rows if e['kind']=='fill'];funding=[e for e in rows if e['kind']=='funding'];flows=[e for e in rows if e['kind']=='flow'];income=[e for e in rows if e['kind']=='income']
    if any(e['kind'] not in ('fill','funding','flow','income') for e in rows):missing.append('unclassified accounting event')
    fee_totals={}
    for f in fills:
        if 'fee' not in f or not f.get('fee_currency'):missing.append('fee amount/currency absent');continue
        token=f['fee_currency'].strip();fee_totals[token]=fee_totals.get(token,ZERO)+decimal(f['fee'])
    observed['fees_by_currency']={k:str(v) for k,v in fee_totals.items()}
    # Conversion requires explicit event-time quote evidence. No current-price FX.
    fees=ZERO
    for f in fills:
        if 'fee' not in f or not f.get('fee_currency'):continue
        token=f['fee_currency'].strip()
        if token==currency:fees+=decimal(f['fee'])
        else:
            fx=f.get('fee_conversion',{})
            if fx.get('currency')!=currency or not fx.get('evidence_ref') or int(fx.get('quote_ms',end+1))>int(f['event_ms']):missing.append('fee conversion unavailable: '+token)
            else:fees+=decimal(f['fee'])*decimal(fx['rate'])
    if any('closed_pnl' not in e or e.get('pnl_currency')!=currency for e in fills):missing.append('realized PnL amount/currency absent')
    realized=sum((decimal(e['closed_pnl']) for e in fills if 'closed_pnl' in e and e.get('pnl_currency')==currency),ZERO)
    def total(entries,label):
        if any(e.get('currency')!=currency or 'amount' not in e for e in entries):missing.append(label+' denomination/amount unavailable')
        return sum((decimal(e['amount']) for e in entries if e.get('currency')==currency and 'amount' in e),ZERO)
    funding_total=total(funding,'funding');flow_total=total(flows,'flows');income_total=total(income,'income')
    # Transfers are external to a scope only if an adapter proves that boundary.
    if any(e.get('boundary_classification') not in ('external','internal') or not e.get('boundary_evidence_ref') for e in flows):missing.append('transfer boundary classification unproven')
    external=[e for e in flows if e.get('boundary_classification')=='external']
    external_total=total(external,'external flows')
    valuations=[]
    for v in data.get('valuations',[]):
        if int(v.get('available_ms',available+1))>available or not start<=int(v['event_ms'])<=end:continue
        if v.get('scope_id')!=scope['id'] or v.get('currency')!=currency or not v.get('evidence_ref'):missing.append('valuation scope/currency/provenance mismatch');continue
        if not all(k in v for k in ('equity','unrealized_pnl','positions')):missing.append('valuation or initial/final positions incomplete');continue
        valuations.append(v)
    valuations.sort(key=lambda v:int(v['event_ms']))
    by_time={}
    for v in valuations:
        key=int(v['event_ms'])
        if key in by_time and by_time[key]!=v:missing.append('conflicting valuation snapshots')
        by_time.setdefault(key,v)
    first,last=by_time.get(start),by_time.get(end)
    if not first or not last:missing.append('exact boundary valuations/positions absent')
    observed.update({'realized_pnl':str(realized),'fees_converted_observed':str(fees),'funding':str(funding_total),'external_flows':str(external_total),'other_income':str(income_total),'events':len(rows),'fill_events':len(fills),'builder_fee_policy':'fee already includes builderFee; no second charge'})
    pnl=expected=residual=return_dietz=twr=drawdown=None
    if first and last:
        change=decimal(last['equity'])-decimal(first['equity']);latent=decimal(last['unrealized_pnl'])-decimal(first['unrealized_pnl'])
        observed.update({'initial_equity':str(decimal(first['equity'])),'final_equity':str(decimal(last['equity'])),'equity_change':str(change),'unrealized_change':str(latent),'initial_positions':first['positions'],'final_positions':last['positions']})
        if not missing:
            pnl=change-external_total;expected=realized+latent-fees+funding_total+income_total;residual=pnl-expected
            denominator=decimal(first['equity'])+sum((decimal(e['amount'])*Decimal(end-int(e['event_ms']))/Decimal(end-start) for e in external),ZERO)
            if denominator>0:return_dietz=pnl/denominator
            # Exact sampled TWR only when every external flow has a valuation at
            # its timestamp; then equity minus that flow yields pre-flow equity.
            times=sorted(by_time);flows_at={}
            for e in external:flows_at[int(e['event_ms'])]=flows_at.get(int(e['event_ms']),ZERO)+decimal(e['amount'])
            if all(t in by_time for t in flows_at):
                wealth=Decimal(1);peak=wealth;dd=ZERO;valid=True
                for left,right in zip(times,times[1:]):
                    previous=decimal(by_time[left]['equity']);before_flow=decimal(by_time[right]['equity'])-flows_at.get(right,ZERO)
                    if previous<=0 or before_flow<0:valid=False;break
                    wealth*=before_flow/previous;peak=max(peak,wealth);dd=max(dd,(peak-wealth)/peak)
                if valid:twr=wealth-1;drawdown=dd
    unique_missing=sorted(set(missing))
    result={'schema_version':1,'scope':scope,'period':{'start_ms':start,'end_ms':end,'as_of_ms':available,'membership':'(start,end] for events; exact valuations at both bounds'},'status':'reconciled_inputs' if not unique_missing else 'unknown','observed':observed,'unknown_reasons':unique_missing,'conflicting_duplicates':conflicts,'metrics':{'economic_pnl':str(pnl) if pnl is not None else None,'component_pnl':str(expected) if expected is not None else None,'reconciliation_residual':str(residual) if residual is not None else None,'modified_dietz_estimate':str(return_dietz) if return_dietz is not None else None,'time_weighted_return':str(twr) if twr is not None else None,'sampled_flow_adjusted_drawdown':str(drawdown) if drawdown is not None else None},'metric_requirements':{'economic_pnl':'complete evidenced scope, exact boundary valuations and classified external flows','time_weighted_return':'positive capital and valuation at every external-flow timestamp','sampled_flow_adjusted_drawdown':'same TWR requirements; only observed checkpoints','modified_dietz_estimate':'positive weighted-capital denominator; explicitly approximate'},'limits':['reconciled_inputs does not mean residual is acceptable or performance is good','Modified Dietz is an approximation; sampled drawdown omits intra-snapshot extremes','valuation-scope completeness is adapter evidence, not assumed from endpoint availability','external hedges and off-platform accounts remain unknown']}
    result['input_fingerprint']=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return result
