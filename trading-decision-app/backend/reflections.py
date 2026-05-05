"""
Reflections API — surface TradingAgents' built-in memory log to the frontend.

TradingAgents already maintains a markdown memory log at
``$TRADINGAGENTS_MEMORY_LOG_PATH`` (default ``~/.tradingagents/memory/trading_memory.md``)
where every completed decision becomes an entry of the form::

    [2026-05-01 | NVDA | Buy | pending]                  ← initial
    DECISION: <markdown>
    -----
    [2026-05-01 | NVDA | Buy | raw +3.2% | alpha +1.8% | 5d]   ← after resolution
    DECISION: <markdown>
    REFLECTION: <markdown>          ← LLM-generated retrospective
    -----

This module wraps ``TradingMemoryLog`` to:
1. Enumerate entries (load_entries)
2. Filter to a single ticker
3. Filter to those that have actual outcomes (not pending)

The HTTP endpoint in server.py uses these helpers; the agent_runner uses
the same memory_log instance to also emit a ``past_context`` SSE event so
the frontend's cockpit can show "what we learned from previous calls" in
the live view.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _memory_log() -> Any:
    """Return a TradingMemoryLog instance bound to the user's config.

    Imported lazily so this module is import-safe even when TradingAgents
    isn't on PYTHONPATH (e.g. CI without full deps installed). Catches
    *any* failure so the API never crashes the surrounding endpoint.
    """
    try:
        from tradingagents.agents.utils.memory import TradingMemoryLog          # type: ignore
        from tradingagents.default_config import DEFAULT_CONFIG                 # type: ignore
    except Exception as e:  # ImportError, KeyError from broken pkg state, etc.
        logger.debug("memory log not available: %s", e)
        return None
    try:
        cfg = dict(DEFAULT_CONFIG)
        return TradingMemoryLog(cfg)
    except Exception as e:
        logger.debug("memory log construct failed: %s", e)
        return None


def list_entries(ticker: Optional[str] = None,
                 only_resolved: bool = False,
                 limit: int = 100) -> List[Dict[str, Any]]:
    """Return memory-log entries, newest first.

    Each dict carries:
      ticker, trade_date, rating, pending,
      raw_return, alpha_return, holding_days, decision, reflection
    """
    log = _memory_log()
    if log is None:
        return []
    try:
        entries = log.load_entries()
    except Exception as e:
        logger.warning("memory load failed: %s", e)
        return []

    if ticker:
        ticker_u = ticker.upper()
        entries = [e for e in entries if (e.get("ticker") or "").upper() == ticker_u]
    if only_resolved:
        entries = [e for e in entries if not e.get("pending")]

    # Newest first (the log appends; reversing preserves chronological order)
    entries = list(reversed(entries))
    return entries[: max(1, int(limit))]


def get_past_context(ticker: str) -> str:
    """Convenience: same `past_context` string the analysts see, exposed
    for the cockpit's "📝 决策回顾" panel."""
    log = _memory_log()
    if log is None:
        return ""
    try:
        return log.get_past_context(ticker)
    except Exception as e:
        logger.warning("past_context failed: %s", e)
        return ""


def stats() -> Dict[str, Any]:
    """Lightweight summary for the Profile usage panel."""
    try:
        log = _memory_log()
    except Exception:
        log = None
    if log is None:
        return {"available": False, "total": 0, "resolved": 0, "pending": 0}
    try:
        entries = log.load_entries()
    except Exception:
        return {"available": False, "total": 0, "resolved": 0, "pending": 0}
    pending = sum(1 for e in entries if e.get("pending"))
    resolved = len(entries) - pending
    avg_alpha = None
    alphas = [e.get("alpha_return") for e in entries
              if e.get("alpha_return") is not None and not e.get("pending")]
    if alphas:
        avg_alpha = sum(alphas) / len(alphas)
    return {
        "available": True,
        "total": len(entries),
        "resolved": resolved,
        "pending": pending,
        "avg_alpha": avg_alpha,
    }
