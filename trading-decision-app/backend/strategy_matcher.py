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
import re
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

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


# ---------- public entry ----------------------------------------------------

def match_strategies(decision: Dict[str, Any], params: Dict[str, Any], top_k: int = 5) -> Dict[str, Any]:
    """Return ranked library matches for the given decision.

    Returns a dict so the front-end can also pretty-print the parsed signals:
        {
          "parsed": {...},
          "items": [
              {"id": "...", "score": 11, "reasons": [...], "strategy": {...}},
              ...
          ]
        }
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
    return {"parsed": parsed, "items": scored[:top_k]}


if __name__ == "__main__":
    # quick sanity check
    sample = {
        "rating": "Buy", "view": "mild_bull", "volatility": "high_vol",
        "horizon": "swing",
        "raw": "Rating: Buy. Trend confirmed, ATR rising, sentiment greedy."
    }
    out = match_strategies(sample, {"instrument_hint": "stock", "risk_tolerance": 3})
    print(json.dumps(out, ensure_ascii=False, indent=2)[:1500])
