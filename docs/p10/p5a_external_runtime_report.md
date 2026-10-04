# P5-A External Video Runtime Contract — 实施报告

```yaml
status: P5-A PASS (contract locked, no runtime installed)
date: 2026-10-03
verification: tests/p10 149 passed · 相邻 171 passed · ruff clean · mypy clean (9 generation files)
```

## 立场

> **P4 不阻塞 canonical generation contract；P4 阻塞 LongCat runtime admission。**
> P5-A 把 admission 从「LongCat 专用逻辑」提升为**任何视频后端都能复用的统一机制**。

LongCat 只是第一个 consumer，不是机制的所有者。

## 交付

### `hevi/generation/external_runtime.py` — surface 契约

HEVI 对外部 runtime 的**全部**认知（六件，无第七件）：

```yaml
ExternalRuntimeRef:
  runtime_id, kind: ENDPOINT|PROCESS, version, checkpoint_identity,
  endpoint: {base_url, protocol, auth_ref} | process: {argv_template, workdir, env_ref, timeout_s},
  requirements: {vram_gb, disk_gb, cuda_required}, provenance
```

- `fingerprint()`：换 checkpoint / 换版本 / 换 runtime_id 即换身份 → **证据不继承，必须重验**。
- `auth_ref` 只存引用，不存凭据。
- `EnvironmentRequirements` + `check_environment()`：**环境不满足 → `ENV_BLOCKED`，不去启动注定失败的进程。**
- `VideoRuntimeSurface` Protocol：HEVI 之外那一侧只需实现 `health / capabilities / generate / validate_media`。

### `hevi/generation/qualification.py` — 通用准入链

```text
ENVIRONMENT → HEALTH → CAPABILITY → T2V → I2V → VC → REFINEMENT → MEDIA → ADMITTED
```

- 输出**实测**能力（`admitted_generation` / `admitted_profiles`），未通过探针即 `False`。
- 输出 `first_blocker`；每条 phase 都记录，含 skipped 原因 → 链可审计。
- 与 provider 无关：同一个 `qualify()` 服务任何后端（测试用三个虚构后端验证）。

### `longcat_probe.py` — 去重

runtime 之后的准入链已抽到通用 `qualify()`；LongCat 侧只保留**源码本地化**特有的前三步
（`SOURCE_AVAILABLE / IMPORTABLE / CHECKPOINT_AVAILABLE`）+ `runtime_ref_for_longcat()`。

## 关键判定：本机当前会直接 ENV_BLOCKED

按你给的 Cog wrapper 前置（~48GB+ VRAM / ~25GB checkpoint），`runtime_ref_for_longcat()`
把这些写进 `requirements`。本机是 RTX 3080 10GB，因此：

```text
ENVIRONMENT = BLOCKED ("vram 10.0G < 48.0G")
→ HEALTH/CAPABILITY/… 全部 skipped
→ ADMITTED = PROVIDER_NOT_INSTALLED
→ longcat-video 能力全 False,不进 registry
```

测试锁死了这条路径（`test_longcat_ref_declares_cog_like_requirements`）。
这不是失败，这是**早退**：不去启动一个注定 OOM 的 13.6B runtime。

## capability matrix 状态（全部待 probe）

| Capability | 当前 |
|---|---|
| T2V / I2V / VC / Refinement / Long-video | **False**（待 runtime probe） |
| 720p / 30fps | **False**（作为 `output_profiles` 独立探测） |
| HEVI registry 中的 `longcat-video` | **不存在**（`get_profile(...) is None`） |

## 实施期抓到的一个真缺陷

`qualify()` 在「runtime 未声明任何能力」时提前 `return`，**没有追加终态 ADMITTED phase**
→ 报告链不完整、`first_blocker` 落到不存在的那一环。已修：所有早退路径都必须以 ADMITTED 收尾，
保证任何一份 qualification report 都是完整可审计的。

## 下一步（不改本次结论）

1. 找到能跑 LongCat 的机器/服务（≥48GB VRAM 或远端 endpoint）→ 实现一个真实
   `VideoRuntimeSurface`（HTTP 客户端或子进程调用），接 `qualify()` 跑**五步真机 probe**；
2. probe 全绿后 `longcat-video` 才会出现在 HEVI 能力表，Director 才可能选它；
3. `ExternalRuntimeRef.fingerprint()` 变化（换 checkpoint/版本）时必须重跑整条链。
