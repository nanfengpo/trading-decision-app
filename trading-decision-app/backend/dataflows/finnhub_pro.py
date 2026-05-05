"""
Finnhub Pro — premium news + fundamentals + insider transactions.

API key env: FINNHUB_API_KEY  (works for free tier too; pro just unlocks
higher rate limits and 1y+ history)

Coverage in this module:
  - news        ✅ /company-news + /news (general)
  - fundamentals✅ /stock/metric  (basic-financials)
  - social      ⚠ /stock/social-sentiment is a separate paid endpoint;
                  this module returns None unless it works.
  - market      ✅ /quote (single quote — used for opportunities scanner)

Each method calls the API, then funnels through dataflows.summarize.* so
the agent only sees a tiny markdown blob, not the raw JSON.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import requests

from .registry import BaseDataSource, Category, VendorMeta, register
from .summarize import (
    summarize_news,
    summarize_quotes,
    summarize_fundamentals,
    summarize_social,
)

logger = logging.getLogger(__name__)

_BASE = "https://finnhub.io/api/v1"
_TIMEOUT = 8


class FinnhubPro(BaseDataSource):
    name = "finnhub_pro"
    api_key_env = "FINNHUB_API_KEY"

    # ---- helpers -------------------------------------------------------

    def _get(self, path: str, **params) -> Optional[dict | list]:
        if not self.is_configured:
            return None
        params["token"] = self.api_key
        try:
            r = requests.get(f"{_BASE}{path}", params=params, timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning("finnhub %s failed: %s", path, e)
            return None

    # ---- news ----------------------------------------------------------

    def fetch_news_summary(self, ticker: str, lookback_days: int = 7) -> Optional[str]:
        end = datetime.utcnow().date()
        start = end - timedelta(days=lookback_days)
        items = self._get(
            "/company-news",
            symbol=ticker,
            **{"from": start.isoformat(), "to": end.isoformat()},
        )
        if not items:
            return None
        return summarize_news(items, top_k=5, ticker=ticker)

    # ---- quote ---------------------------------------------------------

    def fetch_quote_summary(self, ticker: str) -> Optional[str]:
        # Finnhub /quote returns a single point — we synthesise an OHLCV
        # series from /stock/candle (1y daily) for a meaningful trend view.
        end_ts = int(datetime.utcnow().timestamp())
        start_ts = int((datetime.utcnow() - timedelta(days=365)).timestamp())
        candles = self._get(
            "/stock/candle",
            symbol=ticker, resolution="D", **{"from": start_ts, "to": end_ts},
        )
        if not candles or candles.get("s") != "ok":
            return None
        return summarize_quotes({"closes": candles.get("c", [])}, ticker)

    # ---- fundamentals --------------------------------------------------

    def fetch_fundamentals_summary(self, ticker: str) -> Optional[str]:
        data = self._get("/stock/metric", symbol=ticker, metric="all")
        if not data:
            return None
        metrics = (data.get("metric") or {})
        return summarize_fundamentals(metrics, ticker)

    # ---- social --------------------------------------------------------

    def fetch_social_summary(self, ticker: str, lookback_days: int = 7) -> Optional[str]:
        end = datetime.utcnow().date()
        start = end - timedelta(days=lookback_days)
        data = self._get(
            "/stock/social-sentiment",
            symbol=ticker, **{"from": start.isoformat(), "to": end.isoformat()},
        )
        if not data:
            return None
        # Finnhub returns {reddit:[…], twitter:[…]} of {atTime, mention,
        # positiveScore, negativeScore, …}
        flat = []
        for src in ("reddit", "twitter"):
            for p in (data.get(src) or [])[:200]:
                flat.append({
                    "title": f"[{src}] {p.get('mention',0)} mentions",
                    "text": "",
                    "datetime": p.get("atTime"),
                    "_pos": p.get("positiveScore", 0),
                    "_neg": p.get("negativeScore", 0),
                })
        if not flat:
            return None
        return summarize_social(flat, ticker, lookback_days=lookback_days)


def _factory() -> FinnhubPro:
    return FinnhubPro()


register(VendorMeta(
    name="finnhub_pro",
    display_name="Finnhub Pro",
    api_key_env="FINNHUB_API_KEY",
    categories=[Category.NEWS, Category.FUNDAMENTALS, Category.SOCIAL, Category.MARKET],
    factory=_factory,
))
