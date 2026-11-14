# syntax=docker/dockerfile:1.7
# txt2pptx: web UI (default) or MCP server.
#   docker build -t txt2pptx .
#   docker run --rm -p 7860:7860 -e OPENAI_API_KEY=... -v txt2pptx-data:/data txt2pptx
#   docker run --rm -p 8000:8000 -v txt2pptx-data:/data txt2pptx mcp --transport streamable-http --host 0.0.0.0

FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
# Dependencies first (cached layer), then the project itself.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --all-extras --no-install-project
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --all-extras --no-editable

FROM python:3.13-slim AS runtime
# LibreOffice for PDF/PNG export; Carlito/Caladea are metric-compatible with Calibri/Cambria.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-impress-nogui \
        fonts-crosextra-carlito fonts-crosextra-caladea fonts-liberation2 fonts-dejavu-core fonts-noto-core \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --home-dir /data app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/data \
    TXT2PPTX_HOME=/data \
    TXT2PPTX_SERVER_NAME=0.0.0.0 \
    TXT2PPTX_MCP_HOST=0.0.0.0 \
    GRADIO_ANALYTICS_ENABLED=False

USER app
WORKDIR /data
VOLUME ["/data"]
EXPOSE 7860 8000

# Healthy as soon as the web server answers (any HTTP status), on 7860 (UI) or 8000 (MCP).
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 CMD ["python", "-c", "import sys, urllib.request, urllib.error\nfor port in (7860, 8000):\n    try:\n        urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=3); sys.exit(0)\n    except urllib.error.HTTPError:\n        sys.exit(0)\n    except Exception:\n        pass\nsys.exit(1)"]

ENTRYPOINT ["txt2pptx"]
CMD ["ui"]
