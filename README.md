# hevi v6

二代重建。详见 `docs/` 与 `CONTRIBUTING.md`。

## Video Intelligence 状态

HEVI Video Intelligence 已接入现有 Asset、Provider、Verdict、TaskService
与 Studio authority：案例 provenance、冻结 benchmark、Pattern/Template
证据，以及真实 production completion 的 learning writeback 都沿用同一条
durable runtime。当前 production-learning E2E 已有真实 MP4、canonical
Verdict 和 observed-provider 统计证据。

状态必须区分：`CODE_COMPLETE`、`RUNTIME_CONNECTED`、`RUNTIME_QUALIFIED`、
`PRODUCTION_QUALIFIED`、`ENV_BLOCKED`、`OWNER_BLOCKED`。Pattern 与 Template
不会自动 promotion。Cross-model qualification 必须有至少两个独立真实
provider；当前第二 provider 和 HyperFrames CLI 仍是外部 qualification
blocker。详细证据见
[`docs/VIDEO-INTELLIGENCE-FINAL-CLOSURE.md`](docs/VIDEO-INTELLIGENCE-FINAL-CLOSURE.md)。

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
