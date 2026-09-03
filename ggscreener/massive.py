from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class MassiveError(RuntimeError):
    pass


class MassiveClient:
    def __init__(self, api_key: str, base_url: str, timeout: int = 30, retries: int = 3):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "G-GScreener/2.1",
        })
        retry = Retry(
            total=max(0, retries),
            connect=max(0, retries),
            read=max(0, retries),
            status=max(0, retries),
            backoff_factor=0.35,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def get(self, path: str, **params: Any) -> dict:
        params["apiKey"] = self.api_key
        url = path if path.startswith("http") else self.base_url + path
        try:
            r = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise MassiveError(f"Network error: {exc}") from exc
        if r.status_code >= 400:
            body = r.text[:600].replace(self.api_key, "***")
            raise MassiveError(f"HTTP {r.status_code}: {body}")
        try:
            return r.json()
        except ValueError as exc:
            raise MassiveError("Massive returned non-JSON response") from exc

    def snapshot(self) -> list[dict]:
        return self.get(
            "/v2/snapshot/locale/us/markets/stocks/tickers",
            include_otc="false",
        ).get("tickers", []) or []

    def overview(self, ticker: str) -> dict:
        return self.get(f"/v3/reference/tickers/{ticker}").get("results", {}) or {}

    def grouped_day(self, date_iso: str) -> list[dict]:
        return self.get(
            f"/v2/aggs/grouped/locale/us/market/stocks/{date_iso}",
            adjusted="true",
            include_otc="false",
        ).get("results", []) or []

    def aggs(self, ticker: str, multiplier: int, timespan: str, start: str, end: str, limit: int = 50000) -> list[dict]:
        data = self.get(
            f"/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{start}/{end}",
            adjusted="true",
            sort="asc",
            limit=limit,
        )
        rows = data.get("results", []) or []
        if data.get("next_url"):
            raise MassiveError(f"Aggregate result for {ticker} paginated; narrow the requested range.")
        return rows

    def news(self, ticker: str, lookback_hours: int = 72, limit: int = 10) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        data = self.get(
            "/v2/reference/news",
            ticker=ticker,
            **{
                "published_utc.gte": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "order": "desc",
                "sort": "published_utc",
                "limit": limit,
            },
        )
        return data.get("results", []) or []
