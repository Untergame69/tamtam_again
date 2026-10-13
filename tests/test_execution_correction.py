import json
import tempfile
import unittest
from pathlib import Path

from tamtam_again.execution_correction import (attach_session, complete_request,
    record_admin_cancel, register_request, route_request)
from tamtam_again.storage import Store


class ExecutionCorrectionTests(unittest.TestCase):
    def test_admin_cancel_is_audited_and_preserves_residual_and_fills(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/"paper.sqlite3")
            store.connection.execute("CREATE TABLE paper_sessions(session_id TEXT PRIMARY KEY,state_json TEXT,status TEXT,updated_at TEXT)")
            state={"position":"0.05","fills":[{"size":"0.29"},{"size":"-0.24"}],"cash":"999.8",
                   "pending":[{"target":"0","intent":"horizon_exit","priority":100,"reduce_only":True,"expires_ms":12}],"diagnostics":["priority_exit_unresolved_position"]}
            store.connection.execute("INSERT INTO paper_sessions VALUES(?,?,?,?)",("v4",json.dumps(state),"suspended","before"));store.connection.commit()
            action=record_admin_cancel(store,"v4",expected_position="0.05")
            reopened=Store(Path(tmp)/"paper.sqlite3")
            persisted=json.loads(reopened.connection.execute("SELECT state_json FROM paper_sessions WHERE session_id='v4'").fetchone()[0])
            self.assertEqual(persisted['position'],'0.05')
            self.assertEqual(persisted['fills'],state['fills'])
            self.assertEqual(persisted['cash'],state['cash'])
            self.assertEqual(persisted['pending'],[])
            audit=reopened.connection.execute("SELECT action,details_json FROM paper_admin_actions WHERE action_id=?",(action['action_id'],)).fetchone()
            self.assertEqual(audit['action'],'cancel_pending_virtual_orders_administratively')
            self.assertIsNone(json.loads(audit['details_json'])['closing_fill'])
            reopened.close();store.close()

    def test_deterministic_route_and_one_session_one_report_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/"paper.sqlite3")
            request={"request_id":"req-v4","source_session_id":"v4","source_final_report_id":"report-5",
                     "diagnosis":{"code":"priority_exit_unresolved_position"},"correction":{"policy":"preselect-full-close"}}
            register_request(store,request); routed=route_request(store,"req-v4")
            self.assertEqual(routed['route'],"correction d'exécution")
            self.assertEqual(route_request(store,"req-v4")['status'],'routed')
            attach_session(store,"req-v4","variant-v5","session-v5")
            with self.assertRaises(ValueError):attach_session(store,"req-v4","variant-v5","duplicate")
            complete_request(store,"req-v4","report-v5",{"status":"final"})
            row=store.connection.execute("SELECT * FROM execution_correction_requests WHERE request_id='req-v4'").fetchone()
            self.assertEqual((row['target_session_id'],row['result_report_id'],row['status']),('session-v5','report-v5','complete'))
            store.close()


if __name__=='__main__': unittest.main()
