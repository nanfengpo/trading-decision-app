"""
premium_bridge — register external premium dataflows as TradingAgents vendors.

This module is a thin shim. It tries to import a sibling package called
``dataflows`` (provided by the host application — e.g. trading-decision-app's
backend) and registers each of its sources as an additional vendor in
TradingAgents' ``VENDOR_METHODS`` dispatch table.

When the host application is not present (or its `dataflows` package fails
to import), ``register()`` is a no-op and TradingAgents falls back to its
built-in yfinance / alpha_vantage path. This keeps ``tradingagents`` runnable
stand-alone.

Wiring is done in ``interface.py`` by appending::

    from . import premium_bridge
    premium_bridge.register(VENDOR_METHODS)

After registration the user can route a category to the premium vendor by
setting in config::

    config["data_vendors"]["news_data"] = "finnhub_pro"
"""

from __future__ import annotations

import logging
from typing import Callable, Dict

logger = logging.getLogger(__name__)


def _format_signal(text: str) -> str:
    """A tiny helper: empty / None → raise, so route_to_vendor falls back."""
    if not text or not text.strip():
        raise RuntimeError("premium source returned empty result")
    return text


def _wrap_news(src) -> Callable:
    def _impl(ticker: str, start_date: str, end_date: str) -> str:
        # We ignore start_date/end_date precisely — the premium source is
        # already curated by lookback. Pass a reasonable lookback derived
        # from the date range (capped to 14 days to keep summaries tight).
        from datetime import datetime
        try:
            lb = (datetime.fromisoformat(end_date) - datetime.fromisoformat(start_date)).days
        except Exception:
            lb = 7
        return _format_signal(src.fetch_news_summary(ticker, lookback_days=max(1, min(14, lb))))
    return _impl


def _wrap_global_news(src) -> Callable:
    def _impl(curr_date: str, look_back_days: int = 7, limit: int = 5) -> str:
        # Reuse fetch_news_summary on the SPY proxy — most premium news APIs
        # don't have a generic "global news" endpoint that's better than free
        # sources, so let TradingAgents fall back here unless the source
        # exposes a dedicated method.
        out = src.fetch_news_summary("SPY", lookback_days=look_back_days)
        return _format_signal(out)
    return _impl


def _wrap_quote(src) -> Callable:
    def _impl(*args, **kwargs) -> str:
        ticker = args[0] if args else kwargs.get("ticker") or kwargs.get("symbol")
        return _format_signal(src.fetch_quote_summary(ticker))
    return _impl


def _wrap_indicators(src) -> Callable:
    def _impl(*args, **kwargs) -> str:
        ticker = args[0] if args else kwargs.get("ticker") or kwargs.get("symbol")
        # Most premium sources put indicators in their quote summary already
        # (SMA/RSI/MACD synthesised on closes). If a vendor exposes a richer
        # method, the dataflows package can override fetch_indicator_summary.
        out = (src.fetch_indicator_summary(ticker) if hasattr(src, "fetch_indicator_summary")
               else src.fetch_quote_summary(ticker))
        return _format_signal(out)
    return _impl


def _wrap_fundamentals(src) -> Callable:
    def _impl(*args, **kwargs) -> str:
        ticker = args[0] if args else kwargs.get("ticker") or kwargs.get("symbol")
        return _format_signal(src.fetch_fundamentals_summary(ticker))
    return _impl


def _wrap_insider(src) -> Callable:
    def _impl(*args, **kwargs) -> str:
        # Stub — most premium dataflow sources don't differentiate insider
        # transactions; raise so TradingAgents falls back to yfinance.
        raise RuntimeError("premium source has no insider-transactions method")
    return _impl


# Mapping: TradingAgents method name → (premium category, wrapper builder)
_METHOD_BINDINGS = {
    "get_news":              ("news",         _wrap_news),
    "get_global_news":       ("news",         _wrap_global_news),
    "get_insider_transactions": ("news",      _wrap_insider),
    "get_stock_data":        ("market",       _wrap_quote),
    "get_indicators":        ("market",       _wrap_indicators),
    "get_fundamentals":      ("fundamentals", _wrap_fundamentals),
    "get_balance_sheet":     ("fundamentals", _wrap_fundamentals),
    "get_cashflow":          ("fundamentals", _wrap_fundamentals),
    "get_income_statement":  ("fundamentals", _wrap_fundamentals),
}


def register(vendor_methods: Dict[str, Dict[str, Callable]]) -> None:
    """Inject every available premium vendor into ``vendor_methods``.

    No-op when the host's ``dataflows`` package isn't importable.
    """
    try:
        from dataflows.registry import Registry          # type: ignore
        from dataflows.factory import get_source         # type: ignore
    except Exception as e:
        logger.debug("premium_bridge: external dataflows not available (%s) — skipping", e)
        return

    registered = 0
    for vendor_meta in Registry.all():
        # Only register if its key is in env (so route_to_vendor doesn't pick
        # an unconfigured vendor and waste a try-iteration).
        import os
        if vendor_meta.api_key_env and not os.environ.get(vendor_meta.api_key_env):
            continue
        try:
            src = vendor_meta.factory()
        except Exception as e:
            logger.warning("premium_bridge: failed to instantiate %s (%s)", vendor_meta.name, e)
            continue

        for method_name, (premium_cat, builder) in _METHOD_BINDINGS.items():
            if premium_cat not in vendor_meta.categories:
                continue
            vendor_methods.setdefault(method_name, {})[vendor_meta.name] = builder(src)
            registered += 1

    if registered:
        logger.info("premium_bridge: registered %d vendor methods", registered)
