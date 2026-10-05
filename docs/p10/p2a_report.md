# P2-A 报告 — Stock acquisition 真实闭环

范围:**只做 Stock**。procedural / generation / MPT 一律未实现。F3 / F6 未动。

## 闭环

```text
ShotResolution.unresolved_requirement_ids
    ↓  canonical p7 AssetRequirement(不是自造字符串)
evaluate_provider_policy(catalogue=本地声明)      → provider_id,或 fail closed
    ↓
StockAssetAcquirer.propose(requirement)          → 物化 + validate_media + check_compatibility
    │                                              返回**全部**合规候选
    ↓ 候选并入 ShotPreparation
resolve()  ← 第二次。canonical scorer + selector 照常跑
    ↓
ShotResolution → admit_generation()
```

生产与验收测试调**同一个函数** `_resolve_with_acquisition()` —— 不是测试重演一遍生产逻辑。

## 新增/改动

| 文件 | 内容 |
|---|---|
| `hevi/creative/autonomous/acquire_stock.py`(新,198 行) | `StockItem` / `StockSource` / `StockAssetAcquirer` / `materialize_name` / `default_cache_dir` |
| `hevi/creative/autonomous/selection.py` | `resolve()` 新增可选 `required_requirement_ids` |
| `hevi/production/p0_pipeline.py` | 抽出 `_resolve_with_acquisition()`;stage 4b 改为调用它;新增 `stock_acquirer` 参数 |
| `tests/p10/test_p2a_stock_acquisition.py`(新,19 项) | P2-A-01…08 + 两条 invariant |

## 三个必须知道的设计裁决

### 1. `StockAssetAcquirer` **刻意不实现** `Acquirer` 协议

`Acquirer.acquire` 返回 `tuple[str, AssetEvidence]` —— **单值**。单值返回本身就是一次选择。
所以本类提供 `propose() -> tuple[NormalizedCandidate, ...]` 并**不声称**自己是 `Acquirer`。

既有 `LocalAssetAcquirer.acquire:122-126` 返回第一个 `usable` 文件,正是这个错误
(登记为 **F9**),本阶段不修(无生产调用方)。

AST 守卫锁死:`acquire_stock.py` 内不得出现 `max/min/sorted/nlargest/nsmallest`、
`sort/pop/remove`,任何定义名不得含 `select/pick/best/rank/top/choose/score/fitness/relevan`。

### 2. `resolve()` 加了 `required_requirement_ids` —— 这是闭环的真实卡点

原实现 `requirement_ids = sorted({c.requirement_id for c in preparation.candidates})`
只从**候选**推导 requirement,所以零候选的 requirement 只会安静缺席,
`unresolved_requirement_ids` 是空的 —— 而 unresolved 正是 fallback chain 的输入。

生产层自行补 `or {req_id}` 就是 P1 刚拆掉的第二套 resolution 语义,不能做。
参数默认空 = 现有行为不变(275 条既有 p10 测试全绿),不是新 authority。

`test_p2a_06_zero_candidate_requirement_reports_unresolved` 直接对比传/不传两种结果。

### 3. 闭环的成立**依赖 F3**,这是登记不是修复

`P0_ScienceRelevanceScorer` 对 `candidate.asset_ref` 做子串匹配。stock 资产若落到
`<sha>.mp4`,`asset_ref` 不含任何关键词 → 0.0 分 → **即使 acquire / validate / compatible
全部成功,仍然 unresolved**。

因为不许修 F3,P2-A 唯一的做法是让物化文件名保留 provider slug
(`<slug>-<sha16>.mp4`,`materialize_name`),这本身也是 `hevi/sourcing/media_providers.py`
的既有做法。

**这是依赖,不是修复。** F3 一旦修好该依赖自动消失;在那之前,
「P0 科学题材能被 stock 救回」依赖于 slug 里带着词。`test_p2a_01` 的素材标题
因此必须含 `black hole accretion disk` —— 这是被测试钉住的事实,不是巧合。

## 验收结果

```
tests/p10/                                294 passed(19 项新增)
mypy acquire_stock.py + selection.py      Success
mypy p0_pipeline.py                       25 errors —— 与 P1 前基线同款,
                                          无新增(P1 前 30,现存 25)
ruff(本次全部改动文件)                     clean
```

P2-A-01…08 覆盖:acquired → selected / 不兼容 → 不进候选 / provider 故障(检索异常、
下载异常、provider 未登记)→ fail closed / 无 license → 不得 AVAILABLE /
坏媒体 → 不进 resolution / re-resolve 是 selected 的唯一来源 /
最终资产来自 `admit_generation` 而非 acquirer 顺序。

## 物料与许可约定

- 目录:`MATERIAL_CACHE_DIR` env → 否则 `data/material_cache`(沿用 de-facto 约定,非新发明)
- 文件名:`<slug>-<sha256(url)[:16]>.mp4`
- provider 事实:在 `acquire_stock.py` 里声明 `ProviderProfile`,**不改**
  `hevi/providers/facts.py` 的全局 `_SEED`(那是别人的未提交 WIP)。
  事实缺失 → `UNRESOLVED` → fail closed,不被猜出来。
- license:仍是自由文本(p7 只要求非空可审计)。无 license → `AssetEvidence`
  无法标 AVAILABLE(`AVAILABLE_ASSET_WITHOUT_LICENSE`)→ 不进候选。
  provider 级 `ProviderLicenseClass` 与 per-asset license 是两层,不可互替
  (`test_p2a_04_declared_license_class_is_provider_level_fact` 钉住)。

## 未做(明确)

procedural / generation / MPT;F3;F6;F9;许可 vocabulary;
`AssetResolver`(见下);`_observed_fields` 的 license 发射。

## 新增 finding

- **F9** `LocalAssetAcquirer.acquire` 返回第一个 usable → 违反「Acquirer 不选择」,无生产调用方。
- **F10** `AssetResolver.resolve` 返回单个 `selected_source`,与 P1 canonical selection 冲突;
  接进 P2 链子会绕过 candidate scorer/selector。**P2-A 因此不引入它**,它当前全仓无调用方。
  它与 P1 的归属关系需要单独裁决。
- **F11** `_observed_fields` 从不发射 `license`,所以 requirement 里的 `license` 约束
  永远落进 `undecidable_keys`。P2-A 不修;P2-A-04 由 p7 的 `AVAILABLE⇒license` 硬规则兜底。
- **F12** `AssetIntelligenceError` 声明但全仓从未 raise。
- **F13** 11 个架构守卫(`test_p5_1` / `test_p5_1_qualify_harness` / `test_p6_*`)
  用 `git diff --name-only HEAD` 冻结 P0–P4。它们拦的是**未提交**的工作区改动。
  P2-A 提交后恢复通过;守卫本身未被修改。`test_p5_1_qualify_harness` 的失败是
  同根 —— 它以子进程执行 `test_p5_1_architecture.py`,而后者因 p0 未提交而红。