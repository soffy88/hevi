# HEVI P6 — Final Closure

> **VERDICT: PASS_WITH_EXTERNAL_BLOCKERS**
> `P6_FREEZE=PASS_WITH_EXTERNAL_BLOCKERS`
> Architecture qualification: **PASS**. Real render qualification: **BLOCKED_BY_PROVIDER**.

---

## 1. What closed in this final phase

| phase | deliverable | state |
|---|---|---|
| P6.5.3 | semantic match contract repair (G-13) | PASS |
| P6.6 | unified production runtime boundary | PASS |
| P6.6.12 | Level A qualification (no provider required) | PASS |
| P6.6.13 | runtime mutation audit (10 mutations) | PASS |
| P6.7 | ten-product E2E matrix + artefacts | PASS |
| P6.7.7 | cross-product invariants | PASS |
| P6.8 | static / authority / false-success / duplicate / determinism audits | PASS |
| — | real render qualification | **BLOCKED_BY_PROVIDER** |

## 2. The core invariant, measured

`ONE_PRODUCT_GRAMMAR · ONE_PRODUCT_COMPILER · ONE_PRODUCTION_RUNTIME · ONE_SHOT_AUTHORITY · ONE_MOTION_AUTHORITY · ONE_RECIPE_AUTHORITY · ONE_ASSET_AUTHORITY · ONE_QA_AUTHORITY`

Every one of those is verified structurally, not declared:

| invariant | how it is proven |
|---|---|
| one product compiler | exactly one `ProductCompiler` class in all of P6 |
| one runtime | P6.6 satisfies P6.0's `ProductionRuntimePort`; it does not replace it |
| one recipe authority | exactly one `rank_candidates` and one `_semantic_match` in the whole repo |
| one shot / motion authority | P6 defines no `ShotPlan`, `MotionPlan` or `ShotPreparation` — not even aliased |
| one asset / renderer / QA authority | P6 imports none of them |
| no product branch | no product identifier in any P6 `if`/`match`/dict-dispatch |

## 3. What P6.6 actually is

P6.0 already shipped the boundary: `ProductionRuntimePort` (a Protocol),
`RuntimeBoundary.produce()`, `RuntimeBinding`, `SourceMaterial`,
`ProductionConstraints`. What was missing was the connection, because P6.0's
`ProductProfileCompiler` is still an abstract stub that raises.

P6.6 supplies that connection and nothing else:

```
ProductProfile → ProductCompiler (P6.5, the only one) → ProductProductionIntent
   → UnifiedProductionRuntime.submit()   ← P6.0's declared port
   → RuntimeRequest (generic fields, NOT a ShotPlan)
   → the bound existing runtime
```

It defines no renderer, no shot planner, no motion planner, no recipe selector.

### The false-success rule is structural

`ProductionRunResult.__post_init__` **raises** if a success state arrives without an
`ExecutionReceipt` whose `produced=True`. P6.6 cannot assert production it did not
observe, so `FALSE_SUCCESS=0` is a type-level guarantee rather than a promise. Twelve
failure injections — provider 401/403, quota, GPU, credentials, timeout,
cancellation, asset, renderer, QA, grammar, runtime — each keep their identity and
each stay a failure.

### Idempotency

`RuntimeLedger` keys on a content-derived `run_id`. A repeated submit with the same
identity never re-enters the delegate, so retries cannot duplicate logical shots or
assets. Verified across repetition, same-run-id, retry-after-failure, cancel-then-
retry and all ten products: `DUPLICATE_SIDE_EFFECTS=0`.

One design bug was found and fixed here: an unbound attempt originally *recorded*
its failure under the run id, which permanently blocked the legitimate run that
followed. Precondition refusals have no side effects, so they now do not consume
identity — caught by a smoke test, not by a designed test.

## 4. Capabilities are not grammar layers

Character, world and evidence are declared `Capability` values, validated against
the production context, and reported by name when missing
(`CAPABILITY_UNAVAILABLE:evidence`). `CAPABILITY_REQUIREMENTS` is a table keyed by
`ProductType` — declarative data that selects nothing. No new grammar layer was
introduced, per the closure instruction.

## 5. Ten products, one runtime

All ten compile and bind. Capability requirements differ; execution architecture
does not. Structural proof preserved and extended: at least two product pairs
produce byte-identical compiled layers apart from `product_profile_id`.

| product | narrative | presenter | style | visual grammar | recipe |
|---|---|---|---|---|---|
| P01_AVATAR_EXPLAINER | explanatory | avatar_explainer | educational_clarity | educational_clarity | EXPLAINER.CONCEPT_BUILD |
| P02_HISTORY_RECONSTRUCTION | story | historical_reconstruction | cinematic_drama | dramatic_reconstruction | CAMERA.COMBINED_MOVEMENT |
| P03_DOCUMENTARY | documentary | documentary_explainer | documentary_realism | documentary_realism | CAMERA.TRUCK |
| P04_SCIENCE_EXPLAINER | explanatory | avatar_explainer | educational_clarity | educational_clarity | EXPLAINER.CONCEPT_BUILD |
| P05_NEWS_ANALYSIS | documentary | documentary_explainer | documentary_realism | documentary_realism | CAMERA.TRUCK |
| P06_EDUCATIONAL | explanatory | educational_lecture | educational_clarity | educational_clarity | EXPLAINER.CONCEPT_BUILD |
| P07_MARKETING | explanatory | product_presentation | educational_clarity | educational_clarity | CAMERA.DETAIL_TO_CONTEXT |
| P08_BRAND_STORY | story | documentary_explainer | cinematic_drama | dramatic_reconstruction | CAMERA.COMBINED_MOVEMENT |
| P09_SHORT_VIDEO | short_form | avatar_explainer | educational_clarity | educational_clarity | CAMERA.STATIC_HOLD |
| P10_CINEMATIC_STORY | story | historical_reconstruction | cinematic_drama | dramatic_reconstruction | CAMERA.COMBINED_MOVEMENT |

P08 and P10 share the visual *declaration* but not the compiled intent — they use
different presenters, and exactly one field differs (`presenter_grammar_id`). The
divergence is traceable rather than mysterious.

## 6. The honest blocker

```
CUDA available: False    device count: 0    nvidia-smi: Unable to determine device handle
VOLCANO_TTS_API_KEY / VOLCANO_ACCESS_KEY / OPENAI_API_KEY / DASHSCOPE_API_KEY: all unset
```

`REAL_RENDER_STATUS=BLOCKED_BY_PROVIDER`

No mock, fake provider, synthetic success, placeholder media or test-only bypass was
substituted. Every one of the ten artefacts carries
`"real_render_qualification": "BLOCKED_BY_PROVIDER"` and `"mock_used": false`.

## 7. Unresolved observation

During the closure regression, one run reported a single P5.3 failure that did not
reproduce across three subsequent batch runs and three isolated runs of the same
test. Six `@pytest.mark.slow` P5.3 integration tests render real video through
HTML/GSAP or FFMPEG and are resource-sensitive. **I could not reproduce it and am
therefore not calling it a flake** — it is recorded as an open observation for the
owner of that suite.
