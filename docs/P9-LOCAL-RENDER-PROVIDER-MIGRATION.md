# P9.1.c/d — Local Render Provider Promotion

**Remotion: QUALIFIED. HyperMotion: NOT_FOUND.** R1 and R3 closed; R2 partially closed.

## What changed

| | before | after |
|---|---|---|
| identity | none — invisible to `ProviderPolicy` | `ProviderProfile("remotion")`, catalogue entry 18 |
| execution | `hevi/renderers/remotion.py` called `npx` directly | `hevi/providers/remotion/driver.py`, the single invocation site |
| artifact proof | renderer called ffprobe + sha256 on its own output | P8.3 `ProductionReceipt` + P8.4 `ArtifactValidation` |
| selection | framework hardcoded `{"remotion","hyperframes","manim"}` and `["h3_local"]` | validated against `ProviderCatalogue` |

### R1 — renderer no longer owns artifact truth

`_hash_file()` and `_probe_duration()` were **deleted** from
`hevi/renderers/remotion.py`. AST-verified: `ffprobe` not called, no `hashlib`,
`duration_s` and `content_hash` left at declared defaults.

### R3 — qualification no longer names providers

`hevi/qualification/framework.py` hardcoded a provider set and a literal `h3_local`.
Now: a `render_runtime` is validated against the catalogue, and an **undeclared** one
becomes a reported `BLOCKED_UNDECLARED_PROVIDER` line rather than a silent selection.

### R2 — partially closed

`remotion` and `hyperframes` now have identities. **`ffmpeg` and `html_gsap` do not** —
they are real renderers in `hevi/renderers/` still invisible to provider policy, and
recipes naming them now report a blocker instead of qualifying silently.

## Real qualification

```
6 compositions discovered
MotionGraphics rendered via npx -> 176663 bytes, isom, 4.05s
sha256 1937d5e7ca2988e52b1c530d
links proven: observation, acquisition, execution, artifact
verdict: QUALIFIED
```

## Two unplanned findings

**`hyperframes` was a real renderer with no catalogue identity.** The R3 fix surfaced it:
`framework.py` named it as a render runtime, but `ProviderCatalogue.get("hyperframes")`
was `None`. Registered — with an explicit note that it is **declared, not qualified**.
Its module exists; its rendering has not been exercised.

**The P7.3 contract freeze caught the fleet growth.** `assert stats()["providers"] == 16`
and the doc-completeness test both failed on adding two providers — exactly as designed.
Growing the fleet is a contract change. Docs and constants were updated deliberately,
not silently.

## HyperMotion

`NOT_FOUND`. Zero occurrences in the repo; not on PyPI. **Not registered** — a
placeholder provider would be a declared capability that can never be verified, which
is the exact failure P8 closed.

## Not completed

Stated plainly rather than implied:

- **No dedicated mutation test file** for M1–M5. M1 was verified directly (policy.py
  diff unchanged: 45 insertions, all pre-existing P7.2); M2–M4 are covered by the
  existing P9.1.a/1.b guards; **M5 (a renderer gaining ffprobe fails the test) is not
  locked by an automated test** — it is currently verified by the AST check above.
- **No separate `P9-REMOTION-QUALIFICATION.md` / `P9-HYPERMOTION-QUALIFICATION.md`.**
  Consolidated here instead.
- **`hyperframes` and `ffmpeg` remain unqualified**; `ffmpeg`/`html_gsap` remain
  identity-less.
- The manim/P9.1.b scene render is unaffected and still passes.
