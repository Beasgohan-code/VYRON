# ─────────────────────────────────────────────────────────────────────────────
#  VYRON — production image
#
#  stage 1  build the React Mini App (vite → webapp/dist)
#  stage 2  python 3.12 + ffmpeg + the built frontend
#
#  ntgcalls publishes manylinux_2_28 wheels for cp310–cp314, hence 3.12-slim.
# ─────────────────────────────────────────────────────────────────────────────
FROM node:22-alpine AS frontend

WORKDIR /ui

# install deps first so the layer is cached while components change
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

COPY frontend/ ./
# vite writes to ../webapp/dist — keep it inside the build context
RUN npm run build -- --outDir dist && mkdir -p /ui/out && cp -r dist/* /ui/out/


FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-dejavu-core \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# the compiled Mini App from stage 1 (overrides any stale local build)
COPY --from=frontend /ui/out/ /app/webapp/dist/

RUN useradd --create-home --uid 1000 vyron \
    && mkdir -p /app/data /app/downloads \
    && chown -R vyron:vyron /app

USER vyron

ENV PORT=8080 \
    DATA_DIR=/app/data \
    DOWNLOADS_DIR=/app/downloads

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\",\"8080\")}/health', timeout=4)"

CMD ["python", "main.py"]
