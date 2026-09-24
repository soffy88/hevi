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
- **Benchmark gate note (historical, superseded 2026-09-24):** with `<2`
  `benchmark_providers` a benchmark finishes
  `blocked/SECOND_REAL_PROVIDER_UNAVAILABLE`. With `>=2` providers it used
  to end at `CHILD_REPRODUCTIONS_NOT_SUBMITTED` because no composition-layer
  child submission existed (row `fc0b79ee-…` still records that state).
  Pattern promotion still requires `total>=5` and `provider_count>=2` on
  `video_pattern_evidence` — not fabricated for this closure.
  **As of 2026-09-24** the composition layer is wired and a real two-provider
  benchmark succeeds end-to-end; see the status-correction section below.

## Final acceptance report (2026-09-24)

Recorded in `artifacts/qualification/final-acceptance-report.json`.

| gate | value |
|---|---|
| `RUFF` | `PASS` (`ruff check hevi tests`: 0 violations) |
| `MYPY` | `BASELINE` (`mypy --strict hevi`: 13 pre-existing errors in 11 files, unchanged from `7f4ce6d`) |
| `PYTEST` | `PASS` (3343 passed, 30 skipped, 0 failed, 0 errors, 374.02s) |
| `WORKTREE_CLEAN` | `YES` (hevi-remotion test residue restored; no residual tracked changes) |
| `UNRELATED_DIRTY_PRESERVED` | `YES` (`.veya-project/` untracked and untouched) |

### PREEXISTING_STUDIO_FAILURE_MATRIX

| file | baseline count | resolution |
|---|---:|---|
| `tests/test_studio_api.py` | 1 | ENVIRONMENT → PASS after Track 2 |
| `tests/test_studio_combine.py` | 3 | 1 ENVIRONMENT + 2 fixed Track 1 (`20150b9`) |
| `tests/test_studio_daily.py` | 1 | ENVIRONMENT → PASS after Track 2 |
| `tests/test_studio_slate.py` | 3 | 2 ENVIRONMENT + 1 fixed Track 1 (`20150b9`) |
| `tests/test_studio_veya.py` | 2 | ENVIRONMENT → PASS after Track 2 |
| **total** | **10** | **0 open** (4 Track 1 fixes + 6 reclassified env then green) |

### ENV_FAILURE_MATRIX

| bucket | count | resolution |
|---|---:|---|
| setup errors (director/pipeline/providers) | 84 | closed by `torchvision==0.27.0` (`95fd9ee`) |
| provider registration/auth/prompt failures | 8 | same root cause; closed by Track 2 |
| **total baseline** | **92** | **0 open** |

`environment-doctor.json`: software_gate PASS; `ENV_BLOCKED=[cuda]` (hardware).

### Track closure summary

Tracks 1–4 closed (`d897d9c`/`20150b9`, `95fd9ee`, `f5ee649`, `1c59daa`).
Remaining non-pass states are classified ENV_BLOCKED / OWNER_BLOCKED /
missing composition-layer gaps — not `SECOND_PROVIDER_UNQUALIFIED`,
`HYPERFRAMES_CLI_UNAVAILABLE`, `92_ENVIRONMENT_FAILURES`, or
`10_PREEXISTING_STUDIO_FAILURES`.

## Status correction (2026-09-24): composition layer + cross-model runtime

Two claims must not be conflated:

| claim | status | evidence |
|---|---|---|
| `SECOND_INDEPENDENT_PROVIDER=QUALIFIED` | **QUALIFIED** (Track 4, independent of composition layer) | `distinct_succeeded_repro_providers=2`; `second-provider-audit.json` `cross_model_qualified=true` |
| `CROSS_MODEL_BENCHMARK_RUNTIME=QUALIFIED` | **QUALIFIED** (closed 2026-09-24) | `artifacts/qualification/cross-model-benchmark-runtime.json` |

Historical note: before this correction, a `>=2` provider benchmark ended at
`CHILD_REPRODUCTIONS_NOT_SUBMITTED` because no composition layer submitted
child reproductions. That gate is now wired:

- `execute_case_benchmark_task` freezes a plan using the same
  `BENCHMARK_DIMENSIONS` as the API endpoint so `plan_hash` matches, then
  delegates to `run_benchmark_composition` (`hevi/video_intelligence/benchmark_composition.py`).
- Children are created with idempotency key
  `benchmark:{benchmark_id}:{provider}:{plan_revision}` and task key
  `case-benchmark-child:…`, claimed via `TaskRepository.claim_task`, run
  nested under `worker_id=benchmark-composition`, and fan-in waits for all
  children in `{succeeded,failed,blocked}` before aggregating.
- Aggregation persists `BenchmarkEntry` rows (one per terminal succeeded
  child with a verdict) and pattern evidence classified from real
  `verdict.passed` (`positive` / `negative` / `counter_example`). Winner is
  never emitted. Pattern gate remains `total>=5 AND provider_count>=2`;
  `AUTO_PATTERN_PROMOTION` stays `0` (pattern `01f5172b-…` remains
  `lifecycle_status=candidate`, `PROMOTED_PATTERNS=0`).

Real E2E (`scripts/qualification/run_cross_model_benchmark.py`):

| field | value |
|---|---|
| `benchmark_id` | `5c17d91d-c4aa-4b6a-bd45-c8399ae4c5b9` |
| `task_id` | `54c3243c-e804-4f66-851e-8f25b6a04d78` `completed` |
| children | hyperframes `f2a7202d-…` `succeeded` + manim `ce41bd3b-…` `succeeded` |
| `entry_count` | 2 |
| `pattern_evidence_count` | 2 (`positive`×2) |
| `failure_code` | `null` |
| `cross_model_runtime_qualified` | `true` |

Regression after composition close: `RUFF=PASS`, `MYPY=BASELINE (13
pre-existing)`, `PYTEST=3365 passed / 30 skipped / 0 failed`.
Unit coverage: 7 files under `tests/video_intelligence/test_benchmark_*.py`
(submission, idempotency, partial completion, restart recovery, fan-in,
entry persistence, pattern evidence).

## Status vocabulary

`CODE_COMPLETE` means source and tests exist; `RUNTIME_CONNECTED` means the
canonical durable path is wired; `RUNTIME_QUALIFIED` requires real evidence;
`PRODUCTION_QUALIFIED` requires the production acceptance gates; `ENV_BLOCKED`
and `OWNER_BLOCKED` are explicit non-pass states. Cross-model qualification
requires at least two independent real providers.

Current result: production learning E2E is real and auditable; Tracks 1–4
closed their software blockers; cross-model benchmark runtime is now
qualified with a real two-provider entry-persisting run. Remaining non-pass
states are hardware/credential ENV_BLOCKED and OWNER_BLOCKED classifications
above — not `SECOND_PROVIDER_UNQUALIFIED` or
`CROSS_MODEL_BENCHMARK_RUNTIME_UNQUALIFIED`.
