#!/usr/bin/env bash
# Pull latest TradingAgents from upstream and re-apply our patch series.
#
# Workflow:
#   1. fetch upstream
#   2. show what changed
#   3. git subtree pull --squash
#   4. patches/apply-patches.sh --check  (does anything conflict?)
#   5. patches/apply-patches.sh          (apply for real)
#   6. smoke-test the reapplied code
#
# Aborts if any patch conflicts; you'll need to manually re-edit and
# regenerate that patch (instructions printed at the end).

set -eu

cd "$(dirname "$0")/.."

REMOTE="tradingagents-upstream"
BRANCH="${UPSTREAM_BRANCH:-main}"

echo "════════════════════════════════════════════════════════"
echo "  TradingAgents 上游同步"
echo "════════════════════════════════════════════════════════"

# ---- 0) Sanity --------------------------------------------------------
if ! git remote | grep -q "^${REMOTE}$"; then
    echo "✗ Remote '${REMOTE}' not configured. Add it first:"
    echo "    git remote add ${REMOTE} https://github.com/TauricResearch/TradingAgents.git"
    exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "✗ Working tree has uncommitted changes. Commit or stash first."
    git status --short
    exit 1
fi

# ---- 1) Fetch + preview -----------------------------------------------
echo "▶ Fetching upstream …"
git fetch "$REMOTE" "$BRANCH"
echo

CURRENT_HEAD=$(git rev-parse HEAD)
UPSTREAM_HEAD=$(git rev-parse "${REMOTE}/${BRANCH}")
echo "▶ Upstream HEAD: $UPSTREAM_HEAD"
echo "▶ Current HEAD:  $CURRENT_HEAD"
echo

echo "▶ Commits on upstream not yet integrated:"
git log --oneline "${CURRENT_HEAD}..${UPSTREAM_HEAD}" -- 2>/dev/null | head -20 || true
echo

read -r -p "▶ Proceed with subtree pull? [y/N] " ok
[ "${ok:-}" = "y" ] || { echo "aborted."; exit 0; }

# ---- 2) Subtree pull --------------------------------------------------
echo
echo "▶ git subtree pull --prefix=TradingAgents ${REMOTE} ${BRANCH} --squash"
git subtree pull --prefix=TradingAgents "$REMOTE" "$BRANCH" --squash
echo

# ---- 3) Patch check ---------------------------------------------------
echo "▶ Checking if existing patches still apply…"
if bash patches/apply-patches.sh --check; then
    echo "  ✓ All patches apply cleanly"
else
    echo
    echo "✗ One or more patches conflict with new upstream."
    echo
    echo "  Manual fix:"
    echo "    1. Identify which patch failed (see output above)"
    echo "    2. Re-create the edit by hand against the new upstream files:"
    echo "         \$EDITOR TradingAgents/tradingagents/<file>"
    echo "    3. Regenerate the patch:"
    echo "         git diff TradingAgents/... > patches/0001-...patch"
    echo "    4. Re-run this script"
    exit 1
fi
echo

# ---- 4) Apply ---------------------------------------------------------
echo "▶ Re-applying our patch series …"
bash patches/apply-patches.sh
echo

# ---- 5) Smoke test ----------------------------------------------------
echo "▶ Smoke test: import server + check vendor wiring …"
export PYTHONPATH="$(pwd)/TradingAgents:$(pwd)/trading-decision-app/backend:${PYTHONPATH:-}"
cd trading-decision-app/backend
python - <<'PY' || { echo "✗ Smoke test failed"; exit 1; }
import sys
try:
    import server
    from tradingagents.dataflows import premium_bridge
    from tradingagents.llm_clients.factory import _OPENAI_COMPATIBLE
    assert "kimi" in _OPENAI_COMPATIBLE, "Kimi missing from _OPENAI_COMPATIBLE"
    assert len(premium_bridge._METHOD_BINDINGS) >= 9, "premium_bridge bindings missing"
    print("  ✓ server imports clean")
    print("  ✓ Kimi natively registered")
    print(f"  ✓ premium_bridge has {len(premium_bridge._METHOD_BINDINGS)} method bindings")
except Exception as e:
    print(f"  ✗ Smoke test failed: {e}")
    sys.exit(1)
PY
cd ../..
echo

# ---- 6) Done ----------------------------------------------------------
echo "════════════════════════════════════════════════════════"
echo "  ✓ Upgrade complete. Commit when ready:"
echo "      git add -A"
echo "      git commit -m 'chore: bump TradingAgents subtree'"
echo "════════════════════════════════════════════════════════"
