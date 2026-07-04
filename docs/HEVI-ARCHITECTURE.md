# Hevi 总纲 —— 系列化视频的自动化制片厂

- **状态**: **Canonical SSOT(唯一依据来源)** · 修订 2026-07-03
- **效力**: 本文件是后续所有开发的**唯一依据**。与任何旧文档、代码注释、或记忆冲突时,**以本文件为准**。
- **可信度**: 所有状态标注(✅/◐/❌)均经**代码级核验**(附 `file:line` 证据),非愿景自评。
- **一句话**: Hevi 不是 AI 视频创作工具(那是 Runway),是**"系列化视频的自动化制片厂"**——输入剧情,输出"同一个 IP 的第 N 集",**质量有下限、成本有上限**。

图例:✅ 真实可用 · ◐ 部分/存在但未接线 · ❌ 无 · 🛒 外采(→ oprim/3O,热替换) · ❌否 否决

**附属权威子规范**(本文件引用,实现细节以其为准):`specs/3O-new-elements-manifest.md`(上游新元素 + 21 补丁)· `specs/SPEC-oprim-new-primitives.md`(新原语接口)· `specs/RFC-001-longvideo-quality.md` · `specs/RFC-003-omodul-shot-concurrency.md`。

---

## 0. 前置判断:视频生成能力的商品化分界线(12–18 个月)

所有取舍从这条趋势判断推导。

**会被模型层吃掉(不自建,租 + 热替换)**:
- 单镜头画质、物理合理性 —— 每季度换代,自建即贬值。
- lip-sync —— Veo3 已原生音画,Kling/海螺跟进;独立 lip-sync 在 fal 按秒计价,已是水电煤。
- 运镜控制 —— 正从"专门功能"退化为"prompt 一句话"。
- 特效(Pikaffects 类)—— 纯模型能力。

**模型层永远吃不掉(这是 hevi 该建的)**:
- **跨镜头/跨集的叙事与身份一致性** —— 资产管理问题,不是生成问题。
- **成片质量的裁决与定向返工** —— 模型不会知道自己砸了。
- **成本感知的多 provider 路由** —— provider 越卷价,路由层价值越大。
- **人在环上的编排** —— 谁决定重拍哪镜头、何时花钱上 Veo3、何时本地 Wan 凑合。

**设计总纲**:凡生成能力,一律外采并可热替换;Hevi 本体是**编排·资产·裁决·路由**四件事。竞品每发新模型,对纯生成工具是威胁,对本架构是**供给侧利好**(能力矩阵多一行)。这是唯一"模型进步越快、位置越稳"的结构。

---

## 1. 北极星

一个用户能否在**不碰任何参数**的情况下,稳定产出"同一个角色、同一风格的**第 47 集**",且**单集废片率 < 5%**。

要求 **角色一致性 × 风格固化 × 流程编排 × 质量闭环** 四者同时成立。

> **现状校验(2026-07-04 更新)**:四地基里"质量闭环"此前是装饰性的(双变体选优接文本 LLM 而空转);**2026-07-04 已打通第一环**——本地 VLM(C2)+ 身份向量(C1)+ 评分卡(C4)让双变体在角色锁定时**按身份真·图对图选优**。剩下把评分卡升为独立审片阶段 + verdict→返工闭环(C3)。这也是订阅制(按月产能)而非积分零售的唯一支撑形态。

---

## 2. 五层架构(核验总分)

```
L4 导演层    Producer / Director / Editor(Agent,MCP 之上的编排)          [核验 ~15%]
L3 裁决层    hevi-verdict(VLM 审片 → 评分卡 → 过/定向重拍/熔断)          [核验 ~5%]
L2 资产层    Subject / Series / StylePack / Template(一致性的载体)        [核验 ~30%]
L1 执行层    逐镜头生成 + checkpoint + 装配(现有管线,基本不动)          [核验 ~60%]
L0 供给层    Provider 能力矩阵 + 成本感知路由 + 余额探针 + 三层预算熔断     [核验 ~25%]
```

| 层 | 一句话现状 |
|---|---|
| L1 | 核心管线 ✅;**双变体校验已真·图对图选优(2026-07-04,角色锁定时)**;镜头级返工口无、并发引擎休眠 |
| L0 | adapter ✅、错误分类 ◐(未接路由);**路由/余额探针缺失,熔断仅单任务 1 层** |
| L2 | Template ✅(带版本);Subject ◐(缺身份向量);**Series/StylePack资产化全无** |
| L3 | **评分卡跑通(2026-07-04,`hevi/verdict/`,身份锚驱动变体选优)**;非阻断确定性体检仍在;独立审片阶段 + verdict→返工闭环(C3)待做 |
| L4 | canvas 图 + MCP 14 工具 ✅ **但节点执行器是回声桩**;Agent 三角零 |

**核心结论**:真正缺的不是"四层护城河的代码量",而是 ①两个吃 GPU 的 oprim 原语(`subject_embed`、`vlm_judge`)②把已存在的**休眠件接上线**(见 §7)。**本地 VLM 是解锁 L3/L4 的单点命门**。

---

## 3. 逐层元素:设计意图 + 核验状态(附证据)

### L0 供给层 —— 从"fallback 链"升级为"交易所"
现状盲区:provider 硬编码优先级链,对余额/配额是盲的,只能靠 403 感知欠费(fal/DashScope 双欠费即此账单)。

| 元素 | 状态 | 设计意图 / 证据 |
|---|---|---|
| Provider 能力矩阵 | ◐ | **设计**:每 provider 一行 `{t2v,i2v,参考图条件,原生音频,lip-sync,最大时长,分辨率档,秒成本,健康度,余额}`,接新 provider=加一行+一个 adapter。**现状**:碎在三处——`video/capability_guard.py:PROVIDER_LIMITS`(2026-07-03 补齐至 7 provider,4 列)、`cost/pricing_table.py:54-112`(秒成本)、`video/provider_config.py:4-18`(enum);**10 列缺 6**:参考图条件/原生音频/lip-sync/分辨率档/健康度/余额 |
| 成本感知路由(**镜头**粒度) | ❌ | **设计**:`route(shot)→provider` 解 `min(cost) s.t. capability⊇需求`;主角特写→Kling、空镜→本地 Wan。**现状**:按**任务**非镜头 `pipeline/longvideo_orchestrator.py:317-322`;min-cost 函数 `cost/selector.py:13` **死代码零调用**;运行时=固定 fallback `resilience/fallback_chain.py:12-15` |
| 余额探针 → Aegis 告警 | ❌ | **设计**:fal balance 轮询(查不到用滚动 403 率代理),低阈值告警,归 Aegis。**现状**:无;仅二元健康探针 `fallback_chain.py:62` |
| 三层预算熔断 | ◐ | **设计**:全局日 → provider 日 → 单任务。**现状**:仅**单任务**层 `cost/circuit_breaker.py:12-35`+`core/config.py:38`+`tasks/task_service.py:68,196`;全局日/provider 日**均无**;且 `task_service.py:149` tracker 未传 budget 半废 |
| Provider adapters | ✅ 🛒 | 7 个经 oprim 注册 `providers/registry.py:204-266`;veo3/kling/hailuo `:222-226`、edge_tts `:252-254`。**均应回迁 oprim**(见 `SPEC-oprim-new-primitives.md`) |
| 错误分类 → 路由/熔断 | ◐ | `resilience/errors.py:69` `classify_error`+三类(Retryable/Unretryable/Degradable)真实存在;仅喂**重试** `retry_policy.py:45-48`;**不喂**路由与熔断;`DegradableError` 定义但无人 raise/except |

### L1 执行层 —— 只做三个手术,其余冻结
现有管线(逐镜头 + 双变体 + checkpoint + 装配)健康,不重构。

| 元素 | 状态 | 设计意图 / 证据 |
|---|---|---|
| 逐镜头 + 双变体 + checkpoint + 装配 | ✅ | 管线 `pipeline/longvideo_orchestrator.py:265-525`;双变体+选优在 omodul `agentic_longvideo_pipeline.py:325-347`;checkpoint `:304-314,397-402`;装配 `assembly/assembler.py` |
| **双变体校验** | ◐→✅(角色锁定时) | ~~空转~~ **2026-07-04 修复**:①C2 注册本地 Qwen-VL(`local_qwen_vl_adapter`)→ mllm 真看图;②C4 `shot_scorecard` 在角色锁定时按 C1 身份向量**真·图对图**选优(`hevi/verdict/`,orchestrator 注入 `consistency_fn`)。核验:mp4 候选 [0.799 异/1.0 同]→选同。**遗留**:`short/standard` 档仍 v0 复制 v1 跳过双变体(`orchestrator:279-286`,提速取舍) |
| **i2v 前端暴露** | ◐ | 后端已接 `task_service.py:178-206`+`orchestrator:358-369`;前端仅经角色选择器隐式触发 `hevi-web/.../SimpleGenerate.tsx:317-345`,`LongVideoForm.tsx` 无显式 i2v/参考图控件 |
| **镜头级返工 `regenerate(task_id, shot_ids[], hints)`** | ❌ | **设计**:用分镜卡片列表替代时间轴(工程量 1/10),是 L3/L4 前置。**现状**:仅整任务 resume `api/routers/tasks.py:223-238`→`task_service.py:314-324`;无 shot 定向、无 hints |
| lip-sync 作 L0 能力列(降格) | 🛒 ❌ | **设计**:非"加功能"是矩阵一列;头像镜头路由到 (视频→fal lipsync 后处理) 或 (原生音画 provider),Veo 普及后后处理自然退役。**现状**:仅 Duix 数字人 `audio/avatar_service.py`,无通用 lipsync 列 |
| 双变体选优数据落库 | ❌ | `ShotState` 表+`create_shot_state`/`get_shots` 齐全(`tasks/models.py:43-57`,`repository.py:51-63`)但**零调用**;选优结果内存即弃 |
| RFC-003 多镜头并发 | ◐ 休眠 | 引擎**已在 omodul v1.35.0 内置**(`max_concurrent_shots` 窗口并发);hevi 从不设 >1(`pipeline/config_builder.py` 无此键)→ 严格顺序。见 `RFC-003-*`(文档旧 pin 已失效) |

### L2 资产层 —— 一致性不是功能,是资产的属性(护城河)

| 元素 | 状态 | 设计意图 / 证据 |
|---|---|---|
| **Subject** | ◐ | 4 类 `subjects/repository.py:9` + 多参考图 + i2v 锁定 ✅;**缺 `identity_embedding` 字段** `subjects/models.py:14-35`(建角色时离线算,是 L3 审片"还是不是这个人"的锚 + 跨 provider 一致性基准) |
| **`subject_embed` 身份向量原语** | 🆕🛒 ❌ | 隐含必需 → oprim 原语(吃 GPU)。**全 3O 唯一真·新原语**(无 arcface/insightface/clip;见 3O manifest §C1)。oprim 仅文本 embedder(bge_m3/qwen3)。**参考图条件化应写进 L0 能力矩阵**,路由器对"含固定角色的镜头"只在支持参考图的 provider 子集里选 |
| **StylePack** | ◐ | **设计**:内置 fork + 用户调色/运镜/负向覆盖 + 版本号;每集引用同一 `StylePack@version`=风格不漂移的机制。**现状**:20 条**静态 dict** `prompt/style_presets.py:14-115`,无 DB/版本/fork |
| **Series(核心)** | ❌ | **设计**:`{角色组引用, StylePack@ver, 片头尾模板, 规格锁, 集数序列}`;做第 N 集=继承+只写新剧情;一张表+tasks 加 `series_id` FK。**迁移成本即护城河**。**现状**:无表、无 `series_id`、零命中 |
| Template | ✅ | 全栈 `templates/template_models.py:14-34`+`api/routers/templates.py:84-97`(apply/用同款),**已带 version**;可直接当 Series/StylePack 版本化范式 |
| 翻译配音(收编此层) | ◐ | **设计**:Series 导出"出 X 语种版"=ASR→翻译(本地 qwen)→edge-tts 目标语种→复用装配。**现状**:ASR `assembly/subtitle_align.py` ✅ + edge-tts `registry.py:251-254` ✅,**无翻译步骤、流程未串** |

### L3 裁决层 —— hevi-verdict(核验 ~5%)
"guilty until proven innocent":及格率超阈才交付,否则定向重拍/熔断退款。

| 元素 | 状态 | 设计意图 / 证据 |
|---|---|---|
| 确定性审查(时长/字幕/响度) | ◐ | `video/quality_check.py:120-155` 查时长/分辨率/音轨存在 + phash 连续性;**无字幕检查、无 LUFS 响度**;且**非阻断**:`orchestrator:596-618` 仅 `logger.info`,`rep.passed`/`violations` **从不被消费** |
| **VLM 审片(Qwen2.5-VL 本地)** | 🛒 ❌ | **设计**:抽帧审(每镜头 3–5 帧 + 首尾),本地=审片零边际成本。**现状**:oprim `vlm_video_analyze` + oskill `mllm_frame_consistency_check` **已存在**;缺的只是**注册一个真实 VLM provider**(`qwen3_vl`,见 3O manifest §C2)——不是新原语。hevi 现只接文本 qwen(`local_qwen_adapter.py:107` 丢图) |
| 评分卡 schema | ◐ | **2026-07-04**:`hevi/verdict/scorecard.py` `Scorecard{identity_score,style_score,vlm_score,checks,passed,hints}` + `shot_scorecard`(C4)。identity=帧 CLIP 向量 vs `Subject.identity_embedding`(C1)余弦 —— 已跑通、已接双变体选优。**留待**:`vlm_score`/style 基准帧接入、作为独立审片阶段(现仅驱动变体选优) |
| verdict → `regenerate` 闭环 | ❌ | 不及格镜头→`regenerate(shot_ids, hints)`;omodul 有 retry `:321-356` 但无 hints、不由 QC 驱动 |
| hevi-verdict omodul 封装 | ❌ | 无 verdict/judge/review 模块;消费 L2 资产作"标准答案"是竞品做不了逐镜头 QC 的原因 |

### L4 导演层 —— Agent 编排,canvas 升格为 IR(核验 ~15%)

| 元素 | 状态 | 设计意图 / 证据 |
|---|---|---|
| **canvas 节点图 + 执行器** | ✅(桩) | 数据模型 `canvas/graph_models.py:14`、执行器 `executor_service.py:20,50`、节点类型 `node_mapper.py:8`。**但节点执行器返回回声 dict,不调真实 provider** → 尚非"系统 IR" |
| MCP 四组工具 | ✅ | 14 工具 `mcp/server.py:49-61`,`tests/test_mcp.py:42` 断言;video/creative/subject/canvas 四组真实可调,即 Agent 的运行底座 |
| Producer(意图→约束+预算可行性) | ❌ | 跑在现有 MCP 四组上,不新建管线;现无 |
| Director(分镜→选角→下发) | ❌ | **输出物 = canvas 节点图**;现无机器生成图的 Director |
| Editor(消费评分卡→返工/节奏) | ❌ | 依赖 L3 成熟;现无 |
| canvas 升为系统 IR | ◐ | 全自动=生成图直接执行;人在环=改图再执行。图+执行器在,执行器是桩 |

### 横切 / 商业化
| 元素 | 状态 | 证据 |
|---|---|---|
| 订阅制(按月产能) | ❌ | 现为**积分零售** `credits/models.py:36`+`payment/models.py:14`(一次性);无 subscription/recurring。Paddle 闭环 ✅ 可承接 |
| auth/tasks/api/前端/MCP/observability | ✅ | 应用层保留 |
| 成片端点 / 进度 SSE / gallery | ✅ | 属 L1/app |
| DashScope 弃用 / wan_cloud 砍 | ❌ 未动 | 仍全量接线 `registry.py:51,193,213-218`(Phase-1 运营项) |

---

## 4. 隐含依赖 / 硬约束(决定成败)

1. **感知类原语——3O 已有大半,真缺口小**(2026-07-03 核验修正):`vlm_video_analyze`(VLM 审片)、`transcribe_audio`(ASR)、`video_cost_proposal`+`ProviderContractRegistry`(成本路由)、A 组媒体原语(`oprim-b5a4`)**均已存在**。**真正需新增的只有**:`subject_embed`(身份/视觉向量,唯一真·新原语)+ 注册一个 `qwen3_vl` VLM provider(点亮已存在的 VLM 链)。二者均吃 GPU。详见 `3O-new-elements-manifest.md` §C。
2. **GPU 是 L2/L3 的硬前置** —— identity embedding + VLM 审片 + 本地 Wan 出片全靠 3080。
   > ✅ **2026-07-03 更新**:本地 GPU 已恢复可用;`ollama(llama3.2)` + `Wan2GP` + `VibeVoice` + `faster-whisper` 已接通并验证(详见项目 memory `local-models-setup`)。**L3 裁决层的验证前置已解除**,缺的是注册本地 VLM(`vlm_judge`)——见 §7-1。
3. **路由器需要"活的状态"** —— 能力矩阵的 health/balance 是动态状态,需小状态存储(Aegis 供给或 hevi 本地缓存),否则路由是"盲的静态表"。这是 L0 从"数据表"到"交易所"的关键。
4. **运营态**:fal 余额需充值;DashScope 明确弃用(LLM 已本地 qwen,wan_cloud 与 wan_local 能力重叠,砍)。

---

## 5. 3O 范式归位(哪些外采、哪些自建)

范式:`obase(L0基座) ← oprim(L2原语) ← oskill(L3技能) ← omodul(L1编排) ← hevi(应用)`。

- **外采到 oprim(热替换)**:生成/嵌入/审片原语。**已存在(采用/合并)**:`vlm_video_analyze`、`transcribe_audio`、`mllm_frame_consistency_check`、`video_cost_proposal`+`ProviderContractRegistry`、A 组(`oprim-b5a4` 待合)。**真·新增**:`subject_embed`(§C1)+ `qwen3_vl` provider(§C2)+ omodul 结构化 per-shot/返工(§C3)+ `shot_scorecard`(§C4)+ `fal_balance_probe`(§C5)。见 `3O-new-elements-manifest.md` §C + `SPEC-oprim-new-primitives.md`。
- **hevi 自建(护城河四层)**:L0 路由/矩阵/熔断、L2 资产模型、L3 裁决逻辑、L4 导演 Agent。
- **上游修复**:21 处猴补丁对应的 oprim/oskill/omodul 修复,见 manifest B 组;RFC-003 是已就绪范例。

---

## 6. 路线图(严格按依赖排,不跳阶段)

**硬依赖**:没有 L3 裁决,L4 Agent 只是更快地烧钱产烂片;没有 L0 路由,Series 量产在成本上不成立;**没有本地 VLM,L1 双变体 / L3 审片 / L4 Editor 全悬空**。

**Phase 0(命门,先做)—— 点亮本地 VLM**
- 注册 `vlm_judge`(本地 Qwen2.5-VL)为 `mllm` provider → 一次性把 L1 双变体从"选第一个"变成真校验,并解锁 L3。GPU 已就绪(§4-2)。

**Phase 1(2–3 周)止血与地基**
- L0:余额探针 + Aegis 告警 + 三层熔断(补全局日/provider 日两层);i2v 前端暴露;镜头级返工接口 `regenerate`;双变体选优数据落库(需 orchestrator 先透出 per-shot 数据,见 §7-5)。
- L1:`config_builder` 按档位注入 `max_concurrent_shots>1`(引擎已就绪)。
- 运营:fal 充值;DashScope 弃用(砍 wan_cloud)。

**Phase 2(4–6 周)质量闭环**
- L3:hevi-verdict —— 先让确定性体检 `quality_report.passed` 真正 gate/返工(现被 log 吞),补字幕/LUFS;再上 VLM 主观项 + 评分卡。
- L2:Subject 补 `identity_embedding`(`subject_embed`)。
- L0:成本感知路由 v1(接 `cost/selector.py` 死代码到镜头级选择,预算优化后置)。

**Phase 3(6–8 周)产品跃迁**
- L2:Series 资产化 + StylePack 版本化;翻译配音导出(串 ASR→翻译→edge-tts)。
- L1:lip-sync 路由路径。
- L4:canvas 执行器从桩改为调真实 provider(成真 IR);Director Agent v1(自然语言→可行性→canvas 草稿;Editor 待 verdict 成熟)。

---

## 7. 接线清单(已存在但未接线 —— 最高杠杆)

> 这些不是"从零建",是"把死代码/空 schema/休眠开关接上"。按杠杆排序,是路线图的近期 backlog。

| # | 休眠件 | 现状 | 接线动作 | 归属 |
|---|---|---|---|---|
| 1 | ~~本地 VLM provider + `subject_embed`~~ | ✅ **已完成 2026-07-04** | C1 `subject_embed`(CLIP)+ C2 VL provider(`qwen2.5vl:3b`)+ C4 `shot_scorecard` 接线 → L1 双变体真校验、L3 评分卡跑通。见 manifest §C1/C2/C4 | L1+L3 |
| 2 | `cost/selector.py` min-cost | 死代码 0 调用 | 接入 `injected_video_fn` 做镜头级 provider 选择 | L0 路由 v1 |
| 3 | `max_concurrent_shots` | 引擎就绪(omodul v1.35.0) | `config_builder` 按档位注入 >1 | L1 并发 |
| 4 | `quality_report.passed` | 算了但无人读 | 让它 gate/驱动返工,而非仅 log | L3 确定性 |
| 5 | `ShotState` 表 + repo | schema 全、0 调用 | 阻塞于 omodul 透出 per-shot(选优数据现被 omodul 丢弃)——**已知会主库 [omodul#7](https://github.com/helios-plat/omodul/issues/7)**(§C3);上游发版后 hevi 接线 | L1 落库 |
| 6 | `DegradableError` | 定义但无人 raise/except | 接降级路径(配音失败→纯视频) | L0 韧性 |
| 7 | canvas 节点执行器 | 回声桩 | 改调真实 kernel/provider,使 canvas 成真 IR | L4 |
| 8 | 能力矩阵列扩展 | 7 行齐(2026-07-03)、缺 6 列 | 补参考图条件/原生音频/lip-sync/健康/余额列,供 #2 路由消费 | L0 |

---

## 8. 否决清单

| 项 | 裁决 | 理由 |
|---|---|---|
| 运镜/相机控制前端 | ❌否 | 保留 prompt camera 字段即可;模型层 12 个月内吃掉,现建 UI=给贬值资产投资 |
| 全功能时间轴 | ❌否 | 分镜卡片列表替代(删/换/改prompt/单独重拍);时间轴是剪辑软件心智,hevi 是"分镜表" |
| 素材/模板库规模竞赛 | ❌否 | 模板走 Series 骨架 + 画廊 UGC 回填;BGM 授权是法务非产品,规模冻结 |
| 3D 角色 | ❌否 | 接不进 2D 链路,ROI 不成立 |
| 语音克隆 | ⏸️ 缓议 | fal 有现成可租,但滥用面大;先想清同意验证机制,别为 checkbox 背合规风险 |
| 九项创意辅助工具 | ❄️ 冻结 | 维持;"角色一致性工作流"逻辑并入 L2,壳留 |

---

## 9. 收束

竞品分析回答"别人有什么我没有";本架构回答"什么建成后别人补不了"。答案:**制片厂化**——供给层交易所化(L0)、资产层 IP 化(L2)、裁决层制度化(L3)、编排层导演化(L4),**生成能力本身全部外采**。

**当下真相**:护城河四层的"壳"已铺(资产表/canvas/MCP/成本骨架),但**判断力(VLM)未接**,导致 L1 质量闭环空转、L3/L4 悬空。第一优先级不是新建,是**点亮本地 VLM + 接线八件**(§7)。

---

## 附录 A. 核验纠偏记录(2026-07-03)

本次代码级核验对旧版自评的修正(以本文件正文为准):
1. L1"双变体校验"由隐含 ✅ 降为**空转**——文本 qwen 丢图,选优退化为选第一个。
2. L0 三层熔断:旧文档称"仅全局",实为**仅单任务**层;全局日/provider 日均无。
3. RFC-003:并发引擎**已在 omodul v1.35.0 落地**,缺 hevi 侧注入;旧文档"未合/分支/17测试/pin v1.33.1"失真。
4. Template:比旧自评更靠前——**已带 version 的完整资产**。
5. "veo3/kling/hailuo 未声明能力"**非崩溃 bug**——`validate_request` 有守卫且入口 `generate_clip` 仅测试用;2026-07-03 已补齐 7 provider 声明(纯 groundwork)。
6. GPU:旧文档"挂起待重启"→ **已恢复并接通本地模型链**。

## 附录 B. 变更记录
- **2026-07-03**:合并"架构设计 + 完成度核验"为本 SSOT;独立的 `specs/COMPLETION-BASELINE-2026-07-03.md` 已并入本文件并删除。补齐 `capability_guard.PROVIDER_LIMITS` 至 7 provider。本地模型链接通。
- **2026-07-03(3O 核验)**:核对 3O 源码后修正 §4-1/§5/§7——`vlm_video_analyze`/`transcribe_audio`/`video_cost_proposal`/A 组均已存在;真·新增 3O 元素收敛为 5 项,写入 `3O-new-elements-manifest.md` §C(C1 `subject_embed`、C2 `qwen3_vl` provider、C3 omodul per-shot/返工、C4 `shot_scorecard`、C5 `fal_balance_probe`)。
- **2026-07-04(Phase 0 落地)**:实现 C1(`subject_embed` CLIP + `Subject.identity_embedding` 迁移)、C2(`local_qwen_vl_adapter` + orchestrator 注入 mllm,模型 `qwen2.5vl:3b`)、C4(`hevi/verdict/` 评分卡 + 身份锚 `consistency_fn` 接线,PyAV 抽帧)。双变体在角色锁定时真·图对图选优。全套 425 测试绿。
- **2026-07-04(C3/C5 实现 + 提 PR)**:上游改动在 3O 仓实现并提 PR(feat 分支,不在 hevi hack)。C3 → [omodul#8](https://github.com/helios-plat/omodul/pull/8)(v1.36.0,`ShotRecord`/`shots` + `regenerate_shots`,27 tests);C5 → [obase#5](https://github.com/helios-plat/obase/pull/5)(v0.17.0,`provider_live_state`,10 tests)。notice `specs/RFC-C3-upstream-notice.md` / `RFC-C5-upstream-notice.md`。
- **2026-07-04(C 批次收尾)**:上游全合并;hevi `pyproject` 已 bump `omodul@v1.36.0` + `obase@v0.17.0`(oprim 留 v3.11.0——v3.11.1 新增全为 Tide/A股域,hevi 不用)。`ShotRecord`/`regenerate_shots`/`provider_live_state` 装机可用,**全套 425 测试绿**。剩最后一里(hevi 侧,后续):`ShotState` 落库 + verdict→返工闭环 + L0 路由活状态。
