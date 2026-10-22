# ─────────────────────────────────────────────────────────────────────────────
#  VYRON — production image
#  python 3.12 + ffmpeg (ntgcalls ships manylinux_2_28 wheels for cp310–cp314)
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm

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
