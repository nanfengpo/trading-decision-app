"""
Trading Decision Web App - FastAPI server.

Serves the static front-end and exposes a Server-Sent-Events endpoint that
streams TradingAgents progress in real time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import AsyncGenerator, Dict, Any, Optional

from fastapi import FastAPI, Request, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Make the sibling TradingAgents package importable.
ROOT = Path(__file__).resolve().parent.parent.parent
TRADING_AGENTS_DIR = ROOT / "TradingAgents"
if TRADING_AGENTS_DIR.exists() and str(TRADING_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(TRADING_AGENTS_DIR))

# Load .env (project root, then app folder, then cwd) so OPENAI_API_KEY,
# DEEPSEEK_API_KEY, default model overrides, etc. are picked up before any
# downstream module imports.
try:
    from dotenv import load_dotenv  # type: ignore
    for env_path in (
        ROOT / ".env",
        ROOT / "trading-decision-app" / ".env",
        Path.cwd() / ".env",
    ):
        if env_path.exists():
            load_dotenv(env_path, override=False)
except ImportError:  # python-dotenv missing — fall back to OS env
    pass

# Local imports.
sys.path.insert(0, str(Path(__file__).parent))
from agent_runner import AgentRunner, AnalysisRequest  # noqa: E402
from strategy_matcher import match_strategies  # noqa: E402
from model_catalog import serialize as serialize_catalog, PROVIDER_KEY_ENV  # noqa: E402
from dataflows.factory import list_categories as dataflows_list  # noqa: E402
from opportunities import get_feed, start_scanner, stop_scanner  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("trading-decision-app")

STATIC_DIR = ROOT / "trading-decision-app" / "static"

app = FastAPI(title="Trading Decision App", version="2.0.0")

# CORS — comma-separated list in CORS_ORIGINS, default "*" for dev.
# In prod set CORS_ORIGINS to your Cloudflare Pages origin, e.g.
#   CORS_ORIGINS=https://trading-decision.pages.dev,https://yourdomain.com
_cors_raw = os.environ.get("CORS_ORIGINS", "*").strip()
_cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- optional Supabase JWT verification --------------------------------
# When SUPABASE_JWT_SECRET is set, /api/analyze requires a valid JWT in
# the Authorization: Bearer <token> header. This stops random scrapers
# from burning your LLM tokens. When the env var is empty we leave the
# endpoint open (useful for local dev / DEMO mode).

_BEARER = HTTPBearer(auto_error=False)


def _verify_jwt(creds: Optional[HTTPAuthorizationCredentials]) -> Optional[Dict[str, Any]]:
    secret = os.environ.get("SUPABASE_JWT_SECRET")
    if not secret:
        return None  # auth disabled
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        import jwt  # type: ignore
    except ImportError:
        logger.warning("PyJWT not installed but SUPABASE_JWT_SECRET set — auth disabled")
        return None
    try:
        payload = jwt.decode(
            creds.credentials, secret,
            algorithms=["HS256"], audience="authenticated",
            options={"verify_aud": True},
        )
        return payload
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"invalid token: {e}")


async def maybe_user(request: Request) -> Optional[Dict[str, Any]]:
    """Return JWT claims if SUPABASE_JWT_SECRET set & token valid, else None."""
    auth = request.headers.get("authorization")
    if not auth:
        return _verify_jwt(None)
    parts = auth.split(None, 1)
    if len(parts) != 2:
        return _verify_jwt(None)
    creds = HTTPAuthorizationCredentials(scheme=parts[0], credentials=parts[1])
    return _verify_jwt(creds)


# ---------- session registry --------------------------------------------------

class Session:
    """Container for a single analysis run shared between the launcher and SSE stream."""

    def __init__(self, sid: str, params: Dict[str, Any]):
        self.id = sid
        self.params = params
        self.queue: asyncio.Queue = asyncio.Queue()
        self.done = False
        self.cancelled = False


SESSIONS: Dict[str, Session] = {}


# ---------- routes ------------------------------------------------------------

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.post("/api/analyze")
async def start_analysis(
    payload: Dict[str, Any],
    user: Optional[Dict[str, Any]] = Depends(maybe_user),
) -> JSONResponse:
    """Register a new analysis session and return its id.

    The actual run is launched lazily when the client connects to the
    `/api/stream/{sid}` SSE endpoint, so we don't waste an LLM call if the
    client never subscribes.

    Auth: when SUPABASE_JWT_SECRET is set, a valid Supabase JWT is required
    in the Authorization: Bearer header. Otherwise the endpoint is open
    (suitable for local dev or self-hosted single-user deployments).
    """
    required = ["ticker", "trade_date"]
    missing = [k for k in required if not payload.get(k)]
    if missing:
        return JSONResponse({"error": f"missing: {missing}"}, status_code=400)

    sid = uuid.uuid4().hex[:12]
    SESSIONS[sid] = Session(sid, payload)
    user_tag = (user or {}).get("sub", "anon")[:8]
    logger.info("session %s registered (user=%s) for %s @ %s",
                sid, user_tag, payload.get("ticker"), payload.get("trade_date"))
    return JSONResponse({"session_id": sid})


@app.get("/api/stream/{sid}")
async def stream(sid: str, request: Request) -> StreamingResponse:
    """SSE endpoint that pushes agent events to the browser."""
    session = SESSIONS.get(sid)
    if not session:
        return JSONResponse({"error": "unknown session"}, status_code=404)

    async def event_source() -> AsyncGenerator[bytes, None]:
        # Kick off the runner the first time the client subscribes.
        runner = AgentRunner(
            request_data=AnalysisRequest.from_dict(session.params),
            on_event=lambda evt: session.queue.put_nowait(evt),
        )
        runner_task = asyncio.create_task(runner.run())

        try:
            yield _sse({"type": "ready", "session_id": sid})
            while True:
                if await request.is_disconnected():
                    logger.info("client disconnected from %s", sid)
                    session.cancelled = True
                    runner.cancel()
                    break
                try:
                    evt = await asyncio.wait_for(session.queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # heartbeat to keep the proxy from closing the connection
                    yield b": ping\n\n"
                    continue

                # Augment the final decision with library-strategy matches.
                if evt.get("type") == "final_decision":
                    matches = match_strategies(evt.get("decision", {}), session.params)
                    evt["matched_strategies"] = matches

                yield _sse(evt)

                if evt.get("type") in ("complete", "error"):
                    session.done = True
                    break
        finally:
            runner.cancel()
            try:
                await asyncio.wait_for(runner_task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            SESSIONS.pop(sid, None)

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(event_source(), media_type="text/event-stream", headers=headers)


# ---- opportunities feed -------------------------------------------------

@app.get("/api/opportunities")
async def opportunities(
    severity: Optional[str] = None,
    ticker: Optional[str] = None,
    limit: int = 50,
) -> JSONResponse:
    """Return the current 24h opportunities feed (in-memory ring buffer)."""
    return JSONResponse({"items": get_feed(severity=severity, ticker=ticker, limit=limit)})


# ---- dataflows diagnostics (used by Profile page) -----------------------

@app.get("/api/dataflows")
async def dataflows() -> JSONResponse:
    return JSONResponse(dataflows_list())


@app.on_event("startup")
async def _startup_scanner() -> None:
    """Kick off the opportunities scanner unless explicitly disabled."""
    try:
        start_scanner()
    except Exception as e:
        logger.warning("scanner failed to start: %s", e)


@app.on_event("shutdown")
async def _shutdown_scanner() -> None:
    try:
        stop_scanner()
    except Exception:
        pass


@app.get("/api/runtime-config.js")
async def runtime_config_js() -> Response:
    """Emit window.APP_CONFIG = {...} as a JS file for the frontend.

    Public, safe-to-expose values only:
      - SUPABASE_URL, SUPABASE_ANON_KEY (anon key is designed for browsers)
      - API_BASE_URL (where the SSE backend lives — useful when frontend is
        on Cloudflare Pages and backend is on a different host)
    """
    cfg = {
        "SUPABASE_URL": os.environ.get("SUPABASE_URL", ""),
        "SUPABASE_ANON_KEY": os.environ.get("SUPABASE_ANON_KEY", ""),
        "API_BASE_URL": os.environ.get("PUBLIC_API_BASE_URL", ""),
        "AUTH_REQUIRED": bool(os.environ.get("SUPABASE_JWT_SECRET")),
    }
    body = f"window.APP_CONFIG = {json.dumps(cfg)};\n"
    return Response(content=body, media_type="application/javascript",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/strategies-meta")
async def strategies_meta() -> JSONResponse:
    """Lightweight metadata so the front-end matcher can show readable names."""
    return JSONResponse({
        "categories": {
            "entry": "建仓", "sizing": "仓位管理", "hedge": "对冲",
            "income": "收益增强", "directional": "方向性",
            "arbitrage": "套利", "exit": "退出",
        }
    })


@app.get("/api/config")
async def get_config() -> JSONResponse:
    """Front-end calls this once on page load to populate dropdowns and
    pre-fill the form from .env defaults.

    Surfaces:
      - per-provider model lists (deep / quick) from the shared catalog
      - which providers have an API key in env (drives badges/warnings)
      - user-overridable defaults via env vars:
          * DEFAULT_LLM_PROVIDER (openai|anthropic|google|deepseek)
          * DEFAULT_DEEP_LLM, DEFAULT_QUICK_LLM
          * DEFAULT_RESEARCH_DEPTH (1..5)
          * DEFAULT_OUTPUT_LANGUAGE (Chinese|English)
          * DEFAULT_TICKER, DEFAULT_INSTRUMENT, DEFAULT_RISK_TOLERANCE
    """
    cat = serialize_catalog()
    providers_with_keys = [p["id"] for p in cat["providers"] if p["key_present"]]

    # Pick a sensible default provider:
    #   1) DEFAULT_LLM_PROVIDER if set and valid
    #   2) the first provider that has a key
    #   3) openai
    valid_ids = {p["id"] for p in cat["providers"]}
    env_provider = (os.environ.get("DEFAULT_LLM_PROVIDER") or "").strip().lower()
    if env_provider and env_provider in valid_ids:
        default_provider = env_provider
    elif providers_with_keys:
        default_provider = providers_with_keys[0]
    else:
        default_provider = "openai"

    # Find the provider's model lists for default selection
    provider_obj = next((p for p in cat["providers"] if p["id"] == default_provider), None)
    deep_models = (provider_obj or {}).get("models", {}).get("deep", [])
    quick_models = (provider_obj or {}).get("models", {}).get("quick", [])

    default_deep = os.environ.get("DEFAULT_DEEP_LLM") or (deep_models[0]["value"] if deep_models else "")
    default_quick = os.environ.get("DEFAULT_QUICK_LLM") or (quick_models[0]["value"] if quick_models else "")

    return JSONResponse({
        "providers": cat["providers"],
        "defaults": {
            "llm_provider": default_provider,
            "deep_think_llm": default_deep,
            "quick_think_llm": default_quick,
            "research_depth": int(os.environ.get("DEFAULT_RESEARCH_DEPTH", "1") or 1),
            "output_language": os.environ.get("DEFAULT_OUTPUT_LANGUAGE", "Chinese"),
            "ticker": os.environ.get("DEFAULT_TICKER", "NVDA"),
            "instrument_hint": os.environ.get("DEFAULT_INSTRUMENT", "stock"),
            "risk_tolerance": int(os.environ.get("DEFAULT_RISK_TOLERANCE", "3") or 3),
        },
        "providers_with_keys": providers_with_keys,
    })


# Mount static last so /api/* routes win.
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    # Convenience: also expose strategies.js at root for the index page.
    @app.get("/strategies.js")
    async def strategies_js() -> FileResponse:
        return FileResponse(STATIC_DIR / "strategies.js", media_type="application/javascript")
    @app.get("/app.js")
    async def app_js() -> FileResponse:
        return FileResponse(STATIC_DIR / "app.js", media_type="application/javascript")
    @app.get("/auth.js")
    async def auth_js() -> FileResponse:
        return FileResponse(STATIC_DIR / "auth.js", media_type="application/javascript")
    @app.get("/styles.css")
    async def styles_css() -> FileResponse:
        return FileResponse(STATIC_DIR / "styles.css", media_type="text/css")
    @app.get("/logo.svg")
    async def logo_svg() -> FileResponse:
        return FileResponse(STATIC_DIR / "logo.svg", media_type="image/svg+xml")
    @app.get("/favicon.svg")
    async def favicon_svg() -> FileResponse:
        return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


# ---------- helpers -----------------------------------------------------------

def _sse(payload: Dict[str, Any]) -> bytes:
    """Format a payload as a single SSE message."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        reload=os.environ.get("RELOAD", "false").lower() == "true",
    )
