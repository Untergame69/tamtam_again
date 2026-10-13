"""Deterministic execution-correction registry and paper-only v4 disposition."""
from __future__ import annotations

import json
from uuid import uuid4

from .engine import canonical, fingerprint, number
from .storage import Store, utc_now
from .validation import now_ms

SCHEMA = """
CREATE TABLE IF NOT EXISTS execution_correction_requests (
 request_id TEXT PRIMARY KEY, source_session_id TEXT NOT NULL, source_report_id TEXT NOT NULL,
 request_json TEXT NOT NULL, route TEXT NOT NULL, status TEXT NOT NULL,
 target_version TEXT NOT NULL, target_variant_id TEXT, target_session_id TEXT,
 result_report_id TEXT, result_json TEXT, created_ms INTEGER NOT NULL, updated_ms INTEGER NOT NULL,
 UNIQUE(source_session_id,source_report_id));
CREATE TABLE IF NOT EXISTS paper_admin_actions (
 action_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, action TEXT NOT NULL,
 details_json TEXT NOT NULL, created_ms INTEGER NOT NULL);
"""

def initialize(store: Store) -> None:
    store.connection.executescript(SCHEMA)

def register_request(store: Store, request: dict) -> dict:
    initialize(store)
    required=("request_id","source_session_id","source_final_report_id","diagnosis","correction")
    if any(k not in request for k in required): raise ValueError("Incomplete correction request")
    route="correction d'exécution"
    store.connection.execute("""INSERT OR IGNORE INTO execution_correction_requests
      (request_id,source_session_id,source_report_id,request_json,route,status,target_version,created_ms,updated_ms)
      VALUES(?,?,?,?,?,'registered','v5-closeable-order-selection',?,?)""",
      (request['request_id'],request['source_session_id'],request['source_final_report_id'],canonical(request),route,now_ms(),now_ms()))
    store.connection.commit()
    row=store.connection.execute("SELECT * FROM execution_correction_requests WHERE request_id=?",(request['request_id'],)).fetchone()
    if row['source_session_id']!=request['source_session_id'] or row['source_report_id']!=request['source_final_report_id']:
        raise ValueError("Correction request id already bound to different evidence")
    return dict(row)

def route_request(store: Store, request_id: str) -> dict:
    initialize(store)
    store.connection.execute("UPDATE execution_correction_requests SET route=?,status=CASE WHEN status='registered' THEN 'routed' ELSE status END,updated_ms=? WHERE request_id=?",
                             ("correction d'exécution",now_ms(),request_id))
    store.connection.commit()
    row=store.connection.execute("SELECT * FROM execution_correction_requests WHERE request_id=?",(request_id,)).fetchone()
    if not row: raise ValueError("Unknown correction request")
    return dict(row)

def record_admin_cancel(store: Store, session_id: str, *, expected_position: str) -> dict:
    """Cancel only a stale virtual queue entry; append trace and preserve ledger/state position."""
    initialize(store)
    c=store.connection; c.execute("BEGIN IMMEDIATE")
    try:
        row=c.execute("SELECT state_json,status FROM paper_sessions WHERE session_id=?",(session_id,)).fetchone()
        if not row: raise ValueError("Unknown v4 paper session")
        state=json.loads(row['state_json'])
        if number(state['position'])==0 or number(state['position'])!=number(expected_position): raise ValueError("Residual position differs from preserved v4 evidence")
        if row['status']!='suspended': raise ValueError("Administrative cancellation requires suspended source session")
        if not state.get('pending'):
            prior=c.execute("SELECT action_id,details_json FROM paper_admin_actions WHERE session_id=? AND action='cancel_pending_virtual_orders_administratively' ORDER BY created_ms DESC LIMIT 1",(session_id,)).fetchone()
            if prior:
                c.commit();return {"action_id":prior['action_id'],**json.loads(prior['details_json'])}
            raise ValueError("No pending virtual order to cancel")
        cancelled=state['pending']; state['pending']=[]
        action_id=fingerprint({"session_id":session_id,"action":"cancel_pending_virtual_orders_administratively","pending":cancelled})
        details={"cancelled_virtual_orders":cancelled,"position_before":expected_position,"position_after":state['position'],
                 "fills_before":len(state.get('fills',[])),"fills_after":len(state.get('fills',[])),"closing_fill":None,
                 "accounting_changed":False,"reason":"v4 suspended with expired priority order; clear operational queue to permit explicit incomplete disposition"}
        c.execute("INSERT OR IGNORE INTO paper_admin_actions VALUES(?,?,?,?,?)",(action_id,session_id,"cancel_pending_virtual_orders_administratively",canonical(details),now_ms()))
        c.execute("UPDATE paper_sessions SET state_json=?,updated_at=? WHERE session_id=?",(canonical(state),utc_now(),session_id))
        c.commit()
    except BaseException:
        c.rollback(); raise
    return {"action_id":action_id,**details}

def attach_session(store: Store, request_id: str, variant_id: str, session_id: str) -> None:
    c=store.connection; c.execute("BEGIN IMMEDIATE")
    try:
        row=c.execute("SELECT target_session_id,target_variant_id FROM execution_correction_requests WHERE request_id=?",(request_id,)).fetchone()
        if not row: raise ValueError("Unknown correction request")
        if row['target_session_id'] and row['target_session_id']!=session_id: raise ValueError("Correction request already started; refusing duplicate")
        c.execute("UPDATE execution_correction_requests SET target_variant_id=?,target_session_id=?,status='started',updated_ms=? WHERE request_id=?",(variant_id,session_id,now_ms(),request_id));c.commit()
    except BaseException: c.rollback(); raise

def complete_request(store: Store, request_id: str, report_id: str, result: dict) -> None:
    c=store.connection; c.execute("BEGIN IMMEDIATE")
    try:
        row=c.execute("SELECT target_session_id,result_report_id FROM execution_correction_requests WHERE request_id=?",(request_id,)).fetchone()
        if not row or not row['target_session_id']: raise ValueError("Correction request has no started session")
        if row['result_report_id'] and row['result_report_id']!=report_id: raise ValueError("Final report is already linked")
        c.execute("UPDATE execution_correction_requests SET result_report_id=?,result_json=?,status='complete',updated_ms=? WHERE request_id=?",(report_id,canonical(result),now_ms(),request_id));c.commit()
    except BaseException: c.rollback(); raise
