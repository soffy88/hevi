# hevi v6

二代重建。详见 `docs/` 与 `CONTRIBUTING.md`。

## 架构

| Layer | 描述 |
|-------|------|
| L0 | SaaS 基础设施 (Phase 9 SPEC 重建) |
| L1 | ViMax 式 agentic 编排 (自研，基于 oskill.agentic_investigate_loop) |
| L2 | LTX-2 + Wan 双 cloud 可插拔内核 (obase.ProviderRegistry) |
| L3 | VibeVoice + Duix 音频/数字人 |
| L4 | ffmpeg 合成 (obase.ffmpeg + oskill.video_assembler) |

## 快速启动

```bash
cp .env.example .env
docker compose up -d
uv sync
uv run uvicorn hevi.api.main:app --reload --port 8000
curl http://localhost:8000/api/health
```

## 测试

```bash
uv run ruff check hevi tests
uv run mypy --strict hevi
uv run pytest tests/ --cov=hevi --cov-report=term
```
