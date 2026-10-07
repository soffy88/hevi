# P0-4.2.0 — provider authority classification

P0-1 and P0-4.0 counted **six** provider-facing registries. That count was wrong in
both directions: there are **eight** sources of provider facts, and one of the six is
not a provider registry at all.

This document classifies every source by the *dimension* it is authoritative for,
then records what happens when you ask two of them the same question.

---

## 1. Classification by dimension

| # | Source | Dimension it owns | Kind |
|---|--------|-------------------|------|
| 1 | `obase.ProviderRegistry` (`providers/registry.py:8`) | **executability + category identity** — `(category, name) → callable` | binding layer, not a fact table |
| 2 | `PROVIDER_CATALOGUE` (`providers/facts.py:356`) | **identity metadata** — kind, locality, license, runtime class, artifact contract | fact table, self-declared canonical |
| 3 | `PROVIDER_LIMITS` (`video/capability_guard.py:27`) | **capability + quantitative limits** — modes, max resolution/duration/fps, native_audio, lip_sync, last_verified | fact table |
| 4 | `RUNTIME_SPECS` (`providers/runtime_specs.py:247`) | **probeability** — health-check kind, target, auth requirements | derived / operational |
| 5 | `PROVIDER_QUALITY` (`cost/selector.py`) | **human-assigned quality judgement** (0–10) | judgement, not fact |
| 6 | `PROVIDER_SPECS` (`provider_policy/runtime.py:38`) | **setup and credential documentation** — required env, setup prose, default endpoint | docs, not executable |
| 7 | per-provider `*_CAPABILITY` rows (`h3_local`, `manim`, `hyperframes`, `echo_mimic`) | **schema-driven capability evidence** | fact table, per provider |
| 8 | `ProductionAdapterRegistry` (`production/adapters.py:17`) | **`production_source` → task adapter** | *not a provider registry* |

### The two corrections

**`ProductionAdapterRegistry` is not in scope.** Its key is `config_json.production_source`
— a *task shape* (`director_graph`, `explainer`, `clip_video`). It never names a provider.
Counting it as a provider registry was the error that produced "six registries to merge";
merging it into a provider catalogue would have been a category mistake.

**There is an eighth source, and it is in active use.** `PROVIDER_QUALITY`
(`cost/selector.py`) is read directly by the admission policy at `policy.py:155` and by
`cost/shot_router.py`. It is a curated 0–10 score — a human judgement, not a
measurement — and it silently gates selection.

**There is also a seventh: per-provider `*_CAPABILITY` dicts.** Both
`capability_guard.py:60` and `registry.py:304` cite `H3_LOCAL_CAPABILITY` as the
*evidence* for their limits. The limits table and the provider's own capability row
are therefore two copies of one fact, which is precisely the double-source problem
this phase exists to remove.

---

## 2. Identity: how many providers, and where do they disagree?

| Source | Count |
|--------|-------|
| `PROVIDER_CATALOGUE` | 20 |
| `RUNTIME_SPECS` | 15 |
| `PROVIDER_LIMITS` | 14 |
| `PROVIDER_QUALITY` | 16 |
| `PROVIDER_SPECS` | 8 |
| `ProviderRegistry` (live) | 37 |
| `ProductionAdapterRegistry.sources()` | not provider-keyed |

**20 providers exist in `ProviderRegistry` and no fact source at all** — `edge_tts`,
`vibevoice`, `openvoice`, `vidu`, `sdxl_local`, `nim`, `qwen_cloud`, `teamo`, `grok`,
`pi`, `local`, `default`, `img2threejs`, `json2video_scene`, `wan22_kf2v_maas`,
`happyhorse_1_1_ref`, `happyhorse_1_1_maas_ref`, `cosyvoice`, `qwen3_dashscope`.

These are executable. Nothing can say what they can do, where they run, or whether
they are healthy. That is the mirror image of the capability problem, and it is why
"ProviderRegistry is the canonical authority" is not a sufficient answer on its own:
a callable is not a fact.

Conversely, **5 providers exist only as documentation** — `joyai`, `mpt`, `pexels`,
`pocket_tts`, `voxcpm` appear in `PROVIDER_SPECS` with no registry entry and no
catalogue entry. `mpt` in particular has a live service directory (`services/mpt/`)
and untracked provider code, so this is a real drift, not a placeholder.

---

## 3. Capability: 9 of 14 providers contradict themselves

For every provider declared in **both** `PROVIDER_CATALOGUE` and `PROVIDER_LIMITS`,
compare `catalogue.capabilities` against `limits.modes`:

| Provider | catalogue.capabilities | limits.modes | |
|----------|------------------------|--------------|---|
| h3_local | `t2v` | `i2v, t2v` | divergent |
| hailuo | `i2v, t2v` | `t2v` | divergent |
| happyhorse_1_1 | `i2v, t2v` | `t2v` | divergent |
| happyhorse_1_1_maas | `i2v, t2v` | `t2v` | divergent |
| kling_v2 | `i2v, t2v` | `t2v` | divergent |
| manim | `t2v` | `code_scene` | divergent |
| veo3 | `i2v, t2v` | `t2v` | divergent |
| wan_2_7 | `i2v, t2v` | `t2v` | divergent |
| wan_2_7_maas | `i2v, t2v` | `t2v` | divergent |

5 agree. **9 disagree.**

### Which source is wrong

`PROVIDER_LIMITS`, checked against the actual callables:

```
happyhorse_1_1_generate             reference-image params: NONE
wan_2_7_generate                   reference-image params: NONE
veo3_generate                      reference-image params: NONE
kling_v2_generate                  reference-image params: NONE
hailuo_generate                    reference-image params: NONE
happyhorse_1_1_reference_to_video  reference-image params: ['reference_images']
```

Image-to-video for these families is a **separate registered provider id**
(`happyhorse_1_1_ref`, `wan22_kf2v_maas` under `image_to_video`), registered precisely
because "any video_provider value" could not serve it — see `registry.py`, the
2026-07-13 note. The t2v entry point takes no reference image.

**So `PROVIDER_LIMITS` is right and `PROVIDER_CATALOGUE` over-claims `i2v` on 7
providers.** The catalogue is wrong in the fail-open direction: it advertises a
capability that cannot execute.

Two more, confirmed against each provider's own `*_CAPABILITY` row:

- `H3_LOCAL_CAPABILITY = ["i2v", "t2v", "native_audio", "zh_prompt"]` — matches
  `PROVIDER_LIMITS`, contradicts the catalogue's bare `t2v`.
- `MANIM_CAPABILITY = ["t2v", "code_scene", "zh_prompt"]` — **neither** source is
  right. Limits says only `code_scene`; the catalogue says only `t2v`. The truth is
  the union.

### Why this is not academic

`validate_request` (`capability_guard.py:153`) consults obase's registered capability
tags first and falls back to `PROVIDER_LIMITS`. Those tags are **empty for 13 of 14
providers** — only `happyhorse_1_1_maas_lock` has one. So `PROVIDER_LIMITS` is already
the de facto production capability authority, and `PROVIDER_CATALOGUE.capabilities` is
**dead data in the capability path**. It is wrong, and nothing reads it.

---

## 4. Availability: the catalogue states a fact and ignores it

`PROVIDER_CATALOGUE.get("happyhorse_1_1_maas_lock").capability_state` is
`NOT_ADOPTED` — notes: *"locked MaaS variant, not for general routing"*.

That provider is nonetheless **registered**, has a **runtime spec**, is in
**PROVIDER_LIMITS**, and scores **9** in `PROVIDER_QUALITY`. Worse, `registry.py`
calls it the mainline path: *"主线管线(create_episode/Series/orchestrate_longvideo)专用"*.

`policy.py:112` records `decision.capability_states` from the catalogue and then
**never reads it**. `NOT_ADOPTED` is therefore documentation with no effect — the
declared availability signal is both wrong and inert.

Locality, by contrast, agrees between the catalogue and `RUNTIME_SPECS` for all 15
shared providers: every `LOCAL` row has a `local_process`/`cli` health check.

---

## 5. A fourth defect: the policy capability gate can never pass

`policy.py:134` evaluates required capabilities as:

```python
reasons.extend(
    f"capability_missing:{capability}"
    for capability in sorted(policy.required_capabilities)
    if not bool(getattr(limits, capability, False))
)
```

`ProviderLimits` has **no boolean field named after a mode**. Its modes live in
`limits.modes`, a frozenset. So:

```
getattr(limits, "t2v", False)   -> False   (attribute missing)
getattr(limits, "i2v", False)   -> False   (attribute missing)
getattr(limits, "native_audio", False) -> True/False   (the only ones that work)
```

**Any request requiring `t2v` or `i2v` rejects every provider, without exception.**
This is observable in the P0-4.1 run as
`no provider satisfies policy: wan_local (capability_missing:t2v, …)`.

The policy conflates *mode* with *capability*. `policy.mode` is already checked
against `limits.modes` four lines earlier, so the second check is redundant as written
and wrong.

---

## 6. Canonical authority

`ProviderProfile` in `providers/facts.py` becomes the single provider authority. It
already declares itself *"the single provider fact source"* and is the only source
with a complete identity schema. Absorbing the limits does not add a new concept; it
removes a duplicate of one that already exists.

What each other source becomes:

| Source | Disposition |
|--------|-------------|
| `PROVIDER_LIMITS` | **migrate, then delete.** Its modes and limits fold into `ProviderProfile`. `ProviderLimits` survives only as a read-only projection so existing call sites keep working. If a field has no home in the schema, the schema gains the field before the table is deleted — no fact is dropped. |
| per-provider `*_CAPABILITY` | **migrate, then delete.** These are the evidence for the limits and must stop being a third copy. |
| `RUNTIME_SPECS` | **keep, but scope it.** Probeability is genuinely a different dimension — it describes *this moment's* liveness, not declared capability. It stays a separate registry and must never answer a capability question. |
| `PROVIDER_QUALITY` | **keep, but declare it a judgement.** Human-assigned scores are not facts. It may gate selection; it may not masquerade as capability or availability. |
| `PROVIDER_SPECS` | **keep as docs.** Setup instructions are not runtime facts. Its 5 undocumented-but-drifting entries get catalogue rows. |
| `ProviderRegistry` | **keep as the binding layer.** It is authoritative for *executability* only. It is not a fact source and must not grow facts. A provider in the registry with no `ProviderProfile` is a cataloguing debt, tracked explicitly. |
| `ProductionAdapterRegistry` | **out of scope.** Different key space entirely. |

Target shape:

```
ProviderRegistry          executability  ─┐
  (binding layer)                          │
                                          ├─→ ProviderProfile   identity + capability + limits
PROVIDER_LIMITS           capability      │
  *_CAPABILITY rows       evidence       ─┘
                                          │
                                          ├─→ ProviderPolicy    capability evaluation
                                          └─→ RUNTIME_SPECS     liveness probe
```

Not:

```
ProviderRegistry ─┐
                  ├→ two sets of facts
PROVIDER_LIMITS ──┘
```

### Gate status

`PROVIDER_REGISTRY_SINGLE_SOURCE` remains **BLOCKED** at the end of P0-4.2.0, with the
work now precisely enumerated:

1. migrate `PROVIDER_LIMITS` → `ProviderProfile`; delete the table (keep a projection)
2. migrate `*_CAPABILITY` rows → `ProviderProfile`; delete them
3. fix the `policy.py` capability gate (modes vs boolean attributes)
4. make `capability_states` either enforced or removed — and fix `happyhorse_1_1_maas_lock`
5. catalogue the 20 registry-only providers
6. catalogue the 5 spec-only providers
7. make `PROVIDER_REGISTRY_SINGLE_SOURCE` a test, not a claim

Items 3 and 4 are authority defects, not migrations. They are fixed first, per the
rule that authority is repaired before bypasses are discussed.