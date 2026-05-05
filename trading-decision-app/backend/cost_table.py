"""LLM pricing table + cost-estimation helpers.

The price table maps `(provider, model_pattern)` to a `(input_per_1m,
output_per_1m)` pair denominated in USD. `model_pattern` is matched
case-insensitively against the model id with `.startswith()`, and the
longest matching prefix wins (so a request for `gpt-5.5-pro` matches the
`gpt-5.5-pro` row instead of the more generic `gpt-5.5` row).

These numbers reflect publicly announced list prices as of late 2026 and
are intended as a reasonable estimate, not an authoritative bill. Caller
code should treat the result as informational; vendor dashboards remain
the source of truth for actual spend.
"""

from __future__ import annotations

# (provider, model_pattern) -> (input_per_1m, output_per_1m)  in USD
# model_pattern is matched by .startswith() on the model id.
PRICE_TABLE: dict[tuple[str, str], tuple[float, float]] = {
    # OpenAI
    ("openai", "gpt-5.5-pro"):   (30.0, 180.0),
    ("openai", "gpt-5.5"):       (15.0,  60.0),
    ("openai", "gpt-5.5-mini"):  (0.50,   4.0),
    ("openai", "gpt-5.5-nano"):  (0.10,   0.40),
    ("openai", "gpt-5.4-pro"):   (30.0, 180.0),
    ("openai", "gpt-5.4"):       (12.0,  48.0),
    ("openai", "gpt-5.4-mini"):  (0.40,   3.20),
    ("openai", "gpt-4.1"):       (3.00,  12.00),

    # Anthropic
    ("anthropic", "claude-opus-4-7"):   (15.0, 75.0),
    ("anthropic", "claude-opus-4-6"):   (15.0, 75.0),
    ("anthropic", "claude-sonnet-4-7"): (3.0,  15.0),
    ("anthropic", "claude-sonnet-4-6"): (3.0,  15.0),
    ("anthropic", "claude-haiku-4-6"):  (0.25,  1.25),
    ("anthropic", "claude-haiku-4-5"):  (0.25,  1.25),

    # Google Gemini
    ("google", "gemini-3.5-pro"):        (5.0,  20.0),
    ("google", "gemini-3.5-flash"):      (0.10,  0.40),
    ("google", "gemini-3.5-flash-lite"): (0.05,  0.20),
    ("google", "gemini-3.1-pro"):        (3.5,  14.0),
    ("google", "gemini-3-flash"):        (0.10,  0.40),

    # DeepSeek (peak prices; off-peak is ~50% lower)
    ("deepseek", "deepseek-v4-pro-max"): (1.20, 4.50),
    ("deepseek", "deepseek-v4-pro"):     (0.55, 2.20),
    ("deepseek", "deepseek-v4-flash"):   (0.10, 0.40),
    ("deepseek", "deepseek-reasoner"):   (0.55, 2.20),
    ("deepseek", "deepseek-chat"):       (0.27, 1.10),

    # Qwen
    ("qwen", "qwen3.6-max"):    (2.4, 9.6),
    ("qwen", "qwen3.6-plus"):   (0.8, 3.2),
    ("qwen", "qwen3.6-flash"):  (0.1, 0.4),

    # Kimi
    ("kimi", "kimi-k2.6"): (0.6, 2.4),

    # GLM
    ("glm", "glm-5"): (0.5, 1.5),
}


def lookup_price(provider: str, model: str) -> tuple[float, float] | None:
    """Return ``(input_per_1m_usd, output_per_1m_usd)`` for the given
    provider+model pair, or ``None`` if the model is not in the table.

    Matching is case-insensitive and uses longest-prefix-wins semantics:
    ``gpt-5.5-pro`` matches the ``gpt-5.5-pro`` row instead of the
    shorter ``gpt-5.5`` row.
    """
    p = (provider or "").lower()
    m = (model or "").lower()
    candidates = [
        (mp, prices)
        for (pp, mp), prices in PRICE_TABLE.items()
        if pp == p and m.startswith(mp.lower())
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda x: -len(x[0]))  # longest match wins
    return candidates[0][1]


def estimate_cost(
    provider: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
) -> float | None:
    """Estimate the USD cost of a single LLM call.

    Returns ``None`` when the model is not in :data:`PRICE_TABLE`, so
    callers can distinguish "free / unknown" from a genuine zero cost.
    """
    price = lookup_price(provider, model)
    if not price:
        return None
    return (tokens_in / 1_000_000) * price[0] + (tokens_out / 1_000_000) * price[1]
