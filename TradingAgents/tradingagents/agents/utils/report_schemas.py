"""
Pydantic schemas for structured analyst reports.

CURRENT STATUS — foundation only
--------------------------------
These schemas are NOT yet adopted by the analyst factories. They are
defined here as a contract for a future PR that will:

1. Add ``cfg["structured_reports"]`` opt-in flag
2. In each analyst factory, when the flag is True, use
   ``llm.with_structured_output(Schema)`` to get a typed object back
3. Store both the structured dict (for SQL-style queries against the
   `decisions` table) AND a rendered markdown summary (for the cockpit)

See ``docs/FUTURE-WORK.md`` § #10 for the full plan.

Until step 2 ships, these classes are documentation + a stable target
for downstream callers (Bull/Bear, Research Manager) that may want to
consume structured fields when available.
"""

from __future__ import annotations

from typing import List, Literal, Optional

try:
    from pydantic import BaseModel, Field
except ImportError:                                          # pragma: no cover
    # Defer the failure: importing this module shouldn't crash environments
    # that haven't installed pydantic yet.
    BaseModel = object                                       # type: ignore
    def Field(*a, **k):                                      # type: ignore
        return None


# ---- shared enums ---------------------------------------------------------

TrendDirection = Literal["up", "down", "sideways"]
RsiZone        = Literal["oversold", "neutral", "overbought"]
MacdSignal     = Literal["bullish_cross", "bearish_cross", "neutral"]
SentimentBias  = Literal["bullish", "neutral", "bearish"]
NewsTone       = Literal["positive", "neutral", "negative", "mixed"]
ConvictionLvl  = Literal["low", "medium", "high"]


# ---- Market analyst report ------------------------------------------------

class MarketReport(BaseModel):
    """Structured output of the Market Analyst.

    Includes the headline indicators (RSI/MACD/BBands/ATR) plus narrative.
    """
    trend: TrendDirection
    trend_conviction: ConvictionLvl

    # Core indicators (any may be absent for thin instruments)
    rsi: Optional[float] = Field(None, description="RSI(14) latest value")
    rsi_zone: RsiZone = "neutral"

    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    macd_cross: MacdSignal = "neutral"

    bb_position: Optional[float] = Field(None,
        description="%B = (price-lower)/(upper-lower); 0..1, >1 above upper, <0 below lower")
    atr_pct: Optional[float] = Field(None,
        description="ATR(14) divided by current price; rough vol estimate")
    sma_20_above_sma_50: Optional[bool] = Field(None,
        description="True = short-term momentum aligned with mid-term trend")

    # Free-form context
    key_observations: List[str] = Field(default_factory=list,
        description="1-3 bullet points the LLM wants to highlight")
    summary_md: str = Field("", description="Markdown summary for the cockpit")


# ---- Sentiment / social analyst -------------------------------------------

class SentimentReport(BaseModel):
    """Structured output of the Social/Sentiment Analyst."""
    bias: SentimentBias
    bias_conviction: ConvictionLvl

    # Numeric snapshot
    mention_count_7d: Optional[int] = None
    mention_change_pct: Optional[float] = Field(None,
        description="vs previous 7d baseline; positive = increasing chatter")
    positive_pct: Optional[float] = None
    negative_pct: Optional[float] = None

    # Tags
    trending_topics: List[str] = Field(default_factory=list,
        description="High-frequency phrases or themes")
    risk_flags: List[str] = Field(default_factory=list,
        description="e.g. 'short_squeeze_chatter', 'pump_dump_concern'")

    summary_md: str = ""


# ---- News analyst ---------------------------------------------------------

class NewsReport(BaseModel):
    """Structured output of the News Analyst."""
    tone: NewsTone
    tone_conviction: ConvictionLvl

    # Headline-level flags the LLM extracted
    flags: List[Literal[
        "earnings_beat", "earnings_miss", "guidance_raised", "guidance_cut",
        "downgrade", "upgrade", "acquisition", "merger", "spinoff",
        "buyback", "dividend_change", "lawsuit", "investigation",
        "product_launch", "partnership", "exec_change", "macro_event",
    ]] = Field(default_factory=list)

    # Macro context
    macro_themes: List[str] = Field(default_factory=list,
        description="e.g. 'fed_rate_path', 'china_export_curbs'")

    top_headlines: List[str] = Field(default_factory=list,
        description="Up to 5 most-relevant headlines verbatim")

    summary_md: str = ""


# ---- Fundamentals analyst -------------------------------------------------

class FundamentalsReport(BaseModel):
    """Structured output of the Fundamentals Analyst."""
    health: Literal["strong", "stable", "watch", "weak"]
    health_conviction: ConvictionLvl

    # Snapshot ratios (latest available)
    pe_ttm: Optional[float] = None
    pb_ttm: Optional[float] = None
    ps_ttm: Optional[float] = None
    roe_ttm: Optional[float] = None
    debt_to_equity: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None
    fcf_positive: Optional[bool] = None

    # Margin profile
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None

    # Qualitative
    moat_strength: ConvictionLvl = "medium"
    risk_factors: List[str] = Field(default_factory=list)

    summary_md: str = ""


# ---- collection helper ----------------------------------------------------

ALL_SCHEMAS = {
    "market_report":       MarketReport,
    "sentiment_report":    SentimentReport,
    "news_report":         NewsReport,
    "fundamentals_report": FundamentalsReport,
}


__all__ = [
    "TrendDirection", "RsiZone", "MacdSignal", "SentimentBias", "NewsTone",
    "ConvictionLvl",
    "MarketReport", "SentimentReport", "NewsReport", "FundamentalsReport",
    "ALL_SCHEMAS",
]
