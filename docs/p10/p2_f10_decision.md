# P2-F10 裁决 — `AssetResolver` 的最终角色冻结

范围:**只做架构收口**。不实现 P2-B procedural、不实现 P2-C generation、不实现 P2-D MPT。
不动 F3 / F6 / F9。不动既有 WIP。不重构 frozen modules。

## 1. 事实

`hevi/creative/autonomous/resolver.py`,115 行。`AssetResolver.resolve()` 做三件事:

```text
provider_decision(权威产出)
    → Acquirer.acquire() → tuple[str, AssetEvidence]   ← 单值
    → AssetDecisionAuthority.decide(selected_source=…, evidence=…)
    → ExecutionReadyResolution(selected_source=…, usable=…)
```

- **生产调用方:0 个。** 全仓引用只出现在 `tests/p10/test_s1_canonicalization.py`、
  `tests/p10/test_s2_acquisition.py`、两个 S1/S3 守卫,以及 `autonomous/__init__.py` 的 re-export。
- 已在 `test_s1_canonical_authority.py:110` 注册为 canonical vocabulary
  (`require_canonical` 允许它),**不是**被禁的新词汇。
- `resolver.py` 自身的 `FORBIDDEN_METHODS` 已挡住打分/排序/挑 provider/覆盖决策。

## 2. 问题不是「它会选」,而是它的输出**读起来像**选

它内部没有排序、没有 `max`、没有比较 —— 单测也证明它不越权。真正的结构性风险是**类型层面的语义**:

```python
@dataclass(frozen=True)
class ExecutionReadyResolution:
    selected_source: str
    @property
    def usable(self) -> bool: ...
```

`usable == True` 且 `selected_source == "media/x.mp4"`,在任何调用方眼里就是
「资产已定,拿它去生成」。而 `selected_source` 的值直接来自单值返回的
`Acquirer.acquire()` —— 也就是**acquirer 的第一次命中**,正是 P1 刚从 p0 拆掉的那个形态。

只要 P2-B/C/D 有人图省事走这里,就会原样长出:

```text
Acquirer → selected asset          ← 结构性倒退
```

而且这个倒退**测试是绿的**:`test_s1_canonicalization.py:84` 现在就断言
`out.selected_source == "media_assets/control_room.mp4"`。绿灯保护的是错误语义。

## 3. 裁决

### 角色:provider 平面的执行 adapter,**仅此而已**

`AssetResolver` 负责:把 `ProviderDecision` + 执行侧能力转成带 evidence 的 P7 `AssetDecision`。
它**不**是候选选择器,**不**是 generation admission,**不**在生产路径上。

### 三个不可让渡的性质

1. **不产候选。** 它从不构造 `AssetCandidate`,所以它在结构上无法参与 P1 的 selection。
2. **不产 admission。** `ExecutionReadyResolution.usable` **不是** `ready_for_generation`,
   不得被任何 generation 代码消费。唯一的 admission 是
   `selection.admit_generation(resolution, candidates)`,唯一的选择是 `select_candidate`。
3. **不在生产路径。** 无生产调用方,且由 AST 守卫锁死:`hevi/production/**` 与
   `hevi/execution/**` 不得 import `AssetResolver` / `ExecutionReadyResolution`。

### 因此做两处最小改动

**(a) 字段改名:`selected_source` → `obtained_source`。**
它记录的是「acquirer 拿到了什么」,不是「谁被选中」。改名让类型本身不再冒充选择结论,
比注释更难被误用。同步把 `.usable` 的语义写进 docstring:它是
「p7 决策已 ACCEPTED」,**不是**「这个资产可以用」。

**(b) 加机器可读的冻结声明 + `assert_resolver_is_not_production_authority()`。**
与 S3 的 `CANDIDATE_SELECTION` / `assert_single_authority()` 同形:
角色写在数据里,守卫读数据,不是散落在注释里。

## 4. 明确不做

- 不删除 `AssetResolver` —— S1 canonical vocabulary 已注册它,删除要连带改
  `test_s1_canonical_authority.py:110`,那是 S1 的账不是 F10 的账。
- 不改 `Acquirer` 协议本身(单值返回)—— P2-A 已证明可以不实现它就绕过;
  协议怎么改留给 P2-B(Procedural 同样不能单值)。
- 不修 F9 `LocalAssetAcquirer` 的单值 `acquire`(按指示不动)。
- 不动 p7 `AssetDecision.selected_source` —— 那是 p7 的词汇,`ACCEPTED_WITHOUT_SOURCE`
  等不变量依赖它。改名的只有 autonomous 自己的投影类型。

## 5. 回归

- 改 `selected_source` 会红 2 个既有测试(`test_s1_canonicalization.py:84`、
  `test_s2_acquisition.py:160`)。它们断言的是**被裁决为错误**的语义,
  改为断言 `obtained_source` 并**加**一条:该值不得被当作 generation admission。
  这不是「改测试让它变绿」,是把测试从保护错误语义改成保护正确语义 —— 回退点在字段改名。
- 新增 F10 守卫测试:生产模块不得 import;`AssetResolver` 不得构造 `AssetCandidate`;
  `ExecutionReadyResolution` 不得出现在 p0 的 generation 门附近。

## 6. 为什么现在做

P2-B procedural 是下一个要接线的东西。如果那时才裁决,接线的人面对的是一个
字段名叫 `selected_source`、属性叫 `usable`、还有绿灯测试保护的类 —— 几乎必然接成
`Acquirer → selected asset`。先冻结,再接线。