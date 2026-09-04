# LongCat — Internalized Capability Inventory

**Status:** `INTERNALIZED_CAPABILITY` — not an external blocker
**9 段验收链:** `N/A` — LongCat 不在 External Provider Track
**Activated at:** 2026-09-04T02:15+00:00

## 1. 能力边界定义

LongCat 在 HEVI 中是 **内化能力**，不是外部 Provider：

- `hevi/longcat/oprim/` — Pure request/context/tool contracts (no model weights)
- `hevi/longcat/oskill/` — Agent loop compiler + `execute_agent_loop` (pure Python execution, injects tool handlers from HEVI allow-list)
- `hevi/longcat/omodul/` — Transaction workflow (fingerprint/decision_trail/report/cost)
- `hevi/longcat/oservi/provider.py` — **Optional** OpenAI-compatible HTTP adapter (`LONGCAT_BASE_URL` + optional `LONGCAT_API_KEY`)
  - 当 `LONGCAT_BASE_URL` 为空时 `build_longcat_caller()` 返回 `None`
  - workflow 支持 `caller=None` → returns "blocked: no provider configured"
  - workflow 支持 `caller=injected` → normal local execution

证据: `tests/test_longcat_openmontage_3o.py:78-79` — `monkeypatch.delenv("LONGCAT_BASE_URL", raising=False)` 必须返回 "blocked"
证据: `tests/test_coverage_internalized_contracts.py:340` — `build_longcat_caller() is None and longcat_provider_status()["available"] is False`

LongCat 的真实 runtime path:
- **默认**: 走 `hevi-gen-engine` GPU sidecar (`http://127.0.0.1:17600`) — HEVI 自有容器
- `TALKING_FACE_ENGINE=duix` → 本地 Duix docker 容器 (HEVI 自家 `pull_duix.sh`)
- `TALKING_FACE_ENGINE=echomimic` → 本机 ComfyUI EchoMimicV2

这些全是 HEVI 自身模块，**没有外部厂商 API** 被强制要求。

## 2. External Provider Track 状态

- **分类:** `LONGCAT_MODE = INTERNALIZED_CAPABILITY`
- **LONGCAT_API_KEY:** NOT REQUIRED (key only used if user points at external vLLM endpoint)
- **LONGCAT_BASE_URL:** NOT REQUIRED (only needed for optional external provider adapter)
- **应从 External Provider Track 删除:** `LongCat = INTERNALIZED / NOT AN EXTERNAL BLOCKER`
- **HEVI Provider Track 总账影响:** 从 8 个 Provider 中移除 LongCat，剩余有效 External Provider 数量重新核定

## 3. 重新核定 Provider 分母

原本的 "8 个 provider" 分母包含 LongCat（作为外部 Provider 错误归类）。现在的真实分类:

| # | Provider | 模式 | 9 段状态 | 需要的环境变量 |
|---|---|---|---|---|
| 1 | Wan / local | 内化 | ✅ VERIFIED | — |
| 2 | Pexels | 外部 Provider | ✅ VERIFIED (9/9) | `PEXELS_API_KEY` |
| 3 | LongCat | **内化能力** | ❌ 非 Provider Track | `LONGCAT_BASE_URL`/`LONGCAT_API_KEY` 非必须 |
| 4 | JoyAI | 外部 Provider (WebSocket) | 🔴 Stage 1 BLOCKED | `JOYAI_STREAM_WS_URL` / `JOYAI_BASE_URL` |
| 5 | Voicebox | 内部 GPU sidecar | 🟡 Stage 1 PARTIAL | `VOICEBOX_BASE_URL` / gen-engine 健康 |
| 6 | Duix | 本地容器 / 契约占位 | 🔴 Stage 1 BLOCKED (livestream) / 本地已可 | `DUIX_SERVICE_URL` / `DUIX_LIVESTREAM_PATH` 用于 livestream |
| 7 | MPT | 外部 Provider (MPT API) | 🟡 Stage 1 PARTIAL | `MPT_API_BASE` (默认 127.0.0.1:8080) |
| 8 | HELIOS deploy | 未配置 | 🔴 Stage 1 BLOCKED | `.env` 中无 HELIOS_* 变量 |

**新的 External Provider Track 计数:** 6 个真正的外部 Provider (Pexels, JoyAI, Voicebox(视为内部但 provider_policy 仍记录), Duix livestream, MPT, HELIOS)。
LongCat 不再计入 External Provider Track 分母。

## 4. 操作建议

1. **从 provider_activation/README.md 的 Provider 队列表中删除 LongCat (#3 行)**
2. **从 provider_activation/README.md 的总账状态把 `EXTERNAL PROVIDER TRACK = PENDING (2/8 verified)` 改为 `EXTERNAL PROVIDER TRACK = PENDING (2/6 verified: Pexels, ...)`**，并注明 LongCat 已移出
3. **从 `docs/PROVIDER_SETUP.md` 的 Provider 对照表中** — LongCat 那一行改为注明 `INTERNALIZED_CAPABILITY`，不再需要 `LONGCAT_BASE_URL`/`LONGCAT_API_KEY` 为必须项；或者删除该行，改为注脚说明 LongCat 已内化
4. **从 `STATUS.md` 的当前状态描述中移除 LongCat 的 🔴 阻塞行**（或标记为 "INTERNALIZED — no key needed"）
5. **外部 Provider Track 的 next step** 应该从 "LongCat Stage 1" 改为 "JoyAI Stage 1 credential"（JOYAI_STREAM_WS_URL / JOYAI_BASE_URL）
6. **同步 `hevi/provider_policy/runtime.py` ProviderSpec** — LongCat spec 的 `required_env: ("LONGCAT_BASE_URL", "LONGCAT_API_KEY")` 可以保留作为**配置记录**，但不应再把它们当作 production readiness 的必要条件；或者把 spec 标记为 `kind: internalized` 的变体

## 5. 参考审计证据

- `hevi/longcat/__init__.py` — docstring: "This package internalises the useful application-level parts of LongCat-2.0"
- `hevi/longcat/oservi/provider.py:4-5` — "No LongCat package or checkpoint is installed by HEVI. A local GPU/NPU server can be pointed at this adapter with LONGCAT_BASE_URL."
- `hevi/longcat/oservi/provider.py:54-57` — `build_longcat_caller()` returns `None` when `_base_url()` returns empty
- `hevi/longcat/omodul/runtime.py:272-288` — when `caller is None`, returns "blocked: no LongCat-compatible provider configured"
- `tests/test_longcat_openmontage_3o.py:78-79` — monkeypatch deletion of LONGCAT_BASE_URL must result in blocked status
- `tests/test_coverage_internalized_contracts.py:340` — `build_longcat_caller() is None and longcat_provider_status()["available"] is False`
- `hevi/production/capabilities.py:392-395` — `longcat_agent` CapabilityDescriptor `available` depends on `LONGCAT_BASE_URL` but `honest_boundary` says "HEVI owns the context/tool execution contract, not the upstream weights"
- `hevi/digital_human/talking_face.py:3-9` — Three talking face engine choices, LongCat走 gen-engine/http://hevi-gen-engine:17493，绝非外部 Provider
- `hevi/api/routers/longcat.py` — LongCat run route: first probes `probe_provider("longcat")`, if not ready returns blocked; tools are HEVI allow-listed, never external code execution