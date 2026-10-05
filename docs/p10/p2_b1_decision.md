# P2-B1 决策 — ProceduralAcquirer + Manim capability

范围:**一种能力** `PROCEDURAL_MOTION_GRAPHICS`,**一个 backend** Manim。
不做 Blender / Remotion / HTML-GSAP。不做 P2-C generation,不做 P2-D MPT。
不动 F3 / F6 / F9 / F10。不改 p7 语义(B0 已定)。

## 1. 复用既有能力,不新造渲染器

`hevi/providers/manim/provider.py::manim_generate` 已是 canonical Manim 能力
(signature 含 `output_path / duration_s / width / height / fps / quality / code`)。
实测:`quality="low"` 下 **0.2s** 出片,`validate_media` 通过(854x480 / 2.0s / h264)。

所以 B1 **不自己 spawn manim CLI**,直接调它。渲染器归 provider 层,本包只做
「按 requirement 产出候选」—— 与 P2-A 的 Stock 完全同形。

## 2. `substitute_kind` 怎么进 seam

B0 的原语已经在 `check_compatibility`,但它需要 `observed["substitute_kind"]`。
现有唯一入口 `normalize_local_asset` 内部自建 `observed`,没有注入点。

裁决:给它加**可选** `observed_extra: Mapping[str, object] | None = None`,
与 `observed = {**_observed_fields(validation), **observed_extra}` 合并。

- 既有调用方不传 → 行为**完全不变**(`test_s2_acquisition.py` 全绿佐证);
- 不新增第二个 validation 腿 —— 复用 S2 的「probe → compat → candidate + evidence」;
- B0 裁决里「seam 接受 provenance 事实」在这里第一次真正被生产使用。

## 3. 能力名与 provider 声明

- `PROCEDURAL_MOTION_GRAPHICS = "motion_graphics"` —— 复用 catalogue **已有**拼写
  (`remotion` / `html_gsap` 的 `capabilities` 里就有),不引入第二种大小写风格。
- provider = `manim`,`ProviderPolicy(mode="code_scene", candidates=["manim"])`。
  实测 `mode="t2v"` 会被拒(`manim` 的 `PROVIDER_LIMITS.modes == {"code_scene"}`),
  `mode="code_scene"` 正常选中。
- provider 事实用**既有全局 catalogue**(`manim` 已在册:LOCAL / GENERATED / ADOPTED),
  **不**新建 catalogue —— `register` 重复会抛 `PROVIDER_PROFILE_DUPLICATE`。
  与 P2-A 的差别:P2-A 的 stock provider 不在册;`manim` 在册,重复声明反而是错的。

## 4. 能力校验必须自己 fail-closed(见 finding F16)

`required_capabilities` 与 `ProviderProfile.capabilities` 是**两套不相通的机制**:
policy 检查的是 `getattr(PROVIDER_LIMITS[pid], capability)` —— 即
`ProviderLimits` 的**字段名**(`native_audio` / `lip_sync` / `fps_options` …),
而**不是** catalogue 里声明的 `capabilities` 元组。

后果:catalogue 声明的 `motion_graphics` / `explainer` / `captions` 这类 token
**永远无法通过 `required_capabilities` 满足**(实测 `capability_missing:motion_graphics`)。
登记为 **F16**,本阶段不修。

因此 B1 的能力校验落在 acquirer 自己身上:`ProceduralAcquirer` 声明它只支持
`PROCEDURAL_MOTION_GRAPHICS`,被要求别的就拒绝渲染。理由:能力是我自己的能力,
我比 policy 更清楚;而 policy 那条路当前不可用。

## 5. `substitute_kind` 必须诚实 —— 本切片的核心风险

`substitute_kind` 由 **recipe** 声明(配方的固有属性),**不得**由
`propose()` 根据 requirement 的禁止清单挑选。否则 acquirer 就成了
「看约束挑标签」的角色,等于自己给自己发通行证。

所以:同一个 recipe + 同一个 query → **无论** requirement 禁止什么,
`substitute_kind` 恒定。有行为测试钉住。

两个 recipe,各自诚实:

| recipe | substitute_kind | 说明 |
|---|---|---|
| `explanatory_motion_graphics` | `motion_graphics` | 有动画元素的示意画面,**不是**标题卡 |
| `generic_stars` | `generic_stars` | 装饰性星空填充,正是 p0 声明要禁的那类 |

这组划分也解释了为什么 B0 必须先做:**示意性画面可以合理满足「解释某个概念」的
需求;装饰性填充不能。** 被禁止的替代物正是把这两者区分开的机制。

## 6. p0 链从「一个 acquirer」泛化为「有序链」

```text
resolve → unresolved?
    ├─ 否 → 结束
    └─ 是 → acquirer[0].propose() → 有新候选? → **重新 resolve** → 仍 unresolved?
              ├─ 否 → 结束
              └─ 是 → acquirer[1].propose() → …
```

停止条件是 `resolution.unresolved` —— **canonical authority 说话**,不是
acquirer 说「我够了」。每个 acquirer 回合后都重新 resolve,
最终 selected 仍然只由 `scorer → selector` 决定。

`stock_acquirer` 参数改为 `acquirer_chain: tuple[Any, ...] = ()`。
默认空 = 行为与 P2-A 一致(fail closed,不做 fallback)。

## 7. 明确不做

- Blender / Remotion / HTML-GSAP;
- 多种能力(只 `PROCEDURAL_MOTION_GRAPHICS`);
- 修 F16(能力机制);
- 让 p0/p1 真的**声明** `forbidden_substitutes` 约束(B0 已说明顺序:
  执行侧自报 → 之后才可声明;B1 完成执行侧,但声明侧仍需所有 Acquirer 都自报,
  故留到后续 slice);
- 不动 p7 语义。