#!/usr/bin/env bash
# Deploy the trading-forge backend to Fly.io.
#
# Idempotent — re-run any time. Guards against common mistakes.
#
# Usage:
#   1. Edit the SECRETS_*. placeholders below (or set them as env vars
#      before invoking this script).
#   2. ./scripts/deploy-fly.sh
#   3. (Optional) ./scripts/deploy-fly.sh --redeploy  # skip launch, just push code
#
# What it does:
#   1. Verifies flyctl is installed and you're logged in
#   2. Verifies fly.toml has the right app name
#   3. Creates the app via `fly launch --no-deploy` (skipped if it already exists)
#   4. Sets / updates all secrets in one batch (idempotent)
#   5. Pushes the build via `fly deploy`
#   6. Hits /health to confirm the deploy worked

set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────
# Configuration — edit these or override via environment variables
# ─────────────────────────────────────────────────────────────────────────
APP_NAME="${FLY_APP_NAME:-trading-forge}"
REGION="${FLY_REGION:-sjc}"        # San Jose. Run `fly platform regions` for the full list.

# Cloudflare Pages URL — set after creating the project on CF Pages, or leave
# the default (``<APP_NAME>.pages.dev``) and update later via fly secrets set.
PAGES_DOMAIN="${PAGES_DOMAIN:-${APP_NAME}.pages.dev}"

# All values can be exported in your shell so they don't end up in this file:
#   export OPENAI_API_KEY=sk-...
#   export SUPABASE_URL=https://xxxxx.supabase.co
#   export SUPABASE_ANON_KEY=eyJ...
#   export SUPABASE_JWT_SECRET=...
#   ./scripts/deploy-fly.sh
SECRETS_OPENAI_API_KEY="${OPENAI_API_KEY:-}"
SECRETS_ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
SECRETS_GOOGLE_API_KEY="${GOOGLE_API_KEY:-}"
SECRETS_DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}"
SECRETS_DASHSCOPE_API_KEY="${DASHSCOPE_API_KEY:-}"
SECRETS_MOONSHOT_API_KEY="${MOONSHOT_API_KEY:-}"
SECRETS_ZHIPU_API_KEY="${ZHIPU_API_KEY:-}"
SECRETS_FINNHUB_API_KEY="${FINNHUB_API_KEY:-}"
SECRETS_POLYGON_API_KEY="${POLYGON_API_KEY:-}"
SECRETS_ALPHA_VANTAGE_API_KEY="${ALPHA_VANTAGE_API_KEY:-}"
SECRETS_FMP_API_KEY="${FMP_API_KEY:-}"
SECRETS_SUPABASE_URL="${SUPABASE_URL:-}"
SECRETS_SUPABASE_ANON_KEY="${SUPABASE_ANON_KEY:-}"
SECRETS_SUPABASE_JWT_SECRET="${SUPABASE_JWT_SECRET:-}"

REDEPLOY=0
for arg in "$@"; do
    case "$arg" in
        --redeploy) REDEPLOY=1 ;;
        -h|--help)
            sed -n '2,12p' "$0" | sed 's/^# \?//'
            exit 0 ;;
        *)  echo "unknown flag: $arg" >&2; exit 2 ;;
    esac
done

cd "$(dirname "$0")/.."   # → repo root

# ─────────────────────────────────────────────────────────────────────────
# 1) Sanity checks
# ─────────────────────────────────────────────────────────────────────────
echo "▶ checking prerequisites..."
command -v fly >/dev/null 2>&1 || {
    echo "✗ flyctl not installed. Run:"
    echo "    brew install flyctl   (macOS)"
    echo "    curl -L https://fly.io/install.sh | sh   (Linux)"
    exit 1
}
fly auth whoami >/dev/null 2>&1 || {
    echo "✗ not logged in. Run: fly auth login"
    exit 1
}

[ -f trading-decision-app/fly.toml ]         || { echo "✗ trading-decision-app/fly.toml missing — run from repo root"; exit 1; }
[ -f trading-decision-app/Dockerfile ]       || { echo "✗ trading-decision-app/Dockerfile missing"; exit 1; }

echo "  ✓ flyctl ready, app=$APP_NAME, region=$REGION"

# Verify region is valid (most common error).
# `fly platform regions` prints a table with box-drawing │ separators;
# the region CODE is in the rightmost column.
if ! fly platform regions 2>/dev/null \
        | awk -F'│' 'NF>=2 {gsub(/[ \t]+/, "", $NF); if ($NF != "" && $NF != "CODE") print $NF}' \
        | grep -qx "$REGION"; then
    echo "✗ region '$REGION' not in fly's region list."
    echo "  Run: fly platform regions"
    exit 1
fi

# ─────────────────────────────────────────────────────────────────────────
# 2) Make sure fly.toml has app=$APP_NAME (otherwise fly launch will balk)
# ─────────────────────────────────────────────────────────────────────────
if ! grep -q "^app = \"$APP_NAME\"" trading-decision-app/fly.toml; then
    echo "▶ updating fly.toml app name → $APP_NAME"
    sed -i.bak "s|^app = \".*\"|app = \"$APP_NAME\"|" trading-decision-app/fly.toml
    rm -f trading-decision-app/fly.toml.bak
fi

# ─────────────────────────────────────────────────────────────────────────
# 3) Create the app on Fly (no-op if it already exists)
# ─────────────────────────────────────────────────────────────────────────
if [ "$REDEPLOY" -eq 0 ]; then
    if fly status -a "$APP_NAME" >/dev/null 2>&1; then
        echo "▶ app '$APP_NAME' already exists — skipping launch"
    else
        echo "▶ creating Fly app '$APP_NAME' in region '$REGION'..."
        fly launch \
            --no-deploy \
            --copy-config \
            --config trading-decision-app/fly.toml \
            --dockerfile trading-decision-app/Dockerfile \
            --name "$APP_NAME" \
            --region "$REGION" \
            --yes
    fi
fi

# ─────────────────────────────────────────────────────────────────────────
# 4) Set secrets (only the ones with non-empty values)
# ─────────────────────────────────────────────────────────────────────────
echo "▶ setting secrets..."
SECRETS_ARGS=()

add_secret() {
    local name="$1" value="$2"
    if [ -n "$value" ]; then
        SECRETS_ARGS+=("$name=$value")
    fi
}

add_secret OPENAI_API_KEY        "$SECRETS_OPENAI_API_KEY"
add_secret ANTHROPIC_API_KEY     "$SECRETS_ANTHROPIC_API_KEY"
add_secret GOOGLE_API_KEY        "$SECRETS_GOOGLE_API_KEY"
add_secret DEEPSEEK_API_KEY      "$SECRETS_DEEPSEEK_API_KEY"
add_secret DASHSCOPE_API_KEY     "$SECRETS_DASHSCOPE_API_KEY"
add_secret MOONSHOT_API_KEY      "$SECRETS_MOONSHOT_API_KEY"
add_secret ZHIPU_API_KEY         "$SECRETS_ZHIPU_API_KEY"
add_secret FINNHUB_API_KEY       "$SECRETS_FINNHUB_API_KEY"
add_secret POLYGON_API_KEY       "$SECRETS_POLYGON_API_KEY"
add_secret ALPHA_VANTAGE_API_KEY "$SECRETS_ALPHA_VANTAGE_API_KEY"
add_secret FMP_API_KEY           "$SECRETS_FMP_API_KEY"
add_secret SUPABASE_URL          "$SECRETS_SUPABASE_URL"
add_secret SUPABASE_ANON_KEY     "$SECRETS_SUPABASE_ANON_KEY"
add_secret SUPABASE_JWT_SECRET   "$SECRETS_SUPABASE_JWT_SECRET"

# CORS_ORIGINS is intentionally NOT auto-set on every redeploy — once you
# bind a custom domain (or have multi-origin dev/preview/prod), letting
# the script clobber it back to "<app>.pages.dev" silently breaks CORS.
# Set it on first launch (--first-time) or pass CORS_ORIGINS explicitly.
if [ "$REDEPLOY" -eq 0 ] || [ -n "${CORS_ORIGINS:-}" ]; then
    cors_value="${CORS_ORIGINS:-https://${PAGES_DOMAIN}}"
    add_secret CORS_ORIGINS "$cors_value"
fi
add_secret PUBLIC_API_BASE_URL   "https://${APP_NAME}.fly.dev"

if [ "${#SECRETS_ARGS[@]}" -eq 0 ]; then
    echo "  ⚠ no secrets to set — make sure you exported at least one *_API_KEY"
    echo "    and the SUPABASE_* trio before running this script."
else
    fly secrets set -a "$APP_NAME" "${SECRETS_ARGS[@]}"
    echo "  ✓ ${#SECRETS_ARGS[@]} secret(s) configured"
fi

# Show what's set (without leaking values — fly only shows hashes)
echo "▶ current secrets:"
fly secrets list -a "$APP_NAME"

# ─────────────────────────────────────────────────────────────────────────
# 5) Deploy
# ─────────────────────────────────────────────────────────────────────────
echo "▶ deploying (build + push, ~3-5 min for first run)..."
fly deploy \
    --config trading-decision-app/fly.toml \
    --dockerfile trading-decision-app/Dockerfile \
    --remote-only \
    -a "$APP_NAME"

# ─────────────────────────────────────────────────────────────────────────
# 6) Health check
# ─────────────────────────────────────────────────────────────────────────
APP_URL="https://${APP_NAME}.fly.dev"
echo "▶ health check: ${APP_URL}/health"
sleep 3
if curl -sSf "${APP_URL}/health" >/dev/null 2>&1; then
    echo "  ✓ healthy"
else
    echo "  ⚠ /health didn't respond. Check logs:"
    echo "    fly logs -a $APP_NAME"
fi

echo
echo "════════════════════════════════════════════════════════"
echo "  ✓ Backend deployed to ${APP_URL}"
echo "════════════════════════════════════════════════════════"
echo "Next: deploy the frontend on Cloudflare Pages."
echo "  See docs/DEPLOYMENT.md § 4."
echo
echo "Useful follow-ups:"
echo "  fly logs -a $APP_NAME              # tail logs"
echo "  fly status -a $APP_NAME            # vm status"
echo "  fly ssh console -a $APP_NAME       # shell in the running container"
echo "  fly secrets set OPENAI_API_KEY=... # rotate a key (auto-redeploys)"
