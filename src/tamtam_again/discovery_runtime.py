"""Bounded discovery sessions; their coverage is never a complete trade history."""
from __future__ import annotations
import json
import time
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
    millis = lambda stamp: int(datetime.fromisoformat(stamp).timestamp()*1000)
    reports = []
    for coin, batch in events.items():
        coverage = {'status': 'bounded_session_no_gap_proof',
                    'subscription_ack': coin in acks, 'outcome': outcome,
                    'session': session, 'frames': len(batch)}
        store.save_observation(network=network, source='hyperliquid-discovery-session-v1',
            entity_type='market', entity_id=coin, endpoint='trades',
            payload={'events': [{'received_at': r, 'message': m} for r, m in batch]},
            requested_at=start, request_payload=coverage, record_count=len(batch))
        # Include empty sessions, so silence is not mistaken for absent collection.
        record_window(store, network=network, source='hyperliquid-discovery-session-v1',
            market=coin, start_ms=millis(start), end_ms=millis(end),
            available_ms=millis(end), version='bounded-session-v1',
            coverage=coverage, evidence={})
        reports.extend(participants(store, network, coin, batch,
                                    coverage='bounded_session_no_gap_proof'))
    return {'session': session, 'started_at': start, 'ended_at': end,
            'markets': markets, 'outcome': outcome, 'bytes_received': received_bytes,
            'frames_received': frames, 'invalid_messages': invalid,
            'subscriptions_acknowledged': sorted(acks),
            'new_candidates': sum(r['new_candidates'] for r in reports),
            'live_user_slots_used': 0, 'reports': reports}
