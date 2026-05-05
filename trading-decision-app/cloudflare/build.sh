#!/usr/bin/env bash
# Cloudflare Pages build script.
# - Copies static/ → dist/
# - Generates dist/runtime-config.js from build-time env vars
# - Adds dist/_redirects so /api/* hits your backend host
#
# In Cloudflare Pages dashboard set:
#   Build command:        bash trading-decision-app/cloudflare/build.sh
#   Build output dir:     trading-decision-app/dist
#   Environment variables (Production):
#     PUBLIC_API_BASE_URL=https://your-backend.fly.dev
#     SUPABASE_URL=https://xxxxx.supabase.co
#     SUPABASE_ANON_KEY=eyJhbGc...

set -eu

cd "$(dirname "$0")/.."     # → trading-decision-app/

DIST="dist"
mkdir -p "$DIST"
cp -r static/* "$DIST/"

# ---- runtime-config.js (replaces FastAPI's dynamic version) -----------------
SUPABASE_URL_VAL="${SUPABASE_URL:-}"
SUPABASE_ANON_KEY_VAL="${SUPABASE_ANON_KEY:-}"
API_BASE_URL_VAL="${PUBLIC_API_BASE_URL:-}"
AUTH_REQ="${AUTH_REQUIRED:-false}"

cat > "$DIST/runtime-config.js" <<EOF
window.APP_CONFIG = {
  "SUPABASE_URL":     "${SUPABASE_URL_VAL}",
  "SUPABASE_ANON_KEY":"${SUPABASE_ANON_KEY_VAL}",
  "API_BASE_URL":     "${API_BASE_URL_VAL}",
  "AUTH_REQUIRED":    ${AUTH_REQ}
};
EOF

# Patch the index.html to load the static config (instead of /api/runtime-config.js)
sed -i.bak 's|/api/runtime-config.js|/runtime-config.js|g' "$DIST/index.html" && rm "$DIST/index.html.bak"

# ---- _redirects: proxy /api/* to backend, SPA fallback ----------------------
if [ -n "$API_BASE_URL_VAL" ]; then
cat > "$DIST/_redirects" <<EOF
# Proxy API + SSE traffic to backend
/api/*  ${API_BASE_URL_VAL}/api/:splat  200
EOF
else
  echo "WARN: PUBLIC_API_BASE_URL not set — frontend will hit /api on its own origin (won't work)" >&2
fi

# ---- security headers -------------------------------------------------------
cat > "$DIST/_headers" <<'EOF'
/*
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: geolocation=(), microphone=(), camera=()
EOF

echo "build done. files in $DIST/:"
ls -la "$DIST"
