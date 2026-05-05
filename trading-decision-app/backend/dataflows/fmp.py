"""
FMP Premium — Financial Modeling Prep, the "deep fundamentals" vendor.

API key env: FMP_API_KEY  (premium tier unlocks 3-statement quarterly
detail + intraday history + complete news archive)

Coverage in this module:
  - market         ✅ /historical-price-full (1y daily closes)
  - fundamentals   ✅ /key-metrics-ttm + /ratios-ttm  (combined)
  - balance sheet  ✅ /balance-sheet-statement (latest quarterly)
  - income stmt    ✅ /income-statement (latest quarterly)
  - cashflow       ✅ /cash-flow-statement (latest quarterly)
  - news           ✅ /stock_news?tickers=…

Like the other vendors, every fetch_* method funnels through
``dataflows.summarize.*`` so the agent sees a compact markdown blob, not
raw JSON. FMP's response field names are mapped to the canonical names
the summarisers expect (see _map_balance_sheet etc. below).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import requests

from .cache import cached
from .registry import BaseDataSource, Category, VendorMeta, register
from .summarize import (
    summarize_news,
    summarize_quotes,
    summarize_fundamentals,
    summarize_balance_sheet,
    summarize_income_statement,
    summarize_cashflow,
)

logger = logging.getLogger(__name__)

_BASE = "https://financialmodelingprep.com/api/v3"
_TIMEOUT = 8


class FMP(BaseDataSource):
    name = "fmp"
    api_key_env = "FMP_API_KEY"

    # ---- helpers -------------------------------------------------------

    def _get(self, path: str, **params) -> Optional[dict | list]:
        if not self.is_configured:
            return None
        params["apikey"] = self.api_key
        try:
            r = requests.get(f"{_BASE}{path}", params=params, timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning("fmp %s failed: %s", path, e)
            return None

    # ---- quote ---------------------------------------------------------

    @cached(ttl=300)                  # 5 min — daily candles aren't volatile
    def fetch_quote_summary(self, ticker: str) -> Optional[str]:
        # /historical-price-full returns {"symbol":..., "historical":[
        #   {"date":"2024-…", "close":…, "open":…, ...}, ...]}
        # `serietype=line` trims to date+close only (smaller payload).
        data = self._get(
            f"/historical-price-full/{ticker}",
            serietype="line",
            timeseries=365,
        )
        if not data:
            return None
        history = data.get("historical") or []
        if not history:
            return None
        # FMP returns newest first — reverse for chronological order so
        # closes[-1] is the most recent (matches summarize_quotes contract).
        closes = [h.get("close") for h in reversed(history) if h.get("close") is not None]
        if not closes:
            return None
        return summarize_quotes({"closes": closes}, ticker)

    # ---- fundamentals --------------------------------------------------

    @cached(ttl=3600)                 # ratios change slowly — 1 hour
    def fetch_fundamentals_summary(self, ticker: str) -> Optional[str]:
        # /key-metrics-ttm/{T}  → list of length 1 with peRatioTTM, pbRatioTTM,
        # roeTTM, freeCashFlowPerShareTTM, debtToEquityTTM, etc.
        # /ratios-ttm/{T}       → list of length 1 with priceEarningsRatioTTM,
        # priceToSalesRatioTTM, returnOnEquityTTM, debtEquityRatioTTM, etc.
        km = self._get(f"/key-metrics-ttm/{ticker}")
        rt = self._get(f"/ratios-ttm/{ticker}")
        km_row = (km[0] if isinstance(km, list) and km else {}) or {}
        rt_row = (rt[0] if isinstance(rt, list) and rt else {}) or {}
        if not km_row and not rt_row:
            return None
        # summarize_fundamentals uses pick() on a flat dict of standard names
        # (peTTM / pbTTM / psTTM / roeTTM / debtEquity / freeCashFlowTTM /
        # revenueGrowthTTMYoy). Map FMP's field names onto those.
        metrics: Dict[str, float] = {
            "peTTM":      km_row.get("peRatioTTM") or rt_row.get("priceEarningsRatioTTM"),
            "pbTTM":      km_row.get("pbRatioTTM") or rt_row.get("priceToBookRatioTTM"),
            "psTTM":      rt_row.get("priceToSalesRatioTTM") or km_row.get("priceToSalesRatioTTM"),
            "roeTTM":     km_row.get("roeTTM") or rt_row.get("returnOnEquityTTM"),
            "debtEquity": km_row.get("debtToEquityTTM") or rt_row.get("debtEquityRatioTTM"),
            "freeCashFlowTTM":      km_row.get("freeCashFlowPerShareTTM"),
            "revenueGrowthTTMYoy":  km_row.get("revenueGrowthTTM") or rt_row.get("revenueGrowthTTM"),
        }
        # Drop None values so summarize_fundamentals' pick() short-circuits cleanly.
        metrics = {k: v for k, v in metrics.items() if v is not None}
        if not metrics:
            return None
        return summarize_fundamentals(metrics, ticker)

    # ---- 3-statement detail (FMP's strongest suite) -------------------

    @cached(ttl=3600)
    def fetch_balance_sheet_summary(self, ticker: str) -> Optional[str]:
        # /balance-sheet-statement returns a list of filings, newest first.
        rows = self._get(f"/balance-sheet-statement/{ticker}", limit=1)
        if not rows or not isinstance(rows, list):
            return None
        row = rows[0] or {}
        # FMP fields → summarize_balance_sheet canonical names:
        #   totalAssets / totalLiabilities → same
        #   totalEquity (some filings use totalStockholdersEquity)
        #   cashAndShortTermInvestments OR cashAndCashEquivalents
        #   longTermDebt / shortTermDebt → same
        #   date → period
        canonical = {
            "totalAssets":            row.get("totalAssets"),
            "totalLiabilities":       row.get("totalLiabilities"),
            "totalEquity":            row.get("totalEquity") or row.get("totalStockholdersEquity"),
            "cashAndCashEquivalents": row.get("cashAndCashEquivalents") or row.get("cashAndShortTermInvestments"),
            "longTermDebt":           row.get("longTermDebt"),
            "shortTermDebt":          row.get("shortTermDebt"),
            "period":                 (row.get("date") or "")[:10],
        }
        return summarize_balance_sheet(canonical, ticker)

    @cached(ttl=3600)
    def fetch_income_statement_summary(self, ticker: str) -> Optional[str]:
        rows = self._get(f"/income-statement/{ticker}", limit=1)
        if not rows or not isinstance(rows, list):
            return None
        row = rows[0] or {}
        # FMP income-statement field names already align closely with
        # summarize_income_statement's expected keys.
        canonical = {
            "revenue":         row.get("revenue"),
            "costOfRevenue":   row.get("costOfRevenue"),
            "grossProfit":     row.get("grossProfit"),
            "operatingIncome": row.get("operatingIncome"),
            "netIncome":       row.get("netIncome"),
            "eps":             row.get("eps") or row.get("epsdiluted"),
            "period":          (row.get("date") or "")[:10],
        }
        return summarize_income_statement(canonical, ticker)

    @cached(ttl=3600)
    def fetch_cashflow_summary(self, ticker: str) -> Optional[str]:
        rows = self._get(f"/cash-flow-statement/{ticker}", limit=1)
        if not rows or not isinstance(rows, list):
            return None
        row = rows[0] or {}
        # FMP names are very close already; capex is reported as a negative
        # outflow (matches summarize_cashflow's expectation).
        cfo = row.get("operatingCashFlow") or row.get("netCashProvidedByOperatingActivities")
        cfi = row.get("netCashUsedForInvestingActivites") or row.get("netCashUsedForInvestingActivities")
        cff = row.get("netCashUsedProvidedByFinancingActivities")
        capex = row.get("capitalExpenditure")
        if isinstance(capex, (int, float)) and capex > 0:
            capex = -capex
        fcf = row.get("freeCashFlow")
        if fcf is None and isinstance(cfo, (int, float)) and isinstance(capex, (int, float)):
            fcf = cfo + capex
        canonical = {
            "operatingCashFlow":  cfo,
            "investingCashFlow":  cfi,
            "financingCashFlow":  cff,
            "capitalExpenditure": capex,
            "freeCashFlow":       fcf,
            "period":             (row.get("date") or "")[:10],
        }
        return summarize_cashflow(canonical, ticker)

    # ---- news ----------------------------------------------------------

    @cached(ttl=600)                  # news rotates fast; 10 min sweet spot
    def fetch_news_summary(self, ticker: str, lookback_days: int = 7) -> Optional[str]:
        # /stock_news returns [{symbol, publishedDate, title, image, site,
        # text, url}, ...] newest first.
        items = self._get("/stock_news", tickers=ticker, limit=50)
        if not items or not isinstance(items, list):
            return None
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        kept = []
        for it in items:
            ts = it.get("publishedDate") or ""
            try:
                # FMP timestamps look like "2025-10-14 13:42:00" — naive UTC.
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except (ValueError, AttributeError):
                continue
            if dt < cutoff:
                continue
            # Reshape into the keys summarize_news already understands.
            kept.append({
                "title":    it.get("title"),
                "summary":  it.get("text"),
                "url":      it.get("url"),
                "source":   it.get("site"),
                "datetime": dt.isoformat(),
            })
        if not kept:
            return None
        return summarize_news(kept, top_k=5, ticker=ticker)


def _factory() -> FMP:
    return FMP()


register(VendorMeta(
    name="fmp",
    display_name="FMP Premium",
    api_key_env="FMP_API_KEY",
    categories=[Category.FUNDAMENTALS, Category.MARKET, Category.NEWS],
    factory=_factory,
))
