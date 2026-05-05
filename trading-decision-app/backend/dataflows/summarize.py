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

# ----- financial statements (3-statement detail) ------------------------

def _fmt_money(v) -> str:
    """Format a possibly-large number into B / M / K with sign."""
    if v is None or not isinstance(v, (int, float)):
        return "—"
    sign = "-" if v < 0 else ""
    abs_v = abs(v)
    if abs_v >= 1e9:  return f"{sign}${abs_v / 1e9:.2f}B"
    if abs_v >= 1e6:  return f"{sign}${abs_v / 1e6:.2f}M"
    if abs_v >= 1e3:  return f"{sign}${abs_v / 1e3:.2f}K"
    return f"{sign}${abs_v:.0f}"


def summarize_balance_sheet(report: Mapping, ticker: str) -> str:
    """``report`` is a dict of canonical labels → numeric values.
    Caller (vendor) is responsible for normalising vendor-specific names.
    """
    if not report:
        return f"_(no balance sheet for {ticker})_"
    pick = lambda *keys: next((report[k] for k in keys if report.get(k) is not None), None)
    total_assets       = pick("totalAssets", "Assets", "ta")
    total_liabilities  = pick("totalLiabilities", "Liabilities", "tl")
    total_equity       = pick("totalEquity", "totalStockholdersEquity", "Equity")
    cash               = pick("cashAndCashEquivalents", "cash", "Cash")
    long_term_debt     = pick("longTermDebt", "longTermBorrowings")
    short_term_debt    = pick("shortTermDebt", "shortTermBorrowings")
    period             = report.get("period") or report.get("date") or report.get("endDate") or "latest"
    lines = [
        f"## Balance Sheet — {ticker} ({period})",
        f"- 总资产: **{_fmt_money(total_assets)}**  ·  总负债: **{_fmt_money(total_liabilities)}**  ·  净资产: **{_fmt_money(total_equity)}**",
        f"- 现金及等价物: {_fmt_money(cash)}",
        f"- 长期债务: {_fmt_money(long_term_debt)}  ·  短期债务: {_fmt_money(short_term_debt)}",
    ]
    if isinstance(total_liabilities, (int, float)) and isinstance(total_equity, (int, float)) and total_equity:
        lines.append(f"- D/E (近似): {total_liabilities / total_equity:.2f}")
    return "\n".join(lines)


def summarize_income_statement(report: Mapping, ticker: str) -> str:
    if not report:
        return f"_(no income statement for {ticker})_"
    pick = lambda *keys: next((report[k] for k in keys if report.get(k) is not None), None)
    revenue   = pick("revenue", "totalRevenue", "Revenue", "Sales")
    cogs      = pick("costOfRevenue", "cogs", "COGS")
    gross     = pick("grossProfit", "GrossProfit") or (
        revenue - cogs if isinstance(revenue, (int, float)) and isinstance(cogs, (int, float)) else None)
    op_income = pick("operatingIncome", "OperatingIncome", "ebit")
    net_inc   = pick("netIncome", "NetIncome", "Profit")
    eps       = pick("eps", "epsBasic", "epsDiluted", "EPS")
    period    = report.get("period") or report.get("date") or report.get("endDate") or "latest"

    gm = (gross / revenue * 100) if isinstance(gross, (int, float)) and isinstance(revenue, (int, float)) and revenue else None
    om = (op_income / revenue * 100) if isinstance(op_income, (int, float)) and isinstance(revenue, (int, float)) and revenue else None
    nm = (net_inc / revenue * 100) if isinstance(net_inc, (int, float)) and isinstance(revenue, (int, float)) and revenue else None

    lines = [
        f"## Income Statement — {ticker} ({period})",
        f"- 营收: **{_fmt_money(revenue)}**  ·  毛利: {_fmt_money(gross)}  ·  营业利润: {_fmt_money(op_income)}  ·  净利润: **{_fmt_money(net_inc)}**",
    ]
    margin_parts = []
    if gm is not None: margin_parts.append(f"毛利率 {gm:.1f}%")
    if om is not None: margin_parts.append(f"营业利润率 {om:.1f}%")
    if nm is not None: margin_parts.append(f"净利率 {nm:.1f}%")
    if margin_parts: lines.append("- " + "  ·  ".join(margin_parts))
    if eps is not None and isinstance(eps, (int, float)):
        lines.append(f"- EPS: ${eps:.2f}")
    return "\n".join(lines)


def summarize_cashflow(report: Mapping, ticker: str) -> str:
    if not report:
        return f"_(no cashflow for {ticker})_"
    pick = lambda *keys: next((report[k] for k in keys if report.get(k) is not None), None)
    cfo  = pick("operatingCashFlow", "cashFromOperatingActivities", "CFO")
    cfi  = pick("investingCashFlow", "cashFromInvestingActivities", "CFI")
    cff  = pick("financingCashFlow", "cashFromFinancingActivities", "CFF")
    capex= pick("capitalExpenditure", "capex", "CapEx")
    fcf  = pick("freeCashFlow", "FCF") or (
        cfo + capex if isinstance(cfo, (int, float)) and isinstance(capex, (int, float)) else None)
    period = report.get("period") or report.get("date") or report.get("endDate") or "latest"

    lines = [
        f"## Cash Flow — {ticker} ({period})",
        f"- 经营活动: **{_fmt_money(cfo)}**  ·  投资: {_fmt_money(cfi)}  ·  筹资: {_fmt_money(cff)}",
        f"- 资本开支: {_fmt_money(capex)}  ·  自由现金流: **{_fmt_money(fcf)}**",
    ]
    return "\n".join(lines)


# ----- detailed indicators (Phase A.2) ------------------------------------

def summarize_indicators_detailed(values: Mapping, ticker: str) -> str:
    """``values`` is a flat dict of indicator name → latest value.

    Recognised keys (any subset works):
      rsi, macd, macd_signal, macd_hist,
      bb_upper, bb_middle, bb_lower, bb_pct,
      atr, adx, plus_di, minus_di,
      sma_20, sma_50, sma_200, ema_20, vwma_20
    """
    if not values:
        return f"_(no indicator data for {ticker})_"
    fmt = lambda v: f"{v:.2f}" if isinstance(v, (int, float)) else "—"
    lines = [f"## Technical Indicators — {ticker}", ""]

    # RSI
    rsi = values.get("rsi")
    if rsi is not None:
        zone = "超买 ⚠️" if rsi > 70 else ("超卖 ⚠️" if rsi < 30 else "中性")
        lines.append(f"- **RSI(14)**: {fmt(rsi)}  ({zone})")
    # MACD
    macd, sig, hist = values.get("macd"), values.get("macd_signal"), values.get("macd_hist")
    if macd is not None:
        cross = ""
        if isinstance(hist, (int, float)):
            cross = "（金叉/向上）" if hist > 0 else "（死叉/向下）"
        lines.append(f"- **MACD**: {fmt(macd)}  ·  signal {fmt(sig)}  ·  hist {fmt(hist)} {cross}")
    # Bollinger
    bbu, bbm, bbl, bbp = values.get("bb_upper"), values.get("bb_middle"), values.get("bb_lower"), values.get("bb_pct")
    if bbu is not None or bbm is not None:
        line = f"- **Bollinger(20,2)**: lower {fmt(bbl)}  ·  mid {fmt(bbm)}  ·  upper {fmt(bbu)}"
        if isinstance(bbp, (int, float)):
            zone = "贴近上轨 ⚠️" if bbp > 0.85 else ("贴近下轨 ⚠️" if bbp < 0.15 else "")
            line += f"  ·  %B {bbp:.2f} {zone}"
        lines.append(line)
    # ATR / ADX
    atr = values.get("atr")
    if atr is not None:
        lines.append(f"- **ATR(14)**: {fmt(atr)}  (波动绝对值)")
    adx = values.get("adx")
    if adx is not None:
        strength = "强趋势" if adx > 25 else ("弱/无趋势" if adx < 20 else "盘整")
        lines.append(f"- **ADX(14)**: {fmt(adx)}  +DI {fmt(values.get('plus_di'))}  −DI {fmt(values.get('minus_di'))}  ({strength})")
    # MAs
    ma_parts = []
    for k, lbl in [("sma_20","SMA20"), ("sma_50","SMA50"), ("sma_200","SMA200"), ("ema_20","EMA20"), ("vwma_20","VWMA20")]:
        if values.get(k) is not None:
            ma_parts.append(f"{lbl} {fmt(values[k])}")
    if ma_parts:
        lines.append(f"- 均线: {'  ·  '.join(ma_parts)}")

    return "\n".join(lines)


# ----- insider transactions (Phase A.3) -----------------------------------

def summarize_insider(transactions: Iterable[Mapping], ticker: str, lookback_days: int = 90) -> str:
    """transactions = list of dicts; recognised keys:
       name / position / transactionDate / transactionType /
       share / change (signed) / transactionPrice
    """
    txs = list(transactions or [])
    if not txs:
        return f"_(no insider transactions for {ticker} in last {lookback_days}d)_"

    buys = sells = 0
    buy_value = sell_value = 0.0
    sample = []
    for t in txs[:100]:
        chg = t.get("change") or t.get("share") or 0
        try:
            chg = float(chg)
        except (TypeError, ValueError):
            chg = 0
        price = t.get("transactionPrice") or t.get("price") or 0
        try:
            price = float(price)
        except (TypeError, ValueError):
            price = 0
        if chg > 0:
            buys += 1
            buy_value += chg * price
        elif chg < 0:
            sells += 1
            sell_value += abs(chg) * price
        if len(sample) < 5:
            who = t.get("name") or t.get("filerName") or "—"
            pos = t.get("position") or t.get("officerTitle") or ""
            date = t.get("transactionDate") or t.get("date") or ""
            sample.append(f"{date}  {who} ({pos}): {'+' if chg>0 else ''}{int(chg)} 股 @ {_fmt_money(price)}")

    net = buy_value - sell_value
    bias = "🟢 净买入" if net > 0 else ("🔴 净卖出" if net < 0 else "⚪ 中性")
    lines = [
        f"## Insider Transactions — {ticker} (last {lookback_days}d)",
        f"- 买入笔数: **{buys}**  ·  卖出笔数: **{sells}**  ·  方向: **{bias}**  (净额 {_fmt_money(net)})",
    ]
    if sample:
        lines.append("- 近期典型:")
        for s in sample:
            lines.append(f"  · {s}")
    return "\n".join(lines)


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
