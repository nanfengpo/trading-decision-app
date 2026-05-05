"""
GranularStatsHandler — per-call telemetry for the SSE pipeline.

Companion to TradingAgents' aggregate ``StatsCallbackHandler``: this one
emits an SSE ``usage_event`` for every individual LLM call and tool
call, so the frontend can both:

1. Display real-time token consumption in the cockpit.
2. Persist each call to the Supabase ``usage_events`` table for
   cross-decision analytics (the frontend writes them under its own
   user_id via RLS — no service-role key required).

Event shape::

    {
        "type": "usage_event",
        "kind": "llm_call" | "tool_call",
        "ts":   "2026-05-06T08:14:33Z",
        "model":     "...",      # llm_call only
        "tokens_in":  123,       # llm_call only
        "tokens_out": 456,       # llm_call only
        "tool_name": "...",      # tool_call only
    }
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# We import langchain at module load — this file is only imported from
# _run_live, which already requires TradingAgents (and therefore langchain)
# to be installed.
try:
    from langchain_core.callbacks import BaseCallbackHandler   # type: ignore
    from langchain_core.outputs import LLMResult               # type: ignore
    from langchain_core.messages import AIMessage              # type: ignore
except ImportError:                                            # pragma: no cover
    BaseCallbackHandler = object  # type: ignore
    LLMResult = object             # type: ignore
    AIMessage = object             # type: ignore


class GranularStatsHandler(BaseCallbackHandler):                # type: ignore
    """Emits one SSE ``usage_event`` per LLM/tool call."""

    def __init__(self, emit: Callable[[Dict[str, Any]], None], req=None):
        super().__init__()
        self.emit = emit
        # We track the active LLM model name so on_llm_end can include it.
        # langchain's on_chat_model_start passes ``serialized`` with model.
        self._current_model: Dict[Any, str] = {}
        # Some providers don't pass run_id via kwargs; fall back to a stack.
        self._stack: List[str] = []
        # Read provider from request for fallback labeling
        self._fallback_provider = (req.llm_provider if req else "") or "unknown"

    # ── LLM lifecycle ───────────────────────────────────────────────

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs) -> None:
        self._record_llm_start(serialized, kwargs)

    def on_chat_model_start(self, serialized: Dict[str, Any], messages: Any, **kwargs) -> None:
        self._record_llm_start(serialized, kwargs)

    def _record_llm_start(self, serialized: Dict[str, Any], kwargs: Dict[str, Any]) -> None:
        # Try to extract a model name from the serialized payload.
        model_name = "unknown"
        try:
            model_name = (
                (serialized or {}).get("kwargs", {}).get("model")
                or (serialized or {}).get("name")
                or model_name
            )
        except Exception:
            pass
        run_id = kwargs.get("run_id") or id(kwargs)
        self._current_model[run_id] = model_name
        self._stack.append(run_id)

    def on_llm_end(self, response: Any, **kwargs) -> None:
        run_id = kwargs.get("run_id") or (self._stack.pop() if self._stack else None)
        model = self._current_model.pop(run_id, "unknown")

        tokens_in = tokens_out = 0
        try:
            generation = response.generations[0][0]
            message = getattr(generation, "message", None)
            if isinstance(message, AIMessage) and hasattr(message, "usage_metadata"):
                meta = message.usage_metadata or {}
                tokens_in = int(meta.get("input_tokens", 0))
                tokens_out = int(meta.get("output_tokens", 0))
        except Exception:
            pass

        try:
            self.emit({
                "type": "usage_event",
                "kind": "llm_call",
                "ts": _utcnow_iso(),
                "provider": self._fallback_provider,
                "model": model,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            })
        except Exception as e:
            logger.warning("usage_event emit failed: %s", e)

    # ── tool lifecycle ──────────────────────────────────────────────

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs) -> None:
        try:
            tool_name = (serialized or {}).get("name") or "tool"
            self.emit({
                "type": "usage_event",
                "kind": "tool_call",
                "ts": _utcnow_iso(),
                "tool_name": tool_name,
            })
        except Exception as e:
            logger.warning("usage_event emit failed: %s", e)
