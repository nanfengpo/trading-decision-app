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

from concurrent.futures import ThreadPoolExecutor

from .cache import cached
from .registry import BaseDataSource, Category, VendorMeta, register
from .summarize import (
    summarize_quotes,
    summarize_fundamentals,
    summarize_indicators_detailed,
)

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

    @cached(ttl=300)
    def fetch_quote_summary(self, ticker: str) -> Optional[str]:
        data = self._get(function="TIME_SERIES_DAILY_ADJUSTED",
                         symbol=ticker, outputsize="compact")
        ts = (data or {}).get("Time Series (Daily)") or {}
        if not ts:
            return None
        closes = [float(v["5. adjusted close"]) for _, v in sorted(ts.items())]
        return summarize_quotes({"closes": closes}, ticker)

    # ---- detailed indicators (Phase A.2) ------------------------------
    # Alpha Vantage exposes one endpoint per indicator. We fan out 5 calls
    # in parallel (capped to 5 for free-tier rate limit; premium tier is
    # 1200/min so even more parallelism would be safe).

    @staticmethod
    def _last_value(series: dict, key: str) -> Optional[float]:
        """Pick the most recent (lexicographically last) date and return
        the named float field. AV indicator responses are date-keyed."""
        if not series:
            return None
        last_date = max(series.keys())
        try:
            return float(series[last_date][key])
        except (KeyError, ValueError, TypeError):
            return None

    @cached(ttl=300)
    def fetch_indicator_summary(self, ticker: str, days: int = 90) -> Optional[str]:
        if not self.is_configured:
            return None

        # Each call returns the latest 100+ data points; we only need the latest.
        endpoints = [
            ("RSI",   {"function": "RSI",   "symbol": ticker, "interval": "daily", "time_period": 14, "series_type": "close"}),
            ("MACD",  {"function": "MACD",  "symbol": ticker, "interval": "daily", "series_type": "close"}),
            ("BBANDS",{"function": "BBANDS","symbol": ticker, "interval": "daily", "time_period": 20, "series_type": "close", "nbdevup": 2, "nbdevdn": 2}),
            ("ATR",   {"function": "ATR",   "symbol": ticker, "interval": "daily", "time_period": 14}),
            ("ADX",   {"function": "ADX",   "symbol": ticker, "interval": "daily", "time_period": 14}),
        ]
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(self._get, **params): name for name, params in endpoints}
            results: dict[str, dict] = {}
            for fut in futures:
                name = futures[fut]
                try:
                    results[name] = fut.result(timeout=12) or {}
                except Exception as e:
                    logger.warning("alpha-vantage %s failed: %s", name, e)
                    results[name] = {}

        flat = {}
        rsi_series = results["RSI"].get("Technical Analysis: RSI") or {}
        flat["rsi"] = self._last_value(rsi_series, "RSI")

        macd_series = results["MACD"].get("Technical Analysis: MACD") or {}
        flat["macd"]        = self._last_value(macd_series, "MACD")
        flat["macd_signal"] = self._last_value(macd_series, "MACD_Signal")
        flat["macd_hist"]   = self._last_value(macd_series, "MACD_Hist")

        bb_series = results["BBANDS"].get("Technical Analysis: BBANDS") or {}
        flat["bb_upper"]  = self._last_value(bb_series, "Real Upper Band")
        flat["bb_middle"] = self._last_value(bb_series, "Real Middle Band")
        flat["bb_lower"]  = self._last_value(bb_series, "Real Lower Band")
        # %B = (price - lower) / (upper - lower); price not in this response so leave None

        atr_series = results["ATR"].get("Technical Analysis: ATR") or {}
        flat["atr"] = self._last_value(atr_series, "ATR")

        adx_series = results["ADX"].get("Technical Analysis: ADX") or {}
        flat["adx"] = self._last_value(adx_series, "ADX")

        # If all values are None, signal failure so route_to_vendor falls back.
        if not any(v is not None for v in flat.values()):
            return None

        return summarize_indicators_detailed(flat, ticker)

    @cached(ttl=3600)
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
