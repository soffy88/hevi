# P2-A 入口审计 — Stock Acquirer 真实闭环(改代码前)

范围:**只做 Stock**。不实现 procedural / generation / MPT。不修 F3 / F6。
不动既有 220 项 WIP。不重构 frozen modules。

## 1. 现状:闭环缺哪一环

```text
p0 discovery → ShotPreparation → resolve() → ShotResolution → admit_generation()  ✅ P1 已闭环
                                                     │
                                                     └─ unresolved ←── 这里没有任何东西接住
```

`LocalAssetAcquirer`(`hevi/creative/autonomous/acquire.py:94`)是全仓唯一 Acquirer 实现,
**生产零调用方**(`AssetResolver` 从未带 acquirer 构造)。P2-A 要补的就是这条边。

## 2. 五个必须先裁决的发现

### 2.1 `Acquirer` 协议在结构上就是「选择」——P2-A 不实现它

`hevi/creative/autonomous/resolver.py:31-37`:

```python
async def acquire(self, requirement, provider_id, context) -> tuple[str, AssetEvidence]
```

单值返回 = 单个 source。而 P2 的 invariant 是:

> Acquirer NEVER selects the final production asset.

`LocalAssetAcquirer.acquire:122-126` 正是**违反者**:遍历 `available()` 返回**第一个**
`normalized.usable` 的文件。这就是 selection。

裁决:P2-A 的 Stock Acquirer **不实现 `Acquirer` 协议**,改为
`propose() -> tuple[NormalizedCandidate, ...]` —— 返回**全部**合规候选,由
`scorer → selector` 决定。并在代码注释里写明:等协议本身能表达「多候选」之前,
声称自己是 `Acquirer` 就是撒谎。

`LocalAssetAcquirer` 的违反行为**不在 P2-A 修**(无生产调用方,改动风险大于收益),
登记为 F9。

### 2.2 `resolve()` 无法表达「零候选的 requirement 未解决」——这是闭环的真实卡点

`selection.py:resolve()` 的 `requirement_ids = sorted({c.requirement_id for c in preparation.candidates})`
只从**候选**推导 requirement。所以一个完全没有候选的 requirement 根本不会出现在
`unresolved_requirement_ids` 里 —— 它只是安静地缺席。

P2 的 fallback chain 消费的是 `unresolved`,没有它就没有输入。
生产层自行补 `or {req_id}` 就是 P1 刚拆掉的第二套 resolution 语义,不能做。

裁决:给 `resolve()` 加**可选** `required_requirement_ids: tuple[str, ...] = ()`。
提供时,「在 required 里但零合规候选」的 requirement 计入 `unresolved`。
默认空 = 现有行为不变,不是新 authority,是让既有 authority 能说真话。

### 2.3 F3 让闭环的成立依赖文件名(不改 F3,只登记依赖)

`P0_ScienceRelevanceScorer.__call__` 对 `candidate.asset_ref.lower()` 做子串匹配。
stock 资产若落到 `data/material_cache/<sha256>.mp4`,`asset_ref` 不含任何关键词 → 0.0 分
→ **即使成功 acquire、validate、compatible,仍然 unresolved**。

约束是不许修 F3。所以 P2-A 唯一的做法是让**物化文件名保留 provider 的 slug**
(真实 stock 惯例),例如 `black-hole-accretion-disk-<sha16>.mp4`。

这是**依赖**,不是修复。报告里必须写明:F3 一旦修好,这条依赖自动消失;
在那之前,「P0 科学题材能被 stock 救回」这件事依赖于 slug 里带着词。

### 2.4 没有 stock provider 在册,而 `providers/facts.py` 是别人的未提交 WIP

`PROVIDER_CATALOGUE._SEED`(22 个 profile)全是 video/TTS/render,没有 stock。
`evaluate_provider_policy` 对不在册的 provider 判 `unknown_provider`。

裁决:**不动 `hevi/providers/facts.py`**。P2-A 在自己的模块里构造一个
`ProviderCatalogue`(`ProviderProfile` 支持外部构造 + `register`),连同 `ProviderPolicy`
一起传给 `evaluate_provider_policy(catalogue=...)`。已验证:catalogue-only 的 provider
`PROVIDER_LIMITS` 为 None → 跳过 quality/health 门槛 → 单候选时稳定被选中。

### 2.5 `AssetResolver` 在 P2-A 保持不用

`AssetResolver.resolve` 返回单个 `selected_source`,直接给出「用哪个」——
把它接进链子会**绕过** P1 的 candidate scorer/selector,等于把 selection authority 退回 P2 前。
裁决:P2-A 不引入它。登记为 F10:`AssetResolver` 与 P1 canonical selection 的关系待裁决。

## 3. P2-A 的链(唯一新增的编排)

```text
ShotResolution.unresolved_requirement_ids
    ↓  每个 unresolved id 一个 canonical AssetRequirement
evaluate_provider_policy(catalogue=本地声明)      → provider_id 或 fail closed
    ↓
StockAssetAcquirer.propose(requirement, provider_id)
    │   StockSource.search(query) → 多个 StockItem
    │   逐个 materialize(原子)→ normalize_local_asset()  ← 复用 S2,不重写
    │   返回**全部** NormalizedCandidate(不挑)
    ↓
候选并入 ShotPreparation
    ↓
resolve()  ← 第二次,canonical scorer + selector 照常跑
    ↓
admit_generation()
```

`normalize_local_asset` 已经就是「probe → check_compatibility → candidate + evidence」,
S2 已验证,直接复用。

## 4. 物化约定(全仓第一个被声明的约定)

现状无统一约定。沿用 de-facto stock cache:
- 目录:`MATERIAL_CACHE_DIR` env → 否则 `data/material_cache`
- 文件名:`<slug>-<sha256(url)[:16]><suffix>` —— slug 可读、sha 消歧
- 原子:`.part` → `replace()`,复用 `media_providers.py:186-214` 的做法

## 5. 不在 P2-A

procedural / generation / MPT;F3;F6;F9 `LocalAssetAcquirer` 的 selection 违反;
F10 `AssetResolver` 归属;许可 vocabulary(仍是自由文本,靠 p7 既有硬规则兜底)。

## 6. 新增 finding

- **F9** `LocalAssetAcquirer.acquire` 返回第一个 usable → 违反「Acquirer 不选择」,无生产调用方。
- **F10** `AssetResolver` 返回单 `selected_source`,与 P1 canonical selection 冲突,当前无人调用。
- **F11** `_observed_fields` 从不发射 `license`,所以 requirement 里的 `license` 约束
  永远落进 `undecidable_keys`。P2-A 不修(P2-A-04 由 p7 的 `AVAILABLE⇒license` 硬规则兜底)。
- **F12** `AssetIntelligenceError` 声明但全仓从未 raise。