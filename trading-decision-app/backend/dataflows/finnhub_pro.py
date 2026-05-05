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
from typing import Dict, Optional

import requests

from .cache import cached
from .registry import BaseDataSource, Category, VendorMeta, register
from .summarize import (
    summarize_news,
    summarize_quotes,
    summarize_fundamentals,
    summarize_social,
    summarize_balance_sheet,
    summarize_income_statement,
    summarize_cashflow,
    summarize_insider,
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

    @cached(ttl=600)                  # news rotates fast; 10 min sweet spot
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

    @cached(ttl=300)                  # 5 min — daily candles aren't that volatile
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

    @cached(ttl=3600)                 # ratios change slowly — 1 hour
    def fetch_fundamentals_summary(self, ticker: str) -> Optional[str]:
        data = self._get("/stock/metric", symbol=ticker, metric="all")
        if not data:
            return None
        metrics = (data.get("metric") or {})
        return summarize_fundamentals(metrics, ticker)

    # ---- 3-statement detail (Phase A.1) -------------------------------

    def _financials_reported(self, ticker: str, freq: str = "quarterly"):
        """Cached helper: pull the latest filing once, reuse across 3 methods."""
        if not hasattr(self, "_fin_cache"):
            self._fin_cache: Dict[tuple, Dict] = {}
        key = (ticker.upper(), freq)
        if key not in self._fin_cache:
            data = self._get("/stock/financials-reported", symbol=ticker, freq=freq)
            # Finnhub returns { data: [{report: {bs, ic, cf}, year, quarter, endDate, ...}, ...] }
            reports = (data or {}).get("data") or []
            self._fin_cache[key] = reports[0] if reports else {}
        return self._fin_cache[key]

    def _normalize_concepts(self, items: list[dict]) -> Dict[str, float]:
        """Finnhub `bs/ic/cf` items are `[{concept, label, unit, value}, ...]`.
        Build a flat dict keyed by both normalized labels and concept ids.
        """
        out: Dict[str, float] = {}
        for it in items or []:
            try:
                v = float(it.get("value"))
            except (TypeError, ValueError):
                continue
            label = (it.get("label") or "").lower().replace(" ", "").replace(",", "").replace("'", "")
            concept = (it.get("concept") or "").lower()
            if label: out[label] = v
            if concept: out[concept] = v
        return out

    @cached(ttl=3600)
    def fetch_balance_sheet_summary(self, ticker: str) -> Optional[str]:
        report = self._financials_reported(ticker)
        if not report:
            return None
        flat = self._normalize_concepts(((report.get("report") or {}).get("bs") or []))
        # canonical-name aliases
        canonical = {
            "totalAssets":          flat.get("assets") or flat.get("totalassets") or flat.get("us-gaap:assets"),
            "totalLiabilities":     flat.get("liabilities") or flat.get("totalliabilities") or flat.get("us-gaap:liabilities"),
            "totalEquity":          flat.get("stockholdersequity") or flat.get("totalstockholdersequity") or flat.get("us-gaap:stockholdersequity"),
            "cashAndCashEquivalents": flat.get("cashandcashequivalentsatcarryingvalue") or flat.get("cashandcashequivalents"),
            "longTermDebt":         flat.get("longtermdebt") or flat.get("longtermdebtnoncurrent"),
            "shortTermDebt":        flat.get("shorttermborrowings") or flat.get("longtermdebtcurrent"),
            "period":               (report.get("endDate") or "")[:10],
        }
        return summarize_balance_sheet(canonical, ticker)

    @cached(ttl=3600)
    def fetch_income_statement_summary(self, ticker: str) -> Optional[str]:
        report = self._financials_reported(ticker)
        if not report:
            return None
        flat = self._normalize_concepts(((report.get("report") or {}).get("ic") or []))
        canonical = {
            "revenue":          flat.get("revenues") or flat.get("revenuefromcontractwithcustomerexcludingassessedtax") or flat.get("salesrevenuenet"),
            "costOfRevenue":    flat.get("costofrevenue") or flat.get("costofgoodssold") or flat.get("costofgoodsandservicessold"),
            "grossProfit":      flat.get("grossprofit"),
            "operatingIncome":  flat.get("operatingincomeloss") or flat.get("ebit"),
            "netIncome":        flat.get("netincomeloss") or flat.get("netincome"),
            "eps":              flat.get("earningspersharebasic") or flat.get("earningspersharediluted"),
            "period":           (report.get("endDate") or "")[:10],
        }
        return summarize_income_statement(canonical, ticker)

    @cached(ttl=3600)
    def fetch_cashflow_summary(self, ticker: str) -> Optional[str]:
        report = self._financials_reported(ticker)
        if not report:
            return None
        flat = self._normalize_concepts(((report.get("report") or {}).get("cf") or []))
        cfo = flat.get("netcashprovidedbyusedinoperatingactivities") or flat.get("cashflowfromoperatingactivities")
        capex = flat.get("paymentstoacquirepropertyplantandequipment") or flat.get("capitalexpenditure")
        # capex on Finnhub is reported as a negative outflow
        if isinstance(capex, (int, float)) and capex > 0:
            capex = -capex
        canonical = {
            "operatingCashFlow":  cfo,
            "investingCashFlow":  flat.get("netcashprovidedbyusedininvestingactivities"),
            "financingCashFlow":  flat.get("netcashprovidedbyusedinfinancingactivities"),
            "capitalExpenditure": capex,
            "freeCashFlow":       (cfo + capex) if (isinstance(cfo, (int, float)) and isinstance(capex, (int, float))) else None,
            "period":             (report.get("endDate") or "")[:10],
        }
        return summarize_cashflow(canonical, ticker)

    # ---- insider transactions (Phase A.3) ------------------------------

    @cached(ttl=1800)                 # insider txs trickle in — 30 min
    def fetch_insider_summary(self, ticker: str, lookback_days: int = 90) -> Optional[str]:
        from datetime import date, timedelta
        end = date.today()
        start = end - timedelta(days=lookback_days)
        data = self._get(
            "/stock/insider-transactions",
            symbol=ticker,
            **{"from": start.isoformat(), "to": end.isoformat()},
        )
        if not data:
            return None
        txs = data.get("data") or []
        if not txs:
            return None
        return summarize_insider(txs, ticker, lookback_days=lookback_days)

    # ---- social --------------------------------------------------------

    @cached(ttl=600)
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
