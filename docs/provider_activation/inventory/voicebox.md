# Voicebox / HEVI Gen Engine — Internal GPU Sidecar (Provider Policy still records it)

**Status:** `INTERNALIZED_CAPABILITY` (runtime runs inside HEVI-gen-engine) but **still recorded in provider_policy** as configured
**9 段验收链:** Stage 1 PARTIAL (VOICEBOX_BASE_URL set but gen-engine not fully proven) → Stage 2 probe
**Activated at:** 2026-09-04T02:25+00:00

## 1. 能力边界定义

Voicebox 在 HEVI 中是 **内部 GPU 算力引擎 sidecar**（位于 `services/gen_engine/`），不是外部第三方 Provider：

- `services/gen_engine/` — HEVI 自有 FastAPI 容器（Docker compose），提供 `/api/ai/*` 端点
- `hevi/audio/cosyvoice_service.py` — 只负责“把脚本 POST 到内网引擎端点 `http://hevi-gen-engine:17493/api/ai/cosyvoice`”，等待引擎合成并下载 WAV
- `hevi/audio/voicebox_client.py` — Voicebox sidecar 的小型 HTTP 客户端（音色档案、生成请求）
- `hevi/production/capabilities.py:113-119` — `voice_studio_tts` CapabilityDescriptor `available = bool(VOICEBOX_BASE_URL)`，`setup` 注明 "配置 VOICEBOX_BASE_URL 并启动 hevi-voicebox 服务后自动开放"
- `hevi/provider_policy/runtime.py:43-45` — ProviderSpec `("VOICEBOX_BASE_URL",)`，setup 文字 "启动 hevi-gen-engine/Voicebox，并设置 VOICEBOX_BASE_URL"

Voicebox 的真实 runtime path:
- **默认入口:** `http://127.0.0.1:17600` (`.env` 设置 `VOICEBOX_BASE_URL=http://127.0.0.1:17600`)
- `GEN_ENGINE_BASE_URL` 优先，`AI_ENGINE_BASE_URL` 兼容回退
- **健康探测:** `probe_provider("voicebox")` → GET `/api/ai/health` 对 gen-engine
- **生产路径:** TTS 合成 → `/api/ai/tts/synthesize` → 等待 terminal event → 下载 WAV

## 2. Provider Policy 与 Capability Catalog 的分类

| 视角 | 分类 | 环境变量 | 说明 |
|---|---|---|---|
| **provider_policy.runtime** | 配置记录 (配置即可调用) | `VOICEBOX_BASE_URL` / `GEN_ENGINE_BASE_URL` | 必须有配置才能 `provider_configuration()["configured"] = True` |
| **production.capabilities** | 运行时可用 (依赖 gen-engine 健康) | 同上 | `execution_ready` 由 gen-engine `/api/ai/health` 就绪决定 |
| **外部 Provider Track** | ❌ 不属于外部厂商 | N/A | Voicebox 代码完全在 HEVI 仓库内 (`services/`)，不需要外部 key 或第三方凭据 |

## 3. 9 段验收链入口

| 段位 | 所需条件 | 状态 |
|---|---|---|
| 1 — credential/config | `VOICEBOX_BASE_URL` 或 `GEN_ENGINE_BASE_URL` 已设置 | 🟡 Stage 1 PARTIAL (`.env` 已设但 gen-engine 容器可能未启动) |
| 2 — readiness probe | `gen-engine /api/ai/health` HTTP 200 | 仍待探测 (gen-engine 是否运行) |
| 3 — real submit | POST `/api/ai/tts/synthesize` 并等待完成 | 待 Stage 2-5 |
| 4 — ACK / job_id | 服务返回任务 ID / 生成记录 | 待 |
| 5 — real artifact | WAV 写入 `output/` 并非空 | 待 |
| 6 — local freeze | WAV 落盘固化 + 写入台账 | 待 |
| 7 — provenance | source manifest: provider, model, params, sha256 | 待 |
| 8 — evaluation | 音质/可播放性判定 | 待 |
| 9 — billing/usage | TTS 计费记录 (若适用) | 待 |

## 4. 配置与诊断

```bash
# 检查配置 (provider_policy)
uv run python -m hevi.skills.providers_cli status --provider voicebox

# 探测健康 (需要 gen-engine 运行)
uv run python -m hevi.skills.providers_cli readiness --provider voicebox
```

## 4. 行动建议

1. **provider_activation/README.md** Voicebox 一行保留为 🟡 Stage 1 PARTIAL，阻塞原因: `VOICEBOX_BASE_URL` 已设但 gen-engine 未启动；缺真实 ACK
2. **provider_activation/README.md** 下一步继续 Stage 2 探测 (健康探测)
3. **provider_policy/runtime.py** Voicebox ProviderSpec 的 `required_env: ("VOICEBOX_BASE_URL",)` 可以保留，但不应把它归类为"必须有外部 key"；它是 HEVI 内部 runtime config
4. **docs/PROVIDER_SETUP.md** Voicebox 一行: `VOICEBOX_BASE_URL` 或 `GEN_ENGINE_BASE_URL` 均为必须项，本地/容器默认入口 `http://127.0.0.1:17600`；就绪条件: gen-engine `/api/ai/health` 可达
5. 继续 Stage 2-5 的探测 (真实 submit/ACK/artifact)