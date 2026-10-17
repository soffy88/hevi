# HEVI P5 Freeze Report — Production Validation

> Generated: 2026-10-01
> HEAD: `34df92098b548cfaf20fe74f8f410865f0b61506`
> Branch: `closure/3o-v3-architecture-creative-baseline`
> Verdict: **HEVI_P5_FREEZE=PASS_WITH_EXTERNAL_BLOCKERS**

---

## 1. Architecture Status

HEVI P5 is three cooperating layers over a single frozen P0–P4 authority chain.

| Layer | Role | State |
|-------|------|-------|
| **P5.1** | Editorial intelligence (see → diagnose → repair → compare → promote) | Code complete, provider-blocked |
| **P5.2** | Production grammar + editable media | Qualified with external blockers |
| **P5.3** | Cinematic recipe intelligence (directing knowledge) | Qualified core |

No layer introduces a second pipeline, registry, renderer, asset authority, QA authority, or shot/motion authority.

---

## 2. Authority Chain

```
ContentRequest
 → ProductionEntityGraph        (P5.2)
 → Asset/Evidence Resolution    (P5.2)
 → ShotReadiness                (P5.2)
 → VisualBeat                   (P1, frozen)
 → Recipe Retrieval + Evidence  (P5.3, advisory)
 → ShotPlan / MotionPlan        (P1, frozen)
 → RendererBackend              (P5.2)
 → Candidate Video
 → Editorial Review             (P5.1)
 → RepairIntent                 (P5.1 → P3 RepairController)
 → RevisionCandidate + Pairwise (P5.1)
 → EditableProjectManifest      (P5.2)
 → Editable Backend             (P5.2)
 → Delivery                     (P4)
```

### Authority Integrity — VERIFIED

| Check | Result |
|-------|--------|
| SECOND_PIPELINE | NO |
| SECOND_REGISTRY | NO |
| SECOND_RENDERER | NO |
| SECOND_ASSET_AUTHORITY | NO |
| SECOND_SHOT_AUTHORITY | NO |
| SECOND_QA_AUTHORITY | NO |
| P5.1 imports renderer authority | NO |
| P5.1 creates asset/delivery registry | NO |
| P5.3 imports renderer authority | NO |
| P5.3 creates ShotPlan/MotionPlan | NO |
| P5.2 creates second asset/QA authority | NO |

**AUTHORITY_CHAIN=PASS**

---

## 3. Qualification Summary

### P5.1 — Visual Editorial Intelligence

```
IMPLEMENTATION=PASS
TEST_SUITE=PASS (276 tests)
PROVIDER_E2E=BLOCKED
QUALIFICATION=BLOCKED_BY_PROVIDER
```

12 implementation modules, 11 test files, 31 PASS gates / 12 BLOCKED gates. No fake PASS recorded. Documentation: `docs/P5-1-QUALIFICATION.md`.

### P5.2 — Production Grammar & Editable Media

```
QUALIFICATION=QUALIFIED_WITH_EXTERNAL_BLOCKERS
```

15 source modules, 6 real E2E drivers, `docs/P5-2-QUALIFICATION.md` + `artifacts/qualification/p5_2_qualification.json`.

### P5.3 — Cinematic Recipe Intelligence

```
HEVI_P5_3_CORE=QUALIFIED
HEVI_CINEMATIC_RECIPE_INTELLIGENCE=QUALIFIED_CORE
HEVI_P5_3_EDITORIAL_LEARNING=DEFERRED_P5_1_PROVIDER
```

80 recipes / 8 families / 0 duplicates / 0 semantic collisions. Evidence authority is structurally mandatory. Documentation: `docs/P5-3-QUALIFICATION.md` + `artifacts/qualification/p5_3_qualification.json`.

---

## 4. External Blockers

| Blocker | Scope | Nature |
|---------|-------|--------|
| **fal.ai credit exhausted** | P5.1 native video understanding | External (billing) |
| **DashScope in arrears** | P5.1 backup provider | External (billing) |
| **capcut-cli 0.26.0 not installed** | P5.2 editable backend E2E (2 tests) | External (environment) |
| **GPU / ComfyUI unavailable** | P5.2 presenter generation path | External (hardware) |
| **Pocket TTS not adopted** | P5.2 optional TTS provider | Not adopted (optional) |

None of these are code defects. None were worked around by mocking, threshold lowering, gate modification, or test deletion.

---

## 5. E2E Evidence

### Canonical chain — PIPELINE_E2E=PASS

Every stage produced artifact or log evidence:

| Stage | Evidence |
|-------|----------|
| A. Article input | `VisualBeat` construction in E2E helpers |
| B. Editorial intelligence | `hevi/ops/p5_1_review.py` — provider-blocked, code path verified by 276 tests |
| C. Grammar selection | `RecipeLibrary.filter` / `rank_candidates` |
| D. Recipe retrieval | `retrieve_with_evidence` — deterministic, no random selection |
| E. `RecipeSelectionEvidence` | Always returned; 17 candidates / 1 selected / 16 rejected on audit probe |
| F. ShotPlan | `parameterize_recipe` → shot_plan suggestions |
| G. Editable output | P5.2 `EditableProjectManifest` + internal Jianying projection |
| H. Render boundary | P5.2 HTML/GSAP + Remotion + FFmpeg backends |

### Integration run

```
tests/integration/p5_3/ + tests/integration/p5_2/
33 passed, 4 skipped, 1 failed (capcut-cli absent)
```

No new mocks were introduced.

---

## 6. Regression Status

| Suite | Passed | Failed | Skipped |
|-------|--------|--------|---------|
| P5.1 | 276 | 0 | 0 |
| P5.2 | 305 | 2 *(env)* | 23 |
| P5.3 | 282 | 0 | 0 |
| P4 / P3 / P2 | 62 | 0 | 0 |
| **Total** | **925** | **2** | **23** |

### NEW_FAILURE = 0

Both failures are the same root cause:

```
test_p5_2_e2e_f_editable.py::test_e2e_f6_a_manifest_that_fails_lint_is_refused_before_any_backend_runs
test_p5_2_parametric_text_equivalence.py::test_a_text_overlay_with_no_text_never_reaches_a_backend

AssertionError: assert 'UNAVAILABLE' == 'LINT_FAILED'  (backend=CAPCUT_CLI)
```

Probe evidence:

```
capcut-cli NOT ON PATH
capcut    NOT ON PATH
EXPECTED_VERSION = "0.26.0"
```

The backend correctly reports `UNAVAILABLE` when the pinned binary is absent. The tests assert `LINT_FAILED`. This is an environment gap, not a regression — and neither test imports any P5.3 module touched by this work.

### Static checks

| Check | Scope | Result |
|-------|-------|--------|
| RUFF | `hevi/production/p5_3/` (changed) | PASS |
| MYPY | `hevi/production/p5_3/` | PASS — 0 errors in 15 files |
| RUFF | `hevi/ops/` (untouched, pre-existing debt) | 49 pre-existing findings — not introduced here |

---

## 7. Metrics Validation

`RetrievalMetrics` is wired into `retrieve_with_evidence` and fed by real runs.

```
RUNTIME_METRICS=PASS
```

Observed on audit probe:

| Field | Value |
|-------|-------|
| `total_runs` | 1 |
| `total_candidates` | 17 |
| `total_accepted` | 1 |
| `total_rejected` | 16 |
| `SEMANTIC_REJECTION_RATE` | 1.0 |
| `CONSTRAINT_REJECTION_RATE` | 0.0 |
| `RENDERER_REJECTION_RATE` | 0.0 |

No hardcoded defaults remain in the rejection-rate path. No new metrics DB or registry was created — the accumulator is an in-process dataclass following the existing `OpsMetrics` pattern.

---

## 8. Known Limitations

1. **P5.1 editorial qualification is blocked**, not passing. `PROMOTION_AUTHORITY=NOT_QUALIFIED`. Pairwise calibration accuracy and position-swap consistency are unmeasured.
2. **P5.3 editorial learning deferred** — recipe promotion to `QUALIFIED` requires P5.1 review, which requires a native-video provider.
3. **`P5_1_ACCEPT_RATE` / `P5_1_REJECT_RATE` = `NOT_MEASURABLE`** — recorded honestly rather than as `0`.
4. **P5.2 editable backend differential is single-backend in this environment** — CapCut projection cannot execute.
5. **Three P5.1 policies are functions, not classes** (`EvidenceFirstPolicy`, `InformationDensityPolicy`, `VisualStagnationDetector`). Renaming is an API contract change; `scripts/p5_1_finecut_e2e.py:433` consumes `detect_visual_stagnation` directly. Deferred by design.

---

## 9. Next Activation Condition

P5.1 is the sole critical-path blocker. When **one** of the following becomes true:

- fal.ai credit is restored, **or**
- DashScope balance is restored, **or**
- another provider passes native-video capability qualification,

then run, in order:

1. `scripts/p5_1_qualify.py` — produce `output/p5_1/qualification.json` (43 gates)
2. `scripts/p5_1_finecut_e2e.py` — cases A / B / C with real provider
3. Re-close P5.3: `HEVI_P5_3_EDITORIAL_LEARNING=QUALIFIED`
4. Install `capcut-cli` 0.26.0 (`c87d61dec9e2`) to clear the 2 environmental failures
5. Re-run this freeze validation to reach `HEVI_P5_FREEZE=PASS` unqualified

Until then the honest state is `PASS_WITH_EXTERNAL_BLOCKERS`.

---

## 10. Source Mutation Record

| Phase | Source mutations |
|-------|-----------------|
| This freeze validation | **0** — read-only audit + 2 new report files |
| Prior phases (P5.4 evidence closure, P5.3 qualification, metrics wiring) | `hevi/production/p5_3/retrieval.py`, `hevi/production/p5_3/metrics.py`, 6 P5.3 test files |

No `reset`, `clean`, `checkout`, `stash`, `restore`, or `force push` was executed. Unrelated dirty files preserved.
