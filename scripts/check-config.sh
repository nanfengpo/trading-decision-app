#!/usr/bin/env bash
# Diagnostic: show what's configured (without leaking secrets).
# Prints ✓/✗ for each LLM provider, premium data source, and Supabase.

set -eu

cd "$(dirname "$0")/.."

ENV_FILE="trading-decision-app/.env"
if [ -f "$ENV_FILE" ]; then
    set -a; . "$ENV_FILE"; set +a
fi

green() { printf '\033[32m%s\033[0m\n' "$*"; }
red()   { printf '\033[31m%s\033[0m\n' "$*"; }
gray()  { printf '\033[90m%s\033[0m\n' "$*"; }

check() {
    local name="$1" var="$2"
    local val="${!var:-}"
    if [ -n "$val" ]; then
        green "  ✓ $name  ($var = ${val:0:6}…)"
    else
        red   "  ✗ $name  ($var unset)"
    fi
}

echo "── LLM providers ────────────────────────────────────"
check "OpenAI"          OPENAI_API_KEY
check "Anthropic"       ANTHROPIC_API_KEY
check "Google Gemini"   GOOGLE_API_KEY
check "DeepSeek"        DEEPSEEK_API_KEY
check "Qwen"            DASHSCOPE_API_KEY
check "Kimi (Moonshot)" MOONSHOT_API_KEY
check "智谱 GLM"        ZHIPU_API_KEY
echo

echo "── Premium data sources ─────────────────────────────"
check "Finnhub Pro"      FINNHUB_API_KEY
check "Polygon.io"       POLYGON_API_KEY
check "Alpha Vantage"    ALPHA_VANTAGE_API_KEY
check "FMP Premium"      FMP_API_KEY
check "Nasdaq Data Link" NASDAQ_DATA_LINK_API_KEY
echo

echo "── Supabase (multi-user mode) ───────────────────────"
check "Project URL"      SUPABASE_URL
check "anon key"         SUPABASE_ANON_KEY
check "JWT secret"       SUPABASE_JWT_SECRET
echo

echo "── Optional ─────────────────────────────────────────"
check "CORS origins"     CORS_ORIGINS
check "Public API base"  PUBLIC_API_BASE_URL
check "Translation pin"  TRANSLATION_PROVIDER
echo

# Summary
have_any_llm=0
for v in OPENAI_API_KEY ANTHROPIC_API_KEY GOOGLE_API_KEY DEEPSEEK_API_KEY DASHSCOPE_API_KEY MOONSHOT_API_KEY ZHIPU_API_KEY; do
    [ -n "${!v:-}" ] && have_any_llm=1
done

if [ "$have_any_llm" -eq 0 ]; then
    gray "Mode: DEMO (no LLM keys configured — that's fine for UI exploration)"
elif [ -z "${SUPABASE_URL:-}" ]; then
    gray "Mode: LIVE single-tenant (using .env keys for everyone)"
else
    gray "Mode: LIVE multi-tenant (per-user keys via Supabase profile)"
fi
