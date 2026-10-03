# P10 开放问题收口（Q1–Q3 / Q5–Q9）

```yaml
status: ALL RESOLVED 2026-10-03 (Q4 已在 post_skeletal_acceptance 落地)
verification: tests/p10 100 passed · ruff clean · mypy clean (139 files)
```

## 决策

| Q | 决策 | 落点 |
|---|------|------|
| Q1 | ≤30s 短视频允许 K=2，**记录理由即可，不额外签字** | `Treatment.short_form_reason` 必填；缺失 → `TREATMENT_K_INSUFFICIENT` |
| Q2 | Creative Memory `global` 作用域**保持禁用** | `MEMORY_SCOPE_GLOBAL_DISABLED`（独立错误码，不再混进 `MEMORY_BAD_ENTRY`） |
| Q3 | `structure_clone` **继续禁用** | `BENCHMARK_TRANSFER_FORBIDDEN`（P10b 已拒） |
| Q5 | 多语言：`zh:scene1.line004` 命名空间 + **显式**翻译对应表 | `namespaced_unit_id` / `TranslationIndex` / `build_translation_index(pairs=…)` |
| Q6 | 默认容差不动（工程起点），标定成为可执行动作但**不自动改默认** | `default_tolerance_ms` / `calibrate`（≥5 样本，p95 + 1 帧下限） |
| Q7 | SignatureShot 上限默认 **2**，可配置 | `check_signature_unique(..., max_count=2)` → `SIGNATURE_OVER_BUDGET` |
| Q9 | `cost_class` → 金额/时长由**部署配置**提供，缺配置报错 | `CostTable.estimate` → `COST_TABLE_UNCONFIGURED`；`default_cost_table()` 保守默认 |

## 实施期发现（值得记）

Q5 最初实现为「按文本自动配对源/译单元」。**这是错的**：翻译后源文与译文文本必然不同，
按文本推断等于错连锚点。已改为只接受**显式**对应关系（`pairs`），给不出就不连边——
宁可缺，不可错连。这与 A3「删除 ID 永不复用」是同一类原则：宁可报错，不猜。

## 仍需真实数据才能定死的

- Q6 的 `SYNC_NORMAL` / `EVENT_LOOSE` 最终值：需真实流水线的 declared-vs-observed 偏差分布
  （`calibrate` 已就绪，等样本）。
- Q9 的金额阈值：`default_cost_table()` 是保守起点，需按真实 GPU/Provider 账单校准。