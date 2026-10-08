from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from tamtam_again.telemetry import Telemetry
from tamtam_again.providers.hyperliquid import response_weight_bound, _request_weight

class TelemetryTests(unittest.TestCase):
    def test_shared_quota_serializes_independent_connections(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'metrics.sqlite3';Telemetry(path)
            def reserve(_):return Telemetry(path).reserve(15,now=100,budget_per_minute=900)
            with ThreadPoolExecutor(max_workers=5) as pool: waits=list(pool.map(reserve,range(10)))
            self.assertEqual(sorted(waits),list(range(10)))
    def test_metrics_distinguish_reservation_from_charge(self):
        with tempfile.TemporaryDirectory() as d:
            t=Telemetry(Path(d)/'metrics.sqlite3')
            t.attempt(started_at=100,completed_at=101,task='backfill',endpoint='userFillsByTime',network='test',reserved_weight=120,response_weight_bound=21,retry=0,outcome='ok',http_status=200,elapsed_seconds=1,wait_seconds=0,response_bytes=20,response_items=1)
            r=t.report(100,now=160)
            self.assertEqual(r['reserved_weight_per_minute'],120)
            self.assertEqual(r['groups'][0]['response_weight_bound'],21)
            self.assertTrue(r['charged_weight'].startswith('unknown'))
    def test_ledger_has_no_undocumented_item_surcharge(self):
        self.assertEqual(_request_weight({'type':'userFills'}),120)
        self.assertEqual(response_weight_bound({'type':'userFills'},2000),120)
        self.assertEqual(_request_weight({'type':'userNonFundingLedgerUpdates'}),20)
        self.assertEqual(response_weight_bound({'type':'userNonFundingLedgerUpdates'},500),20)
        self.assertEqual(response_weight_bound({'type':'userFillsByTime'},2000),120)
    def test_provider_records_attempt_without_payload(self):
        from unittest.mock import patch
        from tamtam_again.providers.hyperliquid import HyperliquidInfo
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return b'[{"time":10,"private_marker":"must_not_be_in_metrics"}]'
        with tempfile.TemporaryDirectory() as d:
            t=Telemetry(Path(d)/'metrics.sqlite3')
            client=HyperliquidInfo('hyperliquid-testnet');client.telemetry=t
            with patch('tamtam_again.providers.hyperliquid.urlopen',return_value=Response()):
                self.assertEqual(len(client.post_info({'type':'userFillsByTime','user':'0x'+'1'*40})),1)
            report=t.report(0)
            self.assertEqual(report['groups'][0]['attempts'],1)
            self.assertEqual(report['groups'][0]['response_items'],1)
            self.assertNotIn(b'must_not_be_in_metrics',t.path.read_bytes())
    def test_provider_records_decode_failure(self):
        from unittest.mock import patch
        from tamtam_again.providers.hyperliquid import HyperliquidInfo,ProviderError
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return b'not JSON'
        with tempfile.TemporaryDirectory() as d:
            t=Telemetry(Path(d)/'metrics.sqlite3');client=HyperliquidInfo('hyperliquid-testnet');client.telemetry=t
            with patch('tamtam_again.providers.hyperliquid.urlopen',return_value=Response()):
                with self.assertRaises(ProviderError):client.post_info({'type':'clearinghouseState','user':'0x'+'1'*40})
            with t.connect() as c:
                self.assertEqual(c.execute('select outcome,response_weight_bound from collection_attempts').fetchone(),('decode_error',None))
