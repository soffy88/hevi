# HEVI P6.0 — Authority Boundary

Every authority P6 must **use** rather than re-own, with the P6.0 guard that
proves it.

Line references are from baseline `34df920`.

---

## 1. Reused authorities

| Concern | Canonical owner | P6.0 guard |
|---------|----------------|-----------|
| Creative profile | `hevi/production/p2_types.py:193` `ProductionProfileRegistry`; `p2_profiles.py:334` `get_registry()` | `test_no_second_authority` — P6 defines neither `ProductionProfile` nor `ProductionProfileRegistry` |
| Visual beat | `hevi/production/p1_types.py:63` `VisualBeat` | `test_no_second_timeline` |
| Shot plan | `hevi/production/p0_pipeline.py:143` `ShotPlan` | `test_no_second_shot_authority` |
| Motion plan | `hevi/production/p0_pipeline.py:162` `MotionPlan` | `test_no_second_shot_authority` |
| Timeline lock | `hevi/production/p0_pipeline.py:68` `TimelineLock` | `test_no_second_timeline` |
| Audio lock | `hevi/production/p0_pipeline.py:44` `AudioLock` | `test_no_second_timeline` |
| Renderer | `hevi/renderers/base.py:115` `RendererBackend`; `_RENDERERS` at `:270` | `test_no_second_renderer` |
| Editable backends | `hevi/editable/base.py` | (out of P6.0 scope; P6 declares no backend) |
| Asset candidate | `hevi/production/shot_readiness.py:53` `AssetCandidate` | `test_no_second_asset_authority` |
| Generation gate | `hevi/production/shot_readiness.py:331` `assert_ready_for_generation` | referenced only |
| Evidence asset | `hevi/ops/p5_1_types.py:628` `EvidenceAsset` | `test_no_second_asset_authority` |
| Product evidence | `hevi/production/product_video.py:161` `ProductVideoPlan`; `:103` `ProductSurfaceManifest` | reused in P6.6-P6.8 |
| Cinematic recipe | `hevi/production/p5_3/library.py:41` `RecipeLibrary`; `schema.py:295` `CinematicRecipe` | `test_no_second_authority` |
| Editorial review | `hevi/ops/p5_1_types.py` — `VideoReview`, `EditorialDiagnosis`, `PairwiseComparison`, `RevisionSession` | `test_no_second_authority` |
| Per-shot verdict | `hevi/verdict/scorecard.py:102` `shot_scorecard` | `test_no_second_qa_authority` |
| Final verdict | `hevi/verdict/final_review.py:122` `run_final_review` | `test_no_second_qa_authority` |
| Gate thresholds | `hevi/quality/gate_policy.py:20` `GatePolicy` | `test_no_second_qa_authority` |
| Bounded repair | `hevi/quality/repair_controller.py:76` `RepairController` | `test_no_second_qa_authority` |
| Entity graph | `hevi/production/entities.py:36` `EntityType` | reused in P6.3-P6.4 |
| Narrative models | `hevi/narrative/models.py:134` `StoryBeat`; `:123` `NarrativeAssertion` | `test_no_second_authority` |
| Continuity | `hevi/narrative/continuity.py:17` `ContinuityEngine` | declared via `ContinuityConstraint`, not reimplemented |
| Provider selection | `obase.provider_registry.ProviderRegistry` (external) | `test_no_provider_authority` |
| Production runtime | `hevi/production/p2_pipeline.py:157` `run_p2_production`; `hevi/tasks/task_service.py:600` | `test_no_second_pipeline` |

## 2. P6 introduces exactly two authorities

| P6 authority | Scope | Why it is not a duplicate |
|--------------|-------|---------------------------|
| `ProductProfileRegistry` | commercial **product intent** | Holds no shot/motion/edit grammar and no asset policy. References creative profiles by id. |
| `GrammarRegistry` | grammar kind → contract | Maps P6's own ten grammar kinds. Not a creative, renderer, asset or QA registry. |

`GrammarRegistry` is not in the P5.3 list because P5.3 has no registry at all —
`hevi/production/p5_3/profile_grammar.py` is a static dict lookup, not a
registry class. P6 introduces the first grammar registry and it is scoped to
P6's own vocabulary.

## 3. Boundaries P6 must not cross

### No provider authority

P6 modules import nothing from `hevi.providers`, `obase`, or any provider
package. `test_grammar_is_provider_and_runtime_independent` fails on any such
import. `RendererConstraint` declares *capabilities required*;
`hevi.renderers.base.select_renderer` decides who can execute.

### No runtime independence violated

P6 modules import nothing from `p0_pipeline`, `p1_pipeline`, `p2_pipeline`,
`hevi.tasks`, `hevi.missions`, `hevi.verdict`, `hevi.quality`. Same guard.

### No private P5 surface

`test_p6_does_not_reach_into_private_p5_modules` refuses imports of
`hevi.ops.p5_1_*` and `hevi.production.p5_3._*`. P6 consumes P5 public contracts
so P5 refactors stay P5's business.

### No hardcoded product branching

`test_product_branching_absent` walks every P6 module and fails on any comparison
of `product_type`/`product_kind` against a `P0*`/`P1*` literal, and on any `if`
whose test touches those attributes. This is the guard that makes "ten products,
one pipeline" true rather than aspirational. Mutation-verified: injecting
`if product_profile.product_type.value == "P08_COMMERCIAL"` fails the test.

### No frozen-module edits

`test_p6_does_not_modify_frozen_p0_to_p5_modules` diffs nine P0-P5 modules
against HEAD and requires zero changes.

## 4. Pre-existing duplicates outside P6

Found during the audit. **Not P6's to fix, and not guarded**, because a
repo-wide glob would fail on code P6 does not own. Recorded so they are not
mistaken for P6 regressions:

| Type | Canonical | Competing definition |
|------|-----------|---------------------|
| `ShotPlan` | `hevi/production/p0_pipeline.py:143` | `hevi/cinematic/shot_intelligence/models.py:84` |
| `MotionPlan` | `hevi/production/p0_pipeline.py:162` | `hevi/production/semantic_motion.py:85` |
| `ShotPreparation` | `hevi/production/shot_readiness.py:77` | `hevi/season_planner/preparation.py:276` |

P5.1's `test_no_second_shot_authority` guards only P5.1 modules and does not
scan `hevi/cinematic/`, so these are currently unasserted. Worth raising
separately.

## 5. `PRODUCT_HERO` dangling reference

`PRODUCT_HERO` appears as a profile token in 11 places — 8 `PRODUCT.*` recipes
(`hevi/production/p5_3/recipes/__init__.py:705-775`), 3 cross-references
(`:222`, `:329`, `:378`), and `tests/integration/p5_3/test_p5_3_e2e_c_product.py:17`
— but it is **not** in `ProfileId` (`p2_types.py:31`) and **not** in
`build_default_registry()` (`p2_profiles.py:270`).
`get_registry().resolve("PRODUCT_HERO")` returns `None` today.

Also `hevi/production/p5_3/profile_grammar.py` has no `PRODUCT_HERO` entry, so
recipe matching falls through to an all-empty preference set.

**Not fixed in P6.0.** Two reasons: registering it means writing a
`ProductionProfile`, which is P2's authority and P6.0's mandate is architecture
only; and it is a real content decision (which shot/motion/edit policy suits a
product hero) rather than a schema question. See the migration map.

Note also that `ProfileId` is already non-exhaustive — `KNOWLEDGE_TALK_FINECUT`
is registered at runtime by `hevi/ops/p5_1_finecut.py:149` without appearing in
the enum. That is accepted precedent (it keeps `DUPLICATE_PROFILE_REGISTRY == 0`),
but it does mean two sources of truth for profile IDs now exist. Worth a
deliberate decision rather than drift.
