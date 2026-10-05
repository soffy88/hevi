# P2-B0 报告 — Canonical Forbidden-Substitute Semantics

```
P2_B0_STATUS PASS
```

范围:**只做语义与执行原语**。未实现 procedural generation,未实现 Manim。
未修改 F3 / F6 / F9 / F10。未改 p0 / p1 声明点。

## 审计结论

`forbidden_substitutes` 是**一条已定义、已赋值、从未执行的产品约束**:

| 项 | 事实 |
|---|---|
| 声明 | `p0_pipeline.py:112`(字段)、`:560`(值)、`p1_pipeline.py:645`(值) |
| 值 | `("generic_stars", "title_card_only", "large_explanatory_text")`,两处相同 |
| **读取点** | **0 个** |
| `KNOWN_CONSTRAINTS` | 无此键 |
| `check_compatibility` | 无此 checker |

## Owner 裁决:p7

它是**对素材的硬约束**,不是 plan 属性,也不是 intent 属性。
「需要什么」由 `p7.AssetRequirement` 表达,「满不满足」由
`p7/constraint_check.py::check_compatibility` 判定,`AssetDecisionAuthority.decide`
消费的正是 `AssetRequirement`。

`VisualIntent.forbidden_substitutes` 是**上游声明者**,不是 owner。

`constraint_check` 模块 docstring 早已写明「只判**硬约束**」——
被禁止的替代物正是硬约束,归属一致,不需要新概念。

## 关系:表达为 `AssetRequirement` 的 constraint key,不加字段

键名 `forbidden_substitutes`,取值逗号分隔的小写 token。
选 `constraints` 而非新增字段:`constraints` 就是「这条素材必须满足什么」的指定位置,
已被 `to_dict` / `content_hash` 覆盖,零额外成本,不新增 canonical 类型。
新增读取器 `forbidden_substitutes()` 与既有 `query()` 完全同形。

### 堵掉 fail-OPEN 缺口

若解析器对畸形值静默丢弃,打错字符的「禁止」就变成 no-op,即**禁止悄悄变成允许**。
所以 `__post_init__` 直接拒绝:空值、尾随/前导分隔符、空 token、大写、空格、
非法字符、非 ASCII。构造期失败,不留到运行期。

9 组畸形取值有测试覆盖。

## 语义:负向约束 + fail-closed

```text
substitute_kind 落在禁止集合 → False(阻塞)
substitute_kind 不在禁止集合 → True
substitute_kind 缺失/空     → None(**不可判定**)
```

`CompatibilityReport.compatible` 要求 `blocked_keys` 与 `undecidable_keys` **同时**为空,
所以「Acquirer 没说自己是什么」= 拒绝。这是 B0 的核心:
缺自报**不得**默认放行 —— 那与 `artifact_exists == success` 是同类陷阱。

4 组「缺失」形态(无键 / None / "" / 纯空格)均有测试。

## 顺带修掉一个潜在缺陷

`OBSERVED_TO_CONSTRAINT` 表名叫 observed→constraint,但 `check_compatibility` 一直
按 **constraint→observed** 反向查(`get(key, key)`)。全部 7 条都是恒等映射,
所以方向错了从未暴露。B0 加入第一条**非恒等**条目(`substitute_kind` →
`forbidden_substitutes`)后必须按表名方向使用,已加 `_CONSTRAINT_TO_OBSERVED` 反向索引。

既有 7 条因恒等,行为零变化(`test_p7_*` 647 条全绿佐证)。

## `substitute_kind` 是 provenance,不是字节探测

**刻意不加进 `hevi/artifact/probes.py::OBSERVABLE_FIELDS`** —— 那个集合是字节派生事实,
且被 `test_probe_module_cannot_write` 守着。

先例已存在:`OBSERVED_TO_CONSTRAINT` 里的 `license` / `locale` / `period` /
`face_required` **本来就不在** `OBSERVABLE_FIELDS` 中。本 seam 本来就同时接受
「字节探测」与「出处 / 授权 / provenance」两类事实,`substitute_kind` 属于后者。
有测试钉住(`test_b0_substitute_kind_is_not_a_byte_probe_field`)。

### 不封闭 `substitute_kind` 词汇

保持自由字符串(形状校验 + 精确匹配)。禁止集合由产品侧声明,观测值由执行侧声明,
两侧自由串时**精确匹配即为正确语义**:不在禁止集合里就是允许。
Acquirer 谎报自己的种类是**诚信**问题 —— 本仓库对诚信问题的答案是 evidence /
provenance,不是封闭 enum(封闭反而会把既有取值变成迁移负债)。
另有测试证明不是子串匹配(`star` 不会因含于 `generic_stars` 被误判)。

## 为什么 B0 **不**接到生产

若此刻让 p0 的 requirement 带上这条约束,blast radius 是**全量拒绝**:
现有 p0 素材都不携带 `substitute_kind` → `undecidable_keys` 非空 →
`compatible` False → 全部 REJECTED → 所有镜次 unresolved →
`scripts/p0_black_hole_e2e.py` 产不出片子。

正确顺序是**先执行侧、后声明侧**:

1. **B0(本次)**:语义进 seam,测试打在 seam 上。**任何 requirement 都不声明它**
   → 零 blast radius。
2. **后续**:给所有 Acquirer 加 `observed["substitute_kind"]` 自报。
3. **再后续**:requirement 才开始声明 `forbidden_substitutes`。此时「缺自报」
   已在第 2 步被消灭,fail-closed 不会误伤真实素材。

B0 的价值正是:第 3 步发生之前,「禁止替代物」已经有唯一的、有测试的判定原语,
不会再有人发明第二套。

## 守卫是可失败的,不是装饰

- **checker 被摘掉** → `monkeypatch.delitem(_CHECKS, ...)` → seam 变为
  `satisfied=None, detail="no checker"` → `compatible` False(**不放行**)。
- **谓词被写反**(换成恒真)→ `test_b0_forbidden_kind_is_blocked` 的断言不再成立,
  `test_b0_blocking_test_has_teeth` 证明该测试有牙。
- **解析器容错** → `test_b0_malformed_value_is_not_silently_dropped` 反证:
  若容错则该测试立即失败。
- **零 blast radius** → 未声明该约束的 requirement `outcomes == ()`、`compatible is True`。

## 验收结果

```
tests/p10/                          343 passed(39 项新增)
tests/p7_* + tests/p8_2              647 passed(含既有 constraint / decision / freeze 套件)
全量(不含 integration)                6701 passed
ruff / mypy                          本次改动文件 clean
```

全量仅剩 2 项失败:`test_history_arc_adapter`(2,P1 基线即失败,与本次无关);
`test_library`(5,asyncpg 需数据库,单独跑 9 passed)。

## 明确未做

- 不实现 procedural / Manim / 任何生成能力;
- 不改 `VisualIntent` / p0 / p1 声明点;
- 不给 `substitute_kind` 建封闭 enum;
- 不动 `OBSERVABLE_FIELDS`;
- 不动 F3 / F6 / F9 / F10。

## 状态

```
S0/S1/S2/S3  PASS
P1           PASS  4bada6f5
P2-A         PASS  8e90bfd1
P2-F10       PASS  8bfae86c
P2-B0        PASS  <this commit>
P2 overall   NOT QUALIFIED

OPEN:  F3  scoring quality
       F6  canonical import topology
       F9  LocalAssetAcquirer implicit selection(暂不动)
       F14 forbidden_substitutes 执行侧未自报 —— B0 已备好原语,
           待给所有 Acquirer 加 observed["substitute_kind"],之后才可声明该约束
       F10 CLOSED
```

下一步可以写 B1(Manim / procedural capability spec)。写 spec 时必须包含
`substitute_kind` 自报,否则声明侧无法安全开启。