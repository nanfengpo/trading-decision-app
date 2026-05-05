"""Vendor registry — maps a category to the providers that implement it."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Categories we care about. TradingAgents' analysts cleanly map to four:
#   market         — quotes, OHLCV, technical indicators
#   fundamentals   — financial statements, ratios, ownership
#   news           — company + macro news
#   social         — social sentiment / influencer chatter
# Two extras for the opportunities scanner:
#   options        — IV, volume, unusual activity
#   crypto         — crypto-specific funding/flows
class Category:
    MARKET = "market"
    FUNDAMENTALS = "fundamentals"
    NEWS = "news"
    SOCIAL = "social"
    OPTIONS = "options"
    CRYPTO = "crypto"


@dataclass
class VendorMeta:
    name: str                       # short slug, e.g. "finnhub_pro"
    display_name: str               # "Finnhub Pro"
    api_key_env: str                # OS env var holding the key
    categories: List[str]           # list of Category.* it supports
    factory: callable               # () -> BaseDataSource


class BaseDataSource:
    """Minimal interface — vendors override only what they support."""

    name: str = ""
    api_key_env: str = ""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get(self.api_key_env, "")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    # Each method returns a compact, LLM-ready string (markdown).
    # None means "this vendor does not implement this method".
    def fetch_news_summary(self, ticker: str, lookback_days: int = 7) -> Optional[str]:
        return None

    def fetch_quote_summary(self, ticker: str) -> Optional[str]:
        return None

    def fetch_indicator_summary(self, ticker: str, days: int = 90) -> Optional[str]:
        return None

    def fetch_fundamentals_summary(self, ticker: str) -> Optional[str]:
        return None

    # ── three-statement detail (Phase A.1) — return None to fall back ──
    def fetch_balance_sheet_summary(self, ticker: str) -> Optional[str]:
        return None

    def fetch_income_statement_summary(self, ticker: str) -> Optional[str]:
        return None

    def fetch_cashflow_summary(self, ticker: str) -> Optional[str]:
        return None

    # ── insider transactions (Phase A.3) ──
    def fetch_insider_summary(self, ticker: str, lookback_days: int = 90) -> Optional[str]:
        return None

    def fetch_social_summary(self, ticker: str, lookback_days: int = 7) -> Optional[str]:
        return None

    def fetch_options_summary(self, ticker: str) -> Optional[str]:
        return None


class Registry:
    _providers: Dict[str, VendorMeta] = {}
    _by_category: Dict[str, List[str]] = {}

    @classmethod
    def register(cls, meta: VendorMeta) -> None:
        cls._providers[meta.name] = meta
        for cat in meta.categories:
            cls._by_category.setdefault(cat, []).append(meta.name)
        logger.debug("registered vendor %s for categories=%s", meta.name, meta.categories)

    @classmethod
    def get(cls, name: str) -> Optional[VendorMeta]:
        return cls._providers.get(name)

    @classmethod
    def list_for_category(cls, category: str) -> List[VendorMeta]:
        return [cls._providers[n] for n in cls._by_category.get(category, []) if n in cls._providers]

    @classmethod
    def all(cls) -> List[VendorMeta]:
        return list(cls._providers.values())


def register(meta: VendorMeta) -> None:
    Registry.register(meta)


def available(category: str) -> List[VendorMeta]:
    """Vendors in this category that have an API key configured."""
    return [m for m in Registry.list_for_category(category)
            if os.environ.get(m.api_key_env)]
