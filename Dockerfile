# hevi API — 根 Dockerfile(与 deploy/Dockerfile.api 对齐, 供 docker-compose-prod.yml 使用)
#
# 与 deploy/Dockerfile.api 保持环境等价(一字不差同步的依赖面):
#   · FFmpeg(成片装配)
#   · Node.js + npm(Remotion 渲染: hevi-remotion 项目 + 内置 chrome-headless-shell)
#   · fonts-noto-cjk(烧录中文字幕)
#   · Chrome 运行库(Remotion/Playwright 无头浏览器)
#   · Playwright(Lite 管道录屏: chromium + 系统依赖)
# 区别: 本文件用 `uv sync` 从 pyproject.toml 安装 Python 依赖(含私库 git+ssh),
#       deploy/Dockerfile.api 直接拷贝宿主预构建 .venv。

FROM python:3.14-slim

WORKDIR /app

# System deps: git+ssh for private pypi, ffmpeg for video assembly,
# nodejs/npm for Remotion render (mirrors deploy/Dockerfile.api)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    openssh-client \
    ffmpeg \
    curl \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# CJK 字体单独一层:烧录中文字幕必需(否则 libass 无字形 → 豆腐块)。
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Chrome Headless (used by Remotion/Playwright) needs these runtime libraries.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64 \
    libcups2t64 libxcomposite1 libxdamage1 \
    && rm -rf /var/lib/apt/lists/*

RUN --mount=type=ssh pip install uv

COPY pyproject.toml uv.lock* ./
RUN --mount=type=ssh uv sync --no-dev --frozen

COPY scripts/ ./scripts/
RUN python scripts/patch_vibevoice.py
RUN python scripts/patch_oprim_prims.py

# Playwright 浏览器 + 系统依赖(补齐 libgtk-3 等, 供 Lite 管道录屏)。
RUN /app/.venv/bin/python -m playwright install --with-deps chromium

# Remotion 渲染项目(与 deploy/Dockerfile.api 完全一致的拷贝策略)。
COPY hevi-remotion/package.json hevi-remotion/package-lock.json ./hevi-remotion/
RUN cd hevi-remotion && npm ci --omit=dev --no-audit --no-fund
COPY hevi-remotion/ ./hevi-remotion/

COPY hevi/ ./hevi/
COPY alembic.ini ./

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -sf http://localhost:8000/api/health || exit 1

CMD ["uv", "run", "uvicorn", "hevi.api.main:app", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
