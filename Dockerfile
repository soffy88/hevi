FROM python:3.14-slim

WORKDIR /app

# System deps: git+ssh for private pypi, ffmpeg for video assembly
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    openssh-client \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN --mount=type=ssh pip install uv

COPY pyproject.toml uv.lock* ./
RUN --mount=type=ssh uv sync --no-dev --frozen

COPY hevi/ ./hevi/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -sf http://localhost:8000/api/health || exit 1

CMD ["uv", "run", "uvicorn", "hevi.api.main:app", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
