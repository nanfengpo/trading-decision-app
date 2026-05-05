"""
Process-level TTL cache for dataflow vendor calls.

Why this exists
---------------
Premium APIs cost money and time. Within a single LIVE decision the same
ticker is queried by multiple analysts (market, fundamentals, news,
social). Across multiple users analysing the same ticker on the same day
the situation is even more wasteful. A simple in-process LRU + TTL cache
removes 80%+ of those duplicates.

Usage
-----
Decorate vendor methods that take ``(self, ticker, ...)`` style args::

    from .cache import cached

    class FinnhubPro(BaseDataSource):
        @cached(ttl=300)
        def fetch_news_summary(self, ticker, lookback_days=7):
            ...

The cache key includes ``self.name`` (vendor id), the method name, and
all args/kwargs (stringified). ``None`` results are NOT cached so a
transient API failure doesn't poison subsequent retries.

Stats
-----
``cache_stats()`` returns a dict of ``hits / misses / size`` for the
``/api/dataflows`` endpoint to surface in the Profile usage panel.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from functools import wraps
from typing import Any, Callable, Tuple

logger = logging.getLogger(__name__)

# Global cap on entries (LRU eviction). 5000 entries × ~1 KB each ≈ 5 MB.
_MAX_ENTRIES = 5000

_store: "OrderedDict[Tuple, Tuple[float, Any]]" = OrderedDict()
_lock = threading.Lock()
_stats = {"hits": 0, "misses": 0, "evictions": 0, "skipped_none": 0}


def _make_key(prefix: str, args: tuple, kwargs: dict) -> Tuple:
    """Best-effort hashable key. Falls back to repr() for unhashable args."""
    def safe(x):
        try:
            hash(x)
            return x
        except TypeError:
            return repr(x)
    return (prefix, tuple(safe(a) for a in args), tuple(sorted((k, safe(v)) for k, v in kwargs.items())))


def cached(ttl: int = 300):
    """Decorator. ``ttl`` is in seconds."""
    def deco(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(self, *args, **kwargs):
            # Vendor name is part of the prefix so two vendors don't collide
            vendor_id = getattr(self, "name", self.__class__.__name__)
            key = _make_key(f"{vendor_id}:{fn.__name__}", args, kwargs)
            now = time.time()

            with _lock:
                if key in _store:
                    expires_at, value = _store[key]
                    if expires_at > now:
                        _store.move_to_end(key)  # mark as recently used
                        _stats["hits"] += 1
                        return value
                    # expired
                    _store.pop(key, None)
                _stats["misses"] += 1

            value = fn(self, *args, **kwargs)
            if value is None:
                with _lock:
                    _stats["skipped_none"] += 1
                return None

            with _lock:
                _store[key] = (now + ttl, value)
                _store.move_to_end(key)
                while len(_store) > _MAX_ENTRIES:
                    _store.popitem(last=False)
                    _stats["evictions"] += 1
            return value
        return wrapper
    return deco


def cache_stats() -> dict:
    with _lock:
        return dict(_stats, size=len(_store))


def cache_clear() -> int:
    with _lock:
        n = len(_store)
        _store.clear()
        return n
