"""
Alpha Vantage Premium — fundamentals + technical indicators.

API key env: ALPHA_VANTAGE_API_KEY  (premium plans get rate limits up
to 1200 calls/min; free is 5/min)

Skeleton: market + fundamentals wired through summarize.*.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from .registry import BaseDataSource, Category, VendorMeta, register
from .summarize import summarize_quotes, summarize_fundamentals

logger = logging.getLogger(__name__)

_BASE = "https://www.alphavantage.co/query"
_TIMEOUT = 10


class AlphaVantage(BaseDataSource):
    name = "alpha_vantage"
    api_key_env = "ALPHA_VANTAGE_API_KEY"

    def _get(self, **params) -> Optional[dict]:
        if not self.is_configured:
            return None
        params["apikey"] = self.api_key
        try:
            r = requests.get(_BASE, params=params, timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning("alpha-vantage failed: %s", e)
            return None

    def fetch_quote_summary(self, ticker: str) -> Optional[str]:
        data = self._get(function="TIME_SERIES_DAILY_ADJUSTED",
                         symbol=ticker, outputsize="compact")
        ts = (data or {}).get("Time Series (Daily)") or {}
        if not ts:
            return None
        closes = [float(v["5. adjusted close"]) for _, v in sorted(ts.items())]
        return summarize_quotes({"closes": closes}, ticker)

    def fetch_fundamentals_summary(self, ticker: str) -> Optional[str]:
        ov = self._get(function="OVERVIEW", symbol=ticker)
        if not ov or "Symbol" not in ov:
            return None
        # Map Alpha Vantage names → the keys our summariser knows
        flat = lambda v: float(v) if v not in (None, "None", "—") else None
        metrics = {
            "peTTM": flat(ov.get("TrailingPE")),
            "pbTTM": flat(ov.get("PriceToBookRatio")),
            "psTTM": flat(ov.get("PriceToSalesRatioTTM")),
            "roeTTM": flat(ov.get("ReturnOnEquityTTM")),
            "debtEquity": None,
            "freeCashFlowTTM": None,
            "revenueGrowthTTMYoy": flat(ov.get("QuarterlyRevenueGrowthYOY")),
        }
        return summarize_fundamentals(metrics, ticker)


def _factory() -> AlphaVantage:
    return AlphaVantage()


register(VendorMeta(
    name="alpha_vantage",
    display_name="Alpha Vantage Premium",
    api_key_env="ALPHA_VANTAGE_API_KEY",
    categories=[Category.MARKET, Category.FUNDAMENTALS],
    factory=_factory,
))
