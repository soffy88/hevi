# RFC-004：出品模式、自动主线与数字人能力收敛

- 状态：已实施 M1、M2 边界和 M4 Presenter MVP；M3 适配器后期执行迁移持续进行
- 日期：2026-07-31
- 范围：产品入口、API 边界、执行状态、数字人（Presenter）能力

## 1. 决策

Hevi 有且仅有两种制作控制模式：

1. **导演台（Studio）**：用户设定、审阅、修改并选择后再执行的人工控制面。
2. **自动流水线（Pipeline）**：按策略自动完成规划、生成、质检、返工和交付的无人值守主线。

通鉴、短剧、解说不是第三种制作引擎；它们是自动流水线的**内容适配器**。它们只保留自己不可替代的前期建设能力，并把通用制作与交付交给自动流水线。

```
导演台（人工选择） ────────────────┐
                                  ├── 自动流水线的通用生产能力 ── Task ── 成片
通鉴 / 短剧 / 解说（内容前适配） ──┘
```

## 2. 资源职责

| 资源 | 唯一职责 | 不负责 |
|---|---|---|
| `Work` | 导演台中的人工制作工作区：素材、草稿、人工锁定与镜头编辑 | 自动模式的持久状态、实际执行状态 |
| `Run` | 内容适配会话：前期解析、领域配置、转交给流水线的输入 | 独立生成队列、独立成片状态 |
| `Production` | 统一生产单：执行策略、质量/预算约束、输入清单与输出目标 | 某一页面的草稿数据 |
| `Task` | `Production` 内可计费、可重试、可追踪的执行单元 | 保存前期会话或 UI 状态 |
| `Graph` | Canvas 的镜头/流程 IR | 另一种任务或成片模型 |
| `Subject` | 角色、肖像、产品或场景的资产身份 | 运行期的数字人口播配置 |
| `Presenter` | 可说话的出镜主体：形象、声音、动作/镜头表现、口型策略 | 剧情角色资产的替代品 |

短期允许 `Production` 由现有 `video_tasks` 承载；新增抽象前，所有模式至少必须归并到同一 `Task` 生命周期、计费、质量报告与交付模型。

## 3. 出品模式与适配器

| 模式 | 用户输入 | 专属前期 | 通用后期 |
|---|---|---|---|
| 导演台 | 人工填写/编辑的创作设定 | 概念、剧本、设计清单、分镜的逐级编辑和确认 | 调用自动流水线执行已锁定方案 |
| 自动单片 | 一句话或结构化创作意图 | 自动意图解析与最小计划 | 自动规划、生成、裁决、装配 |
| 通鉴 | 历史原文/材料 | 史料解析、文言转白话、史实/叙述规则 | 解说或演绎模式调用自动流水线 |
| 短剧 | 小说、剧本或故事梗概 | StoryGraph、季/集规划、角色绑定与资产准备 | 每集调用自动流水线 |
| 解说 | 一句话、主题或材料链接 | 自动扩写脚本和轻量视觉规划 | 解说配置调用自动流水线 |

### 3.1 不可违反的规则

- 内容适配器不得拥有第二套生成、质量裁决、预算熔断、重试或交付逻辑。
- 导演台可以人工覆盖流水线决策；覆盖后的执行仍由同一生产能力完成。
- 所有产物必须能从 `Task` 查到状态、成本、质量报告、镜头和最终媒体。
- `Run` 不能只存内存。重启后必须可查询、恢复或明确标为已失效。

## 4. 数字人：Presenter 一等能力

数字人不是单个 `avatar_portrait` 路径字段，也不是通鉴专属的 `cloud_avatar` 模型选项。它是所有出品模式可选择的表现形式。

### 4.1 Presenter 定义

```text
Presenter
├── identity: subject_id（可选；复用角色/肖像资产）
├── appearance: portrait/reference set、服装、背景/机位偏好
├── voice: voice_profile_id、语言、音色、语速、情绪策略
├── performance: presenter | narrator | character_dialogue
├── motion: still | talking_head | half_body | full_body | picture_in_picture
├── lipsync: native_audio | dedicated_lipsync | avatar_provider | none
└── delivery: aspect_ratio、字幕、B-roll 插入策略
```

其中 `Subject` 管“这个人是谁”；`Presenter` 管“这个人怎样出镜和说话”。一个 Subject 可有多个 Presenter 预设，例如新闻主播、历史讲述者、剧情角色。

### 4.2 三种表现策略

| 策略 | 适用 | 当前能力的归位 |
|---|---|---|
| `picture_in_picture` | 解说、课程、新闻 | 现有 Duix 头像 + B-roll 合成 |
| `talking_scene` | 通鉴演绎、短剧对白 | 现有 cloud avatar / 原生音画模型 |
| `voice_over` | 空镜、非出镜旁白 | TTS + 视频镜头，不要求口型 |

数字人供应商是 L1/L0 可路由能力。选择供应商的依据是表现策略、语言、预算、身份一致性和口型质量，而不是由页面直接写模型名。

### 4.3 质量与降级

- 有台词且人物出镜：必须声明口型策略并产出 ASR/口型质量结果。
- 口型不合格：优先重试同镜头；超过预算后降级为 `voice_over + reaction/B-roll`，不得静默生成“人物张口但声音不符”的成片。
- 数字人生成失败：可降级为空镜/旁白，但该降级必须进入 `Task` 的质量报告与最终交付说明。
- Presenter 的形象、声音和动作必须可追溯到资产版本与 provider 参数。

## 5. API 目标边界

目标 API 仅表达领域意图，不暴露平行执行引擎：

```text
/api/studio/works                 # 导演台人工工作区
/api/pipeline/productions         # 自动流水线生产请求与状态
/api/tongjian/runs                # 通鉴前期适配会话，最终关联 production/task
/api/shortdrama/runs              # 短剧前期适配会话，最终关联 production/task
/api/explainer/runs               # 解说前期适配会话，最终关联 production/task
/api/presenters                   # 数字人预设与测试
/api/tasks                        # 统一执行、成本、质量、镜头与媒体交付
/api/canvas                       # 唯一 Graph/IR 接口
```

迁移期兼容：

- `/api/tasks/longvideo` → `/api/tasks`；标记弃用。
- `/api/canvas/graphs/*` → `/api/canvas/*`；标记弃用并在前端/SDK 停止使用。
- `/api/director-pipeline` → `/api/studio`；先增加新前缀，旧路由保留兼容期。
- `/api/director` → 自动单片的入口，内部创建自动 `Production`；不再成为独立生产链。

## 6. 实施顺序

### M1：边界与可观测性（不改变用户能力）

1. 自动从 OpenAPI 导出 API 清单，给接口标记 `canonical`、`compatibility`、`internal`。
2. 清理 Canvas 和任务的重复路由，保留明确的弃用别名。
3. 为通鉴、短剧、解说 `Run` 持久化 `status`、`production_id/task_ids`、错误和恢复点。
4. 所有模式最终任务统一返回相同的状态、成本、质量、镜头与交付投影。

### M2：自动流水线契约

1. 提取 `PipelineProductionRequest`：内容、资产、StylePack、预算、质量、交付与 Presenter 配置。
2. 让自动单片、通鉴、短剧、解说只构造此请求。
3. 将通鉴/短剧/解说的后期执行、重试与交付迁至该契约。

### M3：导演台与自动化共用执行

1. 导演台锁定分镜后编译为同一 `PipelineProductionRequest`。
2. 自动模式将人工锁定步骤按策略自动完成并记录决策。
3. 统一质量门、预算熔断和返工协议。

### M4：Presenter MVP

1. 新建 Presenter 模型/API，引用 Subject 与语音资产。
2. 先支持 `picture_in_picture` 与 `voice_over`，将现有 `avatar_portrait` 映射为临时 Presenter。
3. 接入 `talking_scene`，输出可审计的口型/ASR 结果与降级原因。
4. 在导演台、通鉴、短剧、解说共用 Presenter 选择器与策略配置。

## 7. 验收标准

- 用户能明确区分“我要人工导演”与“我要一键自动出片”。
- 通鉴、短剧和解说的页面只展示自身前期差异，后期状态统一来自 Production/Task。
- 任一成片都能追溯到输入、资产、Presenter、模型路由、成本、质量门和返工历史。
- 任一数字人成片都能说明：谁出镜、用谁的声音、何种口型策略、失败时如何降级。
- API 能力清单与运行中的 OpenAPI 一致，兼容接口不会被误认为新增主能力。

## 8. 当前实现状态

- `AutomationRun` 已落库；解说使用完整持久化状态，通鉴/短剧已接入状态快照和重启后的查询兜底。
- 通鉴和解说适配器现在会创建共享 `video_tasks` 投影，并回写运行中/失败/完成进度及最终媒体路径；适配器仍保留自己的领域状态。
- 通鉴/解说启动后不再直接挂接各自后台渲染函数，而是由 `TaskService.run_task()` 按 `production_source` 分发到适配器执行器；统一任务生命周期负责启动、失败和完成回写。
- `ProductionRequest` 是自动任务和 `/api/pipeline/productions` 的统一输入，编译到现有 `TaskService` 生命周期。
- 导演台 `/api/director/episodes` 和 Canvas `/api/director/render` 已以 `source="studio"` 编译到同一生产契约；旧测试替身仍保留兼容调用。
- Presenter 已提供用户隔离的 CRUD、配置就绪检查、Subject/voice 引用、出镜/动作/口型/交付策略字段，并有独立数据库迁移。
- 通鉴/短剧的丰富前期仍保留在各自适配器；其全部后期执行、质量报告和交付统一迁移仍是下一阶段工作，不在本次改动中虚报为已完成。
