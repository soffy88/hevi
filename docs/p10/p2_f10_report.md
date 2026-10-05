# P2-F10 报告 — `AssetResolver` 角色冻结

范围:**只做架构收口**。未实现 P2-B / P2-C / P2-D。未动 F3 / F6 / F9。

```
P2_F10_STATUS PASS
```

## 裁决

`AssetResolver` = **provider 平面的执行 adapter,仅此而已**。

把 `ProviderDecision` + 执行侧能力转成带 evidence 的 P7 `AssetDecision`。
它**不**是候选选择器,**不**是 generation admission,**不**在生产路径上。

三条不可让渡的性质,由测试逐条锁死:

| 性质 | 守卫 |
|---|---|
| 不产候选 | `test_f10_resolver_module_never_constructs_a_candidate` —— AST 扫 `resolver.py`,出现 `AssetCandidate` / `select_candidate` / `admit_generation` / `ready_for_generation` 即失败 |
| 不产 admission | `test_f10_usable_is_not_generation_admission` + `test_f10_usable_does_not_imply_admit_generation` —— `usable=True` 仍然进不了 `admit_generation` |
| 不在生产路径 | `test_f10_production_modules_do_not_import_the_resolver` —— AST 扫 7 棵生产树 163 个文件 |

## 改了什么

| 文件 | 改动 |
|---|---|
| `hevi/creative/autonomous/resolver.py` | 字段 `selected_source` → **`obtained_source`**;新增 `RESOLVER_ROLE` 冻结声明 + `ResolverRole` + `assert_resolver_is_not_production_authority()`;docstring 写入 F10 裁决 |
| `tests/p10/test_p2_f10_resolver_role.py`(新,10 项) | 四类守卫 + 守卫自身的**可失败性**验证 |
| `tests/p10/test_s1_canonicalization.py` | 改断言字段名 + 注明 F10 理由 |
| `tests/p10/test_s2_acquisition.py` | 改断言字段名 + 新增「`usable` 不等于可生成」 |

## 关键点:问题不是「它会选」,而是它的输出**读起来像**选

`resolver.py` 内部没有排序、没有 `max`、没有比较 —— 它确实不越权。
风险是**类型层面的语义**:

```python
selected_source: str
@property
def usable(self) -> bool: ...
```

`usable == True` 且 `selected_source == "media/x.mp4"`,在调用方眼里就是
「资产已定,拿它去生成」。而它的值直接来自单值返回的 `Acquirer.acquire()` ——
**acquirer 的第一次命中**,正是 P1 刚从 p0 拆掉的那个形态。

更糟的是:`test_s1_canonicalization.py:84` 原本就断言
`out.selected_source == "media_assets/control_room.mp4"`。**绿灯保护的是错误语义。**

所以改名不是洁癖:让类型本身不再冒充选择结论,比注释更难被误用。
`obtained_source` 说的是「acquirer 拿到了什么」,不是「谁被选中」。

## 两条回归测试的改动需要复核

改字段名会红 2 条既有测试。它们断言的是**被本裁决判为错误**的语义,
已改为断言 `obtained_source`,并各自**加**一条正向约束
(`usable` 不等于可生成 / 不得暴露 admission 词汇)。

这不是「改测试让它变绿」,是把测试从保护错误语义改成保护正确语义。
**回退点:`ExecutionReadyResolution.selected_source` → `obtained_source` 的改名。**

## 守卫是有效的,不是装饰

逐条验证过会失败:

- 生产 import 守卫:临时往 `hevi/production/delivery_gate.py` 追加
  `from hevi.creative.autonomous.resolver import AssetResolver`,
  守卫报 `RESOLVER_ON_PRODUCTION_PATH: {'hevi/production/delivery_gate.py:260'}`;
  已还原,`git diff` 干净。
- 冻结声明守卫:`test_f10_assert_guard_detects_a_regression` 把 `RESOLVER_ROLE`
  三个布尔位逐个改成 `True`,断言 `assert_resolver_is_not_production_authority()`
  每次都抛 `RESOLVER_OVERREACH` / `RESOLVER_ON_PRODUCTION_PATH`。
- 扫描范围非空:7 棵生产树、163 个 `.py` 文件实际被遍历。

## 验收结果

```
tests/p10/                          304 passed(10 项新增)
ruff(本次全部改动文件)                clean
mypy resolver.py                    Success
```

既有 294 条 p10 测试全绿,含 S1/S2/S3 三套守卫。

## 为什么现在做

P2-B procedural 是下一个要接线的东西。若那时才裁决,接线的人面对的是一个
字段叫 `selected_source`、属性叫 `usable`、还有绿灯测试保护的类 ——
几乎必然接成 `Acquirer → selected asset`。**先冻结,再接线。**

## 明确未做

- 未删除 `AssetResolver` —— S1 canonical vocabulary 已注册它
  (`test_s1_canonical_authority.py:110`),删除要连带改 S1,那是 S1 的账。
- 未改 `Acquirer` 协议的单值返回 —— 协议怎么改留给 P2-B
  (Procedural 同样不能单值)。
- 未修 F9 `LocalAssetAcquirer`。
- 未动 p7 `AssetDecision.selected_source`(`ACCEPTED_WITHOUT_SOURCE` 等不变量依赖它)。
- 未实现 P2-B / P2-C / P2-D。

## 状态更新

```
S0/S1/S2/S3  PASS
P1           PASS  4bada6f5
P2-A         PASS  8e90bfd1
P2-F10       PASS  <this commit>
P2 overall   NOT QUALIFIED   (B/C/D 未做)

OPEN:  F3 scoring quality
       F6 canonical import topology
       F9  LocalAssetAcquirer implicit selection(暂不动)
       ~~F10 AssetResolver implicit selection~~  ← 本次关闭
```

下一步:P2-B Procedural Acquirer。F10 已冻结,接线时不存在
「Acquirer → selected asset」的入口。