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
# Install our own + TradingAgents' requirements. We copy requirements first
# so Docker layer cache stays warm across code edits.
COPY trading-decision-app/requirements.txt /tmp/req-app.txt
COPY TradingAgents/requirements.txt        /tmp/req-ta.txt

RUN pip install --upgrade pip && \
    pip install -r /tmp/req-app.txt && \
    pip install -r /tmp/req-ta.txt && \
    pip install pyjwt cryptography

# ---- copy source ---------------------------------------------------------
COPY TradingAgents/             /app/TradingAgents/
COPY trading-decision-app/      /app/trading-decision-app/

ENV PYTHONPATH=/app/TradingAgents:/app/trading-decision-app/backend
WORKDIR /app/trading-decision-app/backend

# Healthcheck endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${PORT}/health || exit 1

EXPOSE 8000
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips '*'"]
