"""Lossless bounded episode export: never truncate an episode's event path."""
from __future__ import annotations

from bisect import bisect_left
from typing import Any

from .engine import fingerprint

def complete_episodes(events: list[dict[str,Any]], policy: dict[str,Any], market: str) -> list[dict[str,Any]]:
    if not events:
        return []
    events=sorted(events,key=lambda e:(e.get('available_ms',e['received_ms']),e['received_ms'],str(e['id'])))
    times=[e.get('available_ms',e['received_ms']) for e in events]
    spec=policy['strategy_template'];warmup=max(65000,spec['horizon_ms'])
    horizon=spec['latency_ms']+spec['horizon_ms']
    signals=[i for i,e in enumerate(events) if e['kind']=='leader_fill'
             and times[i]-warmup>=times[0] and times[i]+horizon<times[-1]]
    if not signals:
        return []
    # Fixed temporal quantiles, independent of price direction and PnL.
    anchors=[signals[min(len(signals)-1,int(len(signals)*q))] for q in (0.1,0.5,0.9)]
    episodes=[];previous_end=-1
    for i in anchors:
        start,end=times[i]-warmup,times[i]+horizon+1
        if start<previous_end:
            continue
        left,right=bisect_left(times,start),bisect_left(times,end)
        seeds=[]
        for kind in ('bbo','heartbeat','connection'):
            seed=next((e for e in reversed(events[:left]) if e['kind']==kind),None)
            if seed:seeds.append(seed)
        selected=sorted(seeds+events[left:right],key=lambda e:(e.get('available_ms',e['received_ms']),e['received_ms'],str(e['id'])))
        sessions={};rows=[]
        def session(value):
            if value is None:return None
            if value not in sessions:sessions[value]=len(sessions)+1
            return sessions[value]
        for event in selected:
            common=[event['event_ms']-start,event['received_ms']-start,event.get('available_ms',event['received_ms'])-start]
            kind=event['kind']
            if kind=='bbo':
                row=['b',*common,event['bid'],event['ask'],event['bid_size'],event['ask_size'],session(event.get('session'))]
            elif kind=='leader_fill':
                row=['f',*common,event['delta'],event.get('leader_start_position'),str(event['id']).split(':')[-1],session(event.get('session'))]
            elif kind=='funding':
                row=['u',*common,event.get('unit_funding_usdc'),event.get('provenance')]
            else:
                tag={'heartbeat':'h','connection':'c','disconnection':'d','subscriptions':'s'}.get(kind)
                if tag is None:raise ValueError('Unknown event kind; episode cannot be exported losslessly')
                row=[tag,*common,session(event.get('session')),bool(event.get('connected')),market in event.get('markets',[])]
            rows.append(row)
        first_fill=next((e for e in events[left:right] if e['kind']=='leader_fill'),None)
        episodes.append({'start_ms':start,'end_ms':end,'anchor_available_ms':times[i],
                         'all_archived_events_in_interval':True,'event_count':right-left,'seed_count':len(seeds),
                         'source_fingerprint':fingerprint(selected),'rows':rows,
                         'leader_inventory_before_first_fill':first_fill.get('leader_start_position') if first_fill else None,
                         'funding_observed':any(e['kind']=='funding' for e in selected),
                         'limitations':['Complete archive slice is not proof of uninterrupted collection.',
                                        'Negative offsets are actual pre-window seed observations.',
                                        'No funding observation means unknown funding, not zero.']})
        previous_end=end
    return episodes

ROW_SCHEMA={
    'times':'event_ms,received_ms,available_ms offsets from episode.start_ms; availability controls decisions',
    'b':['tag','event_offset','receipt_offset','available_offset','bid','ask','bid_size','ask_size','session'],
    'f':['tag','event_offset','receipt_offset','available_offset','signed_delta','leader_start_position_or_null','fill_tid','session'],
    'h/c/d/s':['tag','event_offset','receipt_offset','available_offset','session','connected','market_acknowledged'],
    'u':['tag','event_offset','receipt_offset','available_offset','funding_usdc_per_signed_unit','provenance'],
    'sessions':'episode-local aliases; equality preserves session identity, no continuity is invented'}
