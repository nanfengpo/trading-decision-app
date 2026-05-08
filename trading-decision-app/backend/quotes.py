"""
Batch quote fetcher used by the 自选 page.

Routes a list of tickers to the cheapest live source per market:

  - crypto (BTC-USD, ETH-USD, ...USDT)  → Binance public API
  - US stocks (NVDA, AAPL, ...)         → Finnhub Pro / Polygon / yfinance
  - HK / A 股 / 期货                    → yfinance (best-effort), AkShare TODO
  - other / unknown                     → return placeholder

Each quote returns a uniform schema so the frontend renders one table:

  {
    ticker, market, name, price, change, change_pct,
    open, high, low, prev_close, volume, turnover,
    market_cap, pe_ratio, source, ts
  }

Anything we can't fill is null — the UI shows '—'.
"""

from __future__ import annotations

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


# ---------- market detection -------------------------------------------------

_CRYPTO_RE   = re.compile(r"^(BTC|ETH|SOL|XRP|DOGE|ADA|MATIC|LINK|AVAX|DOT)[-/]?(USD|USDT)$", re.I)
_HK_RE       = re.compile(r"^\d{4,5}\.HK$|^\d{4,5}$", re.I)
_CN_RE       = re.compile(r"^(sh|sz)?\d{6}(\.SS|\.SZ)?$", re.I)
_FUTURES_RE  = re.compile(r"^[A-Z]{1,3}=F$|^GC|^CL|^NG|^SI|^HG|^ZC", re.I)
_FOREX_RE    = re.compile(r"^[A-Z]{6}=X$|^USD|^EUR|^GBP|^JPY|^CNY", re.I)
_US_STOCK_RE = re.compile(r"^[A-Z]{1,5}$")


def detect_market(ticker: str) -> str:
    t = (ticker or "").strip().upper()
    if not t:
        return "other"
    if _CRYPTO_RE.match(t) or t.endswith("USDT") or t.endswith("-USD"):
        return "crypto"
    if _HK_RE.match(t):
        return "hk"
    if _CN_RE.match(t):
        return "cn"
    if _FUTURES_RE.match(t):
        return "commodity"
    if _FOREX_RE.match(t):
        return "forex"
    if _US_STOCK_RE.match(t):
        return "us"
    return "other"


# ---------- per-source fetchers ---------------------------------------------

def _empty_quote(ticker: str, market: str) -> Dict[str, Any]:
    return {
        "ticker": ticker, "market": market, "name": None,
        "price": None, "change": None, "change_pct": None,
        "open": None, "high": None, "low": None, "prev_close": None,
        "volume": None, "turnover": None, "market_cap": None, "pe_ratio": None,
        "source": None, "ts": int(time.time()),
    }


def _fetch_crypto(ticker: str) -> Dict[str, Any]:
    """Binance 24h ticker — symbol like BTCUSDT."""
    out = _empty_quote(ticker, "crypto")
    sym = ticker.upper().replace("-", "").replace("/", "")
    if sym.endswith("USD"):
        sym = sym[:-3] + "USDT"
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/24hr",
            params={"symbol": sym}, timeout=4,
        )
        r.raise_for_status()
        d = r.json()
        out.update({
            "name":        ticker,
            "price":       float(d.get("lastPrice", 0)) or None,
            "change":      float(d.get("priceChange", 0)) or None,
            "change_pct":  float(d.get("priceChangePercent", 0)) or None,
            "open":        float(d.get("openPrice", 0)) or None,
            "high":        float(d.get("highPrice", 0)) or None,
            "low":         float(d.get("lowPrice", 0)) or None,
            "prev_close":  float(d.get("prevClosePrice", 0)) or None,
            "volume":      float(d.get("volume", 0)) or None,
            "turnover":    float(d.get("quoteVolume", 0)) or None,
            "source":      "binance",
        })
    except Exception as e:
        logger.debug("binance %s: %s", sym, e)
    return out


def _fetch_us_finnhub(ticker: str) -> Optional[Dict[str, Any]]:
    """Finnhub Pro free quote endpoint — needs FINNHUB_API_KEY."""
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        return None
    out = _empty_quote(ticker, "us")
    try:
        # Quote
        r = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": ticker, "token": key}, timeout=4,
        )
        r.raise_for_status()
        d = r.json()
        if d.get("c"):  # current price
            out.update({
                "price":      d.get("c"),
                "change":     d.get("d"),
                "change_pct": d.get("dp"),
                "open":       d.get("o"),
                "high":       d.get("h"),
                "low":        d.get("l"),
                "prev_close": d.get("pc"),
                "source":     "finnhub",
            })
            # Best-effort metrics (separate paid endpoint; ignore errors)
            try:
                m = requests.get(
                    "https://finnhub.io/api/v1/stock/metric",
                    params={"symbol": ticker, "metric": "all", "token": key},
                    timeout=4,
                )
                if m.ok:
                    metric = (m.json() or {}).get("metric") or {}
                    out["market_cap"] = metric.get("marketCapitalization")  # in M USD
                    out["pe_ratio"]   = metric.get("peTTM") or metric.get("peExclExtraTTM")
            except Exception:
                pass
            try:
                p = requests.get(
                    "https://finnhub.io/api/v1/stock/profile2",
                    params={"symbol": ticker, "token": key}, timeout=4,
                )
                if p.ok:
                    out["name"] = (p.json() or {}).get("name") or ticker
            except Exception:
                pass
            return out
    except Exception as e:
        logger.debug("finnhub %s: %s", ticker, e)
    return None


def _fetch_yfinance(ticker: str, market: str) -> Optional[Dict[str, Any]]:
    """Last-resort fallback — yfinance is bundled, no key needed."""
    try:
        import yfinance as yf
    except ImportError:
        return None
    out = _empty_quote(ticker, market)
    try:
        # yfinance HK uses 0700.HK; pass through as-is
        t = yf.Ticker(ticker)
        info = t.fast_info or {}
        # fast_info attrs: last_price, previous_close, day_high, day_low, etc.
        last  = getattr(info, "last_price", None)
        prev  = getattr(info, "previous_close", None) or getattr(info, "regular_market_previous_close", None)
        op    = getattr(info, "open", None)
        hi    = getattr(info, "day_high", None)
        lo    = getattr(info, "day_low", None)
        vol   = getattr(info, "last_volume", None)
        if last is None:
            return None
        change = (last - prev) if (prev is not None) else None
        change_pct = (change / prev * 100) if (change is not None and prev) else None
        out.update({
            "name":       ticker,
            "price":      last,
            "change":     change,
            "change_pct": change_pct,
            "open":       op,
            "high":       hi,
            "low":        lo,
            "prev_close": prev,
            "volume":     vol,
            "turnover":   (last * vol) if (last and vol) else None,
            "source":     "yfinance",
        })
        return out
    except Exception as e:
        logger.debug("yfinance %s: %s", ticker, e)
        return None


def _fetch_crypto_coingecko(ticker: str) -> Optional[Dict[str, Any]]:
    """Free no-auth fallback when Binance is geo-blocked (e.g. Fly sjc).
    Maps BTC-USD / ETHUSDT → coingecko id via a tiny built-in map."""
    cg_map = {
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple",
        "DOGE": "dogecoin", "ADA": "cardano", "MATIC": "polygon-pos",
        "LINK": "chainlink", "AVAX": "avalanche-2", "DOT": "polkadot",
    }
    sym = ticker.upper().replace("-", "").replace("/", "").replace("USDT", "USD")
    base = sym.replace("USD", "")
    cg_id = cg_map.get(base)
    if not cg_id:
        return None
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={"vs_currency": "usd", "ids": cg_id, "price_change_percentage": "24h"},
            timeout=5,
        )
        r.raise_for_status()
        arr = r.json() or []
        if not arr:
            return None
        d = arr[0]
        out = _empty_quote(ticker, "crypto")
        out.update({
            "name":        d.get("name") or ticker,
            "price":       d.get("current_price"),
            "change":      d.get("price_change_24h"),
            "change_pct":  d.get("price_change_percentage_24h") or d.get("price_change_percentage_24h_in_currency"),
            "high":        d.get("high_24h"),
            "low":         d.get("low_24h"),
            "volume":      d.get("total_volume"),
            "turnover":    d.get("total_volume"),  # USD-denominated already
            "market_cap":  d.get("market_cap"),
            "source":      "coingecko",
        })
        return out
    except Exception as e:
        logger.warning("coingecko %s: %s", cg_id, e)
        return None


def _fetch_one(ticker: str) -> Dict[str, Any]:
    market = detect_market(ticker)
    if market == "crypto":
        # Binance first (richest data), then CoinGecko (geo-resilient),
        # then yfinance (always available with the BTC-USD form).
        q = _fetch_crypto(ticker)
        if q.get("price") is not None:
            return q
        cg = _fetch_crypto_coingecko(ticker)
        if cg:
            return cg
        # yfinance accepts "BTC-USD" natively for crypto
        yf_t = ticker if "-" in ticker.upper() else ticker.upper().replace("USDT", "-USD")
        q = _fetch_yfinance(yf_t, "crypto")
        if q:
            q["ticker"] = ticker  # preserve user's input form
            return q
        return _empty_quote(ticker, "crypto")

    if market == "us":
        q = _fetch_us_finnhub(ticker)
        if q:
            return q

    # All other markets and US fallback → yfinance
    q = _fetch_yfinance(ticker, market)
    if q:
        return q

    return _empty_quote(ticker, market)


# ---------- public API -------------------------------------------------------

def fetch_quotes(tickers: List[str]) -> List[Dict[str, Any]]:
    """Fetch quotes in parallel (one HTTP per ticker; capped concurrency)."""
    if not tickers:
        return []
    seen = set()
    deduped = []
    for t in tickers:
        t = (t or "").strip()
        if t and t.upper() not in seen:
            seen.add(t.upper())
            deduped.append(t)

    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="quotes") as pool:
        return list(pool.map(_fetch_one, deduped))
