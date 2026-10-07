from __future__ import annotations

import json
import re
import threading
import time
from email.utils import parsedate_to_datetime
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from pathlib import Path
from ..telemetry import Telemetry
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
LIGHT_INFO_TYPES = {"l2Book", "clearinghouseState", "spotClearinghouseState"}
INTERVAL_MILLISECONDS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000,
    "4h": 14_400_000, "8h": 28_800_000, "12h": 43_200_000,
    "1d": 86_400_000, "3d": 259_200_000, "1w": 604_800_000,
    "1M": 2_592_000_000,
}
READ_ONLY_INFO_TYPES = {
    "metaAndAssetCtxs", "perpDexs", "allPerpMetas", "spotMetaAndAssetCtxs",
    "userFillsByTime", "userFunding",
    "userNonFundingLedgerUpdates", "clearinghouseState",
    "spotClearinghouseState", "openOrders", "portfolio",
    "l2Book", "candleSnapshot", "userRole", "userAbstraction", "subAccounts",
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
    telemetry_path: Path | None = None

    def __init__(self, network: str, timeout: float = 30.0):
        if network not in NETWORKS:
            raise ValueError(f"Réseau Hyperliquid inconnu : {network}")
        self.network = network
        self.base_url = NETWORKS[network]
        self.timeout = timeout
        self.telemetry = Telemetry(self.telemetry_path) if self.telemetry_path else None
        self.task = threading.current_thread().name

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
            started_at = time.time()
            wait_started = time.monotonic()
            if self.telemetry:
                delay = self.telemetry.reserve(weight, budget_per_minute=INFO_WEIGHT_LIMIT_PER_MINUTE)
                if delay: time.sleep(delay)
            else:
                _wait_for_global_slot(weight)
            wait_seconds = time.monotonic() - wait_started
            sent_at = time.monotonic()
            status, outcome, raw, result = None, "unexpected_error", b"", None
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    status = getattr(response, "status", 200)
                    raw = response.read()
                    result = json.loads(raw.decode("utf-8"))
                    outcome = "ok"
                    return result
            except HTTPError as exc:
                status, outcome = exc.code, "http_error"
                if exc.code not in {429, 500, 502, 503, 504} or attempt >= MAX_RETRIES:
                    raise ProviderError(f"Hyperliquid /info a répondu HTTP {exc.code}.") from exc
                retry_after = _retry_after_seconds(exc.headers.get("Retry-After"))
                delay = retry_after if retry_after is not None else min(30.0, 2.0 ** attempt)
                if self.telemetry: self.telemetry.defer(delay)
                else: _defer_global_requests(delay)
            except (URLError, TimeoutError) as exc:
                outcome = "connection_error"
                if attempt >= MAX_RETRIES:
                    raise ProviderError("Connexion à Hyperliquid impossible ou expirée.") from exc
                delay = min(30.0, 2.0 ** attempt)
                if self.telemetry: self.telemetry.defer(delay)
                else: _defer_global_requests(delay)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                outcome = "decode_error"
                raise ProviderError("Réponse Hyperliquid illisible; rien n’a été enregistré.") from exc
            finally:
                if self.telemetry:
                    items = len(result) if isinstance(result, list) else None
                    self.telemetry.attempt(started_at=started_at, completed_at=time.time(),
                        task=self.task, endpoint=str(query_type), network=self.network,
                        reserved_weight=weight,
                        response_weight_bound=response_weight_bound(payload, items) if outcome == "ok" else None,
                        retry=attempt, outcome=outcome, http_status=status,
                        elapsed_seconds=time.monotonic()-sent_at, wait_seconds=wait_seconds,
                        response_bytes=len(raw), response_items=items)
        raise ProviderError("Échec inattendu des reprises Hyperliquid.")

    def collect_market_snapshot(self) -> Any:
        return self.post_info({"type": "metaAndAssetCtxs"})

    def collect_market_universes(self) -> dict[str, Any]:
        dexes = self.post_info({"type": "perpDexs"})
        if not isinstance(dexes, list) or not dexes:
            raise ProviderError("Réponse perpDexs inattendue.")
        perp_universes = []
        for dex in dexes:
            dex_name = dex.get("name") if isinstance(dex, dict) else None
            request = {"type": "metaAndAssetCtxs"}
            if dex_name:
                request["dex"] = dex_name
            perp_universes.append(self.post_info(request))
        return {
            "perpDexs": dexes,
            "perpUniverses": perp_universes,
            "spotMetaAndAssetCtxs": self.post_info({"type": "spotMetaAndAssetCtxs"}),
        }

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
            "spotClearinghouseState": self.post_info(
                {"type": "spotClearinghouseState", "user": address}
            ),
            "openOrders": self.post_info(
                {"type": "openOrders", "user": address}
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
    if query_type == "userRole":
        return 60
    if query_type == "userFillsByTime":
        return 20 + (MAX_PAGE_ROWS_BY_ENDPOINT[query_type] + 19) // 20
    if query_type == "userFunding":
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


def retained_recent_windows(pages: list[Page], requested_start_ms: int) -> list[Page]:
    """Separate an unprovable old prefix from the API-returned recent suffix.

    Even a short response cannot prove retention before its first fill. The
    first startPosition anchors the observed suffix; no prior PnL is inferred.
    Saturated pagination remains incomplete until it reaches an unsaturated
    response. The known 10k retention cap is not repaired by pagination.
    """
    if not pages or pages[0].endpoint != "userFillsByTime":
        return pages
    times = [int(row["time"]) for page in pages for row in page.rows if isinstance(row,dict) and row.get("time") is not None]
    if not times:
        return [Page(p.endpoint,{**p.request,"coverage_status":"empty_retention_unknown"},p.rows,p.start_ms,p.end_ms,False,p.resume_cursor_ms) for p in pages]
    first = min(times)
    result = []
    if first > requested_start_ms:
        result.append(Page("userFillsByTime",{**pages[0].request,"coverage_status":"old_prefix_retention_unknown"},[],requested_start_ms,first-1,False))
    for page in pages:
        result.append(Page(page.endpoint,{**page.request,"coverage_status":"returned_recent_suffix"},page.rows,max(first,page.start_ms),page.end_ms,page.complete,page.resume_cursor_ms))
    return result


def response_weight_bound(payload: dict[str, Any], items: int | None) -> int:
    """Conservative bound from documented items; charged weight remains unknown."""
    kind = payload.get("type")
    base = 2 if kind in LIGHT_INFO_TYPES else 60 if kind == "userRole" else 20
    if kind == "candleSnapshot": return base + ((items or 0) + 59) // 60
    if kind in {"userFillsByTime", "userFunding"}: return base + ((items or 0) + 19) // 20
    return base
