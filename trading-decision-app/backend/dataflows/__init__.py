"""
Premium data-source layer.

Goal: keep TradingAgents untouched while letting users plug in paid APIs
(Finnhub Pro, Polygon.io, Alpha Vantage Premium, FMP Premium, AkShare,
JQData, RQData, Nasdaq Data Link, …) on a per-category basis.

Architecture
------------
1. Each vendor lives in its own module in this package and exposes the
   same minimal interface (a class extending ``BaseDataSource``).
2. ``Registry`` maps category → list of available providers and lets
   ``factory.get_source(category, prefer=...)`` pick one based on env-var
   keys and explicit user preference.
3. Every source is responsible for **summarising** its raw response into
   a compact form (≤ a couple hundred tokens) before handing it to the
   LLM. Long JSON dumps blow up cost and add noise — `summarize.py`
   provides reusable helpers.

To plug a vendor into TradingAgents' agents:

    from dataflows.factory import get_source
    src = get_source("news", prefer="finnhub_pro")
    text = src.fetch_news_summary(ticker="NVDA", lookback_days=7)
    # text is now a markdown bullet list ready to feed to an analyst.

The factory degrades gracefully: when no vendor is configured for a
category, it returns ``None`` and TradingAgents falls back to its built-in
yfinance/finnhub-free layer.
"""

from .registry import (
    BaseDataSource,
    Registry,
    Category,
    register,
    available,
)
from .factory import get_source, list_categories
from .summarize import summarize_news, summarize_quotes, summarize_fundamentals

__all__ = [
    "BaseDataSource",
    "Registry",
    "Category",
    "register",
    "available",
    "get_source",
    "list_categories",
    "summarize_news",
    "summarize_quotes",
    "summarize_fundamentals",
]

# Trigger registration of bundled vendors. New vendors should add an import
# line here so they get picked up at startup.
from . import finnhub_pro      # noqa: F401
from . import polygon_io       # noqa: F401
from . import alpha_vantage    # noqa: F401
from . import akshare_cn       # noqa: F401
