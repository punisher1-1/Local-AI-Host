# syntax=docker/dockerfile:1
#
# Single-container image for the LJA "Local AI" app:
#   - nginx     serves the built React frontend AND reverse-proxies the API
#   - uvicorn   runs the FastAPI RAG backend (serve.py)
# Both run side by side under supervisord. The database is NOT in here — it's an
# external pgvector Postgres reached via DATABASE_URL.
#
# Build context is this folder (ai-frontend), which now contains both the
# frontend source and the vendored backend in ./server.

# ── Stage 1: build the static frontend ───────────────────────────────────────
FROM node:20-bookworm-slim AS frontend
WORKDIR /app
# We only need Vite to produce dist/, so skip downloading the Electron binary.
ENV ELECTRON_SKIP_BINARY_DOWNLOAD=1
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build          # outputs /app/dist

# ── Stage 2: runtime (python backend + nginx) ────────────────────────────────
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends nginx supervisor \
 && rm -f /etc/nginx/sites-enabled/default \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY server/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Backend code (serve.py imports makerspace_rag.py).
COPY server/ /app/

# Built frontend + nginx/supervisor config.
COPY --from=frontend /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY supervisord.conf /etc/supervisord.conf

EXPOSE 80
CMD ["supervisord", "-c", "/etc/supervisord.conf"]
