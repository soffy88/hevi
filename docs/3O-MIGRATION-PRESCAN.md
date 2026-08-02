# Hevi 3O 范式迁移前静态探查报告

> 探查时间：基于当前工作区快照
> 范围：`hevi/` 目录全部 Python 源码（AST 静态解析，不含测试）
> 目的：为 3O（oskill/omodul/oprim/obase）范式迁移提供依赖、Patch、安全与死代码基线

---

## 0. 结论摘要

| 维度 | 关键结论 |
|------|----------|
| 依赖 | 顶层 65 个模块、466 条 import 边；基石：`db`/`core`/`cost`/`subjects`；汇聚点：`api`（出度 36） |
| Patch | 所有 o* 库侵入改写集中在 **`pipeline/longvideo_orchestrator.py`** 一个文件（3 处钩子注入 + 1 个代理类） |
| PII | **无问题**：`decision_trail` 不存在（实为 `debug_context`），唯一指纹 `vault/service.py:_manifest_hash` 不接收身份标识 |
| 死代码 | `hevi/livestream/` 仅剩 `__pycache__`，源文件已删除；另有 22 个零引用模块 |
| 重复实现 | TTS 4 套并存、视频装配 3 套并存，功能重叠度高 |

**迁移最高风险对象：`hevi/pipeline/longvideo_orchestrator.py`** —— 唯一同时触及 4 个 o* 库的文件，建议作为 3O 迁移首个改造对象。

---

## 1. 依赖矩阵扫描

### 1.1 说明

- 实际顶层子目录 **65 个**（任务描述中"68 个"不精确，另有 `__pycache__` 非模块）。
- 扫描方式：AST 解析 `from hevi.X import ...` / `import hevi.X`，聚合到顶层模块级，去重后统计。

### 1.2 入度 Top 10（被依赖最多 → 迁移需最先稳固/替换的基石）

| # | 模块 | 入度 |
|---|------|------|
| 1 | `db` | 13 |
| 2 | `core` | 11 |
| 3 | `cost` | 11 |
| 4 | `subjects` | 11 |
| 5 | `video` | 9 |
| 6 | `production` | 7 |
| 7 | `tongjian` | 7 |
| 8 | `audio` | 7 |
| 9 | `tasks` | 6 |
| 10 | `assembly` | 6 |

### 1.3 出度 Top 10（最依赖他人 → 迁移改动面最大）

| # | 模块 | 出度 |
|---|------|------|
| 1 | `api` | 36 |
| 2 | `db` | 13 |
| 3 | `pipeline` | 12 |
| 4 | `tasks` | 12 |
| 5 | `director` | 8 |
| 6 | `mcp` | 7 |
| 7 | `vault` | 7 |
| 8 | `tongjian` | 6 |
| 9 | `audio` | 5 |
| 10 | `cinematic` | 5 |

### 1.4 孤立死模块（入度 = 出度 = 0，无任何引用）

`agent`, `agent_runtime`, `ai_models`, `analysis`, `assets`, `blocks`, `deploy`, `design`, `enhancement`, `job_queue`, `livestream`, `media`, `memory`, `n0`, `preparation`, `prompts`, `publisher`, `qnlr`, `scripts`, `services`, `skills`, `utils`

→ 共 22 个模块无任何模块间引用，迁移时可直接判断移除或纳入新范式。

---

## 2. 硬编码与 Patch 扫描（oskill / omodul / oprim / obase）

### 2.1 总览

所有 o* 库引用集中在 **`hevi/pipeline/longvideo_orchestrator.py`**。未发现 `setattr` 式全局 Monkey Patch，但存在 3 处等价于 Patch 的运行期钩子替换 + 1 个包装代理类。

### 2.2 具体位置

| # | 位置 | 对象 | 手段 | 动机 |
|---|------|------|------|------|
| 1 | `longvideo_orchestrator.py:385-410` | `oskill.storyboard_planner` | `patched_storyboard_fn` + `ScriptWrapper` 代理类（`__getattr__` 转发 + 内置 `model_dump()` 绕行） | 规避 oskill 内部 Pydantic 赋值校验 bug（SaaS-2/P10.F2） |
| 2 | `longvideo_orchestrator.py:421-456` | oskill 的 script_writer / storyboard_planner / shot_generator | `_providers_script_fn` / `_providers_storyboard_fn` / `shot_gen_fn` 钩子整体替换 | `locked_shot_list` 存在时跳过 oskill 重规划，锁定数据为唯一真相源（SPEC-003） |
| 3 | `longvideo_orchestrator.py:580+` | `oprim.video_generate` 硬编码分发 | `injected_video_fn` 直接使用 `obase.provider_registry.ProviderRegistry` 逐镜头路由 | 绕过 oprim 硬编码 dispatch，支持 registry 覆盖与混沌演练（SaaS-3/P10.F3） |
| 4 | `longvideo_orchestrator.py`（同文件） | omodul 音频侧 | `injected_audio_fn` / `emotion_aware_voiceover` 分支 | 情感感知配音与按角色分配音色 |

### 2.3 继承 / 重写

- 全项目仅 `ScriptWrapper` 一个代理类，**未发现对 o* 类的直接继承**。
- obase 组件使用面：
  - `from obase.persistence import PgPool`（hevi/db/pg_pool.py、hevi/vault/ 等）
  - `from obase.provider_registry import ProviderRegistry`（hevi/vault/identity_pack.py、hevi/tongjian/ 下 7 处、hevi/video/capability_guard.py 等）

---

## 3. PII 与指纹安全扫描

### 3.1 decision_trail

**不存在实际字段。** 出现位置：

| 位置 | 类型 | 内容 |
|------|------|------|
| `hevi/tongjian/schemas.py:251` | 注释 | INC-001 §K 说明 |
| `hevi/tongjian/scene_render_avatar.py:1026` | 注释 | INC-001 §K 说明 |
| `tests/test_tongjian_scene_render_avatar.py:1376` | 测试 | §K 用例 |
| `tests/test_production_execution_bridge.py:24` | 测试 | 断言 |

实际落库字段名为 **`debug_context: dict`**（`ShotFrame`），内容为 style / emotion / action_beats / phases / lead 等**渲染决策**，不含任何身份标识。

### 3.2 fingerprint

全项目唯一的指纹计算为 **`hevi/vault/service.py:_manifest_hash()`**（L38-43）：对「排序后的 `relpath:sha256` 拼接串」做 sha256 的内容寻址指纹；`hevi/vault/blob_store.py` 的 sha256 对象名去重同理。

**扫描结论：**

- `vault/service.py` 中**无任何 user_id / student_id 参数**，指纹输入仅为文件内容，不含身份信息。
- 项目中**未发现 student_id 相关代码**。
- **当前无 PII 直传指纹/决策轨迹的问题。**

### 3.3 迁移提醒

`hevi/api/` 全目录（出度 36）大量经 `get_current_user` 获取 user_id。3O 迁移时需保证 user_id 不流入新的 `debug_context` / fingerprint 字段，建议在 schema 层固化白名单。

---

## 4. 死代码与重复实现扫描

### 4.1 hevi/livestream/ 实际内容

**只剩 `__pycache__/`**，源文件已删除：

```
hevi/livestream/__pycache__/__init__.cpython-314.pyc
hevi/livestream/__pycache__/scheduler.cpython-314.pyc
hevi/livestream/__pycache__/livestream_service.cpython-314.pyc
```

→ **确认为死代码目录。** 但 `hevi/api/routers/pro_studio.py:130-176` 仍暴露 4 个 livestream API 路由（`GET/POST /livestream/capabilities|start|stop|status`），全部走 503 `CAPABILITY_UNAVAILABLE` 占位。迁移时应删除这些路由或明确保留为能力占位。

### 4.2 TTS 合成重复实现（4 套并存）

| 实现 | 位置 | 机制 / 特征 |
|------|------|-------------|
| vibevoice | `hevi/audio/tts_service.py`（`vibevoice_synthesize` / `synthesize_dialogue`） | subprocess 子进程隔离（`vibevoice_worker.py`），GPU 显存回收 |
| cosyvoice | `hevi/audio/cosyvoice_service.py` | ProviderRegistry 默认 provider（P0） |
| edge-tts 词级字幕 | `hevi/explainer/voiceover.py`（`_synthesize` / `synthesize_storyboard`） | 自带 WordBoundary 字幕与独立 ffprobe 时长探测 |
| edge-tts cue 合成 | `hevi/dub/_synth.py`（`synth_cues_edge_tts`）+ `hevi/audio/voicebox_service.py` | 独立实现 |

另：`hevi/tongjian/voiceover.py`（`_synthesize_line` / `synthesize_voiceover` / `build_voiceover`）是聚合编排层，通过 `tts_fn` 依赖注入复用以上 provider，但自带 `_short_hash` / `_audio_filename` / 时长 / 响度 / CER 全套自有逻辑。

**典型重复**：edge-tts 路径在 `explainer/voiceover.py`、`dub/_synth.py`、`tongjian/voiceover.py` 三处各有实现；音频后处理（probe 时长、响度归一）在 tongjian 与 explainer 各写一份。

### 4.3 视频装配重复实现（3 套并存）

| 实现 | 位置 | 特征 |
|------|------|------|
| 主装配器 | `hevi/assembly/assembler.py`（`assemble_longvideo`、xfade 链、亮度归一、broll） | 最完整 |
| tongjian 装配 | `hevi/tongjian/assemble.py`（`build_final_video`、SRT 字幕、zoompan、黑帧/clipping 门禁） | 独立 ffmpeg 全链路，与 assembler **互不调用** |
| avatar 渲染 | `hevi/tongjian/scene_render_avatar.py`（自带 scale/crop/fps 过滤链）+ `hevi/dub/_mux.py`（`mux_audio_into_video`） | 第三套 ffmpeg 拼装 |

→ **assembly vs tongjian 两套 `assemble_longvideo` / `build_final_video` 均为全量 ffmpeg 装配，功能重叠度高。** 3O 迁移建议以 `hevi/assembly/assembler.py` 为新范式基底，tongjian 侧收敛为参数 / 编排层。

---

## 5. 迁移建议（按优先级）

1. **P0 — 改造 `hevi/pipeline/longvideo_orchestrator.py`**：将 3 处 o* 钩子注入与 `ScriptWrapper` 代理迁移为新范式原生能力，消除运行期 Patch。
2. **P0 — 收敛视频装配**：以 `assembly/assembler.py` 为唯一装配实现，`tongjian/assemble.py` 改为调用方。
3. **P1 — 收敛 TTS**：统一到 ProviderRegistry audio provider 体系，删除 explainer/dub 侧重复 edge-tts 实现。
4. **P1 — 清理死代码**：删除 `hevi/livestream/`（含 `pro_studio.py` 中 4 个占位路由）；对 22 个孤立模块逐一确认保留/移除。
5. **P2 — 依赖重构**：`api`（出度 36）与 `pipeline`（12）应在迁移中分层，降低对 `db`/`core` 的直接耦合。
