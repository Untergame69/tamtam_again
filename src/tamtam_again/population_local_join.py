"""Bounded, deterministic joins of sealed population fills to archived market/state observations."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import zlib
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .engine import canonical, fingerprint
from .hype_diagnostics import start_position_chain_summary
from .storage import decode_observation_payload
from .validation import now_ms

VERSION = 'population-offline-archive-join-v3'
MAX_FILLS = 30_000
MAX_MARKET_LOTS_PER_STREAM = 600_000
MAX_MARKET_EVENTS_PER_STREAM = 4_000_000
MAX_MARKET_DECODED_BYTES_PER_STREAM = 1_000_000_000
MAX_MARKET_DECODED_BYTES_PER_LOT = 16_000_000
MAX_POSITION_SNAPSHOTS = 10_000


def _event_iso(ms):
    return (datetime(1970,1,1,tzinfo=timezone.utc)+timedelta(milliseconds=ms)).isoformat(timespec='milliseconds')


def _ms(iso):
    value = datetime.fromisoformat(iso)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value=value.astimezone(timezone.utc)
    delta=value-datetime(1970,1,1,tzinfo=timezone.utc)
    return delta.days*86_400_000+delta.seconds*1000+delta.microseconds//1000


def _source_specs(network, address, market, cutoff):
    cutoff_iso = _event_iso(cutoff)
    return {
        'fills': ("network=? and source='hyperliquid-population-rest-v1' and entity_type='account' "
            "and entity_id=? and endpoint in ('userFills','userFillsByTime') and observed_at<=? "
            'and (window_end_ms is null or window_end_ms<=?)',
            (network, address, cutoff_iso, cutoff)),
        'bbo': ("network=? and source='hyperliquid-websocket-v1' and entity_type='market' "
            "and entity_id=? and endpoint='bbo' and observed_at<=?", (network, market, cutoff_iso)),
        'l2book': ("network=? and source='hyperliquid-websocket-v1' and entity_type='market' "
            "and entity_id=? and endpoint='l2Book' and observed_at<=?", (network, market, cutoff_iso)),
        'positions': ("network=? and source='hyperliquid-population-rest-v1' and entity_type='account' "
            "and entity_id=? and endpoint='clearinghouseState' and observed_at<=?",
            (network, address, cutoff_iso)),
    }


def _manifest(store, network, address, market, cutoff):
    specs = _source_specs(network, address, market, cutoff)
    manifest = {}
    for kind, (where, params) in specs.items():
        digest = hashlib.sha256()
        count = 0
        declared_records = 0
        first = last = None
        query = ('select observation_id,response_sha256,observed_at,window_start_ms,window_end_ms,'
            'record_count,complete from raw_observations where '+where+' order by observation_id')
        for row in store.connection.execute(query, params):
            count += 1
            declared_records += row['record_count'] or 0
            first = first or row['observed_at']
            last = row['observed_at']
            digest.update(canonical([row['observation_id'], row['response_sha256'], row['observed_at'],
                row['window_start_ms'], row['window_end_ms'], row['record_count'], row['complete']]).encode('utf-8'))
            digest.update(b'\n')
        manifest[kind] = {'lot_count': count,'declared_record_count_total':declared_records,
            'first_received_at': first,
            'last_received_at': last, 'ordered_rows_sha256': digest.hexdigest(),
            'selector': {'network': network, 'market': market if kind in ('bbo','l2book') else None,
                'account': address if kind in ('fills','positions') else None,
                'cutoff_ms': cutoff, 'event_and_receipt_cutoffs_both_enforced_after_decode': True}}
    return manifest


def _source_fingerprint(network, address, market, cutoff, manifest):
    return fingerprint({'schema_version': VERSION, 'network': network, 'address': address,
        'market': market, 'cutoff_ms': cutoff, 'manifest': manifest})


def _decode_verified(row, *, max_decoded_bytes=None, with_size=False):
    if max_decoded_bytes is not None:
        source=row['response_json']
        if row['response_encoding']=='zlib+json':
            if len(source)>MAX_MARKET_DECODED_BYTES_PER_LOT:
                raise ValueError('Archived market lot exceeds compressed-byte bound')
            decoder=zlib.decompressobj()
            raw=decoder.decompress(source,max_decoded_bytes+1)
            if len(raw)>max_decoded_bytes or decoder.unconsumed_tail:
                raise ValueError('Archived observation exceeds decompressed-byte bound')
            raw+=decoder.flush()
        else:
            raw=source.encode('utf-8') if isinstance(source,str) else source
        if len(raw)>max_decoded_bytes:
            raise ValueError('Archived observation exceeds decoded-byte bound')
        payload=json.loads(raw)
    else:
        payload = decode_observation_payload(row)
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    if hashlib.sha256(normalized).hexdigest() != row['response_sha256']:
        raise ValueError('Archived observation hash mismatch: '+str(row['observation_id']))
    return (payload,len(normalized)) if with_size else payload


def _fills_and_receipts(store, network, address, market, cutoff):
    where, params = _source_specs(network, address, market, cutoff)['fills']
    by_tid = defaultdict(list)
    receipts = {}
    page_refs = []
    decoded = 0
    for row in store.connection.execute('select * from raw_observations where '+where+' order by observation_id', params):
        payload = _decode_verified(row)
        values = payload if isinstance(payload, list) else (payload.get('data', {}).get('fills', [])
            if isinstance(payload, dict) and isinstance(payload.get('data'), dict)
            else payload.get('fills', payload.get('data', [])) if isinstance(payload, dict) else [])
        received_ms = _ms(row['observed_at'])
        page_ref = {'observation_id': row['observation_id'], 'sha256': row['response_sha256'],
            'received_at': row['observed_at']}
        page_refs.append(page_ref)
        decoded += len(values)
        for fill in values:
            if not isinstance(fill, dict) or fill.get('coin') != market or fill.get('tid') is None:
                continue
            if type(fill.get('time')) is not int or fill['time'] > cutoff:
                continue
            tid = str(fill['tid'])
            by_tid[tid].append(fill)
            old = receipts.get(tid)
            if old is None or received_ms < old['received_ms']:
                receipts[tid] = {'received_ms': received_ms, 'page_ref': page_ref}
    fills, conflicts = [], []
    for tid, variants in sorted(by_tid.items()):
        if len({canonical(item) for item in variants}) != 1:
            conflicts.append(tid)
            continue
        fills.append(variants[0])
    fills.sort(key=lambda item: (item['time'], str(item['tid'])))
    if len(fills) > MAX_FILLS:
        raise ValueError('Fill-row limit exceeded; no partial artifact was stored')
    return fills, receipts, page_refs, {'decoded_records': decoded,
        'unique_market_fill_ids': len(by_tid), 'usable_unique_market_fills': len(fills),
        'duplicate_fill_instances': sum(max(0, len(rows)-1) for rows in by_tid.values()),
        'conflicting_fill_ids': len(conflicts), 'conflicting_fill_id_examples': conflicts[:20],
        'pages': len(page_refs)}


def _quote_values(kind, payload, market='ETH', *, lot_received_ms=None, cutoff_ms=None):
    """Normalize single WebSocket messages and archived events[] lots.

    Returns admissible event records plus reason-coded rejects. The lot archive
    time is deliberately kept separate from each frame's local received_at.
    """
    expected_channel='bbo' if kind=='bbo' else 'l2Book'
    if isinstance(payload,dict) and isinstance(payload.get('events'),list):
        frames=payload['events']; batched=True
    else:
        frames=[{'message':payload}]; batched=False
    accepted=[]; rejected=defaultdict(int)
    for index,frame in enumerate(frames):
        if not isinstance(frame,dict):
            rejected['event_not_object']+=1; continue
        message=frame.get('message') if batched else payload
        if not isinstance(message,dict):
            rejected['message_not_object']+=1; continue
        if message.get('channel')!=expected_channel:
            rejected['channel_mismatch_or_missing']+=1; continue
        data=message.get('data')
        if not isinstance(data,dict):
            rejected['data_not_object']+=1; continue
        if data.get('coin')!=market:
            rejected['market_mismatch_or_missing']+=1; continue
        if type(data.get('time')) is not int or data['time']<=0:
            rejected['invalid_event_time']+=1; continue
        try:
            receipt_ms=_ms(frame.get('received_at')) if batched else lot_received_ms
        except (TypeError,ValueError,OverflowError):
            rejected['invalid_local_receipt_time']+=1; continue
        if receipt_ms is None:
            rejected['local_receipt_time_missing']+=1; continue
        if cutoff_ms is not None:
            if data['time']>cutoff_ms:
                rejected['event_time_after_cutoff']+=1; continue
            if receipt_ms>cutoff_ms:
                rejected['event_receipt_after_cutoff']+=1; continue
        if kind=='bbo':
            levels=data.get('bbo')
            if not isinstance(levels,list) or len(levels)!=2:
                rejected['invalid_bbo_shape']+=1; continue
            bid,ask=levels
        else:
            levels=data.get('levels')
            if not isinstance(levels,list) or len(levels)!=2 or not levels[0] or not levels[1]:
                rejected['invalid_l2book_shape']+=1; continue
            bid,ask=levels[0][0],levels[1][0]
        if not all(isinstance(x,dict) and x.get('px') is not None and x.get('sz') is not None for x in (bid,ask)):
            rejected['top_level_price_or_size_missing']+=1; continue
        accepted.append({'event_index':index,'event_ms':data['time'],'event_received_ms':receipt_ms,
            'event_received_source':'frame.received_at' if batched else 'raw_observation.observed_at',
            'bid':str(bid['px']),'bid_size':str(bid['sz']),'ask':str(ask['px']),'ask_size':str(ask['sz']),
            'channel':expected_channel,'market':market,'batched':batched})
    return accepted,dict(rejected),len(frames),batched


def _position_value(payload, market):
    if not isinstance(payload, dict) or type(payload.get('time')) is not int:
        return None
    total = Decimal(0)
    found = False
    for row in payload.get('assetPositions', []):
        position = row.get('position', {}) if isinstance(row, dict) else {}
        if position.get('coin') == market:
            try:
                total += Decimal(str(position['szi']))
                found = True
            except (KeyError, ArithmeticError, ValueError):
                return None
    # A valid clearinghouseState without this instrument represents flat inventory.
    return payload['time'], str(total if found else Decimal(0))


def _day(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat()


def _segment_map(fills):
    chain = start_position_chain_summary(fills, include_fill_events=True)
    segment_by_tid = {}
    ranges = {}
    for index, offsets in enumerate(chain.get('ordered_segment_event_offsets', []), 1):
        events = chain['ordered_segment_fill_events'][offsets['first_event']:
            offsets['first_event']+offsets['event_count']]
        for event in events:
            segment_by_tid[str(event['fill']['tid'])] = index
        if events:
            ranges[index] = (min(event['fill']['time'] for event in events),
                max(event['fill']['time'] for event in events))
    return chain, segment_by_tid, ranges


def _ranked(values):
    if not values:
        return {'count': 0, 'p50': None, 'p95': None, 'max': None}
    ordered = sorted(values)
    def serial(value):
        return str(value) if isinstance(value, Decimal) else value
    def nr(percent):
        return serial(ordered[max(0, (percent*len(ordered)+99)//100-1)])
    return {'count': len(ordered), 'p50': nr(50), 'p95': nr(95), 'max': serial(ordered[-1])}


def _make_summary(fill_rows, market_gap_rows):
    grouped = defaultdict(list)
    for row in fill_rows:
        grouped[(row['segment'], row['utc_day'])].append(row)
    gap_map = {(row['stream'], row['segment'], row['utc_day']): row
        for row in market_gap_rows}
    result = []
    for (segment, day), rows in sorted(grouped.items(), key=lambda item: (str(item[0][0]), item[0][1])):
        item = {'segment': segment, 'utc_day': day, 'fill_count': len(rows),
            'bbo_matched': sum(row['bbo'] is not None for row in rows),
            'l2book_matched': sum(row['l2book'] is not None for row in rows),
            'bbo_local_receipt_matched': sum(row['bbo_by_local_receipt'] is not None for row in rows),
            'l2book_local_receipt_matched': sum(row['l2book_by_local_receipt'] is not None for row in rows),
            'position_matched': sum(row['position_snapshot'] is not None for row in rows),
            'position_local_receipt_matched': sum(row['position_by_local_receipt'] is not None for row in rows),
            'position_exact_agreements': sum(row.get('position_exact_agreement') is True for row in rows),
            'position_disagreements': sum(row.get('position_exact_agreement') is False for row in rows),
            'position_local_receipt_exact_agreements':sum(row.get('position_by_local_receipt',{}).get('exact_agreement') is True for row in rows),
            'position_local_receipt_disagreements':sum(row.get('position_by_local_receipt',{}).get('exact_agreement') is False for row in rows),
            'position_comparison_unknown': sum(row['position_snapshot'] is None for row in rows)}
        for stream, key in (('bbo','bbo_event_age_ms'), ('l2book','l2book_event_age_ms'),
                ('position','position_event_age_ms'), ('bbo','bbo_local_receipt_age_ms'),
                ('l2book','l2book_local_receipt_age_ms'), ('position','position_local_receipt_age_ms'),
                ('bbo','bbo_local_archive_age_ms'), ('l2book','l2book_local_archive_age_ms'),
                ('bbo','bbo_receive_minus_fill_event_ms'), ('l2book','l2book_receive_minus_fill_event_ms')):
            vals = [row[key] for row in rows if row.get(key) is not None]
            name = key
            item[name] = _ranked(vals)
        item['market_event_gaps_ms'] = {stream: (gap_map.get((stream, segment, day), {}).get('event_clock_coverage',{})
            .get('max_gap_including_edges_ms'))
            for stream in ('bbo','l2book')}
        item['market_receipt_gaps_ms'] = {stream: (gap_map.get((stream, segment, day), {}).get('local_archive_availability_clock_coverage',{})
            .get('max_gap_including_edges_ms'))
            for stream in ('bbo','l2book')}
        item['bbo_match_rate'] = {'numerator': item['bbo_matched'], 'denominator': len(rows)}
        item['l2book_match_rate'] = {'numerator': item['l2book_matched'], 'denominator': len(rows)}
        item['position_match_rate'] = {'numerator': item['position_matched'], 'denominator': len(rows)}
        item['bbo_local_receipt_match_rate'] = {'numerator':item['bbo_local_receipt_matched'],'denominator':len(rows)}
        item['l2book_local_receipt_match_rate'] = {'numerator':item['l2book_local_receipt_matched'],'denominator':len(rows)}
        item['position_local_receipt_match_rate'] = {'numerator':item['position_local_receipt_matched'],'denominator':len(rows)}
        result.append(item)
    return result


def _build_artifact(store, job, packet, source_fp, manifest, *, row_limit):
    network, address = job['network'], job['address'].lower()
    detail = packet['observations']['market_execution_detail_v1']['ETH']
    cutoff = detail['cutoff_ms']
    fills, fill_receipts, fill_page_refs, fill_coverage = _fills_and_receipts(
        store, network, address, 'ETH', cutoff)
    chain, segment_by_tid, segment_ranges = _segment_map(fills)
    if len(fills) > row_limit:
        raise ValueError('Configured fill-row bound exceeded')

    # A temporary indexed database bounds memory while joining the capped event stream.
    with tempfile.TemporaryDirectory(prefix='population-archive-join-') as temp:
        index = sqlite3.connect(str(Path(temp) / 'join.sqlite3'))
        index.execute('create table quotes(stream text,event_ms integer,event_received_ms integer,archive_available_ms integer,'
            'observation_id integer,event_index integer,sha256 text,bid text,bid_size text,ask text,ask_size text,segment integer,utc_day text)')
        index.execute('create table positions(event_ms integer,received_ms integer,observation_id integer,'
            'sha256 text,position text)')
        quote_batch, position_batch = [], []
        malformed = defaultdict(int)
        event_after_cutoff = defaultdict(int)
        stream_accounting={stream:{'lots_scanned':0,'declared_records':0,'decoded_events':0,
            'admissible_events':0,'decoded_canonical_bytes':0,'batched_lots':0,'individual_lots':0,
            'rejected_events_by_reason':{}} for stream in ('bbo','l2book')}

        for stream in ('bbo','l2book'):
            where, params = _source_specs(network, address, 'ETH', cutoff)[stream]
            for obs in store.connection.execute('select * from raw_observations where '+where+' order by observation_id', params):
                accounting=stream_accounting[stream]
                accounting['lots_scanned']+=1
                if accounting['lots_scanned']>MAX_MARKET_LOTS_PER_STREAM:
                    raise ValueError('Per-stream market lot bound exceeded; no partial artifact was stored')
                archived_ms=_ms(obs['observed_at'])
                if archived_ms>cutoff:
                    raise ValueError('Market lot archived after the sealed cutoff entered the source selector')
                payload,decoded_size=_decode_verified(obs,max_decoded_bytes=MAX_MARKET_DECODED_BYTES_PER_LOT,
                    with_size=True)
                accounting['decoded_canonical_bytes']+=decoded_size
                if accounting['decoded_canonical_bytes']>MAX_MARKET_DECODED_BYTES_PER_STREAM:
                    raise ValueError('Per-stream decoded-byte bound exceeded; no partial artifact was stored')
                declared=obs['record_count'] or 0
                accounting['declared_records']+=declared
                values,rejected,frame_count,batched=_quote_values(stream,payload,'ETH',
                    lot_received_ms=archived_ms,cutoff_ms=cutoff)
                accounting['decoded_events']+=frame_count
                if accounting['decoded_events']>MAX_MARKET_EVENTS_PER_STREAM:
                    raise ValueError('Per-stream decoded-event bound exceeded; no partial artifact was stored')
                accounting['batched_lots' if batched else 'individual_lots']+=1
                for reason,amount in rejected.items():
                    accounting['rejected_events_by_reason'][reason]=accounting['rejected_events_by_reason'].get(reason,0)+amount
                    if reason=='event_time_after_cutoff':event_after_cutoff[stream]+=amount
                    malformed[stream]+=amount
                for value in values:
                    event_ms=value['event_ms']; event_received_ms=value['event_received_ms']
                    segment=next((s for s,(start,end) in segment_ranges.items() if start<=event_ms<=end),None)
                    day=_day(event_ms)
                    quote_batch.append((stream,event_ms,event_received_ms,archived_ms,obs['observation_id'],
                        value['event_index'],obs['response_sha256'],value['bid'],value['bid_size'],
                        value['ask'],value['ask_size'],segment,day))
                    accounting['admissible_events']+=1
                if len(quote_batch) >= 5000:
                    index.executemany('insert into quotes values(?,?,?,?,?,?,?,?,?,?,?,?,?)', quote_batch)
                    quote_batch.clear()
            if quote_batch:
                index.executemany('insert into quotes values(?,?,?,?,?,?,?,?,?,?,?,?,?)', quote_batch)
                quote_batch.clear()

        where, params = _source_specs(network, address, 'ETH', cutoff)['positions']
        position_count = 0
        for obs in store.connection.execute('select * from raw_observations where '+where+' order by observation_id', params):
            position_count += 1
            if position_count > MAX_POSITION_SNAPSHOTS:
                raise ValueError('Account-state observation bound exceeded; no partial artifact was stored')
            payload = _decode_verified(obs)
            values = _position_value(payload, 'ETH')
            if values is None:
                malformed['positions'] += 1
                continue
            event_ms, szi = values
            if event_ms > cutoff:
                event_after_cutoff['positions'] += 1
                continue
            position_batch.append((event_ms,_ms(obs['observed_at']),obs['observation_id'],
                obs['response_sha256'],szi))
        if quote_batch:
            index.executemany('insert into quotes values(?,?,?,?,?,?,?,?,?,?,?)', quote_batch)
        if position_batch:
            index.executemany('insert into positions values(?,?,?,?,?)', position_batch)
        index.execute('create index quote_event_idx on quotes(stream,event_ms,event_received_ms,observation_id,event_index)')
        index.execute('create index quote_receipt_idx on quotes(stream,event_received_ms,archive_available_ms,observation_id,event_index)')
        index.execute('create index quote_archive_idx on quotes(stream,archive_available_ms,observation_id,event_index)')
        index.execute('create index position_event_idx on positions(event_ms,observation_id)')
        index.execute('create index position_receipt_idx on positions(received_ms,observation_id)')
        index.commit()

        fill_rows = []
        position_deltas = []
        market_event_clock_offsets = defaultdict(list)
        archive_page_lags = []
        for fill in fills:
            event_ms = int(fill['time'])
            tid = str(fill['tid'])
            page = fill_receipts.get(tid)
            page_received = page['received_ms'] if page else None
            segment = segment_by_tid.get(tid)
            row = {'fill_id':tid,'event_ms':event_ms,'utc_day':_day(event_ms),'segment':segment,
                'start_position':str(fill.get('startPosition')),'side':fill.get('side'),
                'size':str(fill.get('sz')),'price':str(fill.get('px')),
                'crossed':fill.get('crossed'),'archive_fill_page_ref':page['page_ref'] if page else None,
                'archive_fill_page_received_ms':page_received,
                'fill_local_receipt_ms':None,'own_live_decision_time_ms':None}
            if page_received is not None:
                archive_page_lags.append(page_received-event_ms)
            for stream in ('bbo','l2book'):
                quote = index.execute('select event_ms,event_received_ms,archive_available_ms,observation_id,event_index,sha256,bid,bid_size,ask,ask_size '
                    'from quotes where stream=? and event_ms<=? order by event_ms desc,event_received_ms desc,observation_id desc,event_index desc limit 1',
                    (stream,event_ms)).fetchone()
                key = 'bbo' if stream=='bbo' else 'l2book'
                if quote:
                    row[key]={'event_ms':quote[0],'event_received_at_ms':quote[1],
                        'lot_archived_available_at_ms':quote[2],
                        'event_age_ms':event_ms-quote[0],
                        'raw_event_receipt_minus_fill_event_ms':quote[1]-event_ms,
                        'lot_available_before_fill_page_receipt':(
                            None if page_received is None else quote[2]<=page_received),
                        'timestamp_order_vs_fill_page_receipt_uncalibrated':(
                            None if page_received is None else quote[1]<=page_received),
                        'observation_ref':{'observation_id':quote[3],'event_index':quote[4],'sha256':quote[5]},
                        'bid':quote[6],'bid_size':quote[7],'ask':quote[8],'ask_size':quote[9]}
                    row[key+'_event_age_ms']=event_ms-quote[0]
                    row[key+'_receive_minus_fill_event_ms']=quote[1]-event_ms
                    market_event_clock_offsets[stream].append(quote[1]-quote[0])
                else:
                    row[key]=None
                    row[key+'_event_age_ms']=None
                    row[key+'_receive_minus_fill_event_ms']=None
                receipt_quote = (index.execute('select event_ms,event_received_ms,archive_available_ms,observation_id,event_index,sha256,bid,bid_size,ask,ask_size '
                    'from quotes where stream=? and event_received_ms<=? and archive_available_ms<=? '
                    'order by archive_available_ms desc,event_received_ms desc,observation_id desc,event_index desc limit 1',
                    (stream,page_received,page_received)).fetchone() if page_received is not None else None)
                receipt_key=key+'_by_local_receipt'
                if receipt_quote:
                    row[receipt_key]={'event_ms':receipt_quote[0],'event_received_at_ms':receipt_quote[1],
                        'lot_archived_available_at_ms':receipt_quote[2],
                        'local_receipt_age_ms':page_received-receipt_quote[1],
                        'lot_archive_age_ms':page_received-receipt_quote[2],
                        'event_age_vs_fill_ms':event_ms-receipt_quote[0],
                        'observation_ref':{'observation_id':receipt_quote[3],'event_index':receipt_quote[4],'sha256':receipt_quote[5]},
                        'bid':receipt_quote[6],'bid_size':receipt_quote[7],
                        'ask':receipt_quote[8],'ask_size':receipt_quote[9]}
                    row[key+'_local_receipt_age_ms']=page_received-receipt_quote[1]
                    row[key+'_local_archive_age_ms']=page_received-receipt_quote[2]
                else:
                    row[receipt_key]=None
                    row[key+'_local_receipt_age_ms']=None
                    row[key+'_local_archive_age_ms']=None
            snapshot = index.execute('select event_ms,received_ms,observation_id,sha256,position '
                'from positions where event_ms<=? order by event_ms desc,observation_id desc limit 1',
                (event_ms,)).fetchone()
            if snapshot and fill.get('startPosition') is not None:
                delta = Decimal(snapshot[4])-Decimal(str(fill['startPosition']))
                row['position_snapshot']={'event_ms':snapshot[0],'received_at_ms':snapshot[1],
                    'event_age_ms':event_ms-snapshot[0],
                    'raw_receipt_minus_fill_event_ms':snapshot[1]-event_ms,
                    'observation_ref':{'observation_id':snapshot[2],'sha256':snapshot[3]},
                    'eth_position':snapshot[4]}
                row['position_event_age_ms']=event_ms-snapshot[0]
                row['position_exact_agreement']=delta==0
                row['position_delta_snapshot_minus_startPosition']=str(delta)
                position_deltas.append(abs(delta))
            else:
                row['position_snapshot']=None
                row['position_event_age_ms']=None
                row['position_exact_agreement']=None
                row['position_delta_snapshot_minus_startPosition']=None
            receipt_snapshot=(index.execute('select event_ms,received_ms,observation_id,sha256,position from positions '
                'where received_ms<=? order by received_ms desc,observation_id desc limit 1',
                (page_received,)).fetchone() if page_received is not None else None)
            if receipt_snapshot and fill.get('startPosition') is not None:
                receipt_delta=Decimal(receipt_snapshot[4])-Decimal(str(fill['startPosition']))
                row['position_by_local_receipt']={'event_ms':receipt_snapshot[0],
                    'received_at_ms':receipt_snapshot[1], 'local_receipt_age_ms':page_received-receipt_snapshot[1],
                    'event_age_vs_fill_ms':event_ms-receipt_snapshot[0],
                    'observation_ref':{'observation_id':receipt_snapshot[2],'sha256':receipt_snapshot[3]},
                    'eth_position':receipt_snapshot[4],
                    'position_delta_snapshot_minus_startPosition':str(receipt_delta),
                    'exact_agreement':receipt_delta==0}
                row['position_local_receipt_age_ms']=page_received-receipt_snapshot[1]
            else:
                row['position_by_local_receipt']=None
                row['position_local_receipt_age_ms']=None
            fill_rows.append(row)
        # Measure market coverage inside each fill-day interval in both clocks.
        # A zero-count interval remains explicit; a distant predecessor cannot hide it.
        groups=defaultdict(list)
        for row in fill_rows:groups[(row['segment'],row['utc_day'])].append(row)
        gap_rows=[]
        for (segment,day),rows in sorted(groups.items(),key=lambda item:(str(item[0][0]),item[0][1])):
            event_start=min(row['event_ms'] for row in rows); event_end=max(row['event_ms'] for row in rows)
            page_times=[row['archive_fill_page_received_ms'] for row in rows if row['archive_fill_page_received_ms'] is not None]
            receipt_start=min(page_times) if page_times else None; receipt_end=max(page_times) if page_times else None
            for stream in ('bbo','l2book'):
                event_times=[r[0] for r in index.execute('select event_ms from quotes where stream=? and event_ms between ? and ? order by event_ms',
                    (stream,event_start,event_end))]
                receipt_times=([r[0] for r in index.execute('select event_received_ms from quotes where stream=? and event_received_ms between ? and ? order by event_received_ms',
                    (stream,receipt_start,receipt_end))] if receipt_start is not None else [])
                archive_times=([r[0] for r in index.execute('select archive_available_ms from quotes where stream=? and archive_available_ms between ? and ? order by archive_available_ms',
                    (stream,receipt_start,receipt_end))] if receipt_start is not None else [])
                def coverage(times,start,end):
                    if not times:return {'observation_count':0,'max_gap_including_edges_ms':end-start,
                        'interval_start_ms':start,'interval_end_ms':end}
                    points=[start,*times,end]
                    return {'observation_count':len(times),
                        'max_gap_including_edges_ms':max(b-a for a,b in zip(points,points[1:])),
                        'interval_start_ms':start,'interval_end_ms':end}
                gap_rows.append({'stream':stream,'segment':segment,'utc_day':day,
                    'event_clock_coverage':coverage(event_times,event_start,event_end),
                    'local_receipt_clock_coverage':(coverage(receipt_times,receipt_start,receipt_end)
                        if receipt_start is not None else {'observation_count':0,'max_gap_including_edges_ms':None,
                            'interval_start_ms':None,'interval_end_ms':None}),
                    'local_archive_availability_clock_coverage':(coverage(archive_times,receipt_start,receipt_end)
                        if receipt_start is not None else {'observation_count':0,'max_gap_including_edges_ms':None,
                            'interval_start_ms':None,'interval_end_ms':None})})
        index.close()

    daily = _make_summary(fill_rows, gap_rows)
    market_gap_summary = {}
    for stream in ('bbo','l2book'):
        entries = [row for row in gap_rows if row['stream']==stream]
        market_gap_summary[stream] = {'segment_day_groups':len(entries),
            'max_event_gap_ms':max((r['event_clock_coverage']['max_gap_including_edges_ms']
                for r in entries if r['event_clock_coverage']['max_gap_including_edges_ms'] is not None),default=None),
            'max_receipt_gap_ms':max((r['local_receipt_clock_coverage']['max_gap_including_edges_ms']
                for r in entries if r['local_receipt_clock_coverage']['max_gap_including_edges_ms'] is not None),default=None),
            'max_archive_availability_gap_ms':max((r['local_archive_availability_clock_coverage']['max_gap_including_edges_ms']
                for r in entries if r['local_archive_availability_clock_coverage']['max_gap_including_edges_ms'] is not None),default=None)}
    position_match = [row for row in fill_rows if row['position_snapshot'] is not None]
    position_receipt_match=[row for row in fill_rows if row['position_by_local_receipt'] is not None]
    position_receipt_deltas=[abs(Decimal(row['position_by_local_receipt']['position_delta_snapshot_minus_startPosition']))
        for row in position_receipt_match]
    artifact = {'schema_version':VERSION,'request_id':job['request_id'],
        'packet_fingerprint':packet['fingerprint'],'network':network,'address':address,'market':'ETH',
        'cutoff_ms':cutoff,'cutoff_utc':_event_iso(cutoff),
        'clock_contract':{'fill_event_clock':'fill.time from archived venue fill records',
            'market_event_clock':'data.time from BBO/l2Book payload',
            'position_event_clock':'time from clearinghouseState payload',
            'market_event_local_receipt_clock':'events[].received_at for a batch; raw_observations.observed_at fallback for an individual message',
            'lot_archive_availability_clock':'raw_observations.observed_at for the whole archived lot',
            'cross_clock_interpretation':'Differences between venue event time and local receipt/availability are raw comparisons; offset and drift are not calibrated and values are not transport latency.',
            'fill_receipt_limit':'REST fills are archived by response page. No per-fill local receipt time or own decision timestamp exists; direct live-decision availability is unknown.'},
        'source_manifest':manifest,'source_fingerprint':source_fp,
        'fill_coverage':fill_coverage,'position_chain':{'segment_count':len(chain.get('position_chain_segments',[])),
            'rupture_count':len(chain.get('position_chain_ruptures',[])),
            'ruptures':chain.get('position_chain_ruptures',[]),
            'continuity_proven':False},
        'market_snapshot_coverage':{'rejected_events_by_stream':dict(malformed),
            'event_time_after_cutoff_excluded':dict(event_after_cutoff),
            'lot_and_event_accounting':stream_accounting,
            'processing_bounds':{'max_lots_per_stream':MAX_MARKET_LOTS_PER_STREAM,
                'max_decoded_events_per_stream':MAX_MARKET_EVENTS_PER_STREAM,
                'max_canonical_decoded_bytes_per_lot':MAX_MARKET_DECODED_BYTES_PER_LOT,
                'max_canonical_decoded_bytes_per_stream':MAX_MARKET_DECODED_BYTES_PER_STREAM},
            'by_segment_utc_day_gaps':gap_rows,
            'gap_summary':market_gap_summary},
        'matching_summary':{'fill_count':len(fill_rows),
            'bbo_matched':sum(row['bbo'] is not None for row in fill_rows),
            'l2book_matched':sum(row['l2book'] is not None for row in fill_rows),
            'position_snapshot_matched':len(position_match),
            'bbo_local_receipt_matched':sum(row['bbo_by_local_receipt'] is not None for row in fill_rows),
            'l2book_local_receipt_matched':sum(row['l2book_by_local_receipt'] is not None for row in fill_rows),
            'position_local_receipt_matched':sum(row['position_by_local_receipt'] is not None for row in fill_rows),
            'position_exact_agreement':sum(row['position_exact_agreement'] is True for row in position_match),
            'position_disagreement':sum(row['position_exact_agreement'] is False for row in position_match),
            'position_local_receipt_exact_agreement':sum(row['position_by_local_receipt']['exact_agreement'] is True for row in position_receipt_match),
            'position_local_receipt_disagreement':sum(row['position_by_local_receipt']['exact_agreement'] is False for row in position_receipt_match),
            'position_unknown':len(fill_rows)-len(position_match),
            'bbo_age_ms':_ranked([row['bbo_event_age_ms'] for row in fill_rows if row['bbo_event_age_ms'] is not None]),
            'l2book_age_ms':_ranked([row['l2book_event_age_ms'] for row in fill_rows if row['l2book_event_age_ms'] is not None]),
            'position_snapshot_age_ms':_ranked([row['position_event_age_ms'] for row in fill_rows if row['position_event_age_ms'] is not None]),
            'bbo_local_receipt_age_ms':_ranked([row['bbo_local_receipt_age_ms'] for row in fill_rows if row['bbo_local_receipt_age_ms'] is not None]),
            'l2book_local_receipt_age_ms':_ranked([row['l2book_local_receipt_age_ms'] for row in fill_rows if row['l2book_local_receipt_age_ms'] is not None]),
            'bbo_local_archive_age_ms':_ranked([row['bbo_local_archive_age_ms'] for row in fill_rows if row['bbo_local_archive_age_ms'] is not None]),
            'l2book_local_archive_age_ms':_ranked([row['l2book_local_archive_age_ms'] for row in fill_rows if row['l2book_local_archive_age_ms'] is not None]),
            'position_local_receipt_age_ms':_ranked([row['position_local_receipt_age_ms'] for row in fill_rows if row['position_local_receipt_age_ms'] is not None]),
            'position_abs_difference':_ranked(position_deltas),
            'position_local_receipt_abs_difference':_ranked(position_receipt_deltas),
            'fill_event_to_archive_page_receipt_ms':_ranked(archive_page_lags),
            'market_receipt_minus_event_raw_ms':{key:_ranked(values) for key,values in sorted(market_event_clock_offsets.items())}},
        'by_position_segment_and_utc_day':daily,'fills':fill_rows,
        'historical_comparisons_possible':['market BBO and top L2 context at or before each fill according to venue event timestamps, with event-time age, source event receipt, lot archive availability and raw evidence references','nearest prior account ETH position snapshot according to venue payload event timestamps compared with fill startPosition'],
        'comparisons_not_established':['whether the matched quote had arrived before this account fill or before a decision by our engine; the fill has no local receipt or decision timestamp','a gap-free market or position history; a snapshot is only a point observation','order placement, amendment, cancellation, unfilled opportunities, queue position, intent or causality'],
        'decision':{'state':'local_archive_analysis_complete','additional_collection_requested':False,
            'conclusion':'Existing archives support an event-time historical context join and point-in-time position comparison. Their coverage gaps and missing per-fill receipt/decision times prevent direct live-availability claims; no order-placement comparison is possible.'},
        'evidence_refs':{'fill_pages':fill_page_refs,
            'matched_quote_refs':'embedded per fill row as observation_id, event_index and response sha256',
            'matched_position_refs':'embedded per fill row as observation_id and response sha256',
            'manifest_hashes':'source_manifest.*.ordered_rows_sha256'},
        'interpretation_limits':['Event-time joins use only a quote or state snapshot whose payload event time is at or before fill.time.','Local-receipt joins use only events received and archived before the archived REST page containing the fill; this page arrival is later/less precise than the fill and is not engine availability.','For a batch, event receipt (events[].received_at) and lot archive availability (raw_observations.observed_at) are retained separately.','Receipt-time and event-time predecessor joins are separate; any comparison between the clocks remains uncalibrated.','Position mismatches compare a point snapshot with fill.startPosition at different times and are not proof that either value is wrong.','Same-millisecond ties use event receipt, observation_id and event_index as deterministic ordering; source order inside unresolved ties is not established.','A blank match is retained as unknown, not filled from a future observation.','No freshness threshold is imposed; ages and gaps are descriptive.']}
    artifact['analysis_fingerprint'] = fingerprint(artifact)
    return artifact


def execute_offline_archive_join(store, request_id, *, max_fill_rows=MAX_FILLS):
    """Run/retrieve the local join for a routed task; no budget or model dependency."""
    if type(max_fill_rows) is not int or not 1 <= max_fill_rows <= MAX_FILLS:
        raise ValueError('Explicit bounded fill-row limit required')
    from .population_routing import route
    route_state = route(store, request_id)
    if route_state.get('state') not in ('local_archive_analysis_required','local_archive_analysis_complete'):
        return {'request_id':request_id,'status':'not_routed','route_state':route_state.get('state')}
    job = store.connection.execute('select * from population_research_jobs where request_id=?',
        (request_id,)).fetchone()
    if not job or job['status']!='needs_data':
        raise ValueError('Terminal needs-data population task required')
    packet = json.loads(job['packet_json'])
    body = {key:value for key,value in packet.items() if key!='fingerprint'}
    if packet.get('fingerprint') != fingerprint(body):
        raise ValueError('Sealed packet fingerprint mismatch')
    if packet.get('network') != job['network'] or packet.get('address','').lower()!=job['address'].lower():
        raise ValueError('Sealed packet account identity mismatch')
    pilot = packet.get('pilot_research',{})
    if pilot.get('candidate')!='67f7' or 'ETH' not in packet.get('observations',{}).get('markets',[]):
        raise ValueError('This resolver is limited to the sealed 67f7/ETH request')
    detail = packet.get('observations',{}).get('market_execution_detail_v1',{}).get('ETH')
    if not isinstance(detail,dict) or type(detail.get('cutoff_ms')) is not int:
        raise ValueError('Sealed ETH detail cutoff is required')
    cutoff = detail['cutoff_ms']
    admission_cutoff = pilot.get('admission_cutoff_ms')
    if type(admission_cutoff) is not int or cutoff > admission_cutoff:
        raise ValueError('ETH source cutoff exceeds the sealed research authorization')
    from .research_memory import authorized_account_history
    if not authorized_account_history(store,job['network'],job['address'].lower(),cutoff):
        raise PermissionError('Account archive period is not authorized at the sealed cutoff')
    local = json.loads(job['result_json'] or '{}').get('local_resolution',{})
    followup = local.get('followup_task',{}) if isinstance(local,dict) else {}
    if followup.get('kind')!='offline_archive_join':
        raise ValueError('Persisted offline-archive-join task is required')

    manifest = _manifest(store, job['network'], job['address'].lower(), 'ETH', cutoff)
    source_fp = _source_fingerprint(job['network'], job['address'].lower(), 'ETH', cutoff, manifest)
    store.connection.execute('create table if not exists population_local_archive_joins '
        '(request_id text not null,resolver_version text not null,source_fingerprint text not null,'
        'artifact_fingerprint text not null,artifact_json text not null,created_ms integer not null,'
        'primary key(request_id,resolver_version,source_fingerprint))')
    existing = store.connection.execute('select artifact_fingerprint,artifact_json from population_local_archive_joins '
        'where request_id=? and resolver_version=? and source_fingerprint=?',
        (request_id,VERSION,source_fp)).fetchone()
    if existing:
        value = json.loads(existing['artifact_json'])
        return _persist_route_result(store, job, value, existing['artifact_fingerprint'], reused=True)

    # Authorization is checked before any payload decode; manifests contain metadata only.
    artifact = _build_artifact(store,job,packet,source_fp,manifest,row_limit=max_fill_rows)
    encoded = canonical(artifact)
    artifact_fp = fingerprint(artifact)
    created = now_ms()
    store.connection.execute('insert into population_local_archive_joins values(?,?,?,?,?,?)',
        (request_id,VERSION,source_fp,artifact_fp,encoded,created))
    store.connection.commit()
    return _persist_route_result(store, job, artifact, artifact_fp, reused=False)


def _persist_route_result(store, job, artifact, artifact_fp, *, reused):
    result = json.loads(job['result_json'] or '{}')
    joined={'version':VERSION,'state':'completed',
        'source_fingerprint':artifact['source_fingerprint'],'artifact_fingerprint':artifact_fp,
        'artifact_path':'docs/continuous-research/POPULATION-67F7-ETH-LOCAL-ARCHIVE-JOIN-20261014-v3.json.gz',
        'matched_fills':artifact['matching_summary']['fill_count'],
        'model_calls':0,'collection_started':False}
    result['local_archive_join']=joined
    existing_result=json.loads(job['result_json'] or '{}')
    if existing_result.get('local_archive_join')!=joined:
        store.connection.execute('update population_research_jobs set result_json=?,updated_ms=? where request_id=? and status=?',
            (canonical(result),now_ms(),job['request_id'],'needs_data'))
        store.connection.commit()
    from .population_routing import route
    next_route=route(store,job['request_id'])
    return {'request_id':job['request_id'],'status':'unchanged' if reused else 'prepared',
        'resolver_version':VERSION,'source_fingerprint':artifact['source_fingerprint'],
        'artifact_fingerprint':artifact_fp,'artifact_path':result['local_archive_join']['artifact_path'],
        'fill_count':artifact['matching_summary']['fill_count'],
        'bbo_matched':artifact['matching_summary']['bbo_matched'],
        'l2book_matched':artifact['matching_summary']['l2book_matched'],
        'position_matched':artifact['matching_summary']['position_snapshot_matched'],
        'position_disagreement':artifact['matching_summary']['position_disagreement'],
        'route':next_route,'model_calls':0,'collection_started':False}
