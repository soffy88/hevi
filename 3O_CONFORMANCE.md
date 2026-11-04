# hevi 3O Conformance (HELIOS_3O_SPEC_v3_0)

Status: layered registry conformance. Flat-namespace rename is a
separate, parent-confirmed migration (see §5) — names are unchanged in
this round; only additive metadata was added.

## 1. Decision (Soffy, 2026-11-04)

The capabilities registry is governed as a **layered** system, not a
flat product-line catalog: every registered capability carries a 3O
layer (`oprim` / `oskill` / `omodul` / `obase` / `oservi`). The old
`kind` (render category) and `line` (product line) fields are kept as
descriptive metadata only; they are not layer attribution.

## 2. SPEC mapping (registry scope)

| SPEC § | Requirement | hevi landing |
|---|---|---|
| §1.1 five elements | oprim/oskill/omodul/obase/oservi | `Capability.layer` + `layer_attribution.py` (one entry per name) |
| §1.2 composition vs bare call | upper uses lower freely; same-layer bare calls constrained | Sibling-import adjudication list in §4; oskill 4-constraint check in tests |
| §1.3 asset pool | conforming + red-line-passing elements accumulate | Unchanged: registry keeps accumulating; admission stays test-gated |
| §1.4 single source | one implementation per logic; duplicates converge to canonical + delegating alias + guard test | Price index (§4), compiler/gate clusters (§4), riso dual source (§4) |
| §2.2 flat namespace | oprim/oskill/omodul flat, no domain submodules | **Pending parent confirmation** — see §5 migration plan; names unchanged |
| §2.4 no project prefix | element names carry capability semantics, no project/vendor anchor | Lint `check_no_project_prefix` PASS (verified in lint re-run) |
| §2.5 `__manifest__` | element list + signature + version | `hevi.capabilities.__manifest__` (built at import tail) |
| §4 oprim | atomic, mutually non-calling, ≤1 positional + kwonly | Attribution rule only; signature rule enforced for newly declared oprim modules, not retrofitted onto gates (see §6 exceptions) |
| §5 oskill | ≥2 oprim, stateless, no persistence, LLM via Protocol | Attribution rule; LLM-injection retrofit is out of scope (recorded exception) |
| §6 omodul | standard signature `(config, input_data, output_dir)`, status/error always returned, never raise, `_enabled_pillars` ≥ 1 | `omodul_contract.py` adapters for the omodul set (§3); pillars declared per adapter |
| §7 oservi | 5 red lines, injection contracts, no hardcoded elements | Only genuine engine skeletons are attributed `oservi`; the rest stay omodul/obase with reasons |
| §8 project service layer | API/CLI/Worker not in the master library | Out of scope: hevi service layer is not the registry |

## 3. omodul contract

`hevi/capabilities/omodul_contract.py` provides `omodul_entry()`: it
validates `_enabled_pillars` (≥1 of fingerprint/decision_trail/report/
cost), calls the underlying implementation, and normalises the result
to `{status, error, ...}` — failures return `status="failed"` instead
of raising (async cancellation is re-raised per SPEC §5.6 C4).
Adapters are thin delegating wrappers over the existing entry points;
no business logic was moved or rewritten. Pillar assignment rule
(auditable): `fingerprint` + `report` for every omodul, guaranteed by
the adapter by construction (artefact sha256 + status/error
envelope); `cost` additionally for the 3 workflows whose modules
name paid generation executors directly (`storyfilm.py`,
`shortstory.py`); `decision_trail` additionally for the 2 workflows
whose product is a persisted decision sequence
(`project_handoff` step records, `stable_film_assembly` manifest).
The table is built from the attribution table, so a new omodul
cannot slip in undeclared (guard test locks the 51 names).

## 4. Layer attribution and single-source convergence

### 4.1 Layer attribution (397 names, zero remainder)

Source of truth: ~/workspace/3o-conformance/layer_attribution.json
(397 entries, one per registered name; each entry carries layer +
one-line reason + defining file). A copy is kept on ubuntu26 at
/data/soffy/3o-conformance/layer_attribution.json. The table module
hevi/capabilities/layer_attribution.py is generated from it by
scripts/ci/gen_layer_attribution.py -- never hand-edit entries.

Counts (live import, clean checkout, Batch 3a re-attribution):
oprim 59, oskill 228, omodul 51, obase 59, oservi 0. Four
capabilities were corrected oprim -> oskill in Batch 3a with
evidence-based reasons (multi-step validate+execute+validate across
subsystems, not single-backend round-trips; the sibling audit had
flagged the same four as atomicity violations and upgrading the
caller was its prescribed convergence): qa.browser_check_executor,
edit.karaoke_render, world.threejs_imaging_upgrade,
video.word_pop_renderer. oservi = 0 is a finding, not a gap: no
registry capability passes all five SPEC 7.2 red lines; the only
oservi engine reference in-tree sits outside the registry
(hevi/pipeline/longvideo_manifest.py importing the canonical
oservi package). Attribution rules: atomic single-call execution
-> oprim; multi-rule composition / stateless algorithm -> oskill;
end-to-end business transaction -> omodul; adapter / cross-cutting
-> obase; registry-shell wrappers take the layer of their delegate
module (named in the JSON evidence). The 65 batch/dynamic
registrations were individually decomposed in the JSON -- no
"unclassified" remainder. Coverage is machine-checked by
tests/test_3o_conformance.py (full-coverage + manifest + validity).

### 4.2 Single-source convergence and sibling adjudication

Convergence (Batch 3a, guard tests `tests/test_3o_single_source.py`,
11 passed):

- Price index: 5 price tables converge on one write path --
  `model_directory.record_in_directory()` (single writer via
  `register_model`; all records unverified). Floyo and Modal
  `record_in_directory` delegate to it (thin wrappers kept for
  existing callers/tests). Floyo `local_h3_config()` delegates H3
  config values to `config_record()` under an `h3_config` sub-record.
  Seedance and VidoGrid `_render` gained a `describe` (default,
  validate-only, current behaviour) / `record` action (refuses
  failing records, writes via the shared writer). Current price
  overlap between the sources is empty; the guard test locks that
  fact. Canonical execution pricing remains
  `hevi/cost/pricing_table.get_pricing_table()`.
- Compilers (5): written divisions kept; shared implementation is
  forbidden by the guard test (no shared impl across the 5 compiler
  modules). `build_three_layer_fixtures` was reclassified pure
  in-memory construction (no file IO) after inspection -- the sibling
  audit's constraint-2 failure verdict for it was a file-level-grep
  heuristic error; it is restricted-allowed pending its docstring
  composition list (landed).
- Consistency gates (5), disclosure gates (4), subtitle/ASR gates
  (6): written divisions; each cluster's independence/order is
  locked by a guard test (disclosure tracks independent; subtitle
  pipeline order enforced).
- Athenaion: `qa.look_shot_separation` is an explicit delegating
  alias of the canonical `world.athenaion_discipline` render (fixes
  `mode`, delegates the rest); single-source guard test locks it.
- Riso: single implementation registered twice (package import +
  registry import, with the tree's only `overwrite=True` call) is
  converged by a `_once` guard at both call sites; explicit
  re-registration still records overwrite history (10 entries,
  verified). Guard test locks single registration under the real
  entry order (`hevi.capabilities` imported first; importing
  `hevi.riso` first fails identically on main HEAD -- pre-existing
  circular-import entry-order limitation, not introduced here).
- Helper sink: 33 shared pure definitions moved to the unregistered
  module `hevi/capabilities/pure_helpers.py` (SPEC 1.2 sink);
  origin modules re-export every moved name (verified identical
  objects live); a static undefined-name check over the touched
  files reports clean.

Sibling imports (103 edges / 65 files adjudicated in the audit):
37 combination-allowed, 12 data/type sharing, 5 infrastructure-
internal, 24 restricted-allowed (3 pass all 4 SPEC 1.2 constraints;
the rest are covered by docstring composition lists, machine-checked
in 16 caller files / 22 edges by
`tests/test_3o_single_source.py::test_sibling_composition_lists_present`;
3 further candidate edges dissolved by the helper sink --
`edit_plan_compiler`/`is_on_grid`,
`subtitle_discipline`/`_containment_coverage`,
`issue_kind_labels`/`normalise_verdict` -- and are excluded from the
list set),
1 restricted-failed reclassified pure (see above), 1 helper-to-sink
dissolved, 10 banned (7 atomicity -- 4 fixed by re-attribution, 3
remaining recorded in section 6; 3 reverse dependency -- recorded in
section 6), 6 bare omodul->omodul calls and 7 upward oskill->omodul
calls recorded in section 6 with reasons. Docstring composition
lists follow the form `Composes (3O SPEC 1.2): <callee>, ...` on the
caller function's docstring.

### 4.3 Spend-gate wiring (Batch 3b)

The 4 generation executors consult `spend_brake.check_spend_approval`
first -- before any key read, network call, or GPU work -- when the
caller supplies a `spend_approval` block
`{storyboard, confirmed, smoke_passed, batch_size,
estimated_unit_cost}`; a refused block raises before any spend.
When no block is supplied, spending responsibility stays
caller-side and the result `qa` carries
`spend_gate_not_consulted: true`. `image.nano_banana_generate` keeps
its pre-existing `allow_paid` gate first (order preserved); the
spend consultation runs after it, before key resolution. Each
executor's schema gained the `spend_approval` property
(`additionalProperties` is False). Coverage, same grep method
(real `gate_spend(`/`authorize_spend(`/`check_spend_approval(` call
sites, baseline `7df618cb`): 5 files -> 9 files; executors 0/4 ->
4/4. Guard tests `tests/test_3o_omodul_spend.py` (9 passed) prove
refusal precedes key/network access and that an approved block
passes through to the key/service stage.

### 4.4 avcraft admission (Batch 4)

`hevi/avcraft/{obase,oskill,omodul}` (31 files) was admitted from
the previously untracked worktree directory, per the reviewed
partial-admission decision: `__pycache__` excluded,
`oskill/shotprompt.py` DEFERRED (separate owner decision; LEGACY
status preserved in the source worktree copy; callers lazy-import
it and raise `ModuleNotFoundError` until decided),
`save/load_timeline` implementation moved to `obase/timeline_io.py`
(re-exported from `oskill/timeline.py`), omodul envelope gap
disclosed in `UPSTREAM-3O.md` (ValueError raises, no status/error
envelope, no `_enabled_pillars` -- pre-envelope, adapter pending
registration; do not cite as SPEC section-6-conformant), package
`__manifest__` added with the deferred module listed explicitly.
The `tests/test_avcraft_3o.py` referenced in the P0 notes did not
exist at admission; no test files were admitted. Guard tests
`tests/test_3o_avcraft_admission.py` (6 passed). The lint check
`check_no_sibling_call` flags 8 items in the admitted tree; see
section 6.

## 5. Flat-namespace rename plan — PENDING PARENT CONFIRMATION

Renaming 397 dotted names is breaking: every caller, test fixture,
skill doc, and the production frontend/backend wiring keys off the
current names. The migration plan (mapping table, alias mechanism,
caller migration list, alias-removal timetable) is delivered
separately for confirmation. Until confirmed: no renames, old names
stay canonical, `layer` is the only new axis.

## 6. Recorded exceptions (with reasons)

- oprim keyword-only signature (§3.4): not retrofitted onto existing
  gate functions (`check_*` take a single plan dict positionally by
  long-standing convention). New oprim declarations follow it.
- oskill LLM Protocol injection (§4.3): existing LLM-calling skills
  keep their provider wiring; injection is required for new ones.
- Flat namespace (§2.2): pending §5 confirmation; recorded here, not
  silently waived.
- Sibling exceptions (SPEC 1.2 / section 6), each with reason and
  recheck condition (recheck when an oservi `sequential_composer`
  orchestration engine lands in-tree; oservi count is 0 today):
  - `project_handoff` state functions (`create_project` /
    `record_step`): genuine IO transaction composition, not a
    reusable algorithm; moving them would split a transaction.
  - `drama_gates` registry-mediated `story.script_polish` call via
    `_registry_get().render_safe()` + registration side-effect
    import: mediated by the registry, not a bare sibling call.
  - Canvas orchestration kernel (`plan_canvas_execution` /
    `create_workflow` / `rerun_selection` / `expand_seed_batch`):
    moving it wholesale was judged too risky; orchestration via
    oservi deferred.
  - `build_h3_prompt` (300 lines + 7 private helpers) +
    `check_h3_prompt` hosted in omodul `scene_reference.py`: move
    deferred; the host module is the H3 prompt authority.
  - 12 data/type-sharing constant edges: deferred to a
    constants-consolidation follow-up; sharing names, not behaviour.
  - 3 reverse-dependency edges and 3 remaining atomicity edges from
    the sibling audit: behaviour-preserving convergence was not
    safe in this round; each stays with its audit reason on file
    (`sibling_imports.md` in the analysis deliverables).
  - avcraft `highlight_clips` -> `reframe_vertical` (optional
    vertical post-step inside one transaction): bare omodul call,
    kept because no orchestration engine exists in-tree and the
    shared contract (`detector`/`stats`/`files`) must not be
    duplicated without the package's own tests (absent at
    admission). Recheck with the oservi engine.
  - avcraft `omodul/__init__.py` lazy `__getattr__` re-exports (7
    lint flags): namespace mechanism only; no sibling is called at
    import time or by the re-export itself. The lint check matches
    import statements textually; these flags are heuristic, not
    calls, and are recorded rather than worked around.
- avcraft omodul envelope gap: disclosed in `UPSTREAM-3O.md`
  (see section 4.4); the package must not be cited as SPEC
  section-6-conformant until its functions are registered and
  adapted.

## 7. Acceptance criteria (machine-checked)

- Clean-checkout import passes; registry count is 397 with zero
  unattributed names (`test_3o_conformance.py`).
- `__manifest__` covers all 397 names with layer + signature.
- Every omodul adapter returns status/error and never raises on
  business failure; pillars declared.
- Single-source guard tests pass (price index, cluster aliases).
- Spend-gate coverage re-measured and recorded (see spend section).
- 3O lint re-run with site-packages excluded: hevi-tree verdict PASS
  or per-item exceptions listed in §6.
- `stale_timeline` gate and existing gates unweakened (regression
  suite green on the touched files).

## 8. Verification record (2026-11-04, Batch 4b)

- Clean-checkout verification (detached worktree at the Batch 4
  commit): import passes, 397 registered / 397 unique, layers
  oprim 59 / oskill 228 / omodul 51 / obase 59 / oservi 0,
  manifest 397, zero unattributed; avcraft manifest obase 8 /
  oskill 6 / omodul 8, deferred `oskill.shotprompt`; timeline
  re-export identical to the obase implementation.
- Guard suites green standalone and under full-collection import:
  `test_3o_conformance` (6) + `test_3o_single_source` (11) +
  `test_3o_omodul_spend` (9) + `test_3o_avcraft_admission` (6) =
  32 passed. Targeted regression on touched areas: 345 + 159 + 114
  (sink/convergence/docstring sets) + 51 (executor/spend) + 83
  (canvas/asr/beginner/canvas-matrix spot set), all green.
- Scope rule (Batch 4b): the conformance tests scope the registry to
  production names. `tests/test_jobguard.py` registers two
  `test.*` fake capabilities at import time
  (`test.jobguard_echo`, `test.jobguard_fail`); the tests exclude
  the `test.` prefix and fail loudly on any other unattributed
  name, so the fakes cannot silently widen the registry.
- Full suite (13,333 items collected, 8 pre-existing collection
  errors excluded, baseline-confirmed at `7df618cb`): 502 failed /
  11,418 passed / 92 skipped / 45 xfailed / 1,276 errors in 35:11.
  The failures concentrate in areas untouched by this round
  (vimax, dirstyle, creative_runtime, freezone, gold, and 4
  architecture history-shape tests). Spot re-runs of touched files
  that failed in the full run pass standalone (83 passed), and the
  environment hits `Errno 24 Too many open files` (per-process
  `ulimit -n` is 1024) during a run of this size -- the full-suite
  tally is therefore NOT a green/red verdict on this round; the
  scoped evidence above is. Re-running the whole suite to green
  needs an FD-limit raise and a separate pre-existing-failure
  triage, both out of this round's scope.
- `stale_timeline`: untouched by this round; its gate tests pass in
  the targeted sets above (no weakening).

- Registry growth (video-shotcraft graft, 2026-11-04): 397 -> 405
  registered names (6 oskill gates + 2 obase contracts/indexes).
  Layer attribution JSON and the generated table were extended
  through `scripts/ci/gen_layer_attribution.py`; the conformance
  scope count in `tests/test_3o_conformance.py` was updated to 405.
  No renames; the rename/alias migration plan is unchanged.

- Registry growth (aicameramovements completion graft, 2026-11-04): 405 -> 413 registered names (6 oskill gates + 2 obase index/assembler). The camera movement catalogue itself grew 40 -> 46 in the same single source. Layer attribution JSON and the generated table were extended through `scripts/ci/gen_layer_attribution.py`; the conformance scope count in `tests/test_3o_conformance.py` was updated to 413.

- Registry growth (20 open skills graft, 2026-11-04): 413 -> 421
  registered names (6 oskill gates + 2 obase fake contracts),
  landing on top of the aicameramovements graft. Layer
  attribution JSON and the generated table were extended
  through `scripts/ci/gen_layer_attribution.py` from the
  shared JSON, which now converges both grafts (421 entries);
  the conformance scope count in `tests/test_3o_conformance.py`
  was updated to 421. No renames; the rename/alias migration
  plan is unchanged.

- Registry growth (15 open tools graft, 2026-11-04): 421 -> 428
  registered names (5 oskill gates + 2 obase fake contracts),
  landing on top of the 20 open skills graft. Layer attribution
  JSON and the generated table were extended through
  `scripts/ci/gen_layer_attribution.py` from the shared JSON,
  which now converges all three grafts (428 entries); the
  conformance scope count in `tests/test_3o_conformance.py`
  was updated to 428. No renames; the rename/alias migration
  plan is unchanged.
- Registry growth (claude-animation-skills graft, 2026-11-04): 428 -> 436
  registered names (6 oskill gates + 2 obase fake contracts),
  landing on top of the 20 open skills graft. Layer attribution
  JSON and the generated table were extended through
  `scripts/ci/gen_layer_attribution.py` from the shared JSON,
  which now converges both grafts (436 entries); the
  conformance scope count in `tests/test_3o_conformance.py`
  was updated to 436. No renames; the rename/alias migration
  plan is unchanged.
- Registry growth (deferred shotcraft batch B, 2026-11-04): 436 -> 438
  registered names (2 obase fake contracts: Remotion bridge
  contract, theme catalog schema), landing on top of the
  claude-animation-skills graft. Layer attribution JSON and the
  generated table were extended through
  `scripts/ci/gen_layer_attribution.py` from the shared JSON
  (438 entries); the conformance scope count in
  `tests/test_3o_conformance.py` was updated to 438. No renames;
  the rename/alias migration plan is unchanged.
- Registry growth (deferred camera-movement batch B, 2026-11-04):
  438 -> 440 registered names (1 obase fake render-mapping
  contract + 1 oskill duration/grid advisory), landing on top
  of the shotcraft batch B. Layer attribution JSON and the
  generated table were extended through
  `scripts/ci/gen_layer_attribution.py` from the shared JSON
  (440 entries); the conformance scope count in
  `tests/test_3o_conformance.py` was updated to 440. No renames;
  the rename/alias migration plan is unchanged.
- Registry growth (deferred 20-skills batch B, 2026-11-04):
  440 -> 443 registered names (2 obase fake contracts: Jolt
  rigid-body, Tweakpane panel; 1 oskill gate: CosyVoice
  voice-authorization hard intercept), landing on top of the
  camera-movement batch B. Layer attribution JSON and the
  generated table were extended through
  `scripts/ci/gen_layer_attribution.py` from the shared JSON
  (443 entries); the conformance scope count in
  `tests/test_3o_conformance.py` was updated to 443. No renames;
  the rename/alias migration plan is unchanged.
