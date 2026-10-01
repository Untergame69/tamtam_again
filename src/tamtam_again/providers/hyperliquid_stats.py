from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .hyperliquid import MAX_RETRIES, ProviderError, _retry_after_seconds


# The official web app fetches leaderboard data from this host. This endpoint is
# not part of the documented /info API, so the adapter stores source snapshots
# and validates the response shape instead of treating it as a stable contract.
LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"


class HyperliquidLeaderboard:
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    def fetch(self) -> dict[str, Any]:
        request = Request(LEADERBOARD_URL, headers={
            "Accept": "application/json",
            "User-Agent": "tamtam-again/0.1 read-only research",
        })
        for attempt in range(MAX_RETRIES + 1):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt >= MAX_RETRIES:
                    raise ProviderError(f"Leaderboard Hyperliquid: HTTP {exc.code}.") from exc
                delay = _retry_after_seconds(exc.headers.get("Retry-After"))
                time.sleep(delay if delay is not None else min(30.0, 2.0 ** attempt))
            except (URLError, TimeoutError) as exc:
                if attempt >= MAX_RETRIES:
                    raise ProviderError("Leaderboard Hyperliquid inaccessible ou délai dépassé.") from exc
                time.sleep(min(30.0, 2.0 ** attempt))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProviderError("Réponse leaderboard illisible.") from exc
        else:
            raise ProviderError("Échec des reprises du leaderboard Hyperliquid.")
        if not isinstance(payload, dict) or not isinstance(payload.get("leaderboardRows"), list):
            raise ProviderError("Format leaderboard inattendu; aucune donnée n’a été enregistrée.")
        return payload
