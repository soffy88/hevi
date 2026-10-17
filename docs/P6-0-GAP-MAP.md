# HEVI P6.0 — Gap Map

What exists, what P6.0 adds, and what remains open. Every "exists" claim is a
file reference; every "adds" claim is a P6.0 file.

---

## 1. Coverage against the P6 spec

| Spec § | Requirement | Status | Where |
|--------|-------------|--------|-------|
| 2 | `ProductProfile` core model | **ADDED** | `hevi/production/p6/schema.py` |
| 3 | G01-G10 grammar layer | **ADDED** (contracts) | `hevi/production/p6/schema.py` |
| 4 | Narrative grammar, 9 modes, 11 nodes | **ADDED** (contract) | `NarrativeGrammar`, `NarrativeMode`, `NarrativeNode` |
| 5 | Presenter grammar, 5 kinds | **ADDED** (contract) | `PresenterGrammar`, `PresenterKind` |
| 6 | Character grammar + continuity | **ADDED** (contract) | `CharacterGrammar`, `ContinuityConstraint` |
| 7 | World grammar | **ADDED** (contract) | `WorldGrammar`, `WorldKind` |
| 8 | Evidence grammar, epistemic split | **ADDED** (contract) | `EvidenceGrammar`, `EvidenceClaim`, `EpistemicStatus` |
| 9 | Documentary grammar, 4 required answers | **ADDED** (contract) | `DocumentaryGrammar` |
| 10 | Commercial grammar, locked identity | **ADDED** (contract) | `CommercialGrammar`, `ProductIdentity` |
| 11 | Instruction grammar, verifiable steps | **ADDED** (contract) | `InstructionGrammar`, `InstructionStep` |
| 12 | Short-form grammar, 4 platforms | **ADDED** (contract) | `ShortFormGrammar`, `ShortFormPlatform` |
| 13 | Cinematic grammar reuses P5.3 | **ADDED** (intent only) | `CinematicIntent` |
| 14 | P01-P10 product matrix | **PARTIAL** — vocabulary only | `ProductType`; profiles land P6.6-P6.10 |
| 15 | `produce()` runtime interface | **ADDED** (boundary) | `RuntimeBoundary`, `PIPELINE_STAGES` |
| 16 | `ProductProfileCompiler` | **ADDED** (contract) | `hevi/production/p6/compiler.py` |
| 17 | `PRODUCT_PROFILE_REGISTRY`, `GRAMMAR_REGISTRY` | **ADDED** | `hevi/production/p6/registry.py` |
| 18 | 14 architecture tests | **ADDED** (157 assertions) | `tests/test_p6_0_architecture.py` |
| 19 | P01-P10 qualification | **NOT STARTED** | P6.11 |
| 20 | Implementation order | P6.0 only | this phase |

## 2. Grammar behaviour: added vs outstanding

P6.0 delivers **contracts**. Each grammar below has its declared fields,
validation and serialisation; none has behaviour.

| Grammar | Contract | Behaviour (compile/validate/emit) |
|---------|----------|-------------------------------|
| G01 Narrative | DONE | P6.1 — node ordering, arc assembly |
| G02 Presenter | DONE | P6.2 — presenter resolution against P2 + P5.1 |
| G03 Character | DONE | P6.3 — entity binding, continuity wiring |
| G04 World | DONE | P6.4 — world-to-constraint derivation |
| G05 Evidence | DONE | P6.5 — claim→scene→shot traceability |
| G06 Documentary | DONE | P6.7 — evidence/narrator/archive composition |
| G07 Commercial | DONE | P6.8 — brand lock enforcement |
| G08 Instruction | DONE | P6.9 — step→shot expansion |
| G09 ShortForm | DONE | P6.10 — platform constraint mapping |
| G10 Cinematic | DONE (intent) | P5.3 owns resolution; P6 declares only |

## 3. Open gaps carried into P6.1+

### G-01 — `UnimplementedCompiler` raises

`P6_0_COMPILER.compile_profile()` raises `COMPILER_NOT_IMPLEMENTED`. Intent
assembly is P6.1 work. **Fail-closed by design**: a stub returning empty intent
would let a caller believe a product compiled.

### G-02 — no product profiles registered

`PRODUCT_PROFILE_REGISTRY` is empty by design. All ten P01-P10 profiles land
P6.6-P6.10. `stats()` reporting `total_profiles: 0` is correct, not a defect.

### G-03 — `profile_refs` unresolved

`ProductProfile.profile_refs` names P2 `ProductionProfile` ids, but P6 does not
resolve them. Resolution belongs at compile time against
`p2_profiles.get_registry()`. Until then a dangling ref is undetectable.

### G-04 — runtime unbound

`RuntimeBoundary` ships unbound. Binding is a deployment decision naming an
existing entry point (`run_p2_production` or `TaskService.run_task`). P6.0
asserts the refusal; it does not perform production.

### G-05 — `PRODUCT_HERO` unresolvable

Used as a profile token in 11 places, absent from `ProfileId` and
`build_default_registry()`. `get_registry().resolve("PRODUCT_HERO")` returns
`None`. P6.8 must resolve this by registering into P2's registry, **not** by
minting a P6 profile. Detail in `docs/P6-0-AUTHORITY-BOUNDARY.md` §5.

### G-06 — `profile_grammar.py` has no `PRODUCT_HERO` entry

`hevi/production/p5_3/profile_grammar.py` keys only the four original P2
profiles. A `PRODUCT_HERO` recipe therefore matches against an all-empty
preference set. P5.3-owned; P6.8 raises it rather than editing P5.3.

### G-07 — evidence grammar not bound to `EvidenceAsset`

`EvidenceClaim.source_refs` are strings. Binding to
`hevi.ops.p5_1_types.EvidenceAsset` happens in P6.5. Until then the epistemic
split is declared but not verified against real assets.

### G-08 — continuity declared, not enforced

`ContinuityConstraint.enforced_by` names the authority that *will* enforce
(e.g. `hevi.narrative.continuity.ContinuityEngine`). `CharacterGrammar` refuses
to exist without at least one, but P6.0 does not call the engine.

### G-09 — CLOSED in P6.2 (presenter half of the P6.1 gap)

P6.1 recorded: *"a profile can declare `narrative_grammar` (P6.0) as one shape
and `narrative_grammar_id` as another, and nothing cross-checks them."*

**Presenter half — CLOSED.** `GRAMMAR_COMPATIBILITY_REGISTRY` (P6.2) is a
declarative table keyed by narrative grammar id, and
`PresenterCompiler.check_compatibility()` refuses any pairing it does not permit.
`narrative=documentary` + `presenter=avatar_explainer` now raises
`INCOMPATIBLE_GRAMMAR_PAIRING`. Verified by
`tests/test_p6_2_presenter.py::test_incompatible_pairing_raises` across 10
incoherent pairings.

**Narrative half — STILL OPEN.** Nothing cross-checks P6.0's
`ProductProfile.narrative_grammar` (mode + nodes) against
`narrative_grammar_id` (the registry reference). A profile can still declare
`mode=NarrativeMode.DOCUMENTARY` and `narrative_grammar_id="explanatory"`, and
the compiler will honour the id while the declaration contradicts it. Carried to
P6.4.

### G-10 — CLOSED in P6.3 (profile identity did not cover its grammar references)

**Before.** `ProductProfile.to_dict()` serialised `product_type`, policies and the
embedded grammar objects, but **not** `narrative_grammar_id` or
`presenter_grammar_id`. Two profiles that differed *only* in which narrative or
presenter grammar they selected therefore produced the **same**
`content_hash()`.

That defeated the purpose of the hash in a chain whose entire design is "a
product references shared grammars by id". Two products that select different
narratives were indistinguishable as cache keys, as diff targets, and as
revision markers — the exact use `content_hash()` is documented for.

**Closed in P6.3.** All three reference ids are serialised:

```python
"narrative_grammar_id": self.narrative_grammar_id,
"presenter_grammar_id": self.presenter_grammar_id,
"visual_style_id": self.visual_style_id,
```

Pinned by
`tests/test_p6_3_visual_style.py::test_architecture_profile_content_hash_covers_every_grammar_reference`
and `::test_architecture_profile_content_hash_covers_the_style_reference`, which
assert a single-field change in each id changes the hash.

**Why P6.3 fixed a P6.1-era omission.** P6.3's product connection depends on
`visual_style_id` being part of the profile's identity. Leaving the two
pre-existing ids unserialised while serialising the new one would have produced
an inconsistent and more confusing contract than either extreme. This was a
pre-existing omission, not a P6.3 regression, and it is recorded here rather than
folded silently into the P6.3 changelog.

**Note.** This changes `ProductProfile.content_hash()` values relative to the
P6.0/P6.1/P6.2 baseline. No test pinned a literal hash, and all 415 P6.0–P6.2
tests pass unchanged, so nothing downstream depended on the old values. Any
externally cached hash from a pre-P6.3 build is invalidated once.

### G-11 — CLOSED in P6.4 (nothing bound P6's directives to the cinematic engine)

**Before.** P6.0–P6.3 declared and compiled a complete chain — product, narrative,
presenter, visual style — and none of it reached the engine that knows how to
shoot. `hevi.production.p5_3` was fully capable (`retrieve_with_evidence()` over
an 80-recipe corpus with mandatory selection evidence) and entirely unwired.
`test_p5_4_evidence_mandatory.py` already insisted that *its* callers record
evidence; there were no P6 callers to insist upon.

**Closed in P6.4.** `VisualCompiler.bind()` is the single door into P5.3:

```
NarrativeIntent + PresenterIntent + VisualGrammar
    → VisualIntent          (camera/motion/composition/editing strategies)
    → retrieve_with_evidence()   ← P5.3's only production retrieval path
    → RecipeSelectionEvidence
    → ShotPlan → Editable Timeline   (P0/P1 — NOT P6.4)
```

P6.4 names no recipe, ranks nothing, and builds no `RecipeLibrary`. Verified
against the real corpus — `documentary_realism`→`CAMERA.TRUCK`,
`dramatic_reconstruction`→`CAMERA.COMBINED_MOVEMENT`,
`educational_clarity`→`EXPLAINER.CONCEPT_BUILD`,
`commercial_clean`→`EMOTIONAL.SOLITUDE_HOLD`.

**P5.3 unmodified.** Only `p5_3.library`, `p5_3.schema` and one
`p5_3.retrieval` import are used; P6.4 is a consumer of P5.3, not an extension of
it. Pinned by `test_integration_does_not_modify_p5_3`.

**Where the chain deliberately stops.** `ShotPlan` and `MotionPlan` belong to
P0/P1, and P5.3's own docstring says it does not "override ShotPlan, override
MotionPlan". P6.4 therefore ends at the evidence. Building a `ShotPlan` here
would be a second shot system, which `NO_SECOND_SHOT` / `NO_SECOND_MOTION` and the
spec's "不要新增 shot system" both forbid.

### G-12 — SCOPED in P6.4 (P6.3's blanket P1-import ban was too wide)

**Before.** P6.3 added `hevi.production.p1_types` to a single
`FORBIDDEN_IMPORT_PREFIXES` list applied to *every* P6 module. Correct when P6.3
was the newest phase; too wide once a binding phase existed.

**Why.** P6.4 must construct P1's `VisualBeat` to hand P5.3, because
`retrieve_with_evidence(library, beat: VisualBeat, ...)` takes that exact type.
Importing an existing request type is the opposite of a second authority — a
second authority would be *defining* its own beat.

**Scoped in P6.4** to two rules, both narrower than the ban they replaced:

1. P6.3's own package may not import `hevi.production.p1_types` at all.
2. Any other P6 phase may import **only the symbol `VisualBeat`** from
   `p1_types`, and no P6 module may declare a `VisualBeat` class.

Pinned by `test_architecture_p6_3_package_imports_no_p1_request_types`,
`test_p1_request_types_allowance_is_symbol_exact` and
`test_p1_request_types_allowance_defines_no_beat_type`.

### G-13 — OPEN (carried to P6.5): the retrieval beat carries thin semantics

`retrieve_with_evidence` scores a candidate's semantic fit from four signals:

| signal | weight | supplied by P6.4? |
|---|---|---|
| `beat.shot_role in recipe.beat_roles` | 0.4 | yes — strategy-derived |
| `beat.intent_id == recipe.intent` | 0.3 | **never matches** — `intent_id` is P6's qualified id, `recipe.intent` is a P5.3 verb like `BUILD_UNDERSTANDING` |
| `beat.motion_purpose in recipe.semantic_roles` | 0.2 | yes — after the P6.4 vocabulary fix |
| `beat.narrative_phase in recipe.beat_roles` | 0.1 | only by leaving the P1 default |

So 0.3 of a possible 1.0 is structurally unreachable, and 0.1 arrives by accident
rather than design. Observable consequence: `commercial_clean` (energetic camera,
PAYOFF role) retrieves `EMOTIONAL.SOLITUDE_HOLD`, which is a defensible *shape*
but not the right recipe.

Closing it needs a real mapping from narrative/presenter semantics onto P5.3's
`recipe.intent` vocabulary, which is P5.3's vocabulary to define. Carried to
P6.5; P6.4 deliberately does not invent a second intent vocabulary to fill it.

## 4. Deliberately not done

| Item | Why not |
|------|---------|
| Ten product profiles | P6.6-P6.10; P6.0 is architecture |
| Grammar compilation | P6.1+ |
| Fixing `ShotPlan`/`MotionPlan` duplicates | Outside P0-P5; P6.0 does not own those modules |
| Fixing `ShotPreparation` duplicate | Same |
| Registering `PRODUCT_HERO` | Writing a `ProductionProfile` is P2's authority; also a content decision |
| Extending `ProfileId` | Would add a second source of truth; precedent (`KNOWLEDGE_TALK_FINECUT`) is runtime registration |
| Populating `tests/architecture/` | Directory does not exist; architecture suites are flat |
| Binding a runtime | Deployment decision; P6.0 proves the refusal instead |
| Any renderer, timeline, shot, asset, QA implementation | Hard-forbidden by spec §21 |

## 5. Risk register

| Risk | Severity | Mitigation in P6.0 |
|------|----------|-------------------|
| P6 drifts into a second pipeline | High | `test_no_second_pipeline`; unbound `produce()` raises |
| Product-specific branching appears | High | `test_product_branching_absent`, mutation-verified |
| P6 redefines a P0-P5 type | High | `test_no_second_authority` across 23 types |
| Grammars couple to providers | High | import guards over all four modules |
| `ProfileId` drift | Medium | documented (G-05/G-06); unresolved by design |
| Guards pass vacuously | Medium | two mutations verified to fail the suite |
| P6 grows a second profile registry | Medium | `ProductionProfileRegistry` mutation → 122 failures |

### G-14 — OPEN: the P6.3/P6.4 coherence matrix is a perfect diagonal

P6.4's coherence check refuses a (style, grammar) pair that disagrees on any
shared language — `motion_language`, `composition_language`, `lighting_language`.
Enforcing it revealed that **only 3 of the 24 possible pairings are coherent**:

| P6.3 style ＼ P6.4 grammar | documentary_realism | dramatic_reconstruction | educational_clarity | commercial_clean |
|---|---|---|---|---|
| `documentary_realism`  | **Y** | . | . | . |
| `archival_history`     | . | . | . | . |
| `educational_clarity`  | . | . | **Y** | . |
| `cinematic_drama`      | . | **Y** | . | . |
| `future_tech`          | . | . | . | . |
| `corporate_clean`      | . | . | . | . |

Consequences, all recorded rather than worked around:

* P6.4's `commercial_clean` grammar has **no** coherent P6.3 style partner, so it
  cannot be used by any product. `P07_MARKETING` therefore compiles to
  `educational_clarity` for both style and grammar, and retrieves
  `EXPLAINER.CONCEPT_BUILD` — a shape match, not a marketing recipe.
* P6.3's `archival_history` and `future_tech` styles have no coherent P6.4
  grammar partner at all, so no product can use them.
* A history reconstruction cannot use `archival_history`: P6.2 gives it the
  `historical_reconstruction` presenter, but the coherent P6.4 partner of
  `cinematic_drama` is `dramatic_reconstruction`, not `archival_history`.

The coherence rule is correct — a disagreement between two layers over motion is a
real defect. The defect is that P6.3 and P6.4 shipped partially-overlapping
vocabularies whose intersection is a diagonal. Fixing it means either adding
`camera_language`/`editing_language` to the coherence set (no — those are P6.4's
own contribution and have no P6.3 counterpart), or adding a small number of
P6.3 styles and P6.4 grammars that align along an off-diagonal. Carried to P6.6.

### G-15 — CLOSED in P6.5 (the two P0x namespaces are separate on purpose)

**Before.** P6.0's closed `ProductType` enum and the P6.5 brief's commercial
labels both use `P01_`–`P10_` prefixes, and **nine of ten slots disagree**
(`P03_HISTORICAL_REENACTMENT` vs `P03_DOCUMENTARY`, and so on). Only
`P01_AVATAR_EXPLAINER` matches.

**Risk.** One enum containing both would make `P03_DOCUMENTARY` and
`P03_HISTORICAL_REENACTMENT` read as variants of the same product. They are not:
P6.0's taxonomy is the canonical production taxonomy (the
`ProductProfile.product_type` field), the brief's labels are the customer-facing
catalogue.

**Closed in P6.5.** `CommercialProduct` is a separate namespace, and every profile
carries both explicitly so no code path infers one from the other. The
asymmetry is used as a safety property — `CommercialProduct("P03_DOCUMENTARY")`
succeeds where `ProductType("P03_DOCUMENTARY")` raises, and vice versa, so a
mix-up fails loudly rather than silently compiling the wrong product. Pinned in
both directions by `test_schema_commercial_label_is_not_a_product_type` and
`test_schema_product_type_is_not_a_commercial_label`, and the count (9 of 10) is
pinned by `test_schema_namespace_collision_with_product_type_is_documented`.

### G-16 — CLOSED in P6.5 (P6.0's canonical registry was not extended)

**Before.** The P6.5 brief asks for a new `PRODUCT_PROFILE_REGISTRY` responsible
for `id → ProductProfile`. P6.0 already owns exactly that under the same name,
keyed `id@version`, with `register`/`get`/`list_ids`/`validate`/`stats`.

**Why not reuse it.** The two registries hold different subjects, and this is
structural rather than stylistic: P6.0's `register()` enforces
`validate_composition()`, which **rejects** a reference-only profile
(`DECLARED_BUT_ABSENT:G01_NarrativeGrammar`). P6.5's profiles declare grammar
*references* and are resolved at compile time, which is precisely the pattern
P6.1/P6.2 established. The commercial profiles could not be registered in P6.0's
registry even if that were desirable.

**Closed.** `COMMERCIAL_PRODUCT_REGISTRY` / `CommercialProductRegistry` — a
sibling, not a copy, following the pattern of P6.1/P6.2 adding grammar
registries beside P6.0's `GRAMMAR_REGISTRY`. `assert_no_id_collision()` fails
loudly if the two namespaces ever drift into a shared id.

**Also closed.** `ProductProfileRegistry` (P6.0) remains exported from
`hevi.production.p6`; the package `__all__` was deduped to 129 unique names after
an interim regression where the rename clobbered P6.0's same-named export and
broke three P6.0 tests.

### G-13 — PARTIALLY CLOSED in P6.5.1 (0.30 semantic term still unreachable)

**Was.** `beat.intent_id != recipe.intent`. P6.4 set `beat.intent_id` to
`"documentary_realism@v1.0.0"`; `recipe.intent` holds **77 distinct values across
80 recipes** — a per-recipe description, not a vocabulary. P5.3's 0.30-weight term
was structurally unreachable and `semantic_match` capped at 0.70, a permanent ~9%
of `selection_score`.

**Closed in P6.5.1** — `hevi/production/semantic_contract.py`. The audit found
three vocabularies that genuinely are shared and built the contract on exactly
those: `semantic_roles` (11, the layer vocabulary), `RecipeFamily` (8), `beat_roles`
(10). `recipe.intent` is excluded from the contract by construction. No new intent
vocabulary was invented; the shared set is asserted equal to the live corpus.

Also repaired: `narrative_phase` was arriving as P1's `DEVELOPMENT` default *by
accident*, and the motion-strategy table collapsed `RESTRAINED_PUSH` and
`DELIBERATE_MOVE` both onto `REVEAL`. Both are now deliberate and recorded.

Measured honestly: mean max `semantic_match` 0.56 → 0.58, `selection_score`
+0.006. **The gain is small and capped by the unreachable term.**

**STILL OPEN — needs an owner decision.** Making the 0.30 reachable requires
either editing P5.3 scoring (forbidden; P5.3 has been read-only throughout) or
setting `beat.intent_id` to a recipe intent — which is recipe selection by label,
i.e. the second selector the architecture forbids, and with 77 singleton intents
would select exactly one recipe.

The fix is one line in P5.3's `_semantic_match`:

```python
if beat.intent_id and beat.intent_id in recipe.semantic_roles:
    score += 0.30
```

with P6 setting `beat.intent_id` to a contract `semantic_id`. No new vocabulary;
ranking stays inside P5.3. **Not done unilaterally.** Until it lands, every
production plan carries a known, quantified ~9% semantic deficit.

### G-14 — CLOSED in P6.5.2 (the compatibility matrix was a perfect diagonal)

**Was.** Coherence required equality across motion *and* lighting *and*
composition simultaneously. Those channels are correlated across P6.3/P6.4 — each
style's `(motion, lighting)` pair maps to exactly one grammar — so only **3 of 24**
pairings were usable. `archival_history`, `future_tech`, `corporate_clean` and
P6.4's `commercial_clean` were all dead, and a history reconstruction could not use
`archival_history`.

**Closed in P6.5.2** — `hevi/production/p6/compatibility_policy.py`. Coherence is
now decided by single-channel constraint rules with explicit severity (`AGREE`,
`EXCLUDE`, `FLEX`, `UNSET`) rather than by three-way equality. Only **motion**
gates hard, because it is the one channel where disagreement is a contradiction
rather than extra work — `MotionLanguage` means the same thing in both layers.
Lighting and composition are advisory; `infographic` is the single absolute
exclusion, being the one composition with no common room with an observed or
performer-centred frame.

**Measured result: 6/24 coherent, 0 dead styles, 0 dead grammars.** The three dead
zones are verified end-to-end against the real recipe corpus. An intermediate
attempt that hard-gated motion *and* lighting measured 0/24 — worse than the
original — which is how the correlated-channel cause was confirmed rather than
assumed.

**Deliberately invented.** `EditingLanguage` and `CameraLanguage`, both required by
P6.4's shipped grammars and neither present in P6.3. No other new visual
vocabulary; a test asserts every value any rule can express already exists in a
P6.3 or P6.4 enum.

### G-17 — CLOSED in P6.5.2 (compatibility advisories were raised as errors)

**Was.** The first wiring of the constraint model appended advisory messages to the
same `errors` list as blocking ones, so a "flexible" pairing refused the product —
silently defeating the entire model it had just introduced.

**Closed.** Advisories are carried on `VisualIntent.flexible_channels` and never
raised. Pinned by
`tests/test_p6_5_2_compatibility_policy.py::test_wiring_flexibility_is_carried_not_raised`.

### G-18 — CLOSED in P6.5.2 (the EXCLUDE guard never fired)

**Was.** `GrammarCompatibilityPolicy.add()` checked `self._rules` for a clash key,
but `_rules` is keyed by rule *key*, not by `channel=value`. Two rules excluding
the same value were silently accepted.

**Closed.** Exclusions are tracked in a dedicated `_exclusions` set keyed by
`(channel, value)`, and a test registers two conflicting exclusions expecting the
refusal.

### G-13 — CLOSED in P6.5.3 (the 0.30 semantic term is reachable)

**Status update on the entry above.** The repair flagged there as "needs an owner
decision" was authorised and applied.

`hevi/production/p5_3/retrieval.py::_semantic_match`, one term:

```python
if beat.intent_id and beat.intent_id in recipe.semantic_roles:   # was: == recipe.intent
    score += 0.3
```

plus P6.4 supplying the contract's `semantic_id` in `beat.intent_id`.

**Measured on the shipped corpus:** recipes reachable by the 0.30 term went
**0/80 → 1-23/80** depending on role; the `semantic_match` ceiling went
**0.70 → 1.00**; the gain is exactly +0.30 on a matching recipe and exactly +0.09
in `selection_score` (0.30 weight x 0.30 term).

**Unchanged and pinned:** all weights (`semantic` 0.30, `variety` 0.05 and the
rest), the ranking authority, every recipe id, every `recipe.intent` value, and the
corpus itself. Exactly one `_semantic_match` exists in the repo. No P6 module names
a recipe id.

**Behaviour change worth knowing:** a beat whose `intent_id` names a legacy recipe
label (`"ESTABLISH_SUBJECT"`) now scores 0 on that term rather than 0.30. Intended
— those callers were asking the label question, and the label is no longer the
contract. No shipped test changes its selected recipe; verified by running the full
P5.3/P5.4 selection under a scratch swap before applying it.

**G-13 is closed. P6.6 no longer inherits a known-broken scoring term.**
