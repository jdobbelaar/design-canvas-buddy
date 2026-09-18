# syntax=docker/dockerfile:1
#
# Two stages: build the frontend with Node, then ship it inside the Python
# image, where FastAPI serves it alongside the API on a single port.
#
#   docker build -t design-canvas-buddy .
#   docker run -p 8000:8000 -v design-canvas-data:/data design-canvas-buddy
#
# Build context is the repo root (it needs both frontend/ and backend/).

# ---- Stage 1: frontend -> static files --------------------------------------
FROM node:24-slim AS frontend
WORKDIR /build

# Manifests first so the dependency layer is cached until they change.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# SPA_BUILD=1 makes TanStack Start prerender a static _shell.html instead of
# emitting only the server-rendered (Cloudflare worker) bundle. See
# frontend/vite.config.ts. Output lands in .output/public.
ENV SPA_BUILD=1
RUN npm run build


# ---- Stage 2: Python runtime ---------------------------------------------------
FROM python:3.14-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Runtime dependencies only (no pytest/httpx), exactly as pinned in uv.lock.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/app ./app
COPY --from=frontend /build/.output/public ./static

# Run unprivileged; /data is the only place the app writes (the SQLite file).
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app && mkdir /data && chown app /data
USER app

# SQLite on the /data volume by default. To use Postgres instead, override at
# run time (the asyncpg driver is already in the image), e.g.
#   docker run -e DATABASE_URL=postgres://user:pass@host:5432/dbname ...
ENV FRONTEND_DIR=/app/static \
    DATABASE_URL=sqlite+aiosqlite:////data/app.db
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/openapi.json')"

# Deliberately a single worker: live presence and the WebSocket connection
# registry are held in this process's memory (app/routers/ws.py), so running
# several workers would split a session's participants across processes.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
