"""
Heuristic matcher: turn a TradingAgents decision into a ranked list of
library strategies.

Approach:
  1. Parse the raw decision text for signals (rating, view, volatility, horizon)
  2. Score each library strategy by overlap with those signals + the user's
     constraints (instrument hint, risk tolerance)
  3. Return the top-K with a short rationale

The strategy library is loaded once from `static/strategies.js` by extracting
the JSON-ish object literal — keeping a single source of truth shared with
the front-end.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# OpenAI-compatible providers we'll try for the AI rerank pass, in order of
# preference. Mirrors translator.PROVIDER_CONFIG so any user with a working
# translator already has reranking too.
_AI_PROVIDERS: List[tuple[str, str, str]] = [
    # (env_var, base_url, default_model)
    ("DEEPSEEK_API_KEY",  "https://api.deepseek.com",                                 "deepseek-chat"),
    ("DASHSCOPE_API_KEY", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",   "qwen-plus"),
    ("ZHIPU_API_KEY",     "https://api.z.ai/api/paas/v4/",                            "glm-4.7-flash"),
    ("MOONSHOT_API_KEY",  "https://api.moonshot.cn/v1",                               "moonshot-v1-32k"),
    ("OPENAI_API_KEY",    "https://api.openai.com/v1",                                "gpt-5.4-mini"),
]

STRATEGIES_JS = Path(__file__).resolve().parent.parent / "static" / "strategies.js"


# ---------- strategy library loader -----------------------------------------

_CACHED: List[Dict[str, Any]] = []


def _load_strategies() -> List[Dict[str, Any]]:
    """Best-effort parse the STRATEGIES = [...] literal from strategies.js."""
    global _CACHED
    if _CACHED:
        return _CACHED
    if not STRATEGIES_JS.exists():
        logger.warning("strategies.js not found at %s", STRATEGIES_JS)
        return []

    text = STRATEGIES_JS.read_text(encoding="utf-8")
    m = re.search(r"const\s+STRATEGIES\s*=\s*(\[[\s\S]*?\n\];)", text)
    if not m:
        logger.warning("could not locate STRATEGIES literal")
        return []
    body = m.group(1).rstrip(";")

    # Convert the JS literal -> JSON:
    #   1) quote every key (foo: -> "foo":)
    #   2) replace single-quoted strings with double-quoted strings (escape inner ")
    #   3) drop trailing commas before ] or }
    body = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', body)

    def _q(m: re.Match) -> str:
        s = m.group(1)
        s = s.replace("\\", "\\\\").replace('"', '\\"')
        return '"' + s + '"'

    body = re.sub(r"'((?:[^'\\]|\\.)*)'", _q, body)
    body = re.sub(r",\s*(\]|\})", r"\1", body)

    try:
        _CACHED = json.loads(body)
    except json.JSONDecodeError as e:
        logger.exception("strategy parse failed: %s", e)
        return []
    logger.info("loaded %d strategies from library", len(_CACHED))
    return _CACHED


# ---------- decision parser -------------------------------------------------

def _parse_decision(decision: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise the structured decision payload from agent_runner."""
    raw = (decision.get("raw") or "") + "\n" + (decision.get("trader_plan") or "")
    text = raw.lower()

    rating = (decision.get("rating") or "Hold").strip().title()

    # view from rating + tone
    view = decision.get("view")
    if not view:
        if rating in ("Buy",):
            view = "strong_bull" if "strong" in text or "高 confidence" in text else "mild_bull"
        elif rating == "Overweight":
            view = "mild_bull"
        elif rating == "Sell":
            view = "strong_bear"
        elif rating == "Underweight":
            view = "mild_bear"
        else:
            view = "range"
        if any(k in text for k in ("range", "区间", "震荡", "rangebound")):
            view = "range"

    # volatility
    vol = decision.get("volatility")
    if not vol:
        if any(k in text for k in ("high vol", "高波动", "iv crush", "波动加大", "atr 抬升", "atr 上行")):
            vol = "high_vol"
        elif any(k in text for k in ("low vol", "低波动")):
            vol = "low_vol"
        else:
            vol = None

    # horizon
    horizon = decision.get("horizon")
    if not horizon:
        if any(k in text for k in ("intraday", "日内", "scalp")):
            horizon = "intraday"
        elif any(k in text for k in ("0dte", "short-term", "短线", "几天")):
            horizon = "short"
        elif any(k in text for k in ("swing", "波段", "周-月")):
            horizon = "swing"
        elif any(k in text for k in ("long-term", "长期", "buy and hold", "持有 1 年")):
            horizon = "long"
        else:
            horizon = "swing"

    return {"rating": rating, "view": view, "volatility": vol, "horizon": horizon}


# ---------- scoring ---------------------------------------------------------

def _user_risk_tolerance(params: Dict[str, Any]) -> int:
    val = params.get("risk_tolerance")
    try:
        n = int(val) if val is not None else 3
    except (TypeError, ValueError):
        n = 3
    return max(1, min(5, n))


def _user_instrument(params: Dict[str, Any]) -> str | None:
    inst = params.get("instrument_hint") or ""
    inst = inst.strip().lower()
    return inst or None


def _score(strategy: Dict[str, Any], parsed: Dict[str, Any], params: Dict[str, Any]) -> tuple[int, list[str]]:
    score = 0
    why: list[str] = []

    # view alignment (heaviest weight)
    if parsed.get("view") and parsed["view"] in (strategy.get("view") or []):
        score += 5
        why.append(f"匹配观点 ({parsed['view']})")

    # volatility
    vol = parsed.get("volatility")
    if vol == "high_vol" and "high_vol" in (strategy.get("view") or []):
        score += 3
        why.append("适合高波动环境")
    if vol == "low_vol" and "low_vol" in (strategy.get("view") or []):
        score += 3
        why.append("适合低波动环境")

    # horizon
    if parsed.get("horizon") and parsed["horizon"] in (strategy.get("horizon") or []):
        score += 3
        why.append(f"周期匹配 ({parsed['horizon']})")

    # instrument hint (e.g. user says "stock"/"crypto")
    inst_hint = _user_instrument(params)
    if inst_hint and inst_hint in (strategy.get("inst") or []):
        score += 2
        why.append(f"覆盖品种 {inst_hint}")

    # risk tolerance: penalise strategies whose risk exceeds tolerance
    tol = _user_risk_tolerance(params)
    srisk = strategy.get("risk", 3) or 3
    if srisk <= tol:
        score += 1
    else:
        score -= (srisk - tol)
        why.append(f"风险 {srisk} 高于偏好 {tol}（已降权）")

    # rating-driven bonuses: pair categories to ratings
    rating = parsed.get("rating", "Hold")
    cat = strategy.get("cat")
    if rating in ("Buy", "Overweight") and cat in ("entry", "directional"):
        score += 2
        why.append("买入评级 → 建仓/方向性")
    elif rating == "Hold" and cat in ("income", "hedge"):
        score += 2
        why.append("持有评级 → 收益增强 / 对冲")
    elif rating in ("Sell", "Underweight") and cat in ("hedge", "exit"):
        score += 2
        why.append("减/卖评级 → 对冲 / 退出")

    return score, why


# ---------- AI rerank --------------------------------------------------------

def _pick_ai_client():
    """Return (client, model_name) for the first available LLM provider, else None."""
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        return None
    for env_var, base_url, default_model in _AI_PROVIDERS:
        key = os.environ.get(env_var)
        if not key:
            continue
        try:
            client = OpenAI(api_key=key, base_url=base_url)
            model = os.environ.get("STRATEGY_RERANK_MODEL") or default_model
            return client, model
        except Exception as e:
            logger.warning("rerank: failed to init %s (%s)", env_var, e)
            continue
    return None


_RERANK_SYSTEM = (
    "你是一名严谨的衍生品/股票交易策略评估师。对于一个最终交易决策与若干候选库策略，"
    "你要：(1) 给每个候选打 0-100 的匹配分（综合考虑观点对齐、品种适配、波动环境、"
    "风险偏好、可执行性）；(2) 写一句中文理由（≤40 字）；(3) 基于当前标的与决策中提到的"
    "具体价位 / 信心 / 周期，写出**针对该标的的具体操作步骤**（1-3 句中文，含价格、仓位、"
    "止损位等可量化的参数；不要用通用模板，不要用其它公司作为占位符）；(4) 给出一组"
    "**具体参数列表**（key/value 二元对，如 [\"建仓价\", \"$X\"]、[\"止损\", \"$Y\"]、"
    "[\"目标\", \"$Z\"]、[\"仓位\", \"组合的 N%\"]），所有数字必须来自决策上下文，没有则写"
    "「视决策细节而定」并保留 key。"
    "\n\n严格输出 JSON：{\"items\":[{\"id\":\"...\",\"score\":N,\"reason\":\"...\","
    "\"concrete_how\":\"...\",\"concrete_params\":[[\"建仓价\",\"...\"],...]}]}，"
    "顺序与输入相同，不要 markdown 围栏。"
)


def _ai_rerank(items: List[Dict[str, Any]], decision: Dict[str, Any], params: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """Ask an LLM to re-score (0-100) and tailor the top-K candidates to the
    real decision context. Returns enriched items or None on any failure
    (caller falls back to the heuristic scores).
    """
    if not items:
        return items
    picked = _pick_ai_client()
    if not picked:
        return None
    client, model = picked

    ticker = (params.get("ticker") or decision.get("ticker") or "").strip()
    payload = {
        "ticker": ticker or "未知",
        "trade_date": params.get("trade_date") or "",
        "instrument_hint": params.get("instrument_hint") or "未指定",
        "risk_tolerance": params.get("risk_tolerance") or 3,
        "decision": {
            "rating": decision.get("rating"),
            "view": decision.get("view"),
            "horizon": decision.get("horizon"),
            "raw": (decision.get("raw") or "")[:4000],   # cap to keep prompt small
            "trader_plan": (decision.get("trader_plan") or "")[:1500],
        },
        "candidates": [
            {
                "id": it.get("id"),
                "name": it.get("name"),
                "cat": it.get("cat"),
                "risk": it.get("risk"),
                "desc": it.get("desc") or "",
                "how": it.get("how") or "",
                "params": it.get("params") or [],
                "example": it.get("example") or "",
            }
            for it in items
        ],
    }

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _RERANK_SYSTEM},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.3,
            max_tokens=3500,
            timeout=45,
        )
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("rerank LLM call failed: %s", e)
        return None

    # Strip ```json fences if present
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", raw).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("rerank: bad JSON (%s); first 200 chars: %s", e, raw[:200])
        return None

    by_id = {x.get("id"): x for x in (data.get("items") or []) if isinstance(x, dict)}
    enriched: List[Dict[str, Any]] = []
    for it in items:
        ai = by_id.get(it.get("id")) or {}
        new_score = ai.get("score")
        try:
            new_score = max(0, min(100, int(new_score))) if new_score is not None else None
        except (TypeError, ValueError):
            new_score = None
        if new_score is None:
            new_score = max(0, min(100, int(round(it.get("score", 0) * 6))))  # scale 0-16 → 0-96
        out = dict(it)
        out["score"] = new_score
        if ai.get("reason"):
            out["reasons"] = [ai["reason"]] + (it.get("reasons") or [])
        if ai.get("concrete_how"):
            out["concrete_how"] = ai["concrete_how"]
        cp = ai.get("concrete_params")
        if isinstance(cp, list) and cp:
            out["concrete_params"] = [list(p)[:2] for p in cp if isinstance(p, (list, tuple)) and len(p) >= 2]
        enriched.append(out)
    enriched.sort(key=lambda x: (-x["score"], x.get("complexity", 3)))
    return enriched


# ---------- public entry ----------------------------------------------------

def match_strategies(decision: Dict[str, Any], params: Dict[str, Any], top_k: int = 5) -> Dict[str, Any]:
    """Return ranked library matches for the given decision.

    Two-stage: heuristic pre-filter → AI rerank with concrete operation plans.
    The AI step uses any OpenAI-compat provider key present in env (DeepSeek
    preferred for cost); if none / call fails, we fall back to the heuristic
    score scaled into 0-100 so the UI is consistent.
    """
    library = _load_strategies()
    parsed = _parse_decision(decision)
    if not library:
        return {"parsed": parsed, "items": [], "warning": "strategy library not loaded"}

    scored = []
    for s in library:
        sc, why = _score(s, parsed, params)
        if sc <= 0:
            continue
        scored.append({
            "id": s.get("id"),
            "name": s.get("name"),
            "en": s.get("en"),
            "cat": s.get("cat"),
            "complexity": s.get("complexity"),
            "risk": s.get("risk"),
            "desc": s.get("desc"),
            "when": s.get("when"),
            "how": s.get("how"),
            "params": s.get("params"),
            "pros": s.get("pros"),
            "cons": s.get("cons"),
            "example": s.get("example"),
            "score": sc,
            "reasons": why,
        })
    scored.sort(key=lambda x: (-x["score"], x.get("complexity", 3)))
    pre_filter = scored[: max(top_k * 2, 8)]   # widen the pool for AI to choose from

    # AI rerank: rescores 0-100 + adds concrete_how / concrete_params
    rerank_disabled = os.environ.get("STRATEGY_RERANK", "1").lower() in ("0", "false", "off")
    enriched = None if rerank_disabled else _ai_rerank(pre_filter, decision, params)
    items = enriched if enriched is not None else [
        # Fallback: scale heuristic score into the same 0-100 range
        {**it, "score": max(0, min(100, int(round(it.get("score", 0) * 6))))}
        for it in pre_filter
    ]
    return {"parsed": parsed, "items": items[:top_k]}


if __name__ == "__main__":
    # quick sanity check
    sample = {
        "rating": "Buy", "view": "mild_bull", "volatility": "high_vol",
        "horizon": "swing",
        "raw": "Rating: Buy. Trend confirmed, ATR rising, sentiment greedy."
    }
    out = match_strategies(sample, {"instrument_hint": "stock", "risk_tolerance": 3})
    print(json.dumps(out, ensure_ascii=False, indent=2)[:1500])
