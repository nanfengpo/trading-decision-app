"""Pick a configured vendor for a given category."""

from __future__ import annotations

import logging
import os
from typing import Optional

from .registry import BaseDataSource, Registry, available

logger = logging.getLogger(__name__)


def get_source(category: str, prefer: Optional[str] = None) -> Optional[BaseDataSource]:
    """Return the first configured vendor for *category*.

    Resolution order:
      1. ``prefer`` argument (e.g. "finnhub_pro") if it's registered + configured
      2. The env var ``DATAFLOW_<CATEGORY_UPPER>`` (e.g. ``DATAFLOW_NEWS``)
      3. First vendor in Registry order that has an API key in env

    Returns None when nothing is configured — callers should fall back to
    TradingAgents' default yfinance/free path.
    """
    # 1) explicit preference
    if prefer:
        meta = Registry.get(prefer)
        if meta and os.environ.get(meta.api_key_env):
            return meta.factory()

    # 2) env var override
    env_name = f"DATAFLOW_{category.upper()}"
    pinned = os.environ.get(env_name, "").strip()
    if pinned:
        meta = Registry.get(pinned)
        if meta and os.environ.get(meta.api_key_env):
            return meta.factory()

    # 3) anything configured
    candidates = available(category)
    if candidates:
        return candidates[0].factory()

    return None


def list_categories() -> dict:
    """Diagnostic dump used by /api/dataflows for the profile page."""
    out = {}
    for cat in ["market", "fundamentals", "news", "social", "options", "crypto"]:
        vendors = Registry.list_for_category(cat)
        out[cat] = [
            {
                "name": v.name,
                "display_name": v.display_name,
                "api_key_env": v.api_key_env,
                "configured": bool(os.environ.get(v.api_key_env)),
            }
            for v in vendors
        ]
    return out
