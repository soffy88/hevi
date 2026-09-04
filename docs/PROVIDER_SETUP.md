# HEVI Provider 运行配置

HEVI 把 Provider 分成三种状态：

- `configured`：已有足够的地址/凭据，可以发起调用；
- `reachable`：实际探针成功；
- `ready`：前两者同时成立。

诊断不会输出密钥：

```bash
uv run python -m hevi.skills.providers_cli status --no-probe
uv run python -m hevi.skills.providers_cli status
uv run python -m hevi.skills.providers_cli status --provider mpt --provider pexels
```

API 服务启动后也可访问 `GET /api/providers/status`，返回同一套脱敏状态。

## Provider 对照

| Provider | HEVI 配置 | 本地/容器默认入口 | 就绪条件 | 分类 |
|---|---|---|---|---|
| Voicebox | `VOICEBOX_BASE_URL` 或 `GEN_ENGINE_BASE_URL` | `http://127.0.0.1:17600` | gen-engine 的 `/api/ai/health` 可达；CPU 也可启动，GPU 需宿主机驱动 | 内部 GPU sidecar (HEVI 自有) |
| LongCat-2.0 | `LONGCAT_BASE_URL`、可选 `LONGCAT_API_KEY` | `http://hevi-gen-engine:17493` (默认) 或外部 OpenAI-compatible `/v1` | `/models` 可达；**HEVI 已内化核心能力 (oprim/oskill/omodul)，不强制需要外部 endpoint** | **内化能力** (外部 endpoint 可选) |
| JoyAI | `JOYAI_STREAM_WS_URL`，或 `JOYAI_BASE_URL` + `JOYAI_STREAM_WS_PATH` | 无内置默认值 | 外部 WebSocket 服务由实际编辑请求完成握手；诊断不会把 HTTP 200 冒充 WS 就绪 | 外部 Provider (WebSocket) |
| MPT | `MPT_API_BASE`、可选 `MPT_API_KEY` | `http://127.0.0.1:8080`；WebUI `:8501` | MPT `/ping` 返回 2xx | 外部 Provider (REST) |
| Pexels | `PEXELS_API_KEY` | `https://api.pexels.com` | `/v1/search` 实际鉴权成功；结果会下载到本地缓存 | 外部 Provider (REST) |
| Duix | `DUIX_SERVICE_URL` + `DUIX_LIVESTREAM_PATH` | 无内置默认值 | health 可达，并且直播接口返回真实 `session_id` + `stream_url` | 外部 Provider (livestream) / **内化离线口型** (`TALKING_FACE_ENGINE=duix` 走本地容器) |

### LongCat 内化说明

LongCat 的核心能力（上下文打包、推理/工具调用规范化、长周期 agent 执行）已完全由 HEVI 自身实现：

- `hevi/longcat/oprim/` — 纯数据契约（无模型权重）
- `hevi/longcat/oskill/` — Agent loop 编译器 + `execute_agent_loop`（纯 Python 执行，注入 HEVI 白名单工具）
- `hevi/longcat/omodul/` — 事务工作流（fingerprint / decision_trail / report / cost）
- `hevi/longcat/oservi/provider.py` — **可选**的 OpenAI-compatible HTTP 适配器

当 `LONGCAT_BASE_URL` 为空时，`build_longcat_caller()` 返回 `None`，workflow 返回 `blocked: no LongCat-compatible provider configured`。
**LongCat 不再需要 `LONGCAT_API_KEY` 或 `LONGCAT_BASE_URL` 才能作为内化能力运行。**

真实 runtime path：
- 默认 → `hevi-gen-engine` GPU sidecar (`http://127.0.0.1:17600`) — HEVI 自有容器
- `TALKING_FACE_ENGINE=duix` → 本地 Duix docker 容器
- `TALKING_FACE_ENGINE=echomimic` → 本机 ComfyUI EchoMimicV2
- `LONGCAT_BASE_URL` 指向外部 vLLM/兼容服务 → 仅当用户显式选择时使用

详见 `docs/provider_activation/inventory/longcat.md`。

## 启动顺序

先在仓库根目录准备 `.env`。`.env.example` 已包含地址、端口和变量名；密钥必须由实际 Provider 控制台或部署 Secret 注入。

启动 HEVI Gen Engine（CPU 默认构建）：

```bash
docker compose -f services/gen_engine/docker-compose.yml up -d --build
```

启动 MPT API/WebUI：

```bash
docker compose -f docker-compose.mpt.yml up -d --build
```

MPT Compose 会把 `MPT_API_KEY`、Pexels/Pixabay/Coverr、OpenAI 和 HEVI 地址传入容器，并映射 `host.docker.internal`。MPT 的容器配置文件由 `MPT_CONFIG_PATH` 指定，不会误读镜像内另一份 `config.toml`。

## 素材供应链

`hevi-media resolve --type image|video` 使用真实链路：

1. 检查已有台账复用；
2. 本地库优先；
3. image 使用 Pexels，video 使用 Pexels/Pixabay/Coverr/Archive.org；
4. 将远程结果原子下载到 `MATERIAL_CACHE_DIR`；
5. 只有存在且非空的本地文件才会交付，并写入台账。

因此缺少 Pexels key 不会让“素材机制”失效：视频仍可尝试 Pixabay、Coverr 和无需 key 的 Archive.org；但 Pexels 图片没有 key 时会明确失败，而不是返回一个不能生产使用的远程 URL。

