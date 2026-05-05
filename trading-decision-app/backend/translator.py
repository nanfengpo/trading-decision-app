"""
Lightweight translation layer for the cockpit.

Why this exists
---------------
TradingAgents intentionally keeps its internal debate (Bull/Bear, Risk 3-way,
Trader, Research Manager) in English even when ``output_language=Chinese`` —
the framework's authors found that switching reasoning language to Chinese
hurts argumentative quality. That leaves a UX problem: a user who picks
中文 still sees English in the debate panels.

Strategy here ("方案 B"): leave TradingAgents untouched and translate the
text in our backend before it leaves the SSE pipe. Every translatable event
(report / debate / risk_debate / final_decision) is emitted *immediately* in
its original language, then a background thread translates and emits a
``translation`` patch event referencing the original by ``msg_id``. The UI
swaps in the Chinese text when the patch arrives.

Provider selection
------------------
Translation uses an OpenAI-compatible chat endpoint (works for OpenAI,
DeepSeek, Qwen, Kimi/Moonshot, GLM). It picks the first provider whose API
key is in env, in this preference order (cheap + Chinese-strong first):

    DeepSeek → Qwen → GLM → Kimi → OpenAI

Override with ``TRANSLATION_PROVIDER`` and ``TRANSLATION_MODEL`` env vars.
"""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# (default_base_url, env_var_for_key, default_quick_model)
PROVIDER_CONFIG: Dict[str, Tuple[str, str, str]] = {
    "deepseek": ("https://api.deepseek.com",                                 "DEEPSEEK_API_KEY",  "deepseek-chat"),
    "qwen":     ("https://dashscope-intl.aliyuncs.com/compatible-mode/v1",   "DASHSCOPE_API_KEY", "qwen-plus"),
    "glm":      ("https://api.z.ai/api/paas/v4/",                            "ZHIPU_API_KEY",     "glm-4.7-flash"),
    "kimi":     ("https://api.moonshot.cn/v1",                               "MOONSHOT_API_KEY",  "moonshot-v1-32k"),
    "openai":   ("https://api.openai.com/v1",                                "OPENAI_API_KEY",    "gpt-5.4-mini"),
}

PREF_ORDER = ["deepseek", "qwen", "glm", "kimi", "openai"]

_SYSTEM_PROMPT = (
    "You are a professional financial translator. Translate the user's English text into "
    "natural, fluent Simplified Chinese. STRICT rules:\n"
    "1. Preserve markdown structure — headings (#), lists (-, *), tables (|), code (```), bold (**), italic (*).\n"
    "2. Keep ticker symbols (e.g. NVDA, BTC-USD), numbers, percentages, dates exactly as-is.\n"
    "3. Keep canonical English finance terms in parentheses where useful (e.g. 移动平均线 (MA))\n"
    "4. Output the translation ONLY — no preamble, no explanation, no quotes around the result.\n"
    "5. If the input is already Chinese, return it unchanged."
)


class Translator:
    """Per-session translator. Thread-safe; uses a small worker pool."""

    def __init__(self, target_lang: str = "Chinese", max_workers: int = 3) -> None:
        self.target = (target_lang or "Chinese").strip()
        self.cache: Dict[int, str] = {}
        self.cache_lock = threading.Lock()
        self.provider: Optional[str] = None
        self.model: Optional[str] = None
        self.client = None
        self.pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="trans")
        self._init_provider()

    # -- provider bootstrap ------------------------------------------------

    def _init_provider(self) -> None:
        if self.target.lower() == "english":
            return  # nothing to do

        try:
            from openai import OpenAI  # type: ignore
        except ImportError:
            logger.warning("openai SDK not installed → translation disabled")
            return

        forced = (os.environ.get("TRANSLATION_PROVIDER") or "").strip().lower()
        order = [forced] + [p for p in PREF_ORDER if p != forced] if forced else PREF_ORDER
        order = [p for p in order if p in PROVIDER_CONFIG]

        for p in order:
            base_url, key_env, default_model = PROVIDER_CONFIG[p]
            key = os.environ.get(key_env)
            if not key:
                continue
            self.provider = p
            self.model = os.environ.get("TRANSLATION_MODEL") or default_model
            try:
                self.client = OpenAI(api_key=key, base_url=base_url)
                logger.info("translator: using provider=%s model=%s", p, self.model)
                return
            except Exception as e:
                logger.warning("translator: failed to init %s (%s)", p, e)
                self.provider = self.model = self.client = None
                continue
        logger.info("translator: no provider key found → pass-through")

    # -- public API --------------------------------------------------------

    def is_available(self) -> bool:
        return self.target.lower() != "english" and self.client is not None

    def status(self) -> Dict[str, Optional[str]]:
        return {
            "available": bool(self.is_available()),
            "provider": self.provider,
            "model": self.model,
            "target": self.target,
        }

    @staticmethod
    def is_chinese(text: str) -> bool:
        """Heuristic: text already considered Chinese if >=30% of letters are CJK."""
        if not text:
            return True
        letters = [c for c in text if c.isalpha() or "一" <= c <= "鿿"]
        if not letters:
            return True
        zh = sum(1 for c in letters if "一" <= c <= "鿿")
        return zh / len(letters) >= 0.30

    def translate_sync(self, text: str) -> str:
        """Blocking translate. Returns input unchanged if not needed/possible."""
        if not text or not self.is_available():
            return text
        if self.is_chinese(text):
            return text
        h = hash(text)
        with self.cache_lock:
            if h in self.cache:
                return self.cache[h]
        try:
            resp = self.client.chat.completions.create(  # type: ignore[union-attr]
                model=self.model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                temperature=0.2,
                max_tokens=4096,
            )
            out = (resp.choices[0].message.content or "").strip()
            if not out:
                return text
            with self.cache_lock:
                self.cache[h] = out
            return out
        except Exception as e:
            logger.warning("translation failed (%s) — passing through", e)
            return text

    def submit(self, text: str, on_done: Callable[[str], None]) -> Optional[Future]:
        """Background translate + callback. Returns a Future you can await/ignore."""
        if not text or not self.is_available() or self.is_chinese(text):
            return None
        future = self.pool.submit(self.translate_sync, text)

        def _cb(f: Future) -> None:
            try:
                result = f.result()
            except Exception as e:
                logger.warning("translate worker error: %s", e)
                return
            if result and result != text:
                try:
                    on_done(result)
                except Exception as e:
                    logger.warning("translate on_done callback error: %s", e)

        future.add_done_callback(_cb)
        return future

    def shutdown(self) -> None:
        try:
            self.pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
