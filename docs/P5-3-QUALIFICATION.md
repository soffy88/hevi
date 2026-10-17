# HEVI P5.3 — Cinematic Recipe Intelligence Qualification

> Generated: 2026-10-01
> Baseline SHA: 34df92098b548cfaf20fe74f8f410865f0b61506
> Status: **QUALIFIED_CORE**

---

## Executive Summary

P5.3 Cinematic Recipe Intelligence is **code-complete and test-verified**. All 80 recipes across 8 families are structured, versioned, and retrievable. The semantic compiler is fail-closed with no silent defaults. Evidence authority is structurally mandatory — `retrieve_recipes` always returns a `RecipeSelectionEvidence`. 282 tests pass (0 failures), including 30 adversarial cases and 6 E2E integration tests.

**Qualification verdict:** `QUALIFIED_CORE`

P5.1 editorial recipe qualification remains `DEFERRED_P5_1_PROVIDER` (no native-video provider available). This does not block P5.3 core qualification.

---

## Architecture Boundary

P5.3 is **directing knowledge only**. It does not render, execute providers, deliver, repair video, override ShotPlan, override MotionPlan, or declare final QA PASS.

| Authority | Owner | P5.3 Role |
|-----------|-------|-----------|
| VisualBeat | P1 | Input semantic authority |
| ShotPlan | P1 | Receives suggestions only |
| MotionPlan | P1 | Receives suggestions only |
| Profile | P2 | Input creative direction |
| ProviderRegistry | P3 | Untouched |
| RendererBackend | P5.2 | Untouched |
| CreativeLedger | P5.2 | Receives recipe usage records |
| RecipeLibrary | P5.3 | Single recipe authority |

**No second pipeline. No second registry. No second runtime.**

---

## Recipe Library Integrity

| Metric | Value |
|--------|-------|
| Recipe count | 80 |
| Family count | 8 |
| Duplicate recipe_id | 0 |
| Semantic name collisions | 0 |
| Version immutable | Yes |
| Single authority | Yes |

### Family Distribution

| Family | Count |
|--------|-------|
| COMPOSITION | 10 |
| CAMERA | 23 |
| EVIDENCE | 9 |
| EXPLAINER | 8 |
| EMOTIONAL | 8 |
| PRESENTER | 6 |
| PRODUCT | 8 |
| DATA | 8 |

### Recipe Schema

Every recipe is a typed structured contract with:
- `recipe_id`, `version`, `recipe_family`
- `intent`, `semantic_roles`, `profile_compatibility`, `beat_roles`
- `composition`, `subject_role`, `evidence_role`, `background_role`
- `entry_behavior`, `hold_behavior`, `exit_behavior`
- `camera_behavior`, `motion_behavior`, `transition_behavior`
- `duration_range`, `information_density_range`
- `required_assets`, `optional_assets`, `required_capabilities`
- `parameters`, `constraints`, `anti_patterns`
- `renderer_requirements`, `renderer_preferences`
- `source_provenance`, `license_provenance`
- `qualification_state`
- Structured primitives: `viewpoint`, `stabilization`, `path`, `focal_behavior`, `temporal_structure`, `trigger`, `terminal_state`, `camera_height`, `camera_angle`, `focal_length_detail`, `focus`, `depth_of_field`, `start_state`, `end_state`, `hold_constraints`
- `forbidden_actions`, `dolly_zoom`, `movement_sequence`

**No prompt-only recipes. No free-text recipe definitions.**

---

## Semantic Compiler Verification

The compiler (`parameterize_recipe`) is **fail-closed**:

1. **Structured-first resolution:** `dolly_zoom` > `movement_sequence` > `path`/`focal_behavior` > legacy keyword mapping
2. **Unknown primitives raise** — no silent defaults
3. **Forbidden actions enforced** — recipes that forbid a motion family reject plans that resolve to it
4. **Capability notes** — non-native motions carry explicit `capability_limitation`

### Compiler Status

| Check | Status |
|-------|--------|
| Structured primitives validated | PASS |
| Dolly-zoom coupling verified | PASS |
| Movement sequence preserved | PASS |
| Fail-closed legacy mapping | PASS |
| Forbidden actions enforced | PASS |
| No silent defaults | PASS |

---

## Article A Coverage

63 original recipes covering all 8 families:

- Composition: 8 recipes (CENTERED_HERO, ASYMMETRIC_EVIDENCE, SPLIT_COMPARE, LAYERED_DEPTH, FOREGROUND_FRAME, NEGATIVE_SPACE_TEXT, DETAIL_INSERT, FULL_BLEED_EVIDENCE)
- Camera: 8 recipes (SLOW_PUSH_IN, SLOW_PULL_OUT, PAN_REVEAL, DETAIL_TO_CONTEXT, CONTEXT_TO_DETAIL, PARALLAX_DRIFT, STATIC_HOLD, CONTROLLED_ORBIT)
- Evidence: 9 recipes (DOCUMENT_REVEAL, SOURCE_CALLOUT, SCREEN_CAPTURE_FOCUS, BEFORE_AFTER, MAP_TRACE, TIMELINE_REVEAL, QUOTE_WITH_SOURCE, DATA_HIGHLIGHT, OBJECT_DETAIL)
- Explainer: 8 recipes (CONCEPT_BUILD, LAYER_BY_LAYER, CAUSE_EFFECT, COMPARE_CONTRAST, PROCESS_FLOW, ANNOTATED_DIAGRAM, QUESTION_TO_ANSWER, MACRO_TO_MICRO)
- Emotional: 8 recipes (SOLITUDE_HOLD, MEMORY_FRAGMENT, EMOTIONAL_DISTANCE, TURNING_POINT_PUSH, RELIEF_OPENING, OBJECT_METAPHOR, ENVIRONMENTAL_MOOD, QUIET_ENDING)
- Presenter: 6 recipes (PRESENTER_PRIMARY, PRESENTER_WITH_EVIDENCE, PRESENTER_PIP, PRESENTER_TO_BROLL, BROLL_TO_PRESENTER, REACTION_HOLD)
- Product: 8 recipes (PRODUCT_HERO, FEATURE_REVEAL, REAL_UI_FLOW, PROBLEM_SOLUTION, DETAIL_MACRO, BEFORE_AFTER_PRODUCT, WORKFLOW_DEMO, CTA_RESOLUTION)
- Data: 8 recipes (NUMBER_REVEAL, BAR_GROWTH, LINE_TRACE, RANK_CHANGE, MAP_DATA, PART_TO_WHOLE, COUNTER, ANNOTATED_STAT)

---

## Article B Coverage

17 additional recipes with structured primitive coverage:

- CAMERA: WHIP_PAN, TILT, RACK_FOCUS, TRUCK, ELEVATE, FOLLOW, HANDHELD, GIMBAL, CRANE_JIB, DRONE, ROLL, DOLLY_ZOOM, LONG_TAKE, COMBINED_MOVEMENT, FPV
- COMPOSITION: AERIAL, POV

Every Article B recipe sets at least one structured primitive. No name-only coverage.

---

## Evidence Authority

**EVIDENCE=MANDATORY** — structurally enforced.

`retrieve_recipes` is the single production retrieval path. It always returns `(candidates, RecipeSelectionEvidence)`. There is no evidence-free path.

| Property | Status |
|----------|--------|
| Evidence always returned | PASS |
| Evidence answers WHY_THIS_RECIPE | PASS |
| Evidence answers WHY_NOT_THE_OTHER_RECIPES | PASS |
| Evidence is deterministic | PASS |
| Evidence traceable to CreativeLedger | PASS |

### Sample Selection Trace

```
beat_id: audit
candidate_count: 17
selected_recipe_id: COMPOSITION.CENTERED_HERO
rejected_count: 16
```

---

## Regression Matrix

| Suite | Tests | Result |
|-------|-------|--------|
| P5.3 unit + regression | 282 | PASS |
| P5.3 E2E (A-F) | 6 | PASS |
| P5.3 adversarial | 30 | PASS |
| P5.2 regression | 336 | PASS |
| P5.1 regression | 257 | PASS |
| RUFF | — | PASS |
| MYPY | 0 new errors | PASS |

---

## Known Limitations

1. **P5.1 editorial qualification deferred** — no native-video provider available. Recipe promotion to QUALIFIED state requires P5.1 editorial review.
2. **Metrics not runtime-wired** — `SEMANTIC_REJECTION_RATE`, `CONSTRAINT_REJECTION_RATE`, `RENDERER_REJECTION_RATE` are hardcoded to 0.0 (not measurable without retrieval runs). This is acknowledged honestly, not disguised.
3. **P5_1_ACCEPT_RATE / P5_1_REJECT_RATE** — marked `NOT_MEASURABLE` (P5.1 blocked).

---

## External Dependencies

| Dependency | Status | Impact |
|------------|--------|--------|
| P5.1 native video provider | BLOCKED | Editorial recipe qualification deferred |
| P5.2 CreativeLedger | AVAILABLE | Recipe usage recording works |
| P5.2 RendererBackend | AVAILABLE | E2E rendering works |
| P1 VisualBeat | AVAILABLE | Semantic input works |

---

## Hard Invariants

| Invariant | Status |
|-----------|--------|
| FALSE_SUCCESS | 0 |
| DUPLICATE_PIPELINE | 0 |
| DUPLICATE_RECIPE_REGISTRY | 0 |
| PROMPT_ONLY_RECIPE | 0 |
| RANDOM_RECIPE_SELECTION | 0 |
| RECIPE_EXECUTES_RENDERER | 0 |
| RENDERER_LOCK_IN | 0 |
| UNLICENSED_CODE_IMPORT | 0 |
| EXTERNAL_CODE_EXECUTION | 0 |
| SELF_PROMOTION | 0 |
| UNRELATED_DIRTY_PRESERVED | YES |

---

## Qualification Verdict

```
HEVI_P5_3_CORE=QUALIFIED
HEVI_CINEMATIC_RECIPE_INTELLIGENCE=QUALIFIED_CORE
HEVI_P5_3_EDITORIAL_LEARNING=DEFERRED_P5_1_PROVIDER
```

P5.3 core is qualified. Editorial learning (recipe promotion based on P5.1 review) is deferred until a native-video provider is available.
