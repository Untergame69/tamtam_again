import tempfile
import unittest
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
