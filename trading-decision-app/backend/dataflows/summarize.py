"""
Token-saving summarisers.

Pattern: every vendor module hits the raw JSON API, then funnels through
one of these helpers BEFORE the result reaches the agent. Two benefits:

1. **Lower LLM cost** — agents see ~200 tokens of curated data instead of
   2000+ tokens of nested JSON.
2. **Higher decision quality** — less noise = better attention. Counter-
   intuitive but consistently observed.

The summarisers are deliberately deterministic (no LLM calls themselves).
For news ranking they use a simple heuristic; if you want LLM-based
summarisation, swap `summarize_news` to call your `quick_think_llm` —
but try the heuristic first; it's good enough for most uses.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Mapping, Optional, Sequence


# ----- news ----------------------------------------------------------------

_HIGH_VALUE_KEYWORDS = {
    # earnings / guidance
    "earnings": 3, "revenue": 2, "beat": 2, "miss": 2, "guidance": 3,
    "outlook": 2, "forecast": 2, "raised": 2, "cut": 2, "downgraded": 3, "upgraded": 3,
    # M&A / corporate actions
    "acquire": 3, "merger": 3, "spinoff": 2, "buyback": 2, "dividend": 2,
    # regulatory / litigation
    "sec": 2, "lawsuit": 2, "investigation": 3, "fine": 2, "settlement": 2,
    "approval": 2, "fda": 3, "ban": 3, "tariff": 3, "sanction": 3,
    # product / partnership
    "launch": 2, "partnership": 2, "contract": 2, "deal": 2,
    # exec changes
    "ceo": 2, "resign": 2, "appoint": 1,
    # macro
    "fed": 2, "inflation": 2, "rate": 1, "recession": 3, "gdp": 1,
}

_NEGATIVE_WORDS = {"miss", "cut", "downgrade", "lawsuit", "investigation", "fine", "ban", "recall", "fraud", "warning", "decline", "loss", "fall", "drop", "plunge", "tumble", "weak"}
_POSITIVE_WORDS = {"beat", "raise", "upgrade", "approval", "partnership", "buyback", "growth", "strong", "surge", "soar", "rally", "record", "boost", "expand", "launch"}


def _score_news(item: Mapping) -> float:
    """Higher = more decision-relevant."""
    title = (item.get("headline") or item.get("title") or "").lower()
    summary = (item.get("summary") or item.get("description") or "").lower()
    text = title + " " + summary

    score = 0.0
    for kw, w in _HIGH_VALUE_KEYWORDS.items():
        if kw in text:
            score += w
    # newer = better (linear decay over a week)
    ts = item.get("datetime") or item.get("published_at") or item.get("timestamp")
    if isinstance(ts, (int, float)):
        # Finnhub returns unix seconds
        published = datetime.fromtimestamp(ts, tz=timezone.utc)
    elif isinstance(ts, str):
        try:
            published = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            published = datetime.now(timezone.utc) - timedelta(days=7)
    else:
        published = datetime.now(timezone.utc) - timedelta(days=7)
    days_old = (datetime.now(timezone.utc) - published).total_seconds() / 86400
    score *= max(0.1, 1 - days_old / 7)
    return score


def _sentiment_from_text(text: str) -> int:
    """Returns -1, 0, +1."""
    t = text.lower()
    pos = sum(1 for w in _POSITIVE_WORDS if w in t)
    neg = sum(1 for w in _NEGATIVE_WORDS if w in t)
    if pos > neg + 1: return 1
    if neg > pos + 1: return -1
    return 0


def summarize_news(items: Sequence[Mapping], top_k: int = 5,
                   ticker: Optional[str] = None) -> str:
    """Compress a list of news dicts into a markdown bullet list + tone."""
    if not items:
        return "_(no recent news)_"

    ranked = sorted(items, key=_score_news, reverse=True)[:top_k]

    sentiments = []
    lines = [f"## News summary{f' — {ticker}' if ticker else ''}", ""]
    for it in ranked:
        title = (it.get("headline") or it.get("title") or "").strip()
        if not title:
            continue
        url = it.get("url") or it.get("link") or ""
        src = it.get("source") or it.get("publisher") or ""
        ts = it.get("datetime") or it.get("published_at") or it.get("timestamp")
        if isinstance(ts, (int, float)):
            ts = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        elif isinstance(ts, str):
            ts = ts[:10]
        else:
            ts = ""
        s = _sentiment_from_text(title + " " + (it.get("summary") or ""))
        sentiments.append(s)
        tone = {1: "🟢", -1: "🔴", 0: "⚪️"}[s]
        meta = " · ".join(x for x in [src, ts] if x)
        lines.append(f"- {tone} **{title}**" + (f"  _{meta}_" if meta else ""))
    if sentiments:
        avg = sum(sentiments) / len(sentiments)
        bias = "看多" if avg > 0.2 else ("看空" if avg < -0.2 else "中性")
        lines.append("")
        lines.append(f"_整体倾向: **{bias}** (n={len(sentiments)}, avg={avg:+.2f})_")
    return "\n".join(lines)


# ----- quotes / indicators -------------------------------------------------

def summarize_quotes(quotes: Mapping, ticker: str) -> str:
    """Compress an OHLCV history into trend / momentum / vol bullets."""
    closes = quotes.get("closes") or quotes.get("c") or []
    if len(closes) < 5:
        return f"_(insufficient price data for {ticker})_"

    last = closes[-1]
    sma20 = sum(closes[-20:]) / min(20, len(closes))
    sma50 = sum(closes[-50:]) / min(50, len(closes))
    chg_5d = (last / closes[-5] - 1) * 100 if len(closes) >= 5 else 0
    chg_20d = (last / closes[-20] - 1) * 100 if len(closes) >= 20 else 0
    chg_60d = (last / closes[-60] - 1) * 100 if len(closes) >= 60 else 0

    # cheap volatility: stdev of daily returns
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))][-30:]
    if rets:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / len(rets)
        vol_30d = math.sqrt(var) * math.sqrt(252) * 100
    else:
        vol_30d = 0

    trend = "上升" if last > sma20 > sma50 else ("下降" if last < sma20 < sma50 else "震荡")

    lines = [
        f"## Price snapshot — {ticker}",
        f"- 现价: **{last:.2f}**",
        f"- 5日 / 20日 / 60日: {chg_5d:+.2f}% / {chg_20d:+.2f}% / {chg_60d:+.2f}%",
        f"- SMA20: {sma20:.2f} · SMA50: {sma50:.2f}",
        f"- 趋势: **{trend}**  (close vs SMA20 vs SMA50)",
        f"- 30 日年化波动率: {vol_30d:.1f}%",
    ]
    return "\n".join(lines)


# ----- fundamentals --------------------------------------------------------

def summarize_fundamentals(metrics: Mapping, ticker: str) -> str:
    """Pull only the headline ratios; ignore everything else."""
    if not metrics:
        return f"_(no fundamentals for {ticker})_"

    pick = lambda *keys: next((metrics[k] for k in keys if metrics.get(k) is not None), None)
    pe   = pick("peTTM", "pe", "trailing_pe", "P/E")
    pb   = pick("pbTTM", "pb", "P/B")
    ps   = pick("psTTM", "ps", "P/S")
    roe  = pick("roeTTM", "roe", "ROE")
    de   = pick("totalDebt/totalEquityQuarterly", "debtEquity", "D/E")
    fcf  = pick("freeCashFlowTTM", "fcf")
    rev  = pick("revenueGrowthTTMYoy", "revenueGrowth")

    fmt = lambda v, suf="": f"{v:.2f}{suf}" if isinstance(v, (int, float)) else "—"
    pct = lambda v: f"{v*100:+.1f}%" if isinstance(v, (int, float)) and abs(v) <= 5 else fmt(v)

    lines = [
        f"## Fundamentals — {ticker}",
        f"- 估值: P/E {fmt(pe)}  ·  P/B {fmt(pb)}  ·  P/S {fmt(ps)}",
        f"- 盈利: ROE {pct(roe)}  ·  自由现金流 {fmt(fcf)}",
        f"- 财务结构: D/E {fmt(de)}",
        f"- 营收增速 (TTM YoY): {pct(rev)}",
    ]
    return "\n".join(lines)


# ----- social --------------------------------------------------------------

def summarize_social(posts: Iterable[Mapping], ticker: str, lookback_days: int = 7) -> str:
    """Reduce a stream of social posts to topic clusters + tone."""
    posts = list(posts or [])
    if not posts:
        return f"_(no social mentions for {ticker} in last {lookback_days}d)_"

    # crude cluster: most-frequent 2-grams in titles
    bigrams: dict[str, int] = {}
    sentiments = []
    for p in posts:
        text = (p.get("title") or p.get("text") or "").lower()
        if not text: continue
        sentiments.append(_sentiment_from_text(text))
        words = re.findall(r"[a-z][a-z0-9]{2,}", text)
        for i in range(len(words) - 1):
            bg = words[i] + " " + words[i + 1]
            bigrams[bg] = bigrams.get(bg, 0) + 1

    top = sorted(bigrams.items(), key=lambda x: -x[1])[:5]
    avg = (sum(sentiments) / len(sentiments)) if sentiments else 0
    bias = "正面" if avg > 0.2 else ("负面" if avg < -0.2 else "中性")
    lines = [
        f"## Social — {ticker} (last {lookback_days}d, n={len(posts)})",
        f"- 整体情绪: **{bias}** (avg={avg:+.2f})",
        "- 高频话题: " + ", ".join(f"`{bg}`×{n}" for bg, n in top) if top else "- 无明显高频话题",
    ]
    return "\n".join(lines)
