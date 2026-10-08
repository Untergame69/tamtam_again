import tempfile
import unittest
import sqlite3,json
from unittest.mock import patch
from pathlib import Path
from tamtam_again.storage import Store
from tamtam_again.discovery_runtime import collect_session


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name)/'db')
        self.store.connection.execute('create table validation_plans(coin text, synthetic integer, address text)')

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_reserved_market_never_connects(self):
        self.store.connection.execute("insert into validation_plans values('CL',0,'0x0000000000000000000000000000000000000001')")
        with self.assertRaises(ValueError):
            collect_session(self.store, 'hyperliquid-mainnet', ['CL'],
                            connector=lambda *a, **k: self.fail('connection attempted'))

    def test_connection_error_archives_empty_window(self):
        def connect(*a, **k):
            raise OSError('secret-looking transport text')
        report = collect_session(self.store, 'hyperliquid-mainnet', ['BTC'], connector=connect)
        self.assertEqual(report['outcome'], 'transport_error:OSError')
        self.assertEqual(report['new_candidates'], 0)
        self.assertEqual(self.store.connection.execute('select count(*) from discovery_windows').fetchone()[0], 1)
        self.assertNotIn('secret-looking', str(report))

    def test_budget_stops_buffer_growth(self):
        class Socket:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def send(self, raw): pass
            def recv(self, **kwargs): return 'x'*101
        report = collect_session(self.store, 'hyperliquid-mainnet', ['BTC'],
                                 max_bytes=100, connector=lambda *a, **k: Socket())
        self.assertEqual(report['outcome'], 'budget_exhausted')
        self.assertEqual(report['frames_received'], 1)

    def test_busy_storage_preserves_spool_and_recovery_never_connects(self):
        from tamtam_again.discovery_runtime import recover_pending
        def unavailable(*a,**k):raise OSError('transport fixture')
        with patch.object(self.store,'save_observation',side_effect=sqlite3.OperationalError('database is locked')):
            with self.assertRaises(sqlite3.OperationalError):
                collect_session(self.store,'hyperliquid-mainnet',['BTC'],connector=unavailable)
        pending=list((self.store.path.parent/'discovery-pending').glob('*.json'))
        self.assertEqual(len(pending),1)
        sealed=json.loads(pending[0].read_text())
        recovered=recover_pending(self.store)
        self.assertEqual(len(recovered['recovered']),1)
        r=recovered['recovered'][0]
        self.assertEqual(r['session'],sealed['session'])
        self.assertEqual(r['started_at'],sealed['started_at'])
        self.assertEqual(r['ended_at'],sealed['ended_at'])
        self.assertEqual(recover_pending(self.store)['recovered'],[])
        self.assertEqual(self.store.connection.execute('select count(*) from raw_observations').fetchone()[0],1)

    def test_partial_ingestion_retries_without_duplicate_receipt_or_retiming(self):
        from tamtam_again.discovery_runtime import recover_pending
        def unavailable(*a,**k):raise OSError('fixture')
        with patch('tamtam_again.discovery_runtime.record_window',side_effect=RuntimeError('interrupted after raw commit')):
            with self.assertRaises(RuntimeError):collect_session(self.store,'hyperliquid-mainnet',['BTC'],connector=unavailable)
        before=self.store.connection.execute('select observation_id,observed_at,requested_at from raw_observations').fetchone()[:]
        anchor=self.store.connection.execute('select available_ms from discovery_ingestion_receipts').fetchone()[0]
        recovered=recover_pending(self.store)
        self.assertEqual(len(recovered['recovered']),1)
        self.assertEqual(self.store.connection.execute('select observation_id,observed_at,requested_at from raw_observations').fetchone()[:],before)
        self.assertEqual(self.store.connection.execute('select count(*) from raw_observations').fetchone()[0],1)
        self.assertEqual(self.store.connection.execute('select available_ms from discovery_windows').fetchone()[0],anchor)

    def test_tampered_spool_is_retained_and_rejected(self):
        from tamtam_again.discovery_runtime import recover_pending
        with patch.object(self.store,'save_observation',side_effect=RuntimeError('interrupt')):
            with self.assertRaises(RuntimeError):collect_session(self.store,'hyperliquid-mainnet',['BTC'],connector=lambda *a,**k: (_ for _ in ()).throw(OSError()))
        path=next((self.store.path.parent/'discovery-pending').glob('*.json'))
        content=json.loads(path.read_text());content['network']='tampered';path.write_text(json.dumps(content))
        with self.assertRaises(ValueError):recover_pending(self.store)
        self.assertTrue(path.exists())

    def test_production_script_recovers_before_any_new_connection(self):
        import runpy,io
        with patch.object(self.store,'save_observation',side_effect=RuntimeError('interrupt')):
            with self.assertRaises(RuntimeError):collect_session(self.store,'hyperliquid-mainnet',['BTC'],connector=lambda *a,**k: (_ for _ in ()).throw(OSError()))
        output=Path(self.tmp.name)/'latest.json'
        script=Path(__file__).resolve().parents[1]/'scripts'/'discovery-tick.py'
        with patch('sys.argv',[str(script),'--db',str(self.store.path),'--output',str(output)]),patch('sys.stdout',new_callable=io.StringIO),patch('tamtam_again.discovery_runtime.collect_session') as connection:
            with self.assertRaises(SystemExit) as exited:runpy.run_path(str(script),run_name='__main__')
        self.assertEqual(exited.exception.code,0);connection.assert_not_called()
        self.assertTrue(json.loads(output.read_text())['ingestion_recovered'])
        self.assertEqual(self.store.connection.execute('select count(*) from discovery_sessions').fetchone()[0],1)
