FROM python:3.14-slim

WORKDIR /app

# SSH for private deps (B路径 git+ssh, L-024)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

RUN --mount=type=ssh pip install uv

COPY pyproject.toml .
RUN --mount=type=ssh uv sync --no-dev

COPY hevi/ ./hevi/

CMD ["uv", "run", "uvicorn", "hevi.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
