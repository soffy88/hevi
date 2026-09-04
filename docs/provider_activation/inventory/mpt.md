# MPT (MoneyPrinterTurbo) — External Provider (REST API)

**Status:** `EXTERNAL_PROVIDER` — requires MPT API endpoint
**9 段验收链:** Stage 1 PARTIAL (MPT_API_BASE set but MPT_API_KEY empty) → Stage 2 probe
**Activated at:** 2026-09-04T02:35+00:00

## 1. 能力边界定义

MPT 在 HEVI 中是 **外部 REST Provider**，HEVI 通过 `services/mpt_adapter.py` 和 `services/mpt_integration.py` 与 MPT 服务交互，不控制 MPT 的内部处理和 GPU 推理：

- `services/mpt_integration.py` — 封装 MPT REST API (包含认证头的可选 `MPT_API_KEY`)
- `services/mpt_adapter.py` — `MPTClient.generate_video()` 调用 MPT 的 `/api/v1/videos` 端点；`submit_mpt_job_from_hevi()` 由 HEVI 任务流水线调度
- `hevi/api/routers/mpt.py` — `/api/mpt/generate` 等 FastAPI 路由使用 `MPTClient`
- `hevi/provider_policy/runtime.py:68-78` — ProviderSpec `("MPT_API_BASE",)`；setup 文字 "启动 MPT API；本机默认监听 127.0.0.1:8080，生产容器由 Compose 使用 mpt-api:8080"
- `hevi/production/capabilities.py:362-371` — `mpt` CapabilityDescriptor `available=True`

MPT 的真实 runtime path:
- **需要:** `MPT_API_BASE`
- **可选:** `MPT_API_KEY`
- **健康探测:** `probe_provider("mpt")` -> GET `/ping`
- **生产路径:** `/api/v1/videos` POST -> 等待 task_id -> 查询 `/api/v1/tasks/{task_id}` -> 下载 artifacts

## 2. External Provider Track 状态

- **分类:** `EXTERNAL_PROVIDER`
- **MPT_API_BASE:** REQUIRED
- **MPT_API_KEY:** 可选，但如果不设置，某些高级功能可能无法访问

## 3. 9 段验收链入口 (Stage 1)

| 段位 | 所需条件 | 状态 |
|---|---|---|
| 1 — credential/config | `MPT_API_BASE` (默认 127.0.0.1:8080) | 🟡 Stage 1 PARTIAL (`.env` 已设但 `MPT_API_KEY` 空) |
| 2 — readiness probe | GET `/ping` 返回 2xx | 待 Stage 2 |
| 3 — real submit | POST `/api/v1/videos` 真实提交 | 待 |
| 4 — ACK / job_id | task_id | 待 |
| 5 — real artifact | video file (MP4) | 待 |
| 6 — local freeze | 本地缓存固化 | 待 |
| 7 — provenance | source manifest | 待 |
| 8 — evaluation | 质量判定 | 待 |
| 9 — billing/usage | 计费记录 | 待 |

## 4. 配置与诊断

```bash
# 检查配置 (provider_policy)
uv run python -m hevi.skills.providers_cli status --provider mpt

# 探测健康 (需要 MPT API 运行)
uv run python -m hevi.skills.providers_cli readiness --provider mpt
```

## 5. 行动建议

1. **provider_activation/README.md** MPT 一行保留为 🟡 Stage 1 PARTIAL，阻塞原因: `MPT_API_BASE` 已设但 `MPT_API_KEY` 空；未拿到 /ping ACK
2. **provider_activation/README.md** 下一步继续 Stage 2 探测 (健康探测)
3. docs/PROVIDER_SETUP.md MPT 一行: `MPT_API_BASE` 必填；可选 `MPT_API_KEY`；本地/容器默认入口 `http://127.0.0.1:8080`；就绪条件: MPT `/ping` 返回 2xx
4. 外部 Provider Track 计数中: MPT 仍计入 6 个外部 Provider (仅 livestream 路径)