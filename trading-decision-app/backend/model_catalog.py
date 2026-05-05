"""
Curated model catalog for the front-end dropdowns.

Strategy:
  1. Start from a bundled fallback that we control (so we can ship newer
     models — gpt-5.5, claude-opus-4-7, gemini-3.5-pro — even if the
     installed TradingAgents catalog is older).
  2. Try to import TradingAgents' own MODEL_OPTIONS and *merge* its entries
     in (preserves anything we missed). Items in our fallback win when there
     are duplicates; new providers/models from TradingAgents are added.

Provider key env vars match TradingAgents' OpenAI-compatible client config so
LIVE mode works without further wiring.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

ModelOption = Tuple[str, str]  # (label, value)

# ---------- bundled fallback -------------------------------------------------
# Keep `quick` short (2-token-ish, picked dozens of times) and `deep` rich
# (picked once per stage, can be expensive).
_FALLBACK_OPTIONS: Dict[str, Dict[str, List[ModelOption]]] = {
    "openai": {
        "deep": [
            ("GPT-5.5 · 最新旗舰",                   "gpt-5.5"),
        ],
        "quick": [
            ("GPT-5.5 · 最新旗舰",                   "gpt-5.5"),
            ("GPT-5.4 Mini · 性价比",                "gpt-5.4-mini"),
        ],
    },
    "anthropic": {
        "deep": [
            ("Claude Opus 4.7 · 最强旗舰",            "claude-opus-4-7"),
            ("Claude Sonnet 4.6 · 均衡",              "claude-sonnet-4-6"),
        ],
        "quick": [
            ("Claude Sonnet 4.6 · 均衡",              "claude-sonnet-4-6"),
            ("Claude Haiku 4.5 · 极速",               "claude-haiku-4-5"),
        ],
    },
    "google": {
        "deep": [
            ("Gemini 3.1 Pro · 推理旗舰",             "gemini-3.1-pro"),
            ("Gemini 3 Flash · 均衡",                 "gemini-3-flash"),
        ],
        "quick": [
            ("Gemini 3 Flash · 均衡",                 "gemini-3-flash"),
            ("Gemini 3.1 Flash-Lite · 最低成本",      "gemini-3.1-flash-lite"),
        ],
    },
    "deepseek": {
        "deep": [
            ("DeepSeek V4 Pro Max · 最强旗舰",         "deepseek-v4-pro-max"),
            ("DeepSeek V4 Pro · 旗舰",                 "deepseek-v4-pro"),
        ],
        "quick": [
            ("DeepSeek V4 Pro · 旗舰",                 "deepseek-v4-pro"),
            ("DeepSeek V4 Flash · 极速",               "deepseek-v4-flash"),
        ],
    },
    "qwen": {
        "deep": [
            ("Qwen 3.6 Max · 最强旗舰",                "qwen3.6-max"),
            ("Qwen 3.6 Plus · 均衡",                   "qwen3.6-plus"),
        ],
        "quick": [
            ("Qwen 3.6 Plus · 均衡",                   "qwen3.6-plus"),
            ("Qwen 3.6 Flash · 极速",                  "qwen3.6-flash"),
        ],
    },
    "kimi": {
        "deep": [
            ("Kimi K2.6 · 最新旗舰",                   "kimi-k2.6"),
        ],
        "quick": [
            ("Kimi K2.6 · 最新旗舰",                   "kimi-k2.6"),
        ],
    },
    "glm": {
        "deep": [
            ("GLM-5 · 旗舰",                           "glm-5"),
        ],
        "quick": [
            ("GLM-5 · 旗舰",                           "glm-5"),
        ],
    },
}

PROVIDER_LABELS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic (Claude)",
    "google": "Google (Gemini)",
    "deepseek": "DeepSeek",
    "qwen": "Qwen 通义千问",
    "kimi": "Kimi (Moonshot)",
    "glm": "智谱 GLM",
}

PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "kimi": "MOONSHOT_API_KEY",
    "glm": "ZHIPU_API_KEY",
}

# Display order in the dropdown
PROVIDER_ORDER = ["openai", "anthropic", "google", "deepseek", "qwen", "kimi", "glm"]


# ---------- merge with TradingAgents' catalog --------------------------------

def _merge_tradingagents(into: Dict[str, Dict[str, List[ModelOption]]]) -> None:
    """Pull TradingAgents' MODEL_OPTIONS and add anything our fallback missed.
    Our entries always win on duplicate values to keep the latest models on top."""
    try:
        from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS  # type: ignore
    except Exception as e:
        logger.info("TradingAgents catalog not importable: %s — fallback only", e)
        return

    for provider, modes in MODEL_OPTIONS.items():
        if provider not in PROVIDER_LABELS:
            continue
        bucket = into.setdefault(provider, {"quick": [], "deep": []})
        for mode, opts in modes.items():
            existing_values = {v for (_, v) in bucket.get(mode, [])}
            for label, value in opts:
                if value == "custom":
                    continue
                if value in existing_values:
                    continue
                bucket[mode].append((label, value))
                existing_values.add(value)


def get_catalog() -> Dict[str, Dict[str, List[ModelOption]]]:
    cat: Dict[str, Dict[str, List[ModelOption]]] = {
        p: {m: list(opts) for m, opts in modes.items()}
        for p, modes in _FALLBACK_OPTIONS.items()
    }
    # Opt-in merge with TradingAgents' (older) catalog. Off by default so the
    # bundled list above stays the single source of truth — turn on with
    # MERGE_TRADINGAGENTS_MODELS=1 to also surface anything TradingAgents
    # ships that we don't already list.
    if os.environ.get("MERGE_TRADINGAGENTS_MODELS") in ("1", "true", "yes"):
        _merge_tradingagents(cat)
    return cat


def serialize() -> Dict[str, object]:
    """Shape the catalog for the front-end."""
    cat = get_catalog()
    providers = []
    for pid in PROVIDER_ORDER:
        if pid not in cat:
            continue
        modes = cat[pid]
        providers.append({
            "id": pid,
            "label": PROVIDER_LABELS.get(pid, pid),
            "key_env": PROVIDER_KEY_ENV.get(pid),
            "key_present": bool(os.environ.get(PROVIDER_KEY_ENV.get(pid, ""))),
            "models": {
                mode: [{"label": l, "value": v} for (l, v) in opts]
                for mode, opts in modes.items()
            },
        })
    return {"providers": providers}
