"""
Per-request API-key injection for multi-tenant deployments.

Why this exists
---------------
TradingAgents reads provider keys from ``os.environ`` at the moment its
LLM clients and dataflow vendor objects are constructed. In single-tenant
mode that's fine — keys live in ``.env`` and never change. In multi-tenant
mode every signed-in user has their own keys (stored in their Supabase
``profiles.llm_api_keys`` / ``custom_api_keys`` JSONB) and we want the
backend to use *those* keys for the duration of that user's run.

The wrinkle: ``os.environ`` is process-wide. If two users start
decisions concurrently, naively setting env from each would race.

The strategy
------------
``KeyInjector`` is a re-entrant context manager that:

1. Acquires a module-level lock.
2. Snapshots the current values of all env vars it's about to touch.
3. Sets the new values from the request payload.
4. Yields control to the caller. The caller MUST do all key-sensitive work
   (constructing LLM clients, instantiating dataflow vendors, calling
   ``Registry.list_for_category`` for keyed vendors) inside the ``with``
   block.
5. On exit, restores the snapshot and releases the lock.

Crucially, once an LLM client / vendor object is constructed, it captures
its key. The streaming graph execution that follows does NOT need the env
to remain set, so the lock window is just a few hundred milliseconds —
multiple concurrent users serialise only at construction, then run in
parallel.

Threat model
------------
- Keys are stored encrypted-at-rest by Supabase (server-side encryption)
- They travel over HTTPS in the request body
- They're never logged
- They're never written to the decision row's ``run_state``
- Backend never persists them to disk

Limitations
-----------
- Two users using the SAME provider but DIFFERENT keys cannot run
  *simultaneously* during the construction window (the lock serialises
  them). This is a few hundred ms — usually acceptable.
- Anthropic SDK reads ``ANTHROPIC_API_KEY`` lazily on first call (not at
  construction); this is documented but works fine in practice because
  the call happens inside the ``with`` block too.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from typing import Dict, Iterable, Optional

logger = logging.getLogger(__name__)

# Whitelist of env vars KeyInjector is allowed to override. Anything not in
# this list is ignored even if the request contains it — defence in depth
# against a malicious frontend trying to overwrite e.g. PATH.
_ALLOWED_KEYS: frozenset[str] = frozenset({
    # LLM providers
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",            # Qwen
    "MOONSHOT_API_KEY",             # Kimi
    "ZHIPU_API_KEY",                # GLM
    "XAI_API_KEY",
    "OPENROUTER_API_KEY",
    # Premium data sources
    "FINNHUB_API_KEY",
    "POLYGON_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
    "FMP_API_KEY",
    "NASDAQ_DATA_LINK_API_KEY",
    # Optional translation override
    "TRANSLATION_PROVIDER",
    "TRANSLATION_MODEL",
})

_lock = threading.Lock()


@contextmanager
def inject(keys: Optional[Dict[str, str]]):
    """Context manager: temporarily set env from ``keys`` while the lock is held.

    Usage::

        with key_injector.inject(req.api_keys):
            graph = TradingAgentsGraph(config=cfg)   # captures keys
        # lock released; graph runs without env access

    ``keys`` may be None or empty — in that case the manager is a no-op
    (and doesn't even acquire the lock, so single-tenant deployments pay
    zero overhead).
    """
    keys = {k: v for (k, v) in (keys or {}).items()
            if k in _ALLOWED_KEYS and isinstance(v, str) and v.strip()}
    if not keys:
        yield
        return

    with _lock:
        snapshot: Dict[str, Optional[str]] = {}
        try:
            for k, v in keys.items():
                snapshot[k] = os.environ.get(k)
                os.environ[k] = v
            n_overrides = len(keys)
            n_changed = sum(1 for k in keys if snapshot[k] != keys[k])
            logger.debug(
                "KeyInjector: %d keys received, %d differ from current env",
                n_overrides, n_changed,
            )
            yield
        finally:
            for k, original in snapshot.items():
                if original is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = original


def filter_allowed(d: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Return only the entries we'd actually use — for diagnostics only.
    Never log the actual values, just the keys."""
    return {k: "***" for k in (d or {}) if k in _ALLOWED_KEYS}
