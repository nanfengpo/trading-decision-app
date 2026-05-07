# Dockerfile — backend (FastAPI + TradingAgents)
# Builds an image suitable for Fly.io / Render / Railway / any Docker host.

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# System deps for some scientific Python wheels (yfinance, pandas, numpy)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*

# ---- Python deps ---------------------------------------------------------
# App deps cached first (changes most frequently together with code).
COPY trading-decision-app/requirements.txt /tmp/req-app.txt
RUN pip install --upgrade pip && \
    pip install -r /tmp/req-app.txt && \
    pip install pyjwt cryptography

# TradingAgents declares its 21 deps (langchain-*, yfinance, stockstats,
# langgraph, pandas, ...) in pyproject.toml — its requirements.txt is just
# a lone "." pointing at it. We pip-install from the source tree directly
# so all those transitive deps land in the image.
COPY TradingAgents/             /app/TradingAgents/
RUN pip install /app/TradingAgents

# ---- copy app source -----------------------------------------------------
COPY trading-decision-app/      /app/trading-decision-app/

ENV PYTHONPATH=/app/TradingAgents:/app/trading-decision-app/backend
WORKDIR /app/trading-decision-app/backend

# Healthcheck endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${PORT}/health || exit 1

EXPOSE 8000
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips '*'"]
