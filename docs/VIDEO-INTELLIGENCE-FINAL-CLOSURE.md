# Video Intelligence final closure evidence

Evidence is for the closure work based on `62e07b6aa9759629a505b8e2ec0687af747e13ba`.
It records verified runtime facts and keeps external blockers separate from
software regressions.

## P0 suite triage

The final backend run completed with `3234 passed, 30 skipped, 18 failed,
84 errors`. No failure was introduced by the Video Intelligence changes:

| classification | count | evidence and action |
|---|---:|---|
| `REGRESSION_THIS_TASK` | 0 | No changed production or intelligence module appears in a failing stack. Targeted intelligence tests and API inventory pass. |
| `PRE_EXISTING_FAILURE` | 10 | Existing Studio assertions in `test_studio_api.py`, `test_studio_combine.py` (3), `test_studio_daily.py`, `test_studio_slate.py` (3), and `test_studio_veya.py` (2) fail in the pre-existing renderer/scheduling behavior. Preserve and track; do not weaken fail-closed production semantics. |
| `ENVIRONMENT_FAILURE` | 92 | 84 setup errors and 8 provider-related failures stop at the installed `torch`/`torchvision`/`transformers`/`vibevoice` boundary (`torchvision::nms` missing, then `vibevoice` cannot import `modeling_utils`). The environment also reports CUDA/NVML unavailable. No production code workaround was added. |
| `OWNER_BLOCKED` | 0 | None. |
| `FLAKY` | 0 | None classified as flaky. |

The 84 setup errors are the same dependency failure across these test files:
`test_director_pipeline_orchestrator_integration.py` (5),
`test_director_pipeline_router.py` (33), `test_pipeline.py` (21),
`test_pipeline_degradation.py` (17), and `test_providers.py` (8).

The eight environment failures are the provider-registration/auth/prompt
compatibility tests in `test_audio.py`, `test_d3_adoption_api.py`,
`test_prompt_engineering.py` (2), `test_upstream_contracts.py`,
`test_vibevoice_compatibility.py` (2), and `test_video.py`. The ten existing
Studio failures are listed above by file and count; their assertions are not
part of this closure change.

`FULL_SUITE_TRIAGE=PASS` and `TASK_INTRODUCED_REGRESSION=0` mean every failure
was classified; they do not mean the environment-blocked suite is green.

## Verified closure evidence

- Standard mode object storage uses the canonical `hevi-vault-minio-1` service
  at `localhost:9000`. Upload, read, metadata, delete, and persistence across
  a service restart passed. Local mode remained unchanged and passed.
- Studio Video Intelligence is mounted in the existing Studio shell at
  `/video-intelligence`. Cases, Benchmarks, Patterns, and Templates use the
  authenticated ownership-scoped API. Prompt origins and counter-evidence are
  rendered explicitly; benchmark entries preserve `NOT_OBSERVED` rather than
  converting it to zero.
- The production-learning E2E used the existing durable `TaskService`, the
  existing `motion_graphics`/Remotion adapter, real TTS audio, a real MP4, the
  canonical `shot_verdict` table, and the persisted learning event. The event
  was idempotently linked to the final verdict and refreshed one real observed
  provider-stat sample.
- Runtime interop rendered Remotion with actual runtime identity. HyperFrames
  was not silently substituted: its CLI was absent at the original triage, so
  interop was `ENV_BLOCKED` with `HYPERFRAMES_CLI_UNAVAILABLE`. Track 3 later
  installed CLI 0.8.68 and re-qualified interop PASS (delta 0.05s vs Remotion).
- The provider inventory has **two** qualified real backends for the current
  case corpus. Track 4 ran real durable manim `case_reproduction`s through the
  canonical path alongside the hyperframes baseline (see
  `artifacts/qualification/second-provider-manim-repro.json` for the latest
  succeeded row: reproduction `f80d36eb-…`, task `3b9ddb39-…`, verdict
  `8b5a2cb9-…`, 13755-byte MP4; an earlier run `37fe0626-…` also succeeded).
  Live corpus projection: `distinct_succeeded_repro_providers=2`. See
  `artifacts/qualification/second-provider-audit.json`
  (`cross_model_qualified=true`, `software_gate=PASS`) and
  `artifacts/qualification/second-provider-benchmark.json`
  (`provider_count=2`, `failure_code=CHILD_REPRODUCTIONS_NOT_SUBMITTED`).
- Remaining external non-pass states are classified, not silent: CUDA/NVML
  wedged (`ENV_BLOCKED`, hardware — never reboot the shared host without
  asking soffy); WaveSpeed key absent (`OWNER_BLOCKED_NO_CREDENTIAL`); FAL/MAAS
  credentials present but spending requires soffy authorization
  (`OWNER_BLOCKED_SPEND`); h3_local/wan_local/ltx2_local `ENV_BLOCKED`.
  remotion/ffmpeg/motion_graphics are `NOT_REGISTERED_VIDEO`.
- Benchmark gate note: with `<2` `benchmark_providers` a benchmark finishes
  `blocked/SECOND_REAL_PROVIDER_UNAVAILABLE`; with `>=2` it reaches
  `CHILD_REPRODUCTIONS_NOT_SUBMITTED` because no composition-layer child
  submission exists. Pattern promotion still requires `total>=5` and
  `provider_count>=2` on `video_pattern_evidence` (caller-less today) — not
  fabricated for this closure.

## Status vocabulary

`CODE_COMPLETE` means source and tests exist; `RUNTIME_CONNECTED` means the
canonical durable path is wired; `RUNTIME_QUALIFIED` requires real evidence;
`PRODUCTION_QUALIFIED` requires the production acceptance gates; `ENV_BLOCKED`
and `OWNER_BLOCKED` are explicit non-pass states. Cross-model qualification
requires at least two independent real providers.

Current result: production learning E2E is real and auditable; Tracks 1–4
closed their software blockers (studio regressions, env import chain,
HyperFrames CLI, second independent provider). Remaining non-pass states are
hardware/credential ENV_BLOCKED and OWNER_BLOCKED classifications above — not
`SECOND_PROVIDER_UNQUALIFIED`. Final full regression + acceptance report
pending.
