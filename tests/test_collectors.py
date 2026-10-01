from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tamtam_again.markets import top_markets
from tamtam_again.providers.hyperliquid import MAX_PAGE_ROWS, HyperliquidInfo
from tamtam_again.storage import Store, decode_observation_payload
from tamtam_again.whales import rank_leaderboard


def address(number: int) -> str:
    return "0x" + format(number, "040x")


class MarketRankingTests(unittest.TestCase):
    def test_ranks_by_daily_notional_volume_and_skips_delisted(self) -> None:
        universe = [
            {"name": f"MKT{i}", "isDelisted": i == 6} for i in range(1, 8)
        ]
        contexts = [{"dayNtlVlm": str(volume)} for volume in
                    (100, 700, 300, 600, 500, 10_000, 0)]
        rows = top_markets([{"universe": universe}, contexts])
        self.assertEqual([row["coin"] for row in rows],
                         ["MKT2", "MKT4", "MKT5", "MKT3", "MKT1"])
        self.assertEqual([row["rank"] for row in rows], [1, 2, 3, 4, 5])

    def test_rejects_misaligned_metadata(self) -> None:
        with self.assertRaises(ValueError):
            top_markets([{"universe": [{"name": "BTC"}]}, []])


class WhaleRankingTests(unittest.TestCase):
    def test_ranks_positive_active_accounts_across_windows(self) -> None:
        payload = {"leaderboardRows": [
            {"ethAddress": address(1), "accountValue": "1000", "displayName": "A",
             "windowPerformances": [["day", {"pnl": "100", "roi": "0.1", "vlm": "900"}],
                                    ["allTime", {"pnl": "500", "roi": "0.5", "vlm": "5000"}]]},
            {"ethAddress": address(2), "accountValue": "2000", "displayName": None,
             "windowPerformances": [["day", {"pnl": "250", "roi": "0.08", "vlm": "1200"}],
                                    ["allTime", {"pnl": "300", "roi": "0.15", "vlm": "8000"}]]},
            {"ethAddress": address(3), "accountValue": "500", "windowPerformances": [
                ["day", {"pnl": "-1", "roi": "-0.1", "vlm": "90"}]]},
            {"ethAddress": address(4), "accountValue": "0", "windowPerformances": [
                ["day", {"pnl": "10000", "roi": "8", "vlm": "20000"}]]},
        ]}
        rankings, candidates = rank_leaderboard(payload, limit_per_window=1)
        day_pnl = next(row for row in rankings
                       if row["window"] == "day" and row["metric"] == "pnl")
        self.assertEqual(day_pnl["address"], address(2))
        self.assertEqual({row["address"] for row in candidates}, {address(1), address(2)})

    def test_ignores_malformed_window_entries(self) -> None:
        payload = {"leaderboardRows": [{
            "ethAddress": address(1), "accountValue": "2",
            "windowPerformances": [["day"], ["week", None]],
        }]}
        rankings, candidates = rank_leaderboard(payload)
        self.assertEqual(rankings, [])
        self.assertEqual(candidates, [])


class StorageTests(unittest.TestCase):
    def test_compressed_observations_are_idempotent_and_decodable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Store(Path(directory) / "collector.sqlite3") as store:
                payload = {"value": "1.234567890123456789", "array": [1, 2]}
                self.assertTrue(store.save_observation(
                    network="hyperliquid-mainnet", source="test", entity_type="market",
                    entity_id="BTC", endpoint="sample", payload=payload,
                ))
                self.assertFalse(store.save_observation(
                    network="hyperliquid-mainnet", source="test", entity_type="market",
                    entity_id="BTC", endpoint="sample", payload=payload,
                ))
                row = store.observations("hyperliquid-mainnet", "market", "BTC")[0]
                self.assertEqual(row["response_encoding"], "zlib+json")
                self.assertEqual(decode_observation_payload(row), payload)

    def test_cursor_advances_monotonically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Store(Path(directory) / "collector.sqlite3") as store:
                store.set_collection_cursor("net", address(1), "fills", 200)
                store.set_collection_cursor("net", address(1), "fills", 150)
                self.assertEqual(store.collection_cursor("net", address(1), "fills"), 200)


class TimePaginationTests(unittest.TestCase):
    def test_inclusive_boundary_is_deduplicable_and_completes(self) -> None:
        client = HyperliquidInfo("hyperliquid-mainnet")
        first = [{"time": value, "tid": value}
                 for value in range(100, 100 + MAX_PAGE_ROWS)]
        boundary = 99 + MAX_PAGE_ROWS
        second = [{"time": boundary, "tid": boundary},
                  {"time": boundary + 1, "tid": boundary + 1}]
        with patch.object(client, "post_info", side_effect=[first, second]):
            pages = client.collect_time_range("userFillsByTime", address(1), 100, 5000)
        self.assertEqual(len(pages), 2)
        self.assertTrue(all(page.complete for page in pages))
        self.assertEqual(pages[1].request["startTime"], boundary)

    def test_flags_unadvanceable_saturated_page_as_incomplete(self) -> None:
        client = HyperliquidInfo("hyperliquid-mainnet")
        rows = [{"time": 100, "tid": value} for value in range(MAX_PAGE_ROWS)]
        with patch.object(client, "post_info", return_value=rows):
            pages = client.collect_time_range("userFillsByTime", address(1), 100, 100)
        self.assertEqual(len(pages), 1)
        self.assertFalse(pages[0].complete)


if __name__ == "__main__":
    unittest.main()
