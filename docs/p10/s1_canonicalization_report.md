# S1 CANONOMICALIZATION 实施报告

```yaml
status: S1 PASS (10/10 交付)
date: 2026-10-03
ruling: 2026-10-03 canonical map(Director / p0 VisualIntent / p7 / provider_policy /
        MissionExecutor / validation+ProductionVerdictAuthority / RepairIncident / MPT adapter)
verification: tests/p10 186 passed · 相邻 221 passed · ruff clean · mypy clean (8 source files)
```

## 交付对照

| # | 交付 | 落点 | 状态 |
|---|------|------|------|
| 1 | Director canonical entry | `canonical.py:DIRECTOR_ENTRY="director_pipeline:semantic_spine"`,复用五级生成器 | ✅ 不新增入口 |
| 2 | VisualIntent canonicalization | `canonical.py:to_visual_intent` → p0 `VisualIntent`(9 必填字段) | ✅ p6 那个不由此出口 |
| 3 | Storyboard→ShotPlan | dry-run 走 concept→screenplay→design_list→scene_stage→shot_list | ✅ 逐场 scene_stage 与 router 同形 |
| 4 | p7 接线 | `canonical.py` 原样再导出 `AssetRequirement/AssetDecision/AssetResolution` | ✅ 无副本 |
| 5 | AssetResolver adapter | `resolver.py` | ✅ 无打分/排序/覆盖 |
| 6 | MissionExecutor 接线 | `execution.py` | ✅ 无新 runner 类 |
| 7 | ProductionVerdictAuthority | `verdict.py` 聚合器 | ✅ 不实现评估 |
| 8 | RepairIncident 接线 | `repair.py` | ✅ 无新 repair 词汇 |
| 9 | production_manifest JSON | `manifest.py`(唯一绿地) | ✅ projection,无状态机 |
| 10 | one-line dry-run | `dry_run.py` | ✅ 真跑 spec 原句 |

## 机械执行的架构裁决(测试锁死,违反即红)

`tests/p10/test_s1_canonical_authority.py`:
- 本包**不得定义** AssetRequirement / AssetDecision / AssetScore / VisualIntent / Storyboard /
  AutonomousRunner / ProductionOrchestrator / RepairPolicy / RepairIncident / QualityEvaluation / ShotPlan …
- canonical 类型必须**从 canonical owner import**(AST 校验 import 来源,不校验文本)
- 不得从 p6 `visual_compiler` 引入第二个 VisualIntent
- Resolver 不得有 `calculate_score/rank_candidates/pick_best_provider/override_decision`
- Verdict aggregator 不得调用任何既有 evaluator(`run_final_review`/`run_delivery_gate`/…)
- manifest 不得有 `set_status`/`advance`(不是状态机)
- 词汇分裂必须登记(`KNOWN_SPLITS`),不许藏

## 实施期抓到的 4 个真问题

1. **`to_root_cause` 是死代码**:我以为能把失败码映射到 `RootCauseCategory`,实测发现既有
   `classify_deterministic` 才是 root_cause 的权威,我的映射根本没生效(返回 `unknown_needs_agent`)。
   已删除该函数并在 docstring 写明「分类归既有 authority」——留着它就是**假装有权限**。
2. **`AUTO_SAFE` 并不等于被拒**:既有语义是 project policy 只门控 **cost-bearing** 动作。
   零成本 AUTO_SAFE 会被放行;花费 >0 才需 opt-in。文档/测试已按真实语义校正。
3. **asset requirement 错键**:`shot_size` 被我塞进 `period`(年代语义)。错键会静默污染
   provider 检索。已删除,只用 `duration`/`query`,景别留在 ShotListItem 与 VisualIntent。
4. **`await` in 推导式**:`tuple(await f(x) for x in ...)` 会变成 async generator 而非并发序列,
   已踩。保留 for 循环并加 `# noqa: PERF401` 注明原因(ruff 的建议在这里是错的)。

## 如实登记的未收口项(未假装完成)

| 项 | 状态 |
|---|---|
| MPT adapter | **未接线**。裁决里是 assembly/execution adapter;`services/mpt_adapter.py:106` 已存在可复用,但 P0 未接 |
| Acquirer 实现 | 只有 Protocol。真实 local/stock/procedural 三个来源未实现(P1) |
| stage adapters 真实执行 | `build_stage_runners` 已校验 kind,但除测试 adapter 外无生产 adapter |
| Director 入口收敛 | dry-run 走五级主干;但 `director.py::director_create_episode` 等 3 个旧入口**仍在**,P0 未删(裁决说不删但不得新增) |
| 4 套 ProviderPolicy 词汇 | 已登记为 seam;**未**统一(MissionExecutor 仍用 p3_types dataclass) |

## 判定

S1 = PASS。**不构成** spec §53 的 P0 DoD —— 那是 S2–S9 的事(真实素材解析、真实 TTS、QC 接线、真实 E2E)。
本次交付的实质是:**把「不许新增第 6/7 套」从口头约定变成会红的测试**。