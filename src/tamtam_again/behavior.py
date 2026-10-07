"""Descriptive population profiles, not strategy or performance certification."""
from __future__ import annotations
import hashlib,json
from decimal import Decimal,InvalidOperation
from typing import Any
from .cycles import reconstruct_position_cycles

def profile_behavior(observations: list[dict[str,Any]], *, start_ms: int,end_ms: int,
                     as_of_ms: int,grouping_ms: int=1000) -> dict[str,Any]:
    if not 0<=start_ms<end_ms<=as_of_ms or type(grouping_ms) is not int or grouping_ms<1:
        raise ValueError('Explicit available period and positive grouping required')
    unique={};conflicts=set();rejected=0;refs=set()
    for observation in observations:
        fill=observation.get('fill');available=observation.get('available_ms')
        if not isinstance(fill,dict) or type(available) is not int or available>as_of_ms:
            rejected+=1;continue
        stamp=fill.get('time')
        if type(stamp) is not int or stamp>available or not start_ms<stamp<=end_ms:
            rejected+=1;continue
        if not fill.get('coin') or not observation.get('evidence_ref') or fill.get('tid',fill.get('hash')) is None:
            rejected+=1;continue
        identity=(fill['coin'],stamp,str(fill.get('tid',fill.get('hash'))))
        canonical=json.dumps(fill,sort_keys=True,separators=(',',':'))
        if identity in unique and unique[identity][0]!=canonical:conflicts.add(identity)
        unique.setdefault(identity,(canonical,fill));refs.add(observation['evidence_ref'])
    fills=[v[1] for k,v in unique.items() if k not in conflicts]
    markets={};buckets={};hypotheses=[]
    for fill in fills:
        markets.setdefault(fill['coin'],[]).append(fill)
        buckets.setdefault(fill['time']//grouping_ms,set()).add(fill['coin'])
    descriptions=[]
    for coin,rows in sorted(markets.items()):
        rows.sort(key=lambda r:(r['time'],str(r.get('tid',r.get('hash')))))
        known=[r for r in rows if type(r.get('crossed')) is bool]
        sizes=[];notionals=[];inventory_rows=[];post_positions=[];signed_exposures=[];invalid_sizes=0
        for r in rows:
            try:
                size=Decimal(str(r['sz']));price=Decimal(str(r['px']))
                if not size.is_finite() or not price.is_finite() or size<=0 or price<=0:raise ValueError()
                sizes.append(size);notionals.append(size*price)
                if 'startPosition' in r and r.get('side') in ('A','B'):
                    before=Decimal(str(r['startPosition']))
                    if not before.is_finite():raise ValueError()
                    inventory_rows.append(r)
                    after=before+size if r['side']=='B' else before-size
                    post_positions.append(after);signed_exposures.append(after*price)
            except (KeyError,InvalidOperation,ValueError,TypeError):invalid_sizes+=1
        episodes=reconstruct_position_cycles(inventory_rows,[],[],include_unexploitable=True)
        # Timing/inventory only: monetary defaults are not inferred zero PnL.
        episodes=[{k:v for k,v in e.items() if k in ('cycle_id','opened_at_ms','closed_at_ms','side','cycle_kind','baseline_position','ending_position','fill_count','order_count','fill_ids','exploitable','all_history_covered','all_bbo_context')} for e in episodes]
        durations={}
        for episode in episodes:
            durations.setdefault(episode['cycle_kind'],[]).append(episode['closed_at_ms']-episode['opened_at_ms'])
        def quantiles(values):
            if not values:return None
            ordered=sorted(values)
            return {'min':str(ordered[0]),'median':str(ordered[(len(ordered)-1)//2]),'max':str(ordered[-1])}
        intervals=[right['time']-left['time'] for left,right in zip(rows,rows[1:])]
        by_order={}
        for r in rows:
            if r.get('oid') is not None:by_order.setdefault(str(r['oid']),0);by_order[str(r['oid'])]+=1
        description={'market':coin,'fill_count':len(rows),'first_event_ms':rows[0]['time'],
          'last_event_ms':rows[-1]['time'],'maker_fills':sum(not r['crossed'] for r in known),
          'taker_fills':sum(r['crossed'] for r in known),'aggression_unknown':len(rows)-len(known),
          'size_units':quantiles(sizes),'notional_in_market_quote_units':quantiles(notionals),
          'inter_fill_ms':quantiles(intervals),'invalid_size_rows':invalid_sizes,
          'observed_post_fill_position_units':quantiles(post_positions),
          'signed_exposure_at_execution_price_in_quote_units':quantiles(signed_exposures),
          'top_five_fill_notional_fraction':str(sum(sorted(notionals,reverse=True)[:5])/sum(notionals)) if notionals else None,
          'fills_first_half':sum(r['time']<(start_ms+end_ms)//2 for r in rows),
          'fills_second_half':sum(r['time']>=(start_ms+end_ms)//2 for r in rows),
          'observed_orders':len(by_order),'orders_with_multiple_fills':sum(n>1 for n in by_order.values()),
          'candidate_episode_duration_ms':{k:quantiles(v) for k,v in durations.items()},
          'candidate_episodes':episodes,'history_coverage':'unknown',
          'episode_interpretation':'observed inventory paths; durations may describe scaling excursions, not whole-position holding time'}
        descriptions.append(description)
        if description['maker_fills']:
            hypotheses.append({'market':coin,'question':'Does passive inventory management explain repeated executions?',
                'needs':['order lifecycle and cancellations','inventory continuity','queue/execution model'],
                'status':'question_only'})
    coordinated=[{'bucket_start_ms':bucket*grouping_ms,'markets':sorted(coins)} for bucket,coins in sorted(buckets.items()) if len(coins)>1]
    if coordinated:
        hypotheses.append({'question':'Are temporally grouped instruments linked by a reproducible rule?',
            'needs':['inventory and cashflow continuity across instruments','market references','causal order sequence'],
            'status':'question_only'})
    result={'schema_version':1,'period':{'start_ms':start_ms,'end_ms':end_ms,'as_of_ms':as_of_ms},
        'grouping_ms':grouping_ms,'fills_observed':len(fills),'market_count':len(markets),
        'markets':descriptions,'multi_market_time_groups':coordinated,'questions':hypotheses,
        'rejected_rows':rejected,'conflicting_fill_identities':[list(k) for k in sorted(conflicts)],
        'evidence_refs':sorted(refs),'performance_status':'not_evaluated',
        'limits':['unknown history coverage; counts are observed, not activity estimates',
                  'temporal grouping is not evidence of arbitrage or coordination',
                  'no summed multi-market notionals or consolidated exposure',
                  'execution-price exposure samples do not establish a continuous risk trajectory',
                  'maker fills do not reveal unfilled orders or queue priority',
                  'candidate excursions are distinct from portfolio PnL and risk']}
    result['fingerprint']=hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return result
