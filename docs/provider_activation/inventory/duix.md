# Duix — Local Container (Talking Face) + Reserved External Livestream Contract

**Status:** `INTERNALIZED_CAPABILITY` for offline talking face；`EXTERNAL_PROVIDER`-style contract **reserved** for livestream (unconfigured in .env)
**9 段验收链:** 
- 离线口型 (talking face): not in External Provider Track — 走本地 Docker 容器
- livestream (`/api/pro/livestream/*`): Stage 1 BLOCKED (no config)
**Activated at:** 2026-09-04T02:30+00:00

## 1. 能力边界定义

Duix 在 HEVI 中有 **两个截然不同的路径**，容易混淆：

### 1a. 离线口型合成 (INTERNALIZED)

- `hevi/digital_human/duix_offline.py` — 离线口型: 参考 still/视频 + 母带 → silent MP4
- `services/` 下 `pull_duix.sh` — HEVI 自己的脚本，拉 `guiji2025/duix.avatar` 镜像到本机
- `TALKING_FACE_ENGINE=duix` — 启动 Duix 本地 Docker 容器，用完停容器
- **不是外部 Provider** — HEVI 自己管理容器生命周期
- `hevi/digital_human/talking_face.py:61-69` — `_run_duix_offline()` 调用 `generate_silent_duix()`，整个生产路径用本地容器

### 1b. livestream 数字人 (EXTERNAL_PROVIDER contract, UNCONFIGURED)

- `hevi/digital_human/duix_service.py` — `DuixLiveService` 类，封装 `DUIX_SERVICE_URL` + `DUIX_LIVESTREAM_PATH`
- `hevi/api/routers/pro_studio.py` — `/api/pro/livestream/start/stop/status/capabilities` 使用 `DuixLiveService`
- **生产状态:** `execution_ready=False, production_ready=False` — livestream capability 永远不可用，除非用户显式配置外部 Duix 服务 URL
- `hevi/production/capabilities.py:252-258` — `livestream` CapabilityDescriptor `available = bool(DUIX_SERVICE_URL + DUIX_LIVESTREAM_PATH)`
- `hevi/digital_human/duix_service.py:61-67` — `start()` 必须要求 provider 返回真实 `session_id` + `stream_url`，否则 `DuixUnavailable`

证据:
- `pull_duix.sh` — HEVI 自己的 container 管理脚本
- `hevi/digital_human/talking_face.py:3,8` — 明确写"本机 Duix 容器离线口型" vs "gen-engine LongCat 端点"
- `hevi/api/routers/pro_studio.py:167` — livestream start 返回 503 `CAPABILITY_UNAVAILABLE`

Duix livestream 的真实 runtime path:
- **需要:** `DUIX_SERVICE_URL` + `DUIX_LIVESTREAM_PATH`
- **没有内置默认值** — 必须用户提供外部 WebRTC/RTMP 适配器
- **健康探测:** `probe_provider("duix")` → GET `{DUIX_SERVICE_URL}/health`
- **生产路径:** POST `{DUIX_LIVESTREAM_PATH}` → 等待 `session_id` + `stream_url`

## 2. Provider Policy 与 Capability Catalog 的分类

| 视角 | 分类 | 环境变量 | 说明 |
|---|---|---|---|
| **对离线口型 (Talking Face)** | INTERNALIZED_CAPABILITY | `TALKING_FACE_ENGINE=duix` | 走本地 Docker 容器，`services/` 自有镜像 |
| **对 livestream** | External Provider contract (UNCONFIGURED) | `DUIX_SERVICE_URL` / `DUIX_LIVESTREAM_PATH` | HEVI 只维护契约，执行依赖外部 provider 返回真实 session_id + stream_url |
| **production.capabilities** | 离线口型:可用；livestream:依赖外部配置 | 同上 | `livestream` `available = bool(DUIX_SERVICE_URL + DUIX_LIVESTREAM_PATH)` |

## 3. External Provider Track 状态（仅 livestream 路径）

| 段位 | 所需条件 | 状态 |
|---|---|---|
| 1 — credential/config | `DUIX_SERVICE_URL` + `DUIX_LIVESTREAM_PATH` | 🔴 Stage 1 BLOCKED (均空) |
| 2 — readiness probe | `{DUIX_SERVICE_URL}/health` HTTP 2xx | 待 Stage 1 |
| 3 — real submit | POST livestream → 真实 `session_id` | 待 |
| 4 — ACK / job_id | `session_id` | 待 |
| 5 — real artifact | `stream_url` 可播放 | 待 |
| 6 — local freeze | session 固化到本地 | 待 |
| 7 — provenance | 直播 session 来源痕迹 | 待 |
| 8 — evaluation | 直播流可播放性判定 | 待 |
| 9 — billing/usage | 直播计费 (若适用) | 待 |

## 4. 行动建议

1. **provider_activation/README.md** Duix 一行保留，但**细分为两个能力**:
   - Offline Talking Face: INTERNALIZED (本地 Duix 容器), 不在 External Provider Track
   - Livestream Digital Human: 🔴 Stage 1 BLOCKED, 阻塞原因: `DUIX_SERVICE_URL` / `DUIX_LIVESTREAM_PATH` 均空
2. **provider_activation/README.md** 把 `#6 Duix` 行标记为 livestream 路径 Stage 1 BLOCKED
3. docs/PROVIDER_SETUP.md Duix 一行: `DUIX_SERVICE_URL` + `DUIX_LIVESTREAM_PATH` 均为必须项，无内置默认值；但需要注明 Duix 有一个**内化的离线口型路径**(TALKING_FACE_ENGINE=duix)，不受此 Track 约束
4. 外部 Provider Track 计数中: Duix livestream 仍计入 6 个外部 Provider (仅 livestream 路径)
5. 离线口型 (Talking Face) **永远不进入 External Provider Track** — 它已经是本地能力