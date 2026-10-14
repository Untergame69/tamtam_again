"""Exploratory, strict-pre-fill market context for the sealed 67f7/ETH join."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .engine import canonical, fingerprint
from .population_local_join import (VERSION as JOIN_VERSION, MAX_MARKET_DECODED_BYTES_PER_LOT,
    MAX_MARKET_DECODED_BYTES_PER_STREAM, MAX_MARKET_EVENTS_PER_STREAM,
    MAX_MARKET_LOTS_PER_STREAM, _decode_verified, _manifest, _quote_values, _source_specs)
from .validation import now_ms

VERSION='population-inventory-market-context-v2'
AGE_SENSITIVITY_MS=(0,1000,5000,30000,60000,300000)
MOVEMENT_HORIZONS_MS=(5000,30000)
PRIMARY_AGE_MS=30000


def _day(ms):
    return datetime.fromtimestamp(ms/1000,timezone.utc).date().isoformat()


def _num(x):
    return Decimal(str(x))


def _percent(n,d):
    return None if not d else round(100.0*float(n)/float(d),6)


def _bucket(pre,cuts):
    magnitude=abs(pre)
    if magnitude==0:return 'flat'
    if cuts['q25'] is not None and magnitude<=cuts['q25']:return 'inventory_q1'
    if cuts['q50'] is not None and magnitude<=cuts['q50']:return 'inventory_q2'
    if cuts['q75'] is not None and magnitude<=cuts['q75']:return 'inventory_q3'
    return 'inventory_q4'


def _nearest_rank(values,q):
    if not values:return None
    values=sorted(values)
    return values[max(0,(q*len(values)+99)//100-1)]


def _fill_class(fill):
    pre=_num(fill['start_position']); size=_num(fill['size'])
    if size<=0 or fill.get('side') not in ('B','A'):
        raise ValueError('Fill has nonpositive size or unknown side; no inferred direction is allowed')
    signed=size if fill.get('side')=='B' else -size
    post=pre+signed
    close=min(abs(pre),abs(signed)) if pre*signed<0 else Decimal(0)
    opened=size-close
    return pre,post,close,opened


def _accumulate(rows):
    out={'fill_count':0,'taker_fill_count':0,'maker_fill_count':0,'crossed_unknown_count':0,
         'taker_close_fill_count':0,'maker_close_fill_count':0,'taker_whole_abs_reduction_count':0,
         'execution_quantity':'0','taker_quantity':'0','close_quantity':'0','taker_close_quantity':'0',
         'reversal_count':0,'reversal_close_quantity':'0','reversal_open_quantity':'0'}
    values={k:Decimal(0) for k in ('execution_quantity','taker_quantity','close_quantity',
                                    'taker_close_quantity','reversal_close_quantity','reversal_open_quantity')}
    for row in rows:
        out['fill_count']+=1
        size=_num(row['size']); close=_num(row['close_quantity']); opened=_num(row['open_quantity'])
        crossed=row.get('crossed')
        if crossed is True:
            out['taker_fill_count']+=1;values['taker_quantity']+=size
            if close>0:
                out['taker_close_fill_count']+=1;values['taker_close_quantity']+=close
            if row['whole_abs_reduction']:out['taker_whole_abs_reduction_count']+=1
        elif crossed is False:
            out['maker_fill_count']+=1
            if close>0:out['maker_close_fill_count']+=1
        else:out['crossed_unknown_count']+=1
        values['execution_quantity']+=size;values['close_quantity']+=close
        if close>0 and opened>0:
            out['reversal_count']+=1;values['reversal_close_quantity']+=close
            values['reversal_open_quantity']+=opened
    for key,val in values.items():out[key]=str(val)
    out['taker_share_of_fills_pct']=_percent(out['taker_fill_count'],out['fill_count'])
    out['taker_closing_fills_per_all_fills_pct']=_percent(out['taker_close_fill_count'],out['fill_count'])
    out['taker_close_rate_within_taker_fills_pct']=_percent(out['taker_close_fill_count'],out['taker_fill_count'])
    out['taker_close_quantity_share_of_execution_pct']=_percent(values['taker_close_quantity'],values['execution_quantity'])
    out['taker_close_share_of_taker_quantity_pct']=_percent(values['taker_close_quantity'],values['taker_quantity'])
    return out


def _bin_quantiles(rows,key):
    vals=[_num(r[key]) for r in rows if r.get(key) is not None]
    return [_nearest_rank(vals,33),_nearest_rank(vals,67)]


def _tertile(value,cuts):
    if value is None:return 'unknown'
    v=_num(value)
    if cuts[0] is not None and v<=cuts[0]:return 'low'
    if cuts[1] is not None and v<=cuts[1]:return 'mid'
    return 'high'


def _build_context(store,request_id,join_artifact,join_fp):
    packetrow=store.connection.execute('select packet_json,network,address from population_research_jobs where request_id=?',(request_id,)).fetchone()
    if not packetrow:raise ValueError('Persisted parent task not found')
    packet=json.loads(packetrow['packet_json']); body={k:v for k,v in packet.items() if k!='fingerprint'}
    if fingerprint(body)!=packet.get('fingerprint'):raise ValueError('Sealed packet fingerprint mismatch')
    if packet.get('network')!=packetrow['network'] or packet.get('address','').lower()!=packetrow['address'].lower():
        raise ValueError('Sealed packet identity mismatch')
    if packet.get('pilot_research',{}).get('candidate')!='67f7' or 'ETH' not in packet.get('observations',{}).get('markets',[]):
        raise ValueError('This analysis is limited to the sealed 67f7/ETH task')
    detail=packet.get('observations',{}).get('market_execution_detail_v1',{}).get('ETH',{})
    cutoff=detail.get('cutoff_ms')
    if type(cutoff)is not int or cutoff!=join_artifact.get('cutoff_ms'):
        raise ValueError('Sealed ETH cutoff does not match v3 join')
    current_manifest=_manifest(store,packetrow['network'],packetrow['address'].lower(),'ETH',cutoff)
    if current_manifest!=join_artifact.get('source_manifest'):
        raise ValueError('Authorized archive manifest changed since the v3 join')
    from .research_memory import authorized_account_history
    if not authorized_account_history(store,packetrow['network'],packetrow['address'].lower(),cutoff):
        raise PermissionError('ETH archive period is not authorized at the sealed cutoff')

    fills=join_artifact.get('fills',[])
    if len(fills)>30_000:raise ValueError('Fill bound exceeded')
    if not fills:return {'schema_version':VERSION,'request_id':request_id,'cutoff_ms':cutoff,
        'base_join_fingerprint':join_fp,'coverage':{'all_fills':0},'fills':[]}
    with tempfile.TemporaryDirectory(prefix='inventory-market-context-') as temp:
        db=sqlite3.connect(str(Path(temp)/'context.sqlite3'))
        db.execute('create table quotes(stream text,event_ms integer,received_ms integer,archive_ms integer,observation_id integer,event_index integer,sha256 text,bid text,bid_size text,ask text,ask_size text)')
        source_manifest=join_artifact['source_manifest']
        excluded_after_cutoff=defaultdict(int)
        for stream in ('bbo','l2book'):
            where,params=_source_specs(packetrow['network'],packetrow['address'].lower(),'ETH',cutoff)[stream]
            lot_count=event_count=byte_count=0;batch=[]
            for obs in store.connection.execute('select * from raw_observations where '+where+' order by observation_id',params):
                lot_count+=1
                if lot_count>MAX_MARKET_LOTS_PER_STREAM:raise ValueError('Per-stream lot bound exceeded')
                payload,decoded_size=_decode_verified(obs,max_decoded_bytes=MAX_MARKET_DECODED_BYTES_PER_LOT,with_size=True)
                byte_count+=decoded_size
                if byte_count>MAX_MARKET_DECODED_BYTES_PER_STREAM:raise ValueError('Per-stream decoded-byte bound exceeded')
                vals,rejected,nframes,_=_quote_values(stream,payload,'ETH',lot_received_ms=_parse_ms(obs['observed_at']),cutoff_ms=cutoff)
                event_count+=nframes
                if event_count>MAX_MARKET_EVENTS_PER_STREAM:raise ValueError('Per-stream decoded-event bound exceeded')
                unexpected={k:v for k,v in rejected.items() if k not in ('event_time_after_cutoff','event_receipt_after_cutoff')}
                if unexpected:raise ValueError('v3-validated archive changed or contains newly rejected events: '+str(unexpected))
                for reason,count in rejected.items():excluded_after_cutoff[f'{stream}:{reason}']+=count
                for q in vals:
                    batch.append((stream,q['event_ms'],q['event_received_ms'],_parse_ms(obs['observed_at']),
                        obs['observation_id'],q['event_index'],obs['response_sha256'],q['bid'],q['bid_size'],q['ask'],q['ask_size']))
                if len(batch)>=10_000:db.executemany('insert into quotes values(?,?,?,?,?,?,?,?,?,?,?)',batch);batch.clear()
            if batch:db.executemany('insert into quotes values(?,?,?,?,?,?,?,?,?,?,?)',batch)
            if lot_count!=source_manifest[stream]['lot_count']:raise ValueError('Market lot count differs from sealed v3 manifest')
        db.execute('create index q_event on quotes(stream,event_ms,observation_id,event_index)');db.commit()
        fill_rows=[]
        nonzero=[]
        raw_classes=[]
        for f in fills:
            pre,post,close,opened=_fill_class(f)
            raw_classes.append((f,pre,post,close,opened))
            if pre:nonzero.append(abs(pre))
        cuts={k:_nearest_rank(nonzero,q) for k,q in (('q25',25),('q50',50),('q75',75))}
        for f,pre,post,close,opened in raw_classes:
            t=f['event_ms']; ref_page=f.get('archive_fill_page_ref') or {};page_ms=f.get('archive_fill_page_received_ms')
            quotes={}
            for stream in ('bbo','l2book'):
                q=db.execute('select event_ms,received_ms,archive_ms,observation_id,event_index,sha256,bid,bid_size,ask,ask_size from quotes where stream=? and event_ms<? order by event_ms desc,observation_id desc,event_index desc limit 1',(stream,t)).fetchone()
                ties=db.execute('select count(*),min(observation_id),min(event_index) from quotes where stream=? and event_ms=?',(stream,t)).fetchone()
                tie_refs=[{'observation_id':r[0],'event_index':r[1],'sha256':r[2],
                    'event_ms':r[3],'event_received_at_ms':r[4],'lot_archived_at_ms':r[5]}
                    for r in db.execute('select observation_id,event_index,sha256,event_ms,received_ms,archive_ms from quotes where stream=? and event_ms=? order by observation_id,event_index limit 10',(stream,t))]
                if q:
                    quotes[stream]={'event_ms':q[0],'received_at_ms':q[1],'lot_archived_at_ms':q[2],
                        'age_to_fill_event_ms':t-q[0],
                        'received_at_minus_fill_page_received_ms':None if page_ms is None else page_ms-q[1],
                        'lot_archived_minus_fill_page_received_ms':None if page_ms is None else page_ms-q[2],
                        'received_before_fill_page_receipt':None if page_ms is None else q[1]<=page_ms,
                        'lot_archived_before_fill_page_receipt':None if page_ms is None else q[2]<=page_ms,
                        'observation_ref':{'observation_id':q[3],'event_index':q[4],'sha256':q[5]},
                        'bid':q[6],'bid_size':q[7],'ask':q[8],'ask_size':q[9]}
                else:quotes[stream]=None
                quotes[stream+'_same_event_time']={'count':ties[0],'references':tie_refs,
                    'references_truncated':ties[0]>len(tie_refs),'relative_order_to_fill':'unknown'}
            bbo=quotes['bbo'];l2=quotes['l2book']
            feat={'bbo':bbo,'l2book':l2,'bbo_same_event_time':quotes['bbo_same_event_time'],
                'l2book_same_event_time':quotes['l2book_same_event_time'],
                'movement':{},'spread_bps':None,'depth':None}
            if bbo:
                mid=(_num(bbo['bid'])+_num(bbo['ask']))/2
                spread=_num(bbo['ask'])-_num(bbo['bid'])
                feat['mid']=str(mid);feat['spread_bps']=str(spread/mid*10_000 if mid else Decimal(0))
                for horizon in MOVEMENT_HORIZONS_MS:
                    base=db.execute('select event_ms,received_ms,archive_ms,bid,ask,observation_id,event_index,sha256 from quotes where stream=? and event_ms<=? order by event_ms desc,observation_id desc,event_index desc limit 1',
                        ('bbo',t-horizon)).fetchone()
                    key=f'{horizon//1000}s'
                    if base:
                        base_mid=(_num(base[3])+_num(base[4]))/2
                        feat['movement'][key]={'return_bps':str((mid/base_mid-1)*10_000 if base_mid else Decimal(0)),
                            'lookback_ms':t-base[0],
                            'from_event_ms':base[0],'from_event_received_at_ms':base[1],
                            'from_lot_archived_at_ms':base[2],
                            'from_ref':{'observation_id':base[5],'event_index':base[6],'sha256':base[7]},
                            'to_ref':bbo['observation_ref']}
                    else:feat['movement'][key]=None
            if l2:
                bid_size=_num(l2['bid_size']);ask_size=_num(l2['ask_size']);total=bid_size+ask_size
                side='long' if pre>0 else 'short' if pre<0 else 'flat'
                close_depth=bid_size if pre>0 else ask_size if pre<0 else None
                feat['depth']={'bid_best_size':str(bid_size),'ask_best_size':str(ask_size),
                    'top_level_total_size':str(total),'inventory_reducing_side_best_size':None if close_depth is None else str(close_depth),
                    'bid_ask_imbalance':str((bid_size-ask_size)/total if total else Decimal(0))}
            side='long' if pre>0 else 'short' if pre<0 else 'flat'
            feat.update({'fill_id':f['fill_id'],'event_ms':t,'utc_day':f['utc_day'],'segment':f['segment'],
                'start_position':f['start_position'],'position_side':side,'position_magnitude':str(abs(pre)),
                'inventory_bucket':_bucket(pre,cuts),'size':f['size'],'fill_size':f['size'],'fill_side':f['side'],
                'crossed':f['crossed'],'close_quantity':str(close),'open_quantity':str(opened),
                'whole_abs_reduction':abs(post)<abs(pre),'reversal':bool(close and opened),
                'fill_page_received_at_ms':page_ms,'fill_page_ref':ref_page})
            for age in AGE_SENSITIVITY_MS:
                feat[f'usable_age_le_{age}ms']=bool(bbo and l2 and bbo['age_to_fill_event_ms']<=age and l2['age_to_fill_event_ms']<=age)
            movement30=feat['movement'].get('30s')
            feat['primary_context_usable']=bool(feat['usable_age_le_30000ms'] and movement30 is not None
                and movement30['lookback_ms']<=60_000 and feat['spread_bps'] is not None and feat['depth'] is not None)
            fill_rows.append(feat)

    # Coverage is reported at multiple resolutions; no age limit is treated as a paper rule.
    coverage_by=defaultdict(list)
    for r in fill_rows:
        for group in ((r['utc_day'],r['segment'],r['position_side'],r['inventory_bucket']),
                      (r['utc_day'],r['segment'],'all','all'),('all',r['segment'],r['position_side'],r['inventory_bucket']),
                      ('all','all',r['position_side'],r['inventory_bucket'])):
            coverage_by[group].append(r)
    coverage=[]
    for key,rows in sorted(coverage_by.items(),key=lambda x:tuple(map(str,x[0]))):
        line={'utc_day':key[0],'segment':key[1],'position_side':key[2],'inventory_bucket':key[3],
            'fill_count':len(rows),'same_event_time_bbo_count':sum(x['bbo_same_event_time']['count']>0 for x in rows),
            'same_event_time_l2book_count':sum(x['l2book_same_event_time']['count']>0 for x in rows),
            'strict_bbo_predecessor_count':sum(x['bbo'] is not None for x in rows),
            'strict_l2book_predecessor_count':sum(x['l2book'] is not None for x in rows),
            'primary_context_usable_count':sum(x['primary_context_usable'] for x in rows)}
        for age in AGE_SENSITIVITY_MS:
            n=sum(x[f'usable_age_le_{age}ms'] for x in rows);line[f'usable_both_streams_age_le_{age}ms']={'count':n,'pct':_percent(n,len(rows))}
        coverage.append(line)

    all_by=defaultdict(list);by_threshold={}
    for r in fill_rows:all_by[(r['position_side'],r['inventory_bucket'])].append(r)
    for age in AGE_SENSITIVITY_MS:
        eligible=[r for r in fill_rows if r[f'usable_age_le_{age}ms']]
        groups=defaultdict(list)
        for r in eligible:groups[(r['position_side'],r['inventory_bucket'])].append(r)
        by_threshold[str(age)]={'eligible_fill_count':len(eligible),'eligible_pct':_percent(len(eligible),len(fill_rows)),
            'all_fill_count':len(fill_rows),'all_fill_baseline_by_position':[
                {'position_side':k[0],'inventory_bucket':k[1],**_accumulate(v)} for k,v in sorted(all_by.items())],
            'covered_by_position':[
                {'position_side':k[0],'inventory_bucket':k[1],**_accumulate(v)} for k,v in sorted(groups.items())]}

    primary=[r for r in fill_rows if r['primary_context_usable']]
    spread_cuts=_bin_quantiles(primary,'spread_bps')
    depth_values=[_num(r['depth']['inventory_reducing_side_best_size']) for r in primary if r['depth']['inventory_reducing_side_best_size'] is not None]
    depth_cuts=[_nearest_rank(depth_values,33),_nearest_rank(depth_values,67)]
    controls=defaultdict(list)
    for r in primary:
        move=r['movement']['30s']['return_bps']
        mv=_num(move)
        movement_bin='down' if mv < -1 else 'up' if mv > 1 else 'flat_within_1bp'
        red_depth=r['depth']['inventory_reducing_side_best_size']
        for cname,cval in (('movement_30s_direction',movement_bin),('spread_tertile',_tertile(r['spread_bps'],spread_cuts)),
                           ('inventory_reducing_depth_tertile',_tertile(red_depth,depth_cuts))):
            controls[(cname,cval,r['position_side'],r['inventory_bucket'])].append(r)
    strata=[]
    for key,rows in sorted(controls.items(),key=lambda x:tuple(map(str,x[0]))):
        strata.append({'control':key[0],'market_condition':key[1],'position_side':key[2],
            'inventory_bucket':key[3],**_accumulate(rows)})
    adjusted=[]
    for control in ('movement_30s_direction','spread_tertile','inventory_reducing_depth_tertile'):
        for side in ('long','short'):
            pairs=[]
            vals=defaultdict(list)
            for s in strata:
                if s['control']!=control or s['position_side']!=side or s['inventory_bucket'] not in ('inventory_q1','inventory_q4'):continue
                vals[(s['market_condition'],s['inventory_bucket'])].append(s)
            for condition in sorted({k[0] for k in vals}):
                low=next((x for x in vals[(condition,'inventory_q1')]),None)
                high=next((x for x in vals[(condition,'inventory_q4')]),None)
                if not low or not high:continue
                weight=min(low['fill_count'],high['fill_count'])
                pairs.append((low,high,weight))
            total_weight=sum(x[2] for x in pairs)
            def weighted(metric,which):
                return None if not total_weight else round(sum(x[2]*x[which][metric] for x in pairs)/total_weight,6)
            adjusted.append({'control':control,'position_side':side,'common_condition_strata':len(pairs),
                'comparison_weight_sum_min_cell_n':total_weight,
                'q1_taker_closing_fills_per_all_fills_pct':weighted('taker_closing_fills_per_all_fills_pct',0),
                'q4_taker_closing_fills_per_all_fills_pct':weighted('taker_closing_fills_per_all_fills_pct',1),
                'q4_minus_q1_taker_closing_fill_rate_pp':None if not total_weight else round(weighted('taker_closing_fills_per_all_fills_pct',1)-weighted('taker_closing_fills_per_all_fills_pct',0),6),
                'q1_taker_close_quantity_share_of_execution_pct':weighted('taker_close_quantity_share_of_execution_pct',0),
                'q4_taker_close_quantity_share_of_execution_pct':weighted('taker_close_quantity_share_of_execution_pct',1),
                'q4_minus_q1_taker_close_quantity_share_pp':None if not total_weight else round(weighted('taker_close_quantity_share_of_execution_pct',1)-weighted('taker_close_quantity_share_of_execution_pct',0),6)})

    return {'schema_version':VERSION,'request_id':request_id,'network':packet['network'],'address':packet['address'].lower(),
        'market':'ETH','cutoff_ms':cutoff,'base_join_version':JOIN_VERSION,'base_join_fingerprint':join_fp,
        'source_fingerprint':join_artifact['source_fingerprint'],'event_time_contract':'Strict event-time predecessor only: quote.event_ms < fill.event_ms. Same-timestamp quotes are counted and referenced separately; relative order is unknown.',
        'clock_contract':{'event_clock':'venue data.time compared to venue fill.time; only strict predecessors enter market features.',
            'local_receipt_clock':'events[].received_at or standalone raw_observations.observed_at; compared only to the local REST fill-page receipt time for diagnostics, never used to claim pre-fill availability.',
            'lot_archive_availability_clock':'raw_observations.observed_at for the whole quote lot; compared only to fill-page receipt time, not interpreted as fill receipt or decision time.',
            'clock_offset_drift':'unknown; cross-clock differences are not transport latency.'},
        'question_and_thresholds':{'question':'Does the descriptive association between pre-fill position magnitude and taker executions that close inventory remain visible after stratifying on observable recent ETH price movement, spread and opposing best-level depth?',
            'primary_age_ms':PRIMARY_AGE_MS,'sensitivity_age_ms':list(AGE_SENSITIVITY_MS),
            'rationale':'30s is the primary descriptive context window: it measures a recent market move alongside both best-book snapshots. The movement baseline is selected at or before fill-30s and must be no older than fill-60s, allowing up to 30s of archive cadence while keeping the measured return local. 5s tests near-term conditions; 60s/300s show staleness sensitivity. 1s is shown only as a freshness sensitivity point, not inherited as a paper rule; zero-age and all strict predecessors are also reported.'},
        'inventory_quantile_cuts_eth':{k:str(v) if v is not None else None for k,v in cuts.items()},
        'market_condition_cuts':{'spread_bps_tertiles':[str(v) if v is not None else None for v in spread_cuts],
            'inventory_reducing_best_depth_eth_tertiles':[str(v) if v is not None else None for v in depth_cuts],
            'movement_30s_direction_bins':'down < -1 bp; flat in [-1,+1] bp; up > +1 bp'},
        'fill_count':len(fill_rows),'same_timestamp_ambiguous_fill_count':sum(r['bbo_same_event_time']['count']>0 or r['l2book_same_event_time']['count']>0 for r in fill_rows),
        'primary_context_usable_count':len(primary),'primary_context_usable_pct':_percent(len(primary),len(fill_rows)),
        'market_events_excluded_by_cutoff':dict(sorted(excluded_after_cutoff.items())),
        'primary_context_requirement':'BBO and l2Book strict-predecessor ages <=30s; 30s BBO movement baseline 30s to 60s before fill; spread and opposing best-level size available.',
        'sensitivity_by_age':by_threshold,'coverage_by_day_segment_position':coverage,
        'unconditional_by_position':[{ 'position_side':k[0],'inventory_bucket':k[1],**_accumulate(v)} for k,v in sorted(all_by.items())],
        'primary_context_by_position':[{ 'position_side':k[0],'inventory_bucket':k[1],**_accumulate([r for r in primary if (r['position_side'],r['inventory_bucket'])==k])} for k in sorted(set((r['position_side'],r['inventory_bucket']) for r in primary))],
        'market_control_strata':strata,'q1_q4_common_support_comparison':adjusted,
        'fills':fill_rows,
        'selection_limits':['Compare primary covered subset with all 23,140 fills; available market context is uneven by day and segment, so the covered subset may be selected by archive activity.',
            'Fills are clustered in two locally reconstructed segments and six days; no fill-level independence or causal effect is assumed.',
            'Only executed fills are observed; conditioning on fills cannot identify unfilled decisions or the order policy.',
            '30s context age and movement/spread/depth strata are descriptive choices, not an execution admission rule.']}


def _parse_ms(value):
    dt=datetime.fromisoformat(value)
    if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
    dt=dt.astimezone(timezone.utc)
    delta=dt-datetime(1970,1,1,tzinfo=timezone.utc)
    return delta.days*86_400_000+delta.seconds*1000+delta.microseconds//1000


def execute_inventory_market_context(store,request_id):
    """Persist or retrieve the versioned market-conditioned execution association."""
    row=store.connection.execute('select * from population_research_jobs where request_id=?',(request_id,)).fetchone()
    if not row or row['status']!='needs_data':raise ValueError('Sealed needs-data task required')
    result=json.loads(row['result_json'] or '{}');joined=result.get('local_archive_join',{})
    if joined.get('state')!='completed' or joined.get('version')!=JOIN_VERSION:
        raise ValueError('Completed population local archive v3 join required')
    saved=store.connection.execute('select artifact_json from population_local_archive_joins where request_id=? and resolver_version=? and artifact_fingerprint=?',
        (request_id,JOIN_VERSION,joined.get('artifact_fingerprint'))).fetchone()
    if not saved:raise ValueError('Referenced v3 join artifact not persisted')
    join_artifact=json.loads(saved['artifact_json'])
    if fingerprint(join_artifact)!=joined['artifact_fingerprint']:raise ValueError('v3 artifact fingerprint mismatch')
    store.connection.execute('create table if not exists population_inventory_market_contexts '
        '(request_id text not null,analysis_version text not null,base_join_fingerprint text not null,analysis_fingerprint text not null,artifact_json text not null,created_ms integer not null,primary key(request_id,analysis_version,base_join_fingerprint))')
    existing=store.connection.execute('select analysis_fingerprint,artifact_json from population_inventory_market_contexts where request_id=? and analysis_version=? and base_join_fingerprint=?',
        (request_id,VERSION,joined['artifact_fingerprint'])).fetchone()
    if existing:
        artifact=json.loads(existing['artifact_json']);analysis_fp=existing['analysis_fingerprint'];reused=True
    else:
        artifact=_build_context(store,request_id,join_artifact,joined['artifact_fingerprint'])
        analysis_fp=fingerprint(artifact);encoded=canonical(artifact)
        store.connection.execute('insert into population_inventory_market_contexts values(?,?,?,?,?,?)',
            (request_id,VERSION,joined['artifact_fingerprint'],analysis_fp,encoded,now_ms()))
        store.connection.commit();reused=False
    result=json.loads(row['result_json'] or '{}')
    context_ref={'version':VERSION,'state':'completed','analysis_fingerprint':analysis_fp,
        'base_join_fingerprint':joined['artifact_fingerprint'],'artifact_path':'docs/continuous-research/POPULATION-67F7-ETH-INVENTORY-MARKET-CONTEXT-20261014-v2.json.gz',
        'model_calls':0,'collection_started':False}
    changed=result.get('local_inventory_market_context')!=context_ref
    if changed:
        result['local_inventory_market_context']=context_ref
        store.connection.execute('update population_research_jobs set result_json=?,updated_ms=? where request_id=? and status=?',
            (canonical(result),now_ms(),request_id,'needs_data'))
        store.connection.commit()
    from .population_routing import route
    route_value=route(store,request_id)
    return {'request_id':request_id,'status':'unchanged' if reused and not changed else 'prepared',
        **context_ref,'fill_count':artifact['fill_count'],'primary_context_usable_count':artifact['primary_context_usable_count'],
        'primary_context_usable_pct':artifact['primary_context_usable_pct'],'route':route_value}
