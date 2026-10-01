from __future__ import annotations

import json
import re
import threading
import time
from email.utils import parsedate_to_datetime
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


NETWORKS = {
    "hyperliquid-mainnet": "https://api.hyperliquid.xyz",
    "hyperliquid-testnet": "https://api.hyperliquid-testnet.xyz",
}
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
MAX_PAGE_ROWS_BY_ENDPOINT = {
    "userFillsByTime": 2_000,
    "userFunding": 500,
    "userNonFundingLedgerUpdates": 500,
}
MAX_PAGES_PER_ENDPOINT = 100
MAX_TOTAL_FILLS_BY_TIME = 10_000
INFO_WEIGHT_LIMIT_PER_MINUTE = 900
MAX_RETRIES = 5
LIGHT_INFO_TYPES = {"l2Book", "clearinghouseState"}
INTERVAL_MILLISECONDS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000,
    "4h": 14_400_000, "8h": 28_800_000, "12h": 43_200_000,
    "1d": 86_400_000, "3d": 259_200_000, "1w": 604_800_000,
    "1M": 2_592_000_000,
}
READ_ONLY_INFO_TYPES = {
    "metaAndAssetCtxs", "userFillsByTime", "userFunding",
    "userNonFundingLedgerUpdates", "clearinghouseState", "portfolio",
    "l2Book", "candleSnapshot",
}


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class Page:
    endpoint: str
    request: dict[str, Any]
    rows: list[Any]
    start_ms: int
    end_ms: int
    complete: bool
    resume_cursor_ms: int | None = None


class HyperliquidInfo:
    """Small read-only adapter limited to Hyperliquid's public /info endpoint."""

    _rate_lock = threading.Lock()
    _global_next_request_at = 0.0

    def __init__(self, network: str, timeout: float = 30.0):
        if network not in NETWORKS:
            raise ValueError(f"Réseau Hyperliquid inconnu : {network}")
        self.network = network
        self.base_url = NETWORKS[network]
        self.timeout = timeout

    def post_info(self, payload: dict[str, Any]) -> Any:
        query_type = payload.get("type")
        if query_type not in READ_ONLY_INFO_TYPES:
            raise ValueError("Type de requête non autorisé par l’adaptateur en lecture seule.")
        request = Request(
            self.base_url + "/info",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "User-Agent": "tamtam-again/0.1 read-only research"},
        )
        weight = _request_weight(payload)
        for attempt in range(MAX_RETRIES + 1):
            _wait_for_global_slot(weight)
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt >= MAX_RETRIES:
                    raise ProviderError(f"Hyperliquid /info a répondu HTTP {exc.code}.") from exc
                retry_after = _retry_after_seconds(exc.headers.get("Retry-After"))
                _defer_global_requests(retry_after if retry_after is not None
                                       else min(30.0, 2.0 ** attempt))
            except (URLError, TimeoutError) as exc:
                if attempt >= MAX_RETRIES:
                    raise ProviderError("Connexion à Hyperliquid impossible ou expirée.") from exc
                _defer_global_requests(min(30.0, 2.0 ** attempt))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProviderError("Réponse Hyperliquid illisible; rien n’a été enregistré.") from exc
        raise ProviderError("Échec inattendu des reprises Hyperliquid.")

    def collect_market_snapshot(self) -> Any:
        return self.post_info({"type": "metaAndAssetCtxs"})

    def collect_order_book(self, coin: str) -> Any:
        return self.post_info({"type": "l2Book", "coin": coin})

    def collect_candles(self, coin: str, interval: str,
                        start_ms: int, end_ms: int) -> Any:
        if start_ms < 0 or end_ms < start_ms:
            raise ValueError("Fenêtre de chandelles invalide.")
        if interval not in {"1m", "3m", "5m", "15m", "30m", "1h", "2h",
                            "4h", "8h", "12h", "1d", "3d", "1w", "1M"}:
            raise ValueError("Intervalle de chandelles non pris en charge.")
        return self.post_info({"type": "candleSnapshot", "req": {
            "coin": coin, "interval": interval,
            "startTime": start_ms, "endTime": end_ms,
        }})

    def collect_account_snapshots(self, address: str) -> dict[str, Any]:
        validate_address(address)
        return {
            "clearinghouseState": self.post_info(
                {"type": "clearinghouseState", "user": address}
            ),
            "portfolio": self.post_info({"type": "portfolio", "user": address}),
        }

    def collect_time_range(self, endpoint: str, address: str, start_ms: int,
                           end_ms: int) -> list[Page]:
        validate_address(address)
        if endpoint not in {"userFillsByTime", "userFunding",
                            "userNonFundingLedgerUpdates"}:
            raise ValueError("Endpoint historique non autorisé.")
        if start_ms < 0 or end_ms < start_ms:
            raise ValueError("Fenêtre de temps invalide (millisecondes UTC attendues).")

        pages: list[Page] = []
        cursor = start_ms
        safe_cursor: int | None = None
        for _ in range(MAX_PAGES_PER_ENDPOINT):
            body = {"type": endpoint, "user": address,
                    "startTime": cursor, "endTime": end_ms}
            rows = self.post_info(body)
            if not isinstance(rows, list):
                raise ProviderError(f"Réponse inattendue pour {endpoint}; rien n’a été enregistré.")
            page_limit = MAX_PAGE_ROWS_BY_ENDPOINT[endpoint]
            has_more = len(rows) >= page_limit
            pages.append(Page(endpoint, body, rows, cursor, end_ms, True))
            if not has_more:
                pages[-1] = Page(endpoint, body, rows, cursor, end_ms, True, end_ms)
                return pages
            timestamps = [_event_time(row) for row in rows]
            timestamps = [value for value in timestamps if value is not None]
            if not timestamps:
                break
            next_cursor = max(timestamps)
            # API time ranges are inclusive. Keep the boundary item for deduplication.
            # If a full response has no later timestamp, report a coverage gap rather
            # than advancing past unseen events sharing the same millisecond.
            if next_cursor > cursor:
                safe_cursor = min(next_cursor, end_ms)
            if (endpoint == "userFillsByTime"
                    and sum(len(page.rows) for page in pages) >= MAX_TOTAL_FILLS_BY_TIME):
                break
            if next_cursor <= cursor or next_cursor >= end_ms:
                break
            cursor = next_cursor
        return [Page(page.endpoint, page.request, page.rows, page.start_ms,
                     page.end_ms, False,
                     safe_cursor if index == len(pages) - 1 else None)
                for index, page in enumerate(pages)]


def validate_address(address: str) -> None:
    if not ADDRESS_RE.fullmatch(address):
        raise ValueError("Adresse attendue au format EVM 0x suivi de 40 caractères hexadécimaux.")


def _event_time(row: Any) -> int | None:
    if not isinstance(row, dict):
        return None
    value = row.get("time")
    if value is None and isinstance(row.get("fill"), dict):
        value = row["fill"].get("time")
    try:
        return int(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _request_weight(payload: dict[str, Any]) -> int:
    query_type = payload.get("type")
    if query_type in LIGHT_INFO_TYPES:
        return 2
    if query_type == "userFillsByTime":
        return 20 + (MAX_PAGE_ROWS_BY_ENDPOINT[query_type] + 19) // 20
    if query_type in {"userFunding", "userNonFundingLedgerUpdates"}:
        limit = MAX_PAGE_ROWS_BY_ENDPOINT[query_type]
        return 20 + (limit + 19) // 20
    if query_type == "candleSnapshot":
        request = payload.get("req", {})
        interval = INTERVAL_MILLISECONDS.get(request.get("interval"))
        if interval and request.get("endTime", 0) >= request.get("startTime", 0):
            bars = (request["endTime"] - request["startTime"]) // interval + 1
            return 20 + (bars + 59) // 60
    return 20


def _wait_for_global_slot(weight: int) -> None:
    cls = HyperliquidInfo
    with cls._rate_lock:
        now = time.monotonic()
        scheduled = max(now, cls._global_next_request_at)
        cls._global_next_request_at = scheduled + weight * 60 / INFO_WEIGHT_LIMIT_PER_MINUTE
    if scheduled > now:
        time.sleep(scheduled - now)


def _defer_global_requests(delay_seconds: float) -> None:
    cls = HyperliquidInfo
    with cls._rate_lock:
        cls._global_next_request_at = max(
            cls._global_next_request_at, time.monotonic() + delay_seconds
        )
