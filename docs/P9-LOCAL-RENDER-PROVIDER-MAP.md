# P9.1.d — Local Render Provider Map

| Provider | Kind | Runtime | State |
|---|---|---|---|
| manim | video | local_process | **qualified** |
| remotion | video | local_process | **qualified** |
| hyperframes | video | local_process | **qualified** — via its ffmpeg fallback; the CLI render path hangs (P9.1.e) |
| html_gsap | renderer | local_process | **qualified** |
| ffmpeg | encoder | cli | **qualified** |

## Architecture

```
ProviderCatalogue ──▶ ProviderDecision ──▶ adapter.execute() ──▶ ExecutionResult
   identity/facts          eligibility        (a locator)         no measurement
                                                                    │
                          framework.qualify() ◀──────────────────────┘
                                   │
                    AcquiredSource + AcquisitionEvidence   (P8.2)
                    ProductionReceipt                      (P8.3)
                    ArtifactValidation                     (P8.4)
                                   │
                                verdict
```

`ExecutionResult` has **no** `checksum`, `duration_s`, `codec` or `passed` field. An
adapter has no field in which to return a verdict, so `return "QUALIFIED"` is
inexpressible rather than merely discouraged.

## Real qualifications

Every artifact produced by the provider under test — no fixtures:

| provider | artifact | receipt issued | P8.4 |
|---|---|---|---|
| manim | manim-scene mp4 | yes | passed |
| remotion | `MotionGraphics` mp4, 176663 B | yes | passed |
| html_gsap | Playwright chromium capture → libx264, 11770 B | yes | passed |
| ffmpeg | manim mp4 → h264 transcode, 20752 B | yes | passed |
| hyperframes | ffmpeg fallback, 1920x1080 h264, 20321 B | yes | passed |

## hyperframes — qualified through its fallback, not through its CLI

The binary exists and reports `0.8.111`, but **`hyperframes render` does not terminate**
— observed past both 90s and 600s. The provider catches that and falls back to an ffmpeg
path, which does produce a real 1920x1080 h264 MP4.

So hyperframes is QUALIFIED, and the qualification record says so honestly:
`runtime_metadata["render_path"] = "ffmpeg_fallback"`. Full detail in
`docs/P9-HYPERFRAMES-AUDIT.md`. **The CLI hang is reported, not fixed** — it is upstream
of P9's scope, and every render costs the declared budget before the fallback runs.

## Runtime classes, declared not guessed

* `manim`, `remotion`, `hyperframes` — a Python or node process driven as a subprocess.
* `html_gsap` — **LOCAL_PROCESS**, not CLI. There is no renderer binary; Playwright is
  driven in-process and ffmpeg is invoked with an argv. Calling it CLI would be exactly
  the name-based classification the P9 audit forbade.
* `ffmpeg` — **CLI**. A binary on PATH, invoked with argv, transforming an existing
  artifact. It has no path from a prompt to video, and its profile records
  `text_to_video` and `image_generation` in `artifact_contract.excluded_capabilities`.

## Mutation suite

`tests/test_p9_1d_mutations.py` — 36 tests.

| | mutation | result |
|---|---|---|
| M1 | provider renamed; policy unchanged | caught |
| M2 | renderer regains `hashlib` | caught |
| M3 | adapter spawns `ffprobe` | caught |
| M4 | adapter returns `"QUALIFIED"` | caught |
| M5 | renderer without a catalogue entry | caught |

M3 is asserted by **AST argv inspection**, not a text scan — ffprobe is never a called
name, it is a string argument to `subprocess.run`, and a token ban would pass it. That is
the eighth recorded instance of Architecture Testing Rule #1.

## Regression

```
P9.1.d 101 · P9.1.b 15 · P9.1.a 21 · P9.0 71 · P8 181 · P7 247 · P6 1280 · P0-E 476
Ruff PASS · Mypy 0 errors (68 files)
```

`hevi/provider_policy/policy.py` and `hevi/sourcing/` untouched; P8 acquisition models
untouched.
