#!/usr/bin/env bash
# Start the backend in dev mode.
# - Loads .env automatically (via python-dotenv inside server.py)
# - Auto-reload on code change
# - Default port 8000, override with PORT=...
#
# Usage:
#   ./scripts/dev.sh                  # port 8000
#   PORT=8765 ./scripts/dev.sh        # custom port

set -eu

cd "$(dirname "$0")/.."   # → repo root

PORT="${PORT:-8000}"

# Make TradingAgents importable
export PYTHONPATH="$(pwd)/TradingAgents:$(pwd)/trading-decision-app/backend:${PYTHONPATH:-}"

cd trading-decision-app/backend

echo "════════════════════════════════════════════════════════"
echo "  TradingForge dev server"
echo "  Backend:   http://localhost:${PORT}"
echo "  Health:    http://localhost:${PORT}/health"
echo "  Docs:      docs/DEVELOPMENT.md"
echo "════════════════════════════════════════════════════════"
echo

# --reload watches both the backend dir and the TradingAgents subtree.
# Static files are served by FastAPI directly — no rebuild step needed.
exec python -m uvicorn server:app \
    --host 0.0.0.0 --port "$PORT" \
    --reload \
    --reload-dir ../../TradingAgents/tradingagents \
    --reload-dir . \
    --log-level info
