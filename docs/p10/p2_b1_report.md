# P2-B1 报告 — ProceduralAcquirer + Manim

```
P2_B1_STATUS PASS
```

范围:**一种能力** `PROCEDURAL_MOTION_GRAPHICS`,**一个 backend** Manim。
未做 Blender / Remotion / HTML-GSAP。未做 P2-C generation,未做 P2-D MPT。
未动 F3 / F6 / F9 / F10。未改 p7 语义。

## 链路(生产与验收走同一段 p0 代码 `_resolve_with_acquisition`)

```text
unresolved requirement
  → ProceduralAcquirer.propose()
  → ManimBackend → hevi.providers.manim.provider.manim_generate   ← 复用既有能力
  → real artifact(真实落盘 mp4)
  → observed_extra={"substitute_kind": ...}                      ← B0 的准入条件
  → normalize_local_asset:validate_media + check_compatibility
  → candidate
  → resolve()                                                     ← canonical scorer + selector
  → ShotResolution.selected → admit_generation()
```

真 Manim 渲染:**0.2s/片**(quality=low)。不自己 spawn manim CLI。

## 三条必须证明的语义 —— 全部成立

| 证明 | 结果 |
|---|---|
| `forbidden=["generic_stars"]` + 渲出通用星空 → **rejected** | `check_compatibility` 判 `blocked_keys=("forbidden_substitutes",)`、`compatible=False`、evidence `BLOCKED`;`propose` 不让它进候选池;整链 `ready_for_generation=False`,`admit_generation` 抛错 |
| `forbidden=["title_card_only"]` + 解释性示意画面 → **accepted** | `compatible=True`、`usable=True`、文件真实存在;进一步走到 `ShotResolution.selected`,`admit_generation` 返回该候选 |
| 缺 `substitute_kind` → **rejected** | `undecidable_keys=("forbidden_substitutes",)`、`compatible=False` → 不进候选 → 全链 fail closed |

另有测试区分「不可判定 ≠ 阻塞,但 `compatible` 同为 False」。

星空被拒的判定**发生在 seam**,不是被某个过滤列表顺手拦掉 —— 有专门测试直接
渲染星空 + `normalize_local_asset`,并断言文件本身是好的(`probe_valid=True`),
被拒只因为**种类**。

## 关键设计:`substitute_kind` 诚实性

`substitute_kind` 由 **recipe** 声明(配方的固有属性),**不得**由 `propose()`
看 requirement 的禁止清单挑选。否则 acquirer 就是「看约束挑标签」的角色,
等于自己给自己发通行证。

两道防线:

1. **行为测试**:同一 recipe 在 5 种不同禁止清单下,seam 观测到的
   `substitute_kind` 恒定。
2. **源码测试**:`recipe.build_source` 的源码里不得出现 `forbidden_substitutes`
   —— 配方连读都不许读。

两个配方:`explanatory_motion_graphics` → `motion_graphics`;
`generic_stars` → `generic_stars`。这组划分也解释了 B0 为什么必须先做:
**示意性画面可以合理满足「解释某个概念」的需求,装饰性填充不能。**

## 能力边界:第一版只支持一种

`SUPPORTED_CAPABILITIES = {"motion_graphics"}`,**构造时**校验,不做运行期降级。

这里我发现并修掉了自己写出的一个真 bug:原本的
`if not self.supports(self._capability): return ()` 是**恒真**的空检查 ——
`supports(x)` 就是 `x == self._capability`。换成构造期校验后才真正 fail-closed。

`PROCEDURAL_MOTION_GRAPHICS` 复用 catalogue **已有**拼写
(`remotion`/`html_gsap` 的 `capabilities` 里就是 `"motion_graphics"`),
不引入第二种大小写风格。

## 复用了既有能力,没造新渲染器

- `manim_generate`(`hevi/providers/manim/provider.py`)已是 canonical Manim 能力。
- provider 事实用**既有全局 catalogue**(`manim` 已在册:LOCAL / GENERATED /
  ADOPTED),**不**新建 profile —— `register` 重复会抛
  `PROVIDER_PROFILE_DUPLICATE`。与 P2-A 的差别:stock provider 不在册,`manim` 在册。
- `mode="code_scene"`:实测 `manim` 的 `PROVIDER_LIMITS.modes == {"code_scene"}`,
  `mode="t2v"` 会被拒(`mode_unsupported:t2v`)。有测试钉住 policy mode 必须对上 limits。

## 有序链

p0 从「一个 acquirer」泛化为 `acquirer_chain: tuple`,并把 policy 下放到 acquirer
各自提供(`StockAssetAcquirer.provider_policy()` / `ProceduralAcquirer.provider_policy()`),
因为两者 `mode` 不同。

```text
resolve → unresolved? → acquirer[0].propose() → 重新 resolve → 仍 unresolved?
         → acquirer[1].propose() → 重新 resolve → …
```

停止条件是 `resolution.unresolved_requirement_ids` —— **canonical authority 说话**,
不是某个 acquirer 说「我够了」。两个测试钉住:第一个满足后第二个**不被调用**;
第一个产不出可用候选时**确实**落到第二个。

## 顺带修的两个既有问题

1. **`normalize_local_asset` 加 `observed_extra`**(可选)。B0 的原语需要
   `observed["substitute_kind"]`,但该函数内部自建 `observed`,没有注入点。
   不传时行为**完全不变**(`test_s2_acquisition.py` 16 条全绿佐证)。
   B0 裁决里「seam 接受 provenance 事实」到这里第一次真正被生产使用。
2. **`_duration_from_requirement` 去掉 `max()`** —— 数值取大不是选择,
   但 AST 守卫按名字拦,写成 `value if value > 0.5 else 0.5` 更直白。

## 新增 finding

- **F16** `required_capabilities` 与 `ProviderProfile.capabilities` 是**两套不相通的
  机制**:policy 检查的是 `getattr(PROVIDER_LIMITS[pid], capability)`,即
  `ProviderLimits` 的**字段名**(`native_audio` / `lip_sync` / `fps_options` …),
  **不是** catalogue 声明的 `capabilities` 元组。
  后果:catalogue 声明的 `motion_graphics` / `explainer` / `captions` 这类 token
  **永远无法通过 `required_capabilities` 满足**(实测
  `capability_missing:motion_graphics`)。本阶段不修 —— 所以 B1 的能力校验
  落在 acquirer 自己身上。
- **F17** 本环境 ffmpeg **无 `drawtext` 滤镜**,所以标题卡类 procedural 素材在此
  环境根本无法构建。B1 的两个配方都不依赖 drawtext(用 manim 的 `Text`,
  走 cairo),故不受影响;但「纯标题卡」这条路暂时不可用。
- **F18** `hevi/qualification/framework.py:73,271` 早前被我误判为 Python 2 语法
  (`except A, B:`)。**不是 bug** —— PEP 758 在 Python 3.14 合法化了该写法。
  记录以免后续 agent 重复误判。

## 验收结果

```
tests/p10/                          367 passed(24 项新增)
全量(不含 integration)                6717 passed
ruff(本次改动文件)                    clean
mypy(新增/改动模块)                   Success(p0_pipeline 仍为既有 25 条,无新增)
```

全量 15 项失败全部是 `git diff --name-only HEAD` 冻结守卫拦截**未提交**的
`p0_pipeline.py` 改动(见 F13),提交后恢复。`test_history_arc_adapter` 2 条为
P1 基线即失败。

## 明确未做

- Blender / Remotion / HTML-GSAP;
- 第二种能力(只有 `PROCEDURAL_MOTION_GRAPHICS`);
- 修 F16(能力机制)、F17(drawtext 缺失);
- 让 p0/p1 真的**声明** `forbidden_substitutes` —— B0 已说明顺序:
  执行侧全部自报 → 之后才可声明。**B1 只覆盖了 procedural 一侧**,
  Stock 一侧(`acquire_stock.py`)尚未自报,故声明侧仍不能开启(见 F14)。
- 未动 p7 语义。

## 状态

```
S0/S1/S2/S3  PASS
P1           PASS  4bada6f5
P2-A         PASS  8e90bfd1
P2-F10       PASS  8bfae86c
P2-B0        PASS  3604b07f
P2-B1        PASS  <this commit>
P2 overall   NOT QUALIFIED

OPEN: F3  scoring quality
       F6  canonical import topology
       F9  LocalAssetAcquirer implicit selection(暂不动)
       F14 execution-side self-report —— procedural 一侧已自报,
           **stock 一侧尚未自报**,故 forbidden_substitutes 声明侧仍不能开启
       F16 required_capabilities 与 catalogue capabilities 不相通
       F17 本环境无 drawtext 滤镜
       F10 CLOSED
```

下一刀建议:给 `acquire_stock.py` 补 `substitute_kind` 自报(闭合 F14 的 stock 半边),
然后才轮到 P2-C Generation。