# 火宝短剧 (huobao-drama v4.x) vs HEVI 智能体层对比调研评估 (HUOBAO_EVAL)

- 上游来源：`/data/soffy/refs/huobao-drama` (chatfire-AI/huobao-drama v4.x)
- 许可证：CC BY-NC-SA 4.0（已在 `docs/third_party/provenance-ledger.yaml` 登记 NC 限制）
- 调研目标：吸收火宝 4 个 Mastra 智能体（`script_rewriter`、`extractor`、`storyboard_breaker`、`prompt_generator`）的设计精髓，与 Hevi 既有架构对比，找差距、补短板，保持 Hevi 既有确定性与 3O 架构不退化。

---

## 一、智能体逐一深度对比

### 1. 剧本改写智能体：`script_rewriter` vs `hevi/shortdrama/screenwriter.py`

| 维度 | 火宝 `script_rewriter` | Hevi 现有 (`screenwriter.py` + `storygraph/chapters.py` + `review.py`) | 优劣判定与补齐要点 |
|---|---|---|---|
| **输入定位** | 纯文本小说/故事手稿 | 小说手稿 / StoryGraph 结构化图谱 | Hevi 输入更结构化，但缺乏轻量的一键语气改写器 |
| **产出规范** | 标准场景头：`## S编号 \| 内景/外景 · 地点 \| 时间段`，动作自然段，对白 `角色名：（状态/表情）台词内容` | `## SC001 内 · 地点 · 时间`，对白 `角色名 → 目标：台词`，事件摘要 | 格式接近。火宝的括号状态/表情便于指导人物演技和TTS情绪 |
| **语气风格把控** | 提示词驱动语气选择（悬疑反转、快节奏爽剧、幽默搞笑等），短视频戏剧节奏（30-60秒/场） | 主要靠 3-layer 审稿把控剧情与节拍，缺少显式语气模板选择（tone preset） | **火宝更灵活**：短剧对“爽点/反转/悬疑/甜宠”的语气风格有明确预设需求，Hevi 需补齐语气选择能力 |
| **台词保留机制** | 无硬性保留机制，易发生 LLM 自由发挥篡改、截断原著经典对白 | **Hevi 极强**：dramaplan r6 拥有严格的逐字台词保留机制、标点保护与 100% 覆盖率断言 | **Hevi 远胜**：火宝无台词安全守卫；Hevi 补齐语气改写时必须继续强制 dramaplan r6 逐字检查 |
| **缺漏项** | 缺乏确定性时长计算与回溯校验 | 缺少小说→分集剧本的一键语气定制（Tone Selection）改写接口 | **Hevi 需补**：支持 `tone` 选项的小说→剧本改写器，严格保障台词不丢失 |

---

### 2. 资产抽取与去重智能体：`extractor` vs `hevi/storygraph/extract.py`

| 维度 | 火宝 `extractor` | Hevi 现有 (`storygraph/extract.py`) | 优劣判定与补齐要点 |
|---|---|---|---|
| **抽取资产类型** | 角色（Character）、场景（Scene）、**道具（Prop）** 三类完整资产 | 角色（StoryCharacter）、地点（StoryLocation）、事件（StoryEvent）、引语（StoryQuote） | **火宝更完备**：火宝有关键道具（Prop）独立资产体系，Hevi 现有完全缺失道具管理 |
| **道具过滤三问** | **极其严密**：①删掉它剧情是否依然成立？②是否日常随手物品？③是否场景陈设？一集 0-3 个高价值道具 | 无道具概念 | **火宝完胜**：这套判定规则能避免道具泛滥，必须完整吸收进 Hevi |
| **场景描述规范** | **强约束**：场景图必须是**无人物纯背景空镜**（即使原剧本提到了人物活动也要剥离） | 地点仅作为事件元数据，未剥离人物生成无人物纯背景提示词 | **火宝更规范**：场景参考图如果有人物会破坏跨镜换角的一致性。Hevi 需吸收纯背景规则 |
| **跨集去重机制** | 支持跨集增量去重；角色/道具按名称+括号别名去重（如 `林小雨（主角）` 与 `林小雨` 合并）；场景按地点+时段合并 | StoryCharacter 支持 aliases 别名，但缺乏跨集资产注册表（Asset Registry）的持久化合并与更新机制 | **火宝更实用**：短剧连载必须有跨集资产去重与别名合并。Hevi 需补齐统一资产表与归一化逻辑 |
| **参考资产图** | 输出字段供提示词生成 Agent 生图 | 依赖外部，未生成资产参考卡 | **Hevi 需补**：三类资产自动生成 CPU 国风动漫风格的参考 keyframe |

---

### 3. 分镜拆解智能体：`storyboard_breaker` vs Hevi `dramaplan` (`script_to_storyboard`)

| 维度 | 火宝 `storyboard_breaker` | Hevi 现有 (`review.py:script_to_storyboard`) | 优劣判定与补齐要点 |
|---|---|---|---|
| **分镜段落定义** | 1 个段落 = 1 个生成任务（8-15秒），内含 2-4 个子镜头（可切景别不跨场景） | 基于预算切为单镜头（Shot），支持基于可读字数的动态时长 | 概念略有差异：火宝偏向大模型单任务生成多子镜头，Hevi 是镜头级（Single Shot）精准控制 |
| **时长锚定与公式** | 目标时长 = 字数 ÷ 500字/分；段落时长 ≥ 台词字数 ÷ 4.5 + 2s 余量 | 段落时长 ≥ max(MIN_SHOT_DURATION_S, 朗读字数 / 3.0)，按场景预算缩放 | 两者思想一致，火宝公式简单直接，Hevi 计算更精细 |
| **资产与引用绑定** | 明确关联 `character_ids`、`prop_ids`、`scene_id`，并在 prompt 中使用 `@角色名`、`@场景名`、`@道具名` | 记录 speaker 与 event_id，但 prompt 为纯自然语言描述，无结构化 `@引用` | **火宝更结构化**：`@引用` 是视频与生图控制资产一致性的核心关键。Hevi 必须全面吸收 `@角色`、`@场景`、`@道具` 语法 |
| **执行可靠性** | 纯 LLM 多轮工具调用，容易丢镜头、超时或漏保存 | **纯确定性算法**：`_plan_scene_shot_counts`、标点二分、贪心合并，100% 不丢台词 | **Hevi 完胜**：Hevi 的底层逻辑更稳健，只需在 prompt 组装中注入 `@引用` 与资产 ID 绑定 |

---

### 4. 提示词生成智能体：`prompt_generator` vs Hevi keyframe prompt translator

| 维度 | 火宝 `prompt_generator` | Hevi 现有 (`prompt_translator.py` / `build_scene_prompt`) | 优劣判定与补齐要点 |
|---|---|---|---|
| **双层提示词体系** | 1. 资产参考图最终提示词（角色三视图、场景纯空镜、道具白底单品）<br>2. 分镜视频提示词（将 `@角色` 解析挂接对应素材标记） | 单一镜头描述直出（通过正则字典与 LLM 翻译） | **火宝体系更成熟**：资产卡与分镜提示词解耦，通过 `@引用` 自动挂接参考图，是短剧工业化的标准流程 |
| **跨镜一致性保证** | 替换 `@角色名` 为 `@图片1角色` 挂接上游生图 API 的参考图 | 靠固定主角 identity tokens（如 `black hair, robe`）拼接在末尾 | **火宝思路优于 Hevi**：Hevi 目前在 CPU 运行下缺少参考图挂接机制，应支持 `@引用` 解析为特定资产的固定 Seed 和视觉描述注入 |
| **离线与 CPU 适配** | 依赖第三方生图/视频云端多模态 API（Seedance, Wan, MiniMax） | 本地 CPU SD-Turbo / SDXL-Turbo / ComicNarr 渲染链路 | **Hevi 本地能力强**：火宝完全无法离线运行。Hevi 吸收其 prompt 生成与引用解析机制，结合 CPU 国风动漫风格预设落地 |

---

## 二、工作台交互与 API 功能对比

火宝在工作台具备三项关键工程保障能力：
1. **批量生成前确认与预估**：
   - 火宝：在提交前列出镜头数、总时长、模型、分辨率，确认后再批量跑。
   - Hevi 现有：直接调用 workflow，缺乏一次性给出（镜头数、预估总时长、预计 CPU 耗时、资源预警）的快速预估 API。
   - **Hevi 需补**：`POST /api/huobao/estimate`（镜头数、总时长、预估 CPU 耗时）。
2. **失败镜头一键重试（Retry Failed Shots）**：
   - 火宝：单个分镜失败可独立重试，不影响其他镜头，也不重新从头生成。
   - Hevi 现有：comicnarr 有 breakpoint 缓存但接口未暴露精细化单镜重试状态。
   - **Hevi 需补**：`POST /api/huobao/retry`，精确只重新渲染状态为 failed 的镜头。
3. **合并前校验文件存在（Merge Pre-Check）**：
   - 火宝：合并视频前先校验每个镜头 clip 文件真实存在且大小非零，防止 ffmpeg concat 挂死或画面黑屏。
   - Hevi 现有：部分代码假设文件存在，缺失时抛 ffmpeg 底层异常，缺乏明确友好的前置校验。
   - **Hevi 需补**：`POST /api/huobao/merge` 前置文件存在性检查，缺失即抛出明确业务错误。

---

## 三、吸收与落地决策（Hevi 补强规划）

不推翻 Hevi 既有架构与 dramaplan 经受住测试的确定性算法，在 `hevi/huobao/` 下建立干净、纯净的适配层，并挂载 API 路由：

1. **统一资产表与跨集去重 (`hevi/huobao/assets.py`)**：
   - 角色（Character）、场景（Scene）、道具（Prop）三类实体。
   - 名称归一化与别名括号合并（如 `沈砚之（男主）` -> `沈砚之`），跨集去重。
   - 道具过滤三问算法，单集关键道具严格控制在 0-3 个。
   - 场景纯背景生成规则（严格剥离人物）。
2. **资产参考图生成 (`hevi/huobao/keyframes.py`)**：
   - 纯 CPU 运行，使用本地 SD-Turbo + 国风动漫 `guofeng_anime` 预设。
   - 为每个资产生成一张标准参考图（角色半身/面部，场景纯空镜，道具白底/特写）并分配固定一致性 Seed。
3. **分镜 `@引用` 解析与跨镜一致性 (`hevi/huobao/refs.py`)**：
   - 解析分镜 prompt 中的 `@角色`、`@场景`、`@道具`。
   - 不存在的引用抛出校验异常（严格防御幻觉）。
   - 渲染时将 `@引用` 自动替换为该资产的标准视觉 Token 并绑定固定资产 Seed，保证同一角色在不同分镜中外貌与服饰一致。
4. **小说→分集剧本改写与语气选择 (`hevi/huobao/rewrite.py`)**：
   - 支持 `tone` 参数（`suspense` 悬疑反转 / `fast_paced` 紧凑爽剧 / `classical` 古风沉浸 / `emotional` 虐恋深情 / `witty` 诙谐幽默）。
   - 遵循标准场景头与对白格式。
   - 继承 dramaplan r6 逐字台词保留检查，确保 100% 不丢台词。
5. **API 与批处理调度 (`hevi/huobao/batch.py` + `hevi/api/routers/huobao.py`)**：
   - 预估接口（镜头数、时长、CPU时间预估）。
   - 失败镜头重试（只重跑指定/失败镜头）。
   - 合并前文件存在性校验。
