# P4 重定义：Provider Evidence Bridge（LongCat runtime admission）

```yaml
status: P1-P3 PASS (b3dd2ad baseline 保留) · P4 = Evidence Bridge PASS · runtime admission BLOCKED
date: 2026-10-03
verification: tests/p10 131 passed · ruff clean · mypy clean (7 generation source files)
```

## 结论修正

初版审计的表述不够准：**LongCat-Video 上游存在**（官方 `generate_t2v` / `generate_i2v` /
`generate_vc` / `generate_refine`、conditioning frames、KV cache、refinement LoRA + BSA、
480p→720p coarse-to-fine、long-video continuation loop），缺的是**进入 HEVI 可执行依赖面**。

因此：

> **P4 不阻塞 HEVI canonical generation contract；P4 阻塞的是 LongCat runtime admission。**

## 交付（无伪造能力）

| 模块 | 职责 |
|---|---|
| `hevi/generation/evidence.py` | `ExternalEvidence`（带出处）、`ProviderEvidenceBridge`（登记 + 准入闸）、8 条上游声明态 evidence |
| `hevi/generation/longcat_probe.py` | 10 步 Evidence Gate：`SOURCE_AVAILABLE → IMPORTABLE → CHECKPOINT_AVAILABLE → RUNTIME_INITIALIZES → T2V → I2V → VC → REFINEMENT → MEDIA_VALIDATION → CAPABILITY_ADMITTED` |
| `hevi/generation/longcat_adapter.py` | `LongCatVideoAdapterSkeleton`：形状齐备、**能力全 False**、`generate()` 抛 `PROVIDER_NOT_INSTALLED`、**不入 registry** |
| `hevi/video/longcat/__init__.py` | 显式 integration boundary（此前是空目录），声明外部 execution surface，不 vendor 模型代码 |

核心不变量（测试锁死）：

- **声明 ≠ 拥有**：`DECLARED_UPSTREAM` 永不自动变成 `supports(...) == True`；未 probe 的能力保持 declared-only。
- **registry 保持现实**：`get_profile("longcat-video") is None`；`longcat` 现状仍是 `ProviderKind.LLM`。**不新增任何 video provider 条目。**
- **门卡在第一步**：当前默认 `SOURCE_AVAILABLE` 即 FAIL，`first_blocker` 如实指向它，全链十步都记录（不静默跳过）。
- **部分覆盖也可准入**：准入以**已核实**集合为准；只 probe 了 t2v 就只准入 t2v，其余保持 declared。

## 实施期抓到的 3 个真 bug

1. **Evidence 实例跨 bridge 泄漏**：`LONGCAT_VIDEO_UPSTREAM_EVIDENCE` 是模块级 frozen dataclass，
   `mark()` 用 `object.__setattr__` 改状态 → 一次 probe 的 `LOCALLY_VERIFIED` 会污染之后所有 bridge，
   等于「跑过一次就永远认为已核实」。已改为每次 `longcat_bridge()` 重建实例，并加回归测试。
2. **准入条件过严**：原 `try_admit` 要求**所有**声明都被核实，而门链只覆盖 5 个能力 →
   门永远无法通过。已改为按已核实集合准入。
3. **`VideoGenerationCapabilities.values` 遮蔽 `dict.values()`**：`caps.values()` 会静默返回字段而非方法。
   已改名 `declared`。

## 解除阻塞的下一步（二选一）

1. **接入真实 runtime**：给出 LongCat-Video 推理栈的实际位置（外部 execution surface 即可，
   参考官方 Cog wrapper 那种独立 inference 包装），我接上 `runtime_probe` 五步并跑真机验证。
2. **换 provider 承接**：若 LongCat 短期不可用，用已注册的视频 provider（wan / veo3 / kling…）
   接同一 canonical 契约，能力按实测声明。

在两者之一发生前，`longcat-video` 不会出现在 HEVI 能力表里，Director 也不会选它。