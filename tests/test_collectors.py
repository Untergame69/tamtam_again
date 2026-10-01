from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tamtam_again.analysis import observed_account_summary
from tamtam_again.cli import _collect_market_cycle
from tamtam_again.markets import top_markets
from tamtam_again.providers.hyperliquid import (
    MAX_PAGE_ROWS_BY_ENDPOINT,
    HyperliquidInfo,
    _request_weight,
)
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

    def test_ranks_spot_and_every_perp_dex_in_one_volume_order(self) -> None:
        snapshot = {
            "perpDexs": [None, {"name": "xyz", "fullName": "XYZ Perps"}],
            "perpUniverses": [
                [{"universe": [{"name": "BTC"}, {"name": "ETH"}]},
                 [{"dayNtlVlm": "500"}, {"dayNtlVlm": "100"}]],
                [{"universe": [{"name": "xyz:XYZ100"}]},
                 [{"dayNtlVlm": "800"}]],
            ],
            "spotMetaAndAssetCtxs": [
                {"universe": [{"name": "TOKEN/USDC"}]},
                [{"coin": "UNLISTED/USDC", "dayNtlVlm": "9000"},
                 {"coin": "TOKEN/USDC", "dayNtlVlm": "700"}],
            ],
        }
        rows = top_markets(snapshot, limit=3)
        self.assertEqual([row["coin"] for row in rows],
                         ["xyz:XYZ100", "TOKEN/USDC", "BTC"])
        self.assertEqual([row["market_type"] for row in rows],
                         ["perp", "spot", "perp"])
        self.assertEqual([row["venue"] for row in rows],
                         ["perps:xyz", "spot", "perps-main"])


class MarketCollectionIntegrationTests(unittest.TestCase):
    def test_collects_combined_universes_and_selected_market_data(self) -> None:
        payload = {
            "perpDexs": [None, {"name": "xyz"}],
            "perpUniverses": [
                [{"universe": [{"name": "BTC"}]}, [{"dayNtlVlm": "500"}]],
                [{"universe": [{"name": "xyz:XYZ100"}]}, [{"dayNtlVlm": "900"}]],
            ],
            "spotMetaAndAssetCtxs": [
                {"universe": [{"name": "TOKEN/USDC"}]},
                [{"coin": "TOKEN/USDC", "dayNtlVlm": "700"}],
            ],
        }

        class FakeInfo:
            def __init__(self, _network: str):
                pass

            def collect_market_universes(self):
                return payload

            def collect_order_book(self, coin: str):
                return {"coin": coin, "levels": [[], []]}

            def collect_candles(self, coin: str, interval: str,
                                start_ms: int, end_ms: int):
                return [{"s": coin, "i": interval, "t": start_ms, "T": end_ms}]

        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "collector.sqlite3"
            with patch("tamtam_again.cli.HyperliquidInfo", FakeInfo):
                result = _collect_market_cycle(db, "hyperliquid-mainnet", "1m", 5)
            with Store(db) as store:
                selection = store.latest_market_selection("hyperliquid-mainnet")
                raw_universes = store.connection.execute(
                    "SELECT endpoint FROM raw_observations WHERE entity_type='market' "
                    "AND endpoint IN ('metaAndAssetCtxs','perpDexs','spotMetaAndAssetCtxs') "
                    "ORDER BY endpoint"
                ).fetchall()
        self.assertEqual(result["markets_in_universe"], 3)
        self.assertEqual([row["coin"] for row in result["top_markets"]],
                         ["xyz:XYZ100", "TOKEN/USDC", "BTC"])
        self.assertEqual(len(selection["markets"]), 3)
        self.assertEqual(len(raw_universes), 4)


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

    def test_latest_observation_timestamp_is_available_for_daily_archiving(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Store(Path(directory) / "collector.sqlite3") as store:
                self.assertIsNone(store.latest_observation_at(
                    "net", "source", "discovery", "leaderboard", "daily"
                ))
                store.save_observation(
                    network="net", source="source", entity_type="discovery",
                    entity_id="leaderboard", endpoint="daily", payload={"rows": []},
                    requested_at="2026-10-01T12:00:00.000+00:00",
                )
                observed_at = store.latest_observation_at(
                    "net", "source", "discovery", "leaderboard", "daily"
                )
                self.assertIsNotNone(observed_at)
                self.assertTrue(observed_at.endswith("+00:00"))

    def test_whale_selection_rotates_to_uncollected_accounts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with Store(Path(directory) / "collector.sqlite3") as store:
                rows = []
                for rank, number in enumerate((1, 2), start=1):
                    rows.append({
                        "window": "allTime", "metric": "pnl", "rank": rank,
                        "address": address(number), "display_name": "",
                        "account_value": "100", "pnl": str(100 - rank),
                        "roi": "0.1", "volume": "1000",
                    })
                store.save_whale_rankings("snapshot", "net", "now", rows)
                store.set_collection_cursor("net", address(1), "fills", 200)
                selected = store.whale_addresses("snapshot", 1)
                self.assertEqual(selected[0]["address"], address(2))

    def test_analysis_deduplicates_inclusive_page_boundaries(self) -> None:
        account = address(1)
        fill_a = {"coin": "BTC", "tid": 1, "time": 200, "closedPnl": "2", "fee": "0"}
        fill_b = {"coin": "BTC", "tid": 2, "time": 201, "closedPnl": "3", "fee": "0"}
        funding = {"time": 200, "hash": "funding-1", "delta": {"usdc": "1"}}
        ledger_a = {"time": 200, "hash": "ledger-1", "delta": {"type": "deposit"}}
        ledger_b = {"time": 201, "hash": "ledger-2", "delta": {"type": "withdraw"}}
        with tempfile.TemporaryDirectory() as directory:
            with Store(Path(directory) / "collector.sqlite3") as store:
                for endpoint, payloads in (
                    ("userFillsByTime", [[fill_a], [fill_a, fill_b]]),
                    ("userFunding", [[funding], [funding]]),
                    ("userNonFundingLedgerUpdates", [[ledger_a], [ledger_a, ledger_b]]),
                ):
                    for window, payload in zip(((100, 200), (199, 300)), payloads):
                        store.save_observation(
                            network="hyperliquid-mainnet", source="test",
                            entity_type="account", entity_id=account,
                            endpoint=endpoint, payload=payload,
                            window_start_ms=window[0], window_end_ms=window[1],
                        )
                result = observed_account_summary(
                    store, "hyperliquid-mainnet", account, 100, 300
                )
        self.assertEqual(result["unique_fill_count_observed"], 2)
        self.assertEqual(result["funding_usdc_observed"], "1")
        self.assertEqual(result["non_funding_ledger_event_count_observed"], 2)
        self.assertTrue(result["history_coverage_complete"])

    def test_completed_resume_closes_prior_incomplete_window(self) -> None:
        account = address(2)
        empty = []
        with tempfile.TemporaryDirectory() as directory:
            with Store(Path(directory) / "collector.sqlite3") as store:
                store.save_observation(
                    network="hyperliquid-mainnet", source="test",
                    entity_type="account", entity_id=account,
                    endpoint="userFunding", payload=empty,
                    window_start_ms=0, window_end_ms=50, complete=False,
                )
                store.save_observation(
                    network="hyperliquid-mainnet", source="test",
                    entity_type="account", entity_id=account,
                    endpoint="userFunding", payload=empty,
                    window_start_ms=100, window_end_ms=200, complete=False,
                )
                store.save_observation(
                    network="hyperliquid-mainnet", source="test",
                    entity_type="account", entity_id=account,
                    endpoint="userFunding", payload=empty,
                    window_start_ms=199, window_end_ms=300, complete=True,
                )
                store.mark_history_observations_complete(
                    "hyperliquid-mainnet", account, "userFunding", 199
                )
                statuses = [row[0] for row in store.connection.execute(
                    "SELECT complete FROM raw_observations WHERE entity_id=? ORDER BY window_start_ms",
                    (account,),
                )]
                result = observed_account_summary(
                    store, "hyperliquid-mainnet", account, 100, 300
                )
        self.assertEqual(statuses, [0, 1, 1])
        self.assertTrue(result["history_coverage_by_endpoint"]["userFunding"])
        self.assertFalse(result["history_coverage_complete"])

    def test_report_marks_uncollected_time_outside_window_incomplete(self) -> None:
        account = address(3)
        with tempfile.TemporaryDirectory() as directory:
            with Store(Path(directory) / "collector.sqlite3") as store:
                for endpoint in ("userFillsByTime", "userFunding",
                                 "userNonFundingLedgerUpdates"):
                    store.save_observation(
                        network="hyperliquid-mainnet", source="test",
                        entity_type="account", entity_id=account,
                        endpoint=endpoint, payload=[],
                        window_start_ms=100, window_end_ms=300,
                    )
                result = observed_account_summary(
                    store, "hyperliquid-mainnet", account, 50, 300
                )
        self.assertFalse(result["history_coverage_complete"])


class TimePaginationTests(unittest.TestCase):
    def test_inclusive_boundary_is_deduplicable_and_completes(self) -> None:
        client = HyperliquidInfo("hyperliquid-mainnet")
        page_limit = MAX_PAGE_ROWS_BY_ENDPOINT["userFillsByTime"]
        first = [{"time": value, "tid": value}
                 for value in range(100, 100 + page_limit)]
        boundary = 99 + page_limit
        second = [{"time": boundary, "tid": boundary},
                  {"time": boundary + 1, "tid": boundary + 1}]
        with patch.object(client, "post_info", side_effect=[first, second]):
            pages = client.collect_time_range("userFillsByTime", address(1), 100, 5000)
        self.assertEqual(len(pages), 2)
        self.assertTrue(all(page.complete for page in pages))
        self.assertEqual(pages[1].request["startTime"], boundary)

    def test_flags_unadvanceable_saturated_page_as_incomplete(self) -> None:
        client = HyperliquidInfo("hyperliquid-mainnet")
        rows = [{"time": 100, "tid": value}
                for value in range(MAX_PAGE_ROWS_BY_ENDPOINT["userFillsByTime"])]
        with patch.object(client, "post_info", return_value=rows):
            pages = client.collect_time_range("userFillsByTime", address(1), 100, 100)
        self.assertEqual(len(pages), 1)
        self.assertFalse(pages[0].complete)
        self.assertIsNone(pages[0].resume_cursor_ms)

    def test_uses_endpoint_specific_time_page_limits(self) -> None:
        client = HyperliquidInfo("hyperliquid-mainnet")
        rows = [{"time": value, "hash": str(value)}
                for value in range(100, 100 + MAX_PAGE_ROWS_BY_ENDPOINT["userFunding"])]
        final = [{"time": 600, "hash": "final"}]
        with patch.object(client, "post_info", side_effect=[rows, final]):
            pages = client.collect_time_range("userFunding", address(1), 100, 1000)
        self.assertEqual(len(pages), 2)
        self.assertTrue(pages[-1].complete)
        self.assertEqual(pages[-1].resume_cursor_ms, 1000)

    def test_saturated_fill_cap_returns_a_safe_resume_cursor(self) -> None:
        client = HyperliquidInfo("hyperliquid-mainnet")
        limit = MAX_PAGE_ROWS_BY_ENDPOINT["userFillsByTime"]
        batches = []
        cursor = 100
        for page_index in range(5):
            batch = [{"time": value, "tid": value}
                     for value in range(cursor, cursor + limit)]
            batches.append(batch)
            cursor = batch[-1]["time"]
        with patch.object(client, "post_info", side_effect=batches):
            pages = client.collect_time_range("userFillsByTime", address(1), 100, 100_000)
        self.assertEqual(len(pages), 5)
        self.assertFalse(pages[-1].complete)
        self.assertEqual(pages[-1].resume_cursor_ms, batches[-1][-1]["time"])


class AccountSnapshotTests(unittest.TestCase):
    def test_collects_perp_spot_orders_and_portfolio_snapshots(self) -> None:
        client = HyperliquidInfo("hyperliquid-mainnet")
        with patch.object(client, "post_info", side_effect=[{}, {}, [], []]) as request:
            snapshots = client.collect_account_snapshots(address(1))
        self.assertEqual(set(snapshots), {
            "clearinghouseState", "spotClearinghouseState", "openOrders", "portfolio",
        })
        self.assertEqual([call.args[0]["type"] for call in request.call_args_list], [
            "clearinghouseState", "spotClearinghouseState", "openOrders", "portfolio",
        ])

    def test_collects_all_perp_dexes_and_spot_contexts(self) -> None:
        client = HyperliquidInfo("hyperliquid-mainnet")
        with patch.object(client, "post_info", side_effect=[
                [None, {"name": "xyz"}], [], [], [[], []]]) as request:
            universes = client.collect_market_universes()
        self.assertEqual(set(universes), {
            "perpDexs", "perpUniverses", "spotMetaAndAssetCtxs",
        })
        self.assertEqual([call.args[0]["type"] for call in request.call_args_list], [
            "perpDexs", "metaAndAssetCtxs", "metaAndAssetCtxs",
            "spotMetaAndAssetCtxs",
        ])
        self.assertNotIn("dex", request.call_args_list[1].args[0])
        self.assertEqual(request.call_args_list[2].args[0]["dex"], "xyz")


class RequestWeightTests(unittest.TestCase):
    def test_estimates_weight_by_endpoint_and_window(self) -> None:
        self.assertEqual(_request_weight({"type": "l2Book", "coin": "BTC"}), 2)
        self.assertEqual(_request_weight({"type": "userFillsByTime"}), 120)
        self.assertEqual(_request_weight({"type": "userFunding"}), 45)
        self.assertEqual(_request_weight({"type": "candleSnapshot", "req": {
            "interval": "1m", "startTime": 0, "endTime": 300_000,
        }}), 21)


if __name__ == "__main__":
    unittest.main()
