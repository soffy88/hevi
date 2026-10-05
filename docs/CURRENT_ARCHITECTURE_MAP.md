# CURRENT_ARCHITECTURE_MAP — 自主视频创作 S0 审计

- **日期**: 2026-10-03 · **方法**: 只读测绘（双子代理核实 + file:line），未改任何代码
- **依据**: HEVI AUTONOMOUS VIDEO CREATION SPEC v1.0 §62 S0 / §63
- **结论**: **P0 不可按 spec 原文直接开工**。spec 有 4 条「缺失」前提为假，另有 3 条「不要重复」指令在现存代码里已被违反（会被新工作继承）。

---

## 1. 复用矩阵（spec §63 要求的六列）

| 组件 | 规范 owner | 复用 | 需 adapter | 需扩展 | 重复 | 死代码 |
|---|---|---|---|---|---|---|
| Director 入口 | **无单一 owner**（3 个并存） | ⚠️ | — | — | **3 入口** | — |
| Concept/Screenplay/DesignList/ShotList | `director/pipeline_schemas.py:25/67/102/494` | ✅ | — | — | — | — |
| 五级流水线 | `api/routers/director_pipeline.py:167 _STAGES` | ✅ | — | — | 与 `director.py` 并行 | — |
| `VisualIntent` | — | ❌ | — | — | **同名两份** | — |
| `VisualBeatPlan` | `production/p1_types.py:111` | ✅ | — | — | — | — |
| Storyboard | — | ❌ | — | — | **5 套实现** | — |
| **AssetRequirement** | `production/p7/asset_requirement.py:67` | ✅ **已存在** | — | — | — | — |
| AssetCandidate | `production/shot_readiness.py:53` | ✅ | — | — | — | — |
| Asset 决策 authority | `production/p7/asset_intelligence.py:74` | ✅ | — | — | — | — |
| **AssetResolver** | — | — | 新建需受约束 | — | — | — |
| provider 选择/排序 | `provider_policy/policy.py:54 ProviderDecision` | ✅ | — | — | **3 个选择器** | — |
| 素材发现 | `sourcing/media_use.py:152` + `loader_bridge.py:14` | ✅ | — | — | — | — |
| 采集闸 | `acquisition/acquire.py:76` | ✅ | — | — | — | — |
| Voice/TTS | `audio/audio_router.py:99/383` | ✅ | — | — | **8 个入口 + 2 registry** | — |
| Music 选择 | `audio/bgm_library.py:61` | ✅ | — | — | policy 定义 ×3 | — |
| Subtitle | **无 owner** | ❌ | — | — | **7 个 writer** | — |
| Edit/Assembly | `assembly/assembler.py:455` | ✅ | — | — | — | — |
| Render | `renderers/` + `providers/remotion/driver.py` | ✅ | — | — | — | — |
| **QC** | **无单一 authority** | ❌ | — | — | **6 evaluator + 4 gate** | — |
| **Repair** | **6 套并存** | ⚠️ | — | — | **6+1** | — |
| `RepairPolicy` AUTO_SAFE/… | `creative/layer4/repair_incident.py:65` | ✅ **已存在** | — | — | — | — |
| artifact 校验 | `validation/artifact.py:122 ValidationResult` | ✅ | — | — | — | — |
| Execution/Receipt | `execution/models.py:134` + `execute.py:53` | ✅ | — | — | — | — |
| RunState | **3 套词汇** | ⚠️ | — | — | **3** | — |
| 生产 manifest (JSON) | **不存在** | — | 新建（绿） | — | — | — |
| GoalRun | **不存在** | — | — | — | — | ✅ spec 引用了它 |
| MPT | `services/mpt/` + `services/mpt_adapter.py:106` | ✅ adapter 已存在 | — | — | 自身也是 pipeline | — |
| P10 Creative Direction | `hevi/creative/direction_*`（本次会话建） | ✅ | — | — | — | — |
| P10 Generation Contract | `hevi/generation/*`（本次会话建） | ✅ | — | — | — | — |

---

## 2. 四条「缺失」前提为假

### 2.1 §9「缺正式 typed AssetRequirement」→ **已存在**

```
hevi/production/p7/asset_requirement.py:67  AssetRequirement  (frozen dataclass)
hevi/production/p7/asset_requirement.py:53  SourcePolicy
hevi/production/p7/asset_requirement.py:35  KNOWN_CONSTRAINTS
hevi/production/p7/asset_requirement.py:49  QUALITY_FLOOR_MIN/MAX
hevi/production/p7/asset_binding.py:77/244/253   生产者(from P6 intent)
```
再新建 `hevi/production/asset_resolution.py` 里的 AssetRequirement = 第二份需求词汇。

### 2.2 §13 AssetResolver 决策树 = 第二选择器（被明文禁止）

```
hevi/production/p7/asset_decision.py:15-25
  "Not a registry, repository, selector or scorer. It does not search, call a
   provider, or rank. … A layer that both decided and recorded would sit beside
   hevi.provider_policy as a second selection authority, and the two would drift
   — exactly the P6.2/P6.3 failure."
hevi/production/p7/__init__.py:35-37  NO_SECOND_ASSET_AUTHORITY
tests/test_p7_0_asset_contract.py:76  FORBIDDEN_AUTHORITY_NAMES（含 AssetSelectionService）
```
spec §14 说「provider ranking 不是 Director 决策」——**正确**，但 ranking 已被 `provider_policy` 拥有。
一个会排序候选并决定 retrieve/generate 的 Resolver 若不建在 p7 + provider_policy 之上，就是 spec 自己禁止的第二 authority。

### 2.3 §26「不要再建第三套 repair architecture」→ 已有 **6+1** 套

| # | 位置 | 要点 |
|---|---|---|
| 1 | `director/repair_agents.py:73/93/108/150` | RepairAction/Plan/plan_repair，budget=3 |
| 2 | `quality/repair_controller.py:13/76/22-31` | RepairBudget + 8 类动作 |
| 3 | `quality/repair_executor.py:62` | apply_repair_decision |
| 4 | `creative/layer4/repair_incident.py` | **RepairPolicy(AUTO_SAFE/CONFIRM_REQUIRED/MANUAL_ONLY) 已存在** `:65-68`，默认不允许自动花费 `:117` |
| 5 | `execution/plan.py:96/202` | RepairPlan + decide_repair |
| 6 | `creative/layer4/plan_projection.py:53/127` | RepairKind |
| +1 | `cinematic/video_gen.py:230` | 自带 reroll/degrade + 独立 cost_limit |
| +1 | `production_graph/contracts.py:50` | RepairDecision |

**且 spec §26「P0 只允许 AUTO_SAFE 自动修复」已经是现状**（`repair_incident.py:65`）——应复用，不是新增。

### 2.4 §24 ArtifactStatus 门禁 → 已有等价且更强的机制

```
hevi/validation/artifact.py:73 ValidationCheck.passed 由 :100 派生
                            :122 ValidationResult.passed 由 :150 派生
                            :160 verify_payload（字节哈希 == 声明校验和）
                            :44  CheckOperator.compare 是「唯一能让检查成功的地方」
```
spec §24 的 `NOT_PRODUCED/PRODUCED_UNVERIFIED/VALID/INVALID` 与之高度重叠，需说明差异再落码。

---

## 3. 三条「唯一权威」在代码里不唯一

### 3.1 Director（spec §3「唯一语义权威」）

| 入口 | 覆盖范围 |
|---|---|
| `director/planner.py:30 plan_from_text` | text → intent → ProducerPlan → shot_prompts + canvas graph（**不产** Concept/Screenplay/ShotList，属另一棵树） |
| `api/routers/director_pipeline.py:787 parse_work` | material → concept → storygraph → season_plan → screenplay → design_list → **止步 design_list**（`:742 inspection_ready`），**从不**到 scene_stage / shot_list |
| `api/routers/director.py:197 director_create_episode` | NL → intent → feasibility → video task，**完全绕过规划阶段** |

`director_pipeline.py:14-16` 自己写明「跟现有 director.py 并行存在，不替换」。
→ 「HEVI Director 唯一语义权威」**目前不是一个事实**，是目标。

### 3.2 Pipeline / Orchestrator（spec §22「不得建立新的大 orchestrator」）

至少 **5 个**编排权威：

1. `production/p0_pipeline.py:237` → `p1_pipeline.py:500`（`:509` 调 P0）→ `p2_pipeline.py:157`（`:180` 调 P1）：一条**嵌套**链
2. `missions/p3_runtime.py:323 MissionExecutor`：durable JSON store + fan-out + 预算 + 幂等 + resume + cancel（`:220-243` 确定性 planner）
3. `pipeline/longvideo_orchestrator.py:75`：omodul 路径，注入 storyboard/audio/video/assembler
4. `pipeline/manifest.py:144 run_with_checkpoint`：obase YAML + checkpoint
5. `tasks/task_service.py:600 TaskService.run_task`

且 `production/p6/runtime.py:26` 已命名约束 `NO_SECOND_PIPELINE`，而 `p0_pipeline.py:8` 声称单一权威——**现存代码自相矛盾**。
spec §22 说「优先复用」，但没说复用哪一个。**这是必须拍板的第一个岔路。**

### 3.3 QC（spec §25 的 `QC_PASSED`）

无单一 owner：6 个 evaluator（`verdict/final_review.py:122`、`delivery_gate.py:199`、`scorecard.py:102`、`aesthetic_canon.py:50`、`production_checks.py:208`、`h3_checks.py:295`）
+ 4 个 gate 概念（`verdict/delivery_gate.py`、`production/delivery_gate.py:39`、`quality/gate_policy.py:20`、visual QC 四处独立实现）
+ 两个 shot verdict 实现（`director/verdict_checks.py:148` vs `verdict/h3_checks.py:295`）。

---

## 4. 其余冲突与结构性问题

| 项 | 事实 | 影响 |
|---|---|---|
| `VisualIntent` 同名两份 | `production/p0_pipeline.py:95`（segment 语义）vs `production/p6/visual_compiler.py:194`（P6.5 指令）；`p1_pipeline.py:24` 与 `:608` 同时按名 import | §8 复用哪一份必须指定 |
| Storyboard 5 套 | `director/storyboard.py:41`、`sketch_storyboard.py`、`explainer/storyboard.py:1`、`assembly/freevideo/storyboard.py:55`、`pipeline/storyboard_locked_override.py` | §8 storyboard 无单一 owner |
| RunState 3 套 | `production/p6/production_runtime.py:73`（唯一真定义）；`execution/*` 刻意不命名它（`models.py:41-43`）；`pipeline/manifest.py:45` 从 obase import 另一个 | §25 状态机词汇会继承分裂 |
| TTS 8 入口 + 2 registry | `audio_router.py` / `tts_service` / `edge_tts_custom` / `pocket_tts_service` / `lux_tts_service` / `voxcpm_service` / `f5_tts_service` / `cosyvoice_service` + `speech_platform.py:21` 第二 registry | §30「统一」= 又一次收口工作，非 P0 可完成 |
| Subtitle 7 writer | `assembly/subtitle_align.py:55`、`subtitle_timeline_atoms.py:146`、`tongjian/assemble.py:99`、`ops/p5_1_production.py:287`、`production/media_workflows.py:141`、`openshorts/clip_engine.py:154`、legacy `openai_audio.py:169` | §32「必须验证」需要一个 canonical writer 先定 |
| readiness 两套词汇 | `director/shot_preparation.py:33`（pending/ready）vs `production/shot_readiness.py:25`（7 态含 BLOCKED/STALE） | §27 repair 触发条件会二义 |
| `required_asset_refs` 类型混用 | `shot_readiness.py:202` 拿 `requirement_id` 去比对 **asset_ref 列表**；除测试外无人写入 requirement id | §9 的 requirement_id 语义与现字段不同源 |
| provider 选择器 3 个 | `provider_policy/policy.py:86`（仅 3 处生产调用）+ `providers/scoring.py:139 choose_provider`（独立加权 + JSONL 决策日志）+ `production/policy.py:34 choose_mode`；另 `resilience.live_state` 是第二道活体健康闸（`policy.py:25` import） | §14 排序维度要指明落到哪个 |
| image 选择 3 条路 | `director/image_selector.py:1-9` 是 legacy re-export；`director/storyboard.py:105 select_best_from_pool`；`sourcing/loader_bridge.py:14 AssetRepository` | §15 本地素材优先需指定 owner |
| MPT 双入口 | 一条走 canonical TaskService（`api/routers/mpt.py:113-152`），一条直接 `MPTClient`（`:155`） | §19 adapter 要收敛到一条 |
| MPT 无 storyboard | `services/mpt/app` grep storyboard = 0 命中 | spec 假设 MPT 有 storyboard stage → 不成立 |
| **`GoalRun` 不存在** | 全仓（含 docs/services）零命中 | spec §22 引用了不存在的组件 |
| **production_manifest JSON 不存在** | grep 只命中 `pipeline/longvideo_manifest.py:36`（oservi ServiceManifest，单 step） | §46 是真绿地 |

---

## 5. 与本会话已建 P10 的关系（好消息）

| spec 诉求 | 已有落点 |
|---|---|
| §7 `director_authority_id` 证明创作决定来自 Director | `creative/direction_state/`（revision + approval pin + `CREATED -> ... -> VERIFIED` 状态机，A1-A14 已过） |
| §24 产物分级门禁 | `creative/direction_verify/models.py`（ObservationSet hash 绑定 + verdict 聚合 5 规则）+ `validation/artifact.py` |
| §29 execution 不得改创作意图 | `creative/direction_content/` pin 校验（内容漂移 → `APPROVAL_VOID`）+ `creative/direction_state/` 非法迁移零变更 |
| §14 provider 能力来自 qualification | `generation/external_runtime.py` + `generation/qualification.py`（ENV_BLOCKED 早退，未实测即 False） |
| §41 bounded retry / §42 idempotency | `direction_state` 幂等 command_id + `generation` journal 按 stage 续跑 |

**结论：P10 已经把 spec 最难的那几条纪律做成了可执行断言。** 缺的是资产层与 QC/编排层的收口。

---

## 6. 开工前必须拍板的 5 件事

1. **复用哪条编排链**：`missions/p3_runtime.MissionExecutor`（最全：durable + fan-out + 预算 + 幂等 + resume）还是 `p0→p1→p2` 嵌套链？spec §22 禁止新增，但现存 5 条必须收敛一条。
2. **AssetResolver 的合法形态**：只能是 p7 `AssetDecisionAuthority` + `provider_policy` 之上的**编排 adapter**（不排序、不决策），还是要先解掉 p7 的 `NO_SECOND_ASSET_AUTHORITY` 约束？
3. **QC canonical owner**：从 6 evaluator + 4 gate 里指定一个作为 `QC_PASSED` 的唯一签发者，其余降级为该 owner 的检查项。
4. **`VisualIntent` / storyboard 复用哪一套**（§8 直接引用这两个名字）。
5. **repair 复用哪一套**（6+1 并存，且 `RepairPolicy` 已有 —— spec §26 实际是「复用」而非「新建」）。

在这 5 条拍板前，写 S1 contracts 会立刻产生第 6 套词汇、第 7 套 repair、第 3 个 Director 入口 —— 正是 spec §67 列的 hard failure。