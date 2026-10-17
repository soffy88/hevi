# VideoAgent 能力内化

HEVI 内化的是 VideoAgent 的控制能力，而不是复制其模型、依赖或运行时：

`用户意图 → 类型化 DAG → 视频证据索引 → 时间戳 EvidenceRef → HEVI 时间线 → 质量/产物门禁`

## 能力边界

- 意图分析：把显式需求、隐含约束、画幅/时长和缺失输入规范化为 `VideoIntent`。
- 图规划：由确定性编译器生成 `VideoAgentPlan`，包含节点、端口、依赖、边、工具和副作用。
- 细粒度视觉查询：把分镜/脚本编译为 `EvidenceQuery`，支持时间窗、模态、目标时长和 top-k。
- 视频记忆：把本地视频、字幕或调用方注入的转写/视觉描述写入 SQLite，保存源文件 SHA-256、时间段、来源、许可和 embedding。
- 证据检索：返回结构化 `EvidenceRef`；剪辑节点只能消费证据引用，不能消费不可追溯的搜索字符串。
- 执行闭环：规划、反思、执行、报告、指纹和本地产物清单均由 HEVI 事务负责。
- 失败语义：`NeedsInput` / `blocked` / `failed` / `completed` 分离；没有字幕、视觉描述或可用 provider 时不会伪造理解结果。

## 入口

- `POST /api/montage/video-agent/plan`：只规划，不写媒体产物。
- `POST /api/montage/video-agent/run`：默认只生成计划；显式传 `execute=true` 才执行。
- 工具：`video.agent.plan`、`video.agent.run`、`video.evidence.index`、`video.evidence.search`、`video.script.from_transcript`、`video.qa`、`video.summary`。

## provider 接入

ASR、VLM、重型 embedding 和 LLM 均位于注入边界：

- `VideoIntentCaller` 只能增强意图和查询，不能直接发出可执行代码或工具图。
- 证据索引可接收带时间戳 `transcript` / `segments`；没有注入结果时只建立时间窗口，语义检索会阻断。
- `video.qa` 只有在注入 QA caller 后才回答事实问题；否则返回阻断状态。
- HEVI 的本地 timeline、质量门禁、ArtifactManifest 和 delivery gate 仍是唯一产物出口。

## 与上游 VideoAgent 的继承关系

继承其“意图—图—证据—反馈”的方法论，落地为 HEVI 的 3O 分层：

- `oprim`：类型合同、端口校验、查询和指纹。
- `oskill`：意图推断、确定性图编译、候选重排、反思。
- `omodul`：SQLite 证据事务、搜索事务、VideoAgent 执行事务。
- HEVI `studio` / `production`：工具注册、可编辑时间线、质量门禁和产物交付。

上游的模型下载、硬编码数据集目录、交互式 `input()`、字符串化搜索结果和未审计的 MoviePy 直连不进入 HEVI 核心。

## 最小调用示例

```json
{
  "requirement": "从本地视频中找出产品展示片段，剪成 9:16 的 30 秒短片",
  "source_path": "/data/media/source.mp4",
  "segments": [
    {"start_s": 12, "end_s": 18, "transcript": "产品展示", "caption": "手持产品近景"}
  ],
  "target_duration_s": 30,
  "aspect_ratio": "9:16",
  "execute": false
}
```

执行前必须提供可用素材与脚本/转写，执行后必须有本地视频文件和 `ArtifactManifest`。这使 VideoAgent 的能力成为 HEVI 的可恢复业务事务，而不是一次性 agent demo。
