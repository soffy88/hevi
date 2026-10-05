# P2-B0 审计与裁决 — Canonical Forbidden-Substitute Semantics

范围:**只做语义与执行原语**。不实现 procedural generation,不实现 Manim。
不修改 F3 / F6 / F9 / F10。不重构 frozen modules。

## 1. 审计:`forbidden_substitutes` 现状

| 项 | 事实 |
|---|---|
| 声明点 | `p0_pipeline.py:112`(字段)、`:560`(值)、`p1_pipeline.py:645`(值) |
| 值 | `("generic_stars", "title_card_only", "large_explanatory_text")`,两处完全相同 |
| **读取点** | **0 个。** 全仓无任何代码读它 |
| `KNOWN_CONSTRAINTS` | 无对应键(只有 period / face_required / resolution / duration / license / locale / aspect / query) |
| `check_compatibility` | 无对应 checker |
| `OBSERVED_TO_CONSTRAINT` | 无对应 observed 字段 |

即:**一条已定义、已赋值、从未执行的产品约束。** HEVI 明确宣告过
「不要拿通用星空 / 纯标题卡 / 大段说明文字代替真实画面」,但没有任何机制拦得住。

为什么它必须在 procedural 之前做:`generic_stars` 正是通用合成图案
(渐变 / 噪声 / testsrc)的产物,`title_card_only` 正是标题卡的产物。
先做 procedural fallback,等于先造出一个必然违反既有产品约束的能力,
再回头补约束 —— 那时 procedural 已经有调用方,补约束就是「破坏既有功能」。

## 2. Owner 裁决:**p7**

理由:它是**对素材的硬约束**,不是 plan 属性,也不是 intent 属性。

- 说「需要什么」的是 `p7.AssetRequirement`;
- 判「这份素材满不满足」的是 `p7/constraint_check.py::check_compatibility`;
- `AssetDecisionAuthority.decide` 消费的正是 `AssetRequirement`。

所以 owner = p7,表达形式 = `AssetRequirement` 的一个 constraint key,
判定位置 = canonical compatibility seam。`VisualIntent.forbidden_substitutes`
是**上游声明**(p0/p1 产出),必须被投影进 requirement;它自己不是 owner。

`constraint_check.py` 模块 docstring 已经写明「只判**硬约束**。软分(scoring)不属本模块」。
被禁止的替代物正是硬约束 —— 归属一致,不需要新概念。

## 3. 与 `AssetRequirement` 的关系

**键名**:`forbidden_substitutes`
**取值**:逗号分隔的小写 token(`[a-z0-9_]+`),例如
`"generic_stars,title_card_only,large_explanatory_text"`

选 `constraints` 而**不是**给 `AssetRequirement` 加字段,理由:
- `constraints` 就是「这条素材必须满足什么」的指定位置;
- 加字段要改 `__post_init__` / `to_dict` / `content_hash`,并让 `AssetDecision`
  的 fingerprint 形状变一次 —— 而 `constraints` 已经被 `to_dict` 覆盖,零额外成本;
- 不新增 canonical 类型。

`asset_requirement.py` 加一个读取器 `forbidden_substitutes() -> tuple[str, ...]`,
与既有 `query()` 完全同形(`constraint_map().get(...)`)。

### fail-OPEN 缺口必须堵

若解析器对畸形值**静默丢弃**,那么打错一个字符的约束就变成 no-op,
即「禁止」被悄悄变成「允许」。所以 `__post_init__` 必须**直接拒绝**畸形取值:
空 token、大写、空格、非法字符 → `ValueError`。

这与既有 `EMPTY_ASSET_CONSTRAINT_KEY` 同一性质:构造期失败,不留到运行期。

## 4. 语义:负向约束

```python
def check_forbidden_substitutes(expected: str, observed: object) -> bool | None:
    """observed 是素材自报的 substitute_kind。

    - observed is None / 空 → None(**不可判定**,不是通过)
    - observed ∈ 禁止集合    → False(阻塞)
    - observed ∉ 禁止集合    → True
    """
```

关键:**缺 `substitute_kind` 时必须不可判定,而不是通过。**
`CompatibilityReport.compatible` 要求 `blocked_keys` 与 `undecidable_keys` 同时为空,
所以「Acquirer 没说自己是什么」= 拒绝。这正是 B0 要求的 fail-closed。

## 5. observed 字段:`substitute_kind` —— 它是 provenance,不是 probe

`check_compatibility` 的 docstring 说 observed 用 `OBSERVABLE_FIELDS` 的键,
但 `OBSERVED_TO_CONSTRAINT` 里已经包含 `license` / `locale` / `period` /
`face_required` —— **这四个都不在 `OBSERVABLE_FIELDS` 里**(那个集合是字节派生,
且被 `test_probe_module_cannot_write` 守着)。

所以 seam 本来就接受**字节探测之外的事实**(授权、出处、年代)。
`substitute_kind` 属于同一类:**Acquirer 自报「我产出的是什么」**。

因此:
- **不加进 `hevi/artifact/probes.py::OBSERVABLE_FIELDS`** —— 那会污染字节观测词汇,
  且与该模块的职责边界冲突;
- `OBSERVED_TO_CONSTRAINT` 加 `"substitute_kind" → "forbidden_substitutes"`。

### 不封闭 substitute_kind 词汇

`substitute_kind` 保持自由字符串(形状校验 `[a-z0-9_]+`,精确匹配)。
理由:禁止集合由 requirement 侧(产品)声明,观测值由 acquirer 侧(执行)声明。
两侧都是自由串时,精确匹配的语义是**正确的** —— 不在禁止集合里就是允许。
Acquirer 若谎报自己的种类,那是**诚信**问题,不是机制问题;
本仓库对诚信问题的答案是 evidence / provenance,不是封闭 enum。
(封闭 enum 反而会把 p0/p1 已有的取值变成需要迁移的负债。)

## 6. 为什么 B0 **不**把它接到生产

如果此刻让 p0 的 `_requirement_for()` 带上这条约束,blast radius 是**全量拒绝**:
现有 p0 素材都不携带 `substitute_kind` → `undecidable_keys` 非空 →
`compatible` False → 全部 REJECTED → 所有镜次 unresolved →
`scripts/p0_black_hole_e2e.py` 产不出片子。

所以正确的接入顺序是**先执行侧、后声明侧**:

1. **B0(本次)**:语义进 canonical seam,测试打在 seam 上。**任何 requirement 都不声明它**
   → 零 blast radius。
2. **后续 slice**:给所有 Acquirer 加 `observed["substitute_kind"]` 自报。
3. **再后续**:requirement 才开始声明 `forbidden_substitutes` —— 此时
   「缺自报」已经在第 2 步被消灭,fail-closed 不会误伤真实素材。

B0 的价值正是:第 3 步发生之前,「禁止替代物」这件事已经有唯一的、
有测试的判定原语,不会再有人发明第二套。

## 7. 明确不做

- 不实现 procedural / Manim / 任何生成能力;
- 不改 `VisualIntent` / p0 / p1 的声明点(第 3 步才做);
- 不给 `substitute_kind` 建封闭 enum;
- 不动 F3 / F6 / F9 / F10;
- 不动 `OBSERVABLE_FIELDS`。