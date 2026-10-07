import json
import tempfile
import unittest
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.paper_evidence import initialize,record


class EvidenceTests(unittest.TestCase):
    def test_immutable_idempotent_and_transactional(self):
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)/'db') as s:
            initialize(s);s.connection.commit()
            state={'last_ms':10}
            first=record(s,'session',20,1,state,{'net_pnl':'1'})
            self.assertEqual(record(s,'session',20,1,state,{'net_pnl':'1'}),first)
            s.connection.commit()
            with self.assertRaises(ValueError):record(s,'session',19,1,state,{'net_pnl':'1'})
            with self.assertRaises(ValueError):record(s,'session',21,1,{'last_ms':22},{'net_pnl':'1'})
            s.connection.execute('begin immediate')
            record(s,'session',30,2,{'last_ms':25},{'net_pnl':'2'})
            s.connection.rollback()
            rows=s.connection.execute('select * from paper_snapshots').fetchall()
            self.assertEqual(len(rows),1)
            self.assertEqual(json.loads(rows[0]['metrics_json'])['net_pnl'],'1')
