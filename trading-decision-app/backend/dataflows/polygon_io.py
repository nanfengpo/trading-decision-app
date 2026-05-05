"""
Polygon.io — premium real-time market data + news flow.

API key env: POLYGON_API_KEY

Coverage (skeleton):
  - market   ✅ /v2/aggs/ticker/{T}/range/1/day   (daily candles)
  - news     ✅ /v2/reference/news?ticker=…
  - options  TODO  /v3/snapshot/options/{ticker} (IV, gamma exposure)
  - crypto   TODO  /v2/aggs/ticker/X:BTCUSD/range/…

The market + news methods are wired up; options/crypto are stubs left
for whoever needs them — wire to summarize.* same way.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import requests

from .cache import cached
from .registry import BaseDataSource, Category, VendorMeta, register
from .summarize import summarize_news, summarize_quotes

logger = logging.getLogger(__name__)

_BASE = "https://api.polygon.io"
_TIMEOUT = 8


class PolygonIO(BaseDataSource):
    name = "polygon_io"
    api_key_env = "POLYGON_API_KEY"

    def _get(self, path: str, **params) -> Optional[dict]:
        if not self.is_configured:
            return None
        params["apiKey"] = self.api_key
        try:
            r = requests.get(f"{_BASE}{path}", params=params, timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning("polygon %s failed: %s", path, e)
            return None

    @cached(ttl=300)
    def fetch_quote_summary(self, ticker: str) -> Optional[str]:
        end = datetime.utcnow().date()
        start = end - timedelta(days=365)
        data = self._get(
            f"/v2/aggs/ticker/{ticker}/range/1/day/{start.isoformat()}/{end.isoformat()}",
            adjusted="true", sort="asc",
        )
        if not data or not data.get("results"):
            return None
        closes = [r["c"] for r in data["results"]]
        return summarize_quotes({"closes": closes}, ticker)

    @cached(ttl=600)
    def fetch_news_summary(self, ticker: str, lookback_days: int = 7) -> Optional[str]:
        # Polygon news has decent coverage with sentiment scores.
        published_gte = (datetime.utcnow() - timedelta(days=lookback_days)).isoformat() + "Z"
        data = self._get(
            "/v2/reference/news",
            ticker=ticker, **{"published_utc.gte": published_gte},
            limit=50, order="desc", sort="published_utc",
        )
        if not data or not data.get("results"):
            return None
        items = [{
            "headline": r.get("title"),
            "summary": r.get("description"),
            "url": r.get("article_url"),
            "source": (r.get("publisher") or {}).get("name"),
            "datetime": r.get("published_utc"),
        } for r in data["results"]]
        return summarize_news(items, top_k=5, ticker=ticker)

    # options / crypto: TODO
    # def fetch_options_summary(self, ticker): ...


def _factory() -> PolygonIO:
    return PolygonIO()


register(VendorMeta(
    name="polygon_io",
    display_name="Polygon.io",
    api_key_env="POLYGON_API_KEY",
    categories=[Category.MARKET, Category.NEWS],
    factory=_factory,
))
