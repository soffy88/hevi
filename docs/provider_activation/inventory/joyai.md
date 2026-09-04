# JoyAI — External Provider (WebSocket Streaming V2V)

**Status:** `EXTERNAL_PROVIDER` — requires WebSocket endpoint
**9 段验收链:** Stage 1 BLOCKED (no config) → pending credential/config
**Activated at:** 2026-09-04T02:20+00:00

## 1. 能力边界定义

JoyAI 是 **外部 WebSocket Provider**，HEVI 只提交审计和真实帧流，从不伪造：

- `hevi/joyai/omodul/stream_edit.py` — Session 管理和 causal frame protocol
- `provider_url()` / `stream_provider_url()` — 解析 `JOYAI_STREAM_WS_URL` 或 `JOYAI_BASE_URL` + `JOYAI_STREAM_WS_PATH`
- `provider_available()` — `bool(stream_provider_url())`；没有 URL 时直接 blocked
- `create_session()` — 只有 `provider_available()` 为真才设 `status: "ready"`；否则 `status: "blocked"`；**从不产生 placeholder 帧**

证据:
- `hevi/joyai/omodul/stream_edit.py:55-60` — `session.status = "ready" if provider_available() and not missing else "blocked"`
- `hevi/joyai/omodul/stream_edit.py:capabilities()` — `"available": provider_available()`, `"status": "available" if provider_available() else "unavailable"`
- `tests/test_longcat_openmontage_3o.py` 语境：虽然是 LongCat test，但 JoyAI provider 路径同上：无 provider = blocked，无伪造

JoyAI 的真实 runtime path:
- **需要:** `JOYAI_STREAM_WS_URL` (显式 WebSocket) 或 `JOYAI_BASE_URL` + `JOYAI_STREAM_WS_PATH` (= `/ws/edit`)
- **健康探测:** `probe_provider("joyai")` 做 WebSocket handshake（不发送编辑请求）
- **生产路径:** `/api/stream-edit/sessions`, `/api/stream-edit/sessions/{id}/stream` 端点依赖真实连接

## 2. External Provider Track 状态

- **分类:** `EXTERNAL_PROVIDER`
- **JOYAI_STREAM_WS_URL / JOYAI_BASE_URL:** REQUIRED — 无配置时 provider 完全不可用
- **必须从 External Provider Track** 保留: JoyAI 需要真实 WebSocket 服务才能完成 V2V 编辑

## 3. 9 段验收链入口 (Stage 1)

| 段位 | 所需条件 | 证据文件 |
|---|---|---|
| 1 — credential/config | `JOYAI_STREAM_WS_URL` 或 `JOYAI_BASE_URL` + `JOYAI_STREAM_WS_PATH` | `01_credential_status.json` |
| 2 — readiness probe | WebSocket handshake success (no edit sent) | `02_probe_status.json` |
| 3 — real submit | 通过 WS 真实发送编辑请求 | `03_resolve_*.log` |
| 4 — ACK / job_id | 服务返回 session_id | `04_resolve_*.json` |
| 5 — real artifact | 渲染出真实视频文件 | `artifacts/` |
| 6 — local freeze | 本地缓存固化 | `data/material_cache/` |
| 7 — provenance | source manifest + sha256 | `07_provenance.json` |
| 8 — evaluation | 质量指标判定 | `08_evaluation_readiness.json` |
| 9 — billing/usage | 计费记录 | `09_billing_usage.json` |

## 4. 配置与诊断

```bash
# 检查配置
uv run python -m hevi.skills.providers_cli status --provider joyai

# 真实探测（需要 WS 服务运行）
uv run python -m hevi.skills.providers_cli readiness --provider joyai
```

## 5. 行动建议

1. **provider_activation/README.md** JoyAI 一行保留为 🔴 Stage 1 BLOCKED，阻塞原因: `JOYAI_BASE_URL` / `JOYAI_STREAM_WS_URL` / `JOYAI_API_KEY` 均空
2. **provider_activation/README.md** 下一步从 "LongCat Stage 1" 改为 "JoyAI Stage 1 credential"
3. docs/PROVIDER_SETUP.md JoyAI 一行: `JOYAI_STREAM_WS_URL` / `JOYAI_BASE_URL` 均为必须项；没有内置默认值
4. 把 JoyAI 计入 External Provider Track 计数：从 6 个有效外部 Provider 中算 (Pexels + JoyAI + Voicebox/internal + Duix + MPT + HELIOS)