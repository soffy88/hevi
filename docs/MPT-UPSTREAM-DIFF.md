# MoneyPrinterTurbo 上游快进

- 对照 clone: `docs/ref-repos/MoneyPrinterTurbo`
- 生产副本: `services/mpt`（保留 hevi 的 `config.toml` 与 `README.md`）
- 旧 rev: `6cd36b5`
- 新 rev: `eb8c237` (`feat(material): add native Seedance provider`)
- 跨度: 25 commits (`6cd36b5..eb8c237`)

## 值得注意的上游变化

| 主题 | 提交 | 对 hevi 的含义 |
|---|---|---|
| 原生 Seedance 素材 | `eb8c237` | `app/services/volcengine_seedance.py`；可作导演/快通道素材源 |
| OpenRouter LLM | `#1277` / `df3df0b` | LLM 网关又多一家 |
| APIMart | `ab1c790` | 又一个聚合网关 |
| 脚本清洗贪婪正则吃正文 | `#1270` | 文案括号/方括号被整段吃掉的修 |
| TTS 音频 clip 泄漏 | `#1269` | elevenlabs/chatterbox/fish_audio `AudioFileClip.duration` finally 关闭 |
| 真实文件测音频时长 | `#1263` / `b4c2810` | 不再信 SubMaker cue |
| SiliconFlow 字幕尾被截 | `#1268` | 字幕时间轴钉到整段音频 |
| Redis 空密码 | `#1266` | URL 不拼空 auth |
| Content-Disposition 文件名 | `#1265` | 交给 FileResponse |
| 批处理清单体积报错文案 | `#1264` | CLI 可读单位 |

## hevi 侧未改动的覆盖层

- `services/mpt/config.toml` — hevi 基础设施对接
- `services/mpt/README.md` — fork 说明
- `docker-compose.mpt.yml` — 容器编排（仓库根，不在上游树里）

API 路由 `GET/POST /api/mpt/*` 现已挂到 `hevi/api/main.py`（此前 `hevi/api/routers/mpt.py` 未 include）。

Hevi canonical 入口为 `POST /api/mpt/production`：MPT 只负责外部生成，Hevi
`TaskService` 负责排队/轮询、`ArtifactManifest` 负责多视频产物回流，质量结果写入
统一 task `config_json`；旧的 `/api/mpt/generate` 保留给兼容调用方。

适配器兼容当前 MPT 的 `/api/v1/video/videos`、`/api/v1/video/tasks/{id}` 和
`{status,data}` 响应，也兼容旧 sidecar 接口。MPT 返回的 `/tasks/...` 成片在共享卷
不可见时会自动下载到 Hevi 任务目录；部署时可设置 `MPT_API_BASE`、可选的
`MPT_API_KEY`，共享卷场景可设置 `MPT_HOST_STORAGE`。
