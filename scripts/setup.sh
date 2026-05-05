#!/usr/bin/env bash
# First-time setup: install deps + generate .env stub + check what's needed.
#
# Idempotent — re-run any time. Won't overwrite an existing .env.

set -eu

cd "$(dirname "$0")/.."   # → repo root

echo "════════════════════════════════════════════════════════"
echo "  TradingForge · 首次安装"
echo "════════════════════════════════════════════════════════"
echo

# ---- 1) Python deps -----------------------------------------------------
echo "▶ Installing Python deps for backend …"
pip install -q -r trading-decision-app/requirements.txt
echo "  ✓ trading-decision-app/requirements.txt"

if [ -f TradingAgents/requirements.txt ]; then
    echo "▶ Installing TradingAgents deps (LIVE mode) …"
    pip install -q -r TradingAgents/requirements.txt && \
      echo "  ✓ TradingAgents/requirements.txt" || \
      echo "  ⚠ Failed; LIVE mode won't work but DEMO will. Check the error above."
fi
echo

# ---- 2) .env stub -------------------------------------------------------
ENV_FILE="trading-decision-app/.env"
if [ ! -f "$ENV_FILE" ]; then
    cp trading-decision-app/.env.example "$ENV_FILE"
    echo "▶ Created $ENV_FILE from template."
    echo "  ⚠ EDIT IT and add at least one *_API_KEY (or skip and use DEMO mode)."
    echo
else
    echo "▶ $ENV_FILE already exists — keeping it."
    echo
fi

# ---- 3) Show what's configured -----------------------------------------
echo "▶ Current configuration:"
bash scripts/check-config.sh || true
echo

# ---- 4) Next steps ------------------------------------------------------
echo "════════════════════════════════════════════════════════"
echo "  Next:"
echo "    1. Edit $ENV_FILE if you want LIVE LLM calls"
echo "    2. ./scripts/dev.sh                   # local server"
echo "    3. Open http://localhost:8000"
echo "    4. For production deploy: docs/DEPLOYMENT.md"
echo "════════════════════════════════════════════════════════"
