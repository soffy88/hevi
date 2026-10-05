# P1 报告 — canonical shot resolution 是 p0 生产 authority

## 结论

`hevi/production/p0_pipeline.py` 的资产选择主路径已收口到唯一 canonical seam:

```text
discovery (只产候选)
  → ShotPreparation
  → resolve(domain, scorer_registry, bindings)   # canonical scorer → canonical selector
  → ShotResolution
  → admit_generation()                            # generation admission 唯一判定点
  → resolved_assets / shot_plans / 渲染
```

p0 内部不再有任何「决定哪个 asset 被选」的代码。

## 改了什么

### `hevi/creative/autonomous/selection.py`

| 变更 | 原因 |
|---|---|
| `resolve()` 新增必填 kwarg `domain` / `scorer_registry` / `bindings` | 旧签名内部硬编码空 `RequirementBindingSet()` 且不跑 scorer —— 生产可绕过 canonical scorer 与 identity 映射 |
| `resolve()` 现在真的调用 `shot_readiness.score_candidates()` | 契约要求 scorer → selector;此前 resolve 只 select,scorer 由调用方自行安排 |
| `NO_APPLICABLE_SCORER` → fail-closed 决议(selected 空 + unresolved + 需人工) | 域外/无 scorer 时不得默认放行 |
| `ready_for_generation` 增加 `unbound_asset_refs` / `human_review_required` 条件 | 旧实现只看 selected + unresolved,两条 blocker 形同虚设 |
| 新增 `blockers` 属性 | 报告需要**全部**拒绝理由,不是第一个 |
| 新增 `admit_generation()` + `GenerationNotAdmitted(Error)` | generation admission 明确 seam;executor 不得自行比较候选 |
| 新增 `GenerationNotAdmitted` 四个理由枚举 | `NO_RESOLUTION` / `NO_SELECTED_CANDIDATE` / `UNRESOLVED` / `UNBOUND` / `HUMAN_REVIEW` |

`resolve()` 只**调用** `shot_readiness` 的既有函数,没有在 autonomous 包内实现打分或排序
(`test_s3_no_scoring_in_autonomous.py` 仍然通过)。

### `hevi/production/p0_pipeline.py`

| 位置 | 改前 | 改后 |
|---|---|---|
| discovery 循环 | 命中即 `append(ResolvedAsset)` + `break`(每 intent 最多 1 个候选) | 产出**全部**匹配候选,按文件去重,无 `break` |
| `semantic_relevance=0.95` | 硬编码 | `confidence=0.0`,由 `P0_ScienceRelevanceScorer` 生产 |
| 选谁 | discovery 自己决定 | `resolve()` → canonical scorer + selector |
| identity | 无 | `_requirement_for()` 产出 canonical `p7.AssetRequirement`,经 `RequirementBindingSet` 显式绑定 local ref |
| generation 门 | `next(resolved_assets by intent_id)`,`if not asset: continue` | `state.shot_resolutions[...].ready_for_generation`,不满足则不生成 |
| 取选中资产 | 直接读 `ResolvedAsset` | `admit_generation(resolution, candidates)` |

新增 `P0ProductionState.shot_resolutions` 作为唯一 selection 结论的存放处。

`ResolvedAsset` / `resolved_assets` / `shot_plans` **全部保留** —— p1_pipeline:705/730 在消费,
没有为了 canonicalization 破坏既有下游契约。

## 测试

`tests/p10/test_p1_production_authority.py`(22 项)覆盖 P1-01…P1-10 与 Invariant D。
`tests/p10/test_s3_selection_wiring.py` 因 `resolve()` 契约收紧而更新(见下)。

```
tests/p10/                    275 passed
tests/test_p2_profiles.py      11 passed
```

## 被记录的 finding(不在 P1 修)

- **F1** `asset_base` 硬编码 `/tmp/hevi-science-v3/assets` —— 临时目录,不可复现。
- **F2** discovery 是黑洞/NASA 专用关键词表,非通用;本阶段只加了适用域声明 `science_nasa`。
- **F3** 评分从 asset **文件名**里的关键词反推(`P0_ScienceRelevanceScorer`),不是真实语义相关性。
  这是把硬编码 0.95 从「写死一个数」变成「写死一张表」,语义等价,不构成改进也不构成回退。
- **F4** `ShotPlan.camera_setup="static"` 硬编码,未用 MotionPlan 的 `ken_burns`。
- **F5** p0 无 retry / resume 实现,故 Invariant E/F 只能以「每次重算 resolution」满足。
- **F6** `hevi/creative/autonomous/canonical.py:29` 反向 import `p0_pipeline.VisualIntent`,
  导致 `p0_pipeline` 不能再在 import 期引入 autonomous 包,只能用 `_canonical_seam()` 延迟导入。
  该反向边是 S1 遗留,**不在 P1 修复范围**。
- **F7** 6 个架构守卫(`test_p5_1` / `test_p6_0` / `test_p6_1` / `test_p6_2` / `test_p6_8`)
  用 `git diff --name-only HEAD` 冻结 P0–P4。它们拦的是**未提交**的工作区改动;
  P1 提交后 `git diff HEAD` 为空,守卫恢复通过。守卫本身未被修改。
- **F8** `tests/test_history_arc_adapter.py` 2 项失败、`tests/test_library.py` asyncpg 连接失败,
  在 P1 之前的 HEAD 上同样失败,与本次改动无关。

## 未做(明确不在 P1)

- 未实现 stock / procedural / generation Acquirer。
- 未实现 MPT(MPT-A)adapter。
- 未改 provider policy、scorer 语义、selector 门槛、`needs_human_review` 语义、RepairPolicy、
  artifact validation、Director authority、VisualIntent 语义。
- 未修 F6 的反向 import(会改动 S1 架构层)。

## 对 S3 测试的改动(需要复核)

`tests/p10/test_s3_selection_wiring.py` 有两条断言的**契约**在 P1 变了:

1. 所有 `resolve(prep)` 调用改为显式传 `domain` / `scorer_registry` / `bindings`
   (新增测试内 `PassThroughScorer`,它同样声明 `applicable_domains`)。
2. 「候选没有 `scored_by` → 不许自动选」不再是**经 resolve 的**可达状态。
   因为 `resolve()` 现在必然盖章 provenance,它是**产出**而非**输入**。
   已替换为两条更强的新断言:
   - `test_resolve_stamps_provenance_instead_of_trusting_the_caller`
   - `test_select_candidate_still_rejects_provenance_free_candidate`(门槛本身未放松)

这是有意的收紧,不是为了让测试变绿而放宽行为。若不同意,回退点是 `selection.py::resolve` 的签名。