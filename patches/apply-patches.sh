#!/usr/bin/env bash
# Re-apply the local TradingAgents patches after a `git subtree pull`.
#
# Usage:
#   bash patches/apply-patches.sh                # apply all
#   bash patches/apply-patches.sh --check        # verify without applying
#   bash patches/apply-patches.sh --reverse      # un-apply (revert to upstream)
#
# Each patch is a `git diff` of TradingAgents/ files; they are independent
# and can be applied in any order, but we keep numeric prefix for audit.

set -euo pipefail

cd "$(dirname "$0")/.."   # → repo root
PATCH_DIR="patches"

CHECK=0; REVERSE=0
for arg in "$@"; do
  case "$arg" in
    --check)   CHECK=1 ;;
    --reverse) REVERSE=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

flags=""
[ $CHECK -eq 1 ] && flags="--check"
[ $REVERSE -eq 1 ] && flags="$flags --reverse"

shopt -s nullglob
patches=( "$PATCH_DIR"/*.patch )
if [ ${#patches[@]} -eq 0 ]; then
  echo "no patches found in $PATCH_DIR/"; exit 0
fi

[ $REVERSE -eq 1 ] && patches=( $(printf '%s\n' "${patches[@]}" | sort -r) ) || \
                      patches=( $(printf '%s\n' "${patches[@]}" | sort) )

failed=0
for p in "${patches[@]}"; do
  echo "→ $p"
  if git apply $flags "$p"; then
    echo "  OK"
  else
    echo "  FAILED"
    failed=$((failed+1))
    [ $CHECK -eq 0 ] && exit 1
  fi
done

if [ $CHECK -eq 1 ] && [ $failed -gt 0 ]; then
  echo
  echo "$failed patch(es) won't apply — likely upstream changed the same lines."
  echo "Resolve manually: re-edit the source, regenerate patches with"
  echo "  git diff TradingAgents/... > patches/0003-...patch"
  exit 1
fi

echo
[ $REVERSE -eq 1 ] && echo "All patches reversed." || echo "All patches applied."
