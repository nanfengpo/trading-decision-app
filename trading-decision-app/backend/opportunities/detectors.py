"""
Sample detectors. Each is small + focused — extend by writing more.

Bundled detectors:
  - BTCWickDetector       BTC 1m candles, flag big upper/lower wicks (插针)
  - IVSpikeDetector       Equity options IV moved >20% over 1d (skeleton)
  - SocialTrendDetector   reddit /r/wallstreetbets ticker mentions blowup
  - EarningsVolDetector   stocks with earnings <= 7d AND IV rank > 70 (skeleton)
  - DemoDetector          emits one synthetic opp every cycle (for the UI)

Set OPPORTUNITIES_SCANNER=off to disable the loop entirely.
The DemoDetector is always emitted so the UI has *something* to show
when no real data sources are configured.
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .scanner import BaseDetector, Opportunity

logger = logging.getLogger(__name__)


# Strategy IDs from static/strategies.js used as suggestions
STRAT = {
    "btc_wick_buy":     ["mean_reversion", "grid", "dca"],
    "btc_wick_sell":    ["fixed_stop", "scaled_tp", "covered_call"],
    "iv_spike":         ["iron_condor", "iv_crush", "short_strangle", "credit_spread"],
    "social_breakout":  ["momentum", "breakout", "trend_following"],
    "earnings_high_iv": ["iv_crush", "iron_condor", "short_strangle"],
    "earnings_low_iv":  ["long_straddle", "long_strangle", "earnings_play"],
}


def _hid(*parts: str) -> str:
    """Stable id so the same event isn't pushed twice within an hour."""
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


# ============================================================ Demo detector

class DemoDetector(BaseDetector):
    """Emits a synthetic opportunity once per scanner cycle so the UI is alive
    even when no real data sources are configured. Disable in production by
    setting OPPS_DEMO=off."""

    name = "demo"
    interval_sec = 60

    _SAMPLES = [
        {"type": "btc_wick", "ticker": "BTC-USD", "severity": "high",
         "headline": "BTC 1m 下插针 −2.1%（24h 内第 2 次）",
         "body": "现货从 $68,420 瞬时下探 $66,980 后 30 秒内拉回 $68,200。币安 + Bybit 同步。",
         "strats": STRAT["btc_wick_buy"]},
        {"type": "iv_spike", "ticker": "TSLA", "severity": "watch",
         "headline": "TSLA 30D ATM IV 一日内 +24%（35% → 43.5%）",
         "body": "无明显基本面消息。Gamma 暴露集中在 $260-$280，期权周成交量翻倍。",
         "strats": STRAT["iv_spike"]},
        {"type": "social_trend", "ticker": "PLTR", "severity": "watch",
         "headline": "PLTR 在 r/wallstreetbets 提及量过去 24h +480%",
         "body": "情绪整体偏多。同一时段 Twitter 提及+220%。",
         "strats": STRAT["social_breakout"]},
        {"type": "earnings_iv", "ticker": "NVDA", "severity": "high",
         "headline": "NVDA 财报前夕：IV Rank 91，预期波动 ±9.6%（历史均值 6.2%）",
         "body": "事件后 IV crush 大概率 -40%。",
         "strats": STRAT["earnings_high_iv"]},
        {"type": "macro", "ticker": None, "severity": "info",
         "headline": "美 10Y 国债收益率单日 +12bp，科技股开盘 -1.2%",
         "body": "联储官员讲话偏鹰，市场重新定价 9 月降息概率。",
         "strats": ["barbell", "vix_hedge", "protective_put"]},
    ]

    def run(self) -> List[Opportunity]:
        if os.environ.get("OPPS_DEMO", "on").lower() in ("off", "false", "0"):
            return []
        spec = random.choice(self._SAMPLES)
        # Hour-bucket id so the same fake event doesn't spam the feed.
        hour_bucket = int(time.time() // 3600)
        opp = Opportunity(
            id=_hid("demo", spec["type"], spec.get("ticker", ""), str(hour_bucket)),
            source=self.name,
            type=spec["type"],
            ticker=spec.get("ticker"),
            severity=spec["severity"],
            headline=spec["headline"],
            body=spec["body"],
            suggested_strategies=spec["strats"],
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        )
        return [opp]


# ============================================================ BTC wick detector

class BTCWickDetector(BaseDetector):
    """Pulls last 60 of BTC 1m candles from Binance public API and flags any
    candle with body/wick ratio < 0.3 AND wick > 1% of price."""

    name = "btc_wick"
    interval_sec = 60

    def run(self) -> List[Opportunity]:
        try:
            import requests
        except Exception:
            return []
        try:
            r = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": "BTCUSDT", "interval": "1m", "limit": 60},
                timeout=4,
            )
            r.raise_for_status()
            kl = r.json()
        except Exception as e:
            logger.debug("btc_wick: binance call failed: %s", e)
            return []

        out: List[Opportunity] = []
        for row in kl:
            open_, high, low, close = float(row[1]), float(row[2]), float(row[3]), float(row[4])
            body = abs(close - open_)
            full = high - low
            if full <= 0 or full / max(close, 1) < 0.01:  # <1% range — uninteresting
                continue
            ratio = body / full
            if ratio < 0.30:
                upper_wick = high - max(open_, close)
                lower_wick = min(open_, close) - low
                side = "upper" if upper_wick > lower_wick else "lower"
                wick_pct = (upper_wick if side == "upper" else lower_wick) / close * 100
                if wick_pct < 0.5:
                    continue
                ts_ms = row[0]
                bucket_min = ts_ms // 60000
                opp = Opportunity(
                    id=_hid("btc_wick", side, str(bucket_min)),
                    source=self.name,
                    type="btc_wick",
                    ticker="BTC-USD",
                    severity="high" if wick_pct >= 1.5 else "watch",
                    headline=f"BTC 1m {('上' if side=='upper' else '下')}插针 {wick_pct:.1f}% — body/range {ratio:.0%}",
                    body=f"OHLC: {open_:.0f} / {high:.0f} / {low:.0f} / {close:.0f}",
                    payload={"open": open_, "high": high, "low": low, "close": close, "side": side},
                    suggested_strategies=STRAT["btc_wick_buy"] if side == "lower" else STRAT["btc_wick_sell"],
                    expires_at=(datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
                )
                out.append(opp)
        return out


# ============================================================ IV spike detector (skeleton)

class IVSpikeDetector(BaseDetector):
    """Detects single-day IV spikes >= 20% on a watchlist.

    Wires up via Polygon options snapshot API when POLYGON_API_KEY is set;
    otherwise no-op. Watchlist comes from OPPS_IV_WATCHLIST env (comma-sep).
    """

    name = "iv_spike"
    interval_sec = 600       # 10 minutes — IV doesn't change every minute

    def run(self) -> List[Opportunity]:
        watchlist = [t.strip().upper() for t in os.environ.get("OPPS_IV_WATCHLIST", "").split(",") if t.strip()]
        if not watchlist or not os.environ.get("POLYGON_API_KEY"):
            return []
        # Implementation left for whoever sets POLYGON_API_KEY — see
        # dataflows/polygon_io.py for the request pattern. The snapshot
        # endpoint is /v3/snapshot/options/{underlying} and returns IV
        # in `implied_volatility`. Compare to a 7-day rolling baseline
        # (cache in self).
        return []


# ============================================================ Social trend (skeleton)

class SocialTrendDetector(BaseDetector):
    """Watches r/wallstreetbets (no auth needed) and flags tickers whose
    mention count spikes ≥ 5× their 7-day baseline."""

    name = "social_trend"
    interval_sec = 900       # 15 min

    _baseline: dict = {}

    def run(self) -> List[Opportunity]:
        try:
            import requests, re, collections
        except ImportError:
            return []
        try:
            r = requests.get(
                "https://www.reddit.com/r/wallstreetbets/hot.json?limit=50",
                headers={"User-Agent": "trading-decision-app/1.0"},
                timeout=4,
            )
            r.raise_for_status()
            posts = r.json()["data"]["children"]
        except Exception as e:
            logger.debug("social_trend: reddit call failed: %s", e)
            return []
        counts: dict[str, int] = collections.Counter()
        for p in posts:
            t = (p["data"].get("title", "") + " " + p["data"].get("selftext", "")).upper()
            for tkr in re.findall(r"\$?([A-Z]{2,5})\b", t):
                if tkr in {"DD", "WSB", "NYSE", "USA", "FED", "CEO", "CPI", "EPS", "ETF", "OTM", "ITM", "ATM"}:
                    continue
                counts[tkr] += 1
        out: List[Opportunity] = []
        now_bucket = int(time.time() // 900)  # 15 min
        for tkr, n in counts.most_common(10):
            base = self._baseline.get(tkr, 0)
            self._baseline[tkr] = (base * 0.85 + n * 0.15)  # EMA
            if base >= 3 and n >= base * 5:
                out.append(Opportunity(
                    id=_hid("social", tkr, str(now_bucket)),
                    source=self.name,
                    type="social_trend",
                    ticker=tkr,
                    severity="watch" if n < 15 else "high",
                    headline=f"{tkr} 在 WSB 提及量瞬时 +{n / max(base,1):.1f}× (n={n}, 基准={base:.1f})",
                    body="近 15 分钟 r/wallstreetbets 高频出现，可能形成 momentum 信号。",
                    suggested_strategies=STRAT["social_breakout"],
                    expires_at=(datetime.now(timezone.utc) + timedelta(hours=8)).isoformat(),
                ))
        return out


# ============================================================ Market pulse (always-on heartbeat)

class MarketPulseDetector(BaseDetector):
    """Pulls BTC + ETH spot from Binance every cycle and emits an info-level
    opportunity with the current price + 24h change. Deduped per hour so it
    refreshes the panel without spamming. Ensures the 24h panel is never
    empty even when no real wick/social signals fire."""

    name = "market_pulse"
    interval_sec = 1800  # 30 min — fresh enough, avoids API hammering

    _SYMBOLS = [("BTCUSDT", "BTC-USD", "比特币"), ("ETHUSDT", "ETH-USD", "以太坊")]

    def run(self) -> List[Opportunity]:
        try:
            import requests
        except Exception:
            return []
        out: List[Opportunity] = []
        bucket = int(time.time() // 3600)  # 1-hour dedup

        # Binance is geo-blocked from some Fly regions. Try CoinGecko first
        # — it's free, no key, and works globally; one HTTP for both coins.
        cg_data = None
        try:
            r = requests.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={
                    "vs_currency": "usd",
                    "ids": "bitcoin,ethereum",
                    "price_change_percentage": "24h",
                },
                timeout=5,
            )
            r.raise_for_status()
            cg_data = {x["symbol"].upper(): x for x in (r.json() or [])}
        except Exception as e:
            logger.debug("market_pulse: coingecko failed: %s", e)

        cg_lookup = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}

        for binance_sym, ticker, zh in self._SYMBOLS:
            price = pct = vol = 0.0
            source = None

            if cg_data and cg_lookup.get(binance_sym) in cg_data:
                d = cg_data[cg_lookup[binance_sym]]
                price = float(d.get("current_price") or 0)
                pct = float(d.get("price_change_percentage_24h") or 0)
                vol = float(d.get("total_volume") or 0)
                source = "CoinGecko"

            if price <= 0:
                # Binance fallback
                try:
                    r = requests.get(
                        "https://api.binance.com/api/v3/ticker/24hr",
                        params={"symbol": binance_sym},
                        timeout=4,
                    )
                    r.raise_for_status()
                    d = r.json()
                    price = float(d.get("lastPrice", 0))
                    pct = float(d.get("priceChangePercent", 0))
                    vol = float(d.get("quoteVolume", 0))
                    source = "Binance"
                except Exception as e:
                    logger.debug("market_pulse: %s failed: %s", binance_sym, e)
                    continue

            if price <= 0:
                continue

            arrow = "📈" if pct >= 0 else "📉"
            sev = "high" if abs(pct) >= 4 else ("watch" if abs(pct) >= 1.5 else "info")
            out.append(Opportunity(
                id=_hid("pulse", ticker, str(bucket)),
                source=self.name,
                type="market_pulse",
                ticker=ticker,
                severity=sev,
                headline=f"{arrow} {zh} 现价 ${price:,.0f} · 24h {pct:+.2f}%",
                body=f"24h 成交额 ${vol/1e9:.2f}B。{('波动放大' if abs(pct) >= 3 else '正常波动')}。来源：{source}。",
                payload={"price": price, "pct_24h": pct, "volume_24h": vol},
                suggested_strategies=(
                    STRAT["btc_wick_buy"] if pct <= -3 else
                    STRAT["btc_wick_sell"] if pct >= 4 else
                    ["dca", "grid", "mean_reversion"]
                ),
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            ))
        return out


# ============================================================ default set

def default_detectors() -> List[BaseDetector]:
    # Default: real-data detectors only. Set OPPS_DETECTORS=demo,... to opt
    # back into the scripted samples for screenshots / offline demos.
    enabled = (os.environ.get("OPPS_DETECTORS", "market_pulse,btc_wick,social_trend") or "").lower()
    enabled_set = {x.strip() for x in enabled.split(",") if x.strip()}
    out: List[BaseDetector] = []
    if "demo" in enabled_set:          out.append(DemoDetector())
    if "market_pulse" in enabled_set:  out.append(MarketPulseDetector())
    if "btc_wick" in enabled_set:      out.append(BTCWickDetector())
    if "iv_spike" in enabled_set:      out.append(IVSpikeDetector())
    if "social_trend" in enabled_set:  out.append(SocialTrendDetector())
    return out
