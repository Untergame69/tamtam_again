"""Bounded discovery sessions; their coverage is never a complete trade history."""
from __future__ import annotations
import json
import time
import os
from pathlib import Path
from .engine import fingerprint
from datetime import datetime
from uuid import uuid4
from .discovery import participants, record_window
from .storage import utc_now
from .websocket import WEBSOCKET_URLS


def collect_session(store, network, markets, *, seconds=45,
                    max_bytes=8_000_000, max_frames=10_000, connector=None):
    if not markets or len(markets) > 10 or len(set(markets)) != len(markets):
        raise ValueError('Require one to ten distinct markets')
    if not 1 <= seconds <= 300 or max_bytes < 1 or max_frames < 1:
        raise ValueError('Invalid bounded session budget')
    protected = {r[0] for r in store.connection.execute(
        'select distinct coin from validation_plans where synthetic=0')}
    if protected.intersection(markets):
        raise ValueError('Reserved market excluded before connection')
    if connector is None:
        from websockets.sync.client import connect
        connector = connect
    session = uuid4().hex
    start = utc_now()
    deadline = time.monotonic() + seconds
    events = {coin: [] for coin in markets}
    acks = set()
    received_bytes = frames = invalid = 0
    outcome = 'duration_elapsed'
    try:
        with connector(WEBSOCKET_URLS[network], ping_interval=15,
                       ping_timeout=15, open_timeout=15, close_timeout=5,
                       max_size=min(max_bytes, 1_000_000), max_queue=4) as ws:
            for coin in markets:
                ws.send(json.dumps({'method': 'subscribe', 'subscription': {
                    'type': 'trades', 'coin': coin}}))
            while time.monotonic() < deadline:
                try:
                    raw = ws.recv(timeout=min(1, max(.001, deadline-time.monotonic())))
                except TimeoutError:
                    continue
                size = len(raw.encode()) if isinstance(raw, str) else len(raw)
                received_bytes += size
                frames += 1
                if received_bytes > max_bytes or frames > max_frames:
                    outcome = 'budget_exhausted'
                    break
                try:
                    message = json.loads(raw)
                    if not isinstance(message, dict):
                        raise ValueError('Invalid message')
                except (ValueError, TypeError):
                    invalid += 1
                    continue
                if message.get('channel') == 'subscriptionResponse':
                    sub = message.get('data', {}).get('subscription', {})
                    if sub.get('type') == 'trades' and sub.get('coin') in events:
                        acks.add(sub['coin'])
                if message.get('channel') != 'trades':
                    continue
                data = message.get('data')
                if not isinstance(data, list):
                    invalid += 1
                    continue
                # Partition every trade; never infer all markets from the first.
                receipt = utc_now()
                for coin in markets:
                    trades = [trade for trade in data if isinstance(trade, dict)
                              and trade.get('coin') == coin]
                    if trades:
                        events[coin].append((receipt, {'channel': 'trades',
                            'data': trades, '_stream': {'connection_id': session}}))
    except Exception as exc:
        # Store only exception class: transport text can contain sensitive URLs.
        outcome = 'transport_error:' + type(exc).__name__
    end = utc_now()
    envelope={'version':'discovery-spool-v1','network':network,'session':session,
        'started_at':start,'ended_at':end,'events':events,'outcome':outcome,
        'bytes_received':received_bytes,'frames_received':frames,'invalid_messages':invalid,
        'subscriptions_acknowledged':sorted(acks),'markets':markets}
    envelope['fingerprint']=fingerprint(envelope)
    directory=store.path.parent/'discovery-pending';directory.mkdir(parents=True,exist_ok=True)
    path=directory/(session+'.json');temporary=path.with_suffix('.tmp')
    with temporary.open('x') as stream:
        json.dump(envelope,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor=os.open(directory,os.O_DIRECTORY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    return ingest_pending(store,path)


def ingest_pending(store,path,*,recovered=False):
    """Replay exactly the saved public receipts; no connection or receipt retiming."""
    path=Path(path);envelope=json.loads(path.read_text())
    digest=envelope.pop('fingerprint',None)
    if envelope.get('version')!='discovery-spool-v1' or fingerprint(envelope)!=digest:
        raise ValueError('Invalid discovery spool identity')
    if path.stem!=envelope['session']:raise ValueError('Spool filename/session mismatch')
    network=envelope['network'];session=envelope['session'];start=envelope['started_at'];end=envelope['ended_at']
    millis=lambda stamp:int(datetime.fromisoformat(stamp).timestamp()*1000)
    reports=[]
    store.connection.execute('create table if not exists discovery_ingestion_receipts '
        '(session_id text,market text,available_ms integer not null,primary key(session_id,market))')
    store.connection.commit()
    for coin,batch in envelope['events'].items():
        coverage={'status':'bounded_session_no_gap_proof','subscription_ack':coin in envelope['subscriptions_acknowledged'],
            'outcome':envelope['outcome'],'session':session,'frames':len(batch)}
        store.save_observation(network=network,source='hyperliquid-discovery-session-v1',
            entity_type='market',entity_id=coin,endpoint='trades',
            payload={'events':[{'received_at':r,'message':m} for r,m in batch]},
            requested_at=start,request_payload=coverage,record_count=len(batch),complete=False)
        # Acquire the write lock before timestamping first successful ingestion;
        # raw observed_at may precede a SQLite busy wait. Preserve the original
        # WebSocket times and reuse this separate access timestamp on retries.
        store.connection.execute('begin immediate')
        try:
            store.connection.execute('insert or ignore into discovery_ingestion_receipts values(?,?,?)',
                (session,coin,max(millis(end),millis(utc_now()))))
            store.connection.commit()
        except BaseException:
            store.connection.rollback();raise
        available=store.connection.execute('select available_ms from discovery_ingestion_receipts where session_id=? and market=?',(session,coin)).fetchone()[0]
        record_window(store,network=network,source='hyperliquid-discovery-session-v1',market=coin,
            start_ms=millis(start),end_ms=millis(end),available_ms=available,version='bounded-session-v1',coverage=coverage,evidence={})
        reports.extend(participants(store,network,coin,batch,coverage='bounded_session_no_gap_proof',available_ms=available))
    result={k:envelope[k] for k in ('session','started_at','ended_at','markets','outcome','bytes_received',
        'frames_received','invalid_messages','subscriptions_acknowledged')}
    result.update(new_candidates=sum(r['new_candidates'] for r in reports),live_user_slots_used=0,reports=reports,
        ingestion_recovered=recovered,ingestion_report_version=2,
        new_candidates_scope='lower bound across recovery; prior partial registrations may precede this report' if recovered else 'registrations in this ingestion')
    store.connection.execute('create table if not exists discovery_sessions '
        '(session_id text primary key,available_ms integer not null,report_json text not null)')
    store.connection.execute('insert or ignore into discovery_sessions values(?,?,?)',(session,millis(utc_now()),json.dumps(result,sort_keys=True)))
    store.connection.commit()
    saved=json.loads(store.connection.execute('select report_json from discovery_sessions where session_id=?',(session,)).fetchone()[0])
    path.unlink()
    return saved


def recover_pending(store,*,max_sessions=2):
    if type(max_sessions) is not int or not 1<=max_sessions<=8:raise ValueError('Bounded spool recovery required')
    directory=store.path.parent/'discovery-pending'
    paths=sorted([*directory.glob('*.json'),*directory.glob('*.tmp')]) if directory.exists() else []
    reports=[ingest_pending(store,path,recovered=True) for path in paths[:max_sessions]]
    return {'recovered':reports,'pending':max(0,len(paths)-len(reports))}
