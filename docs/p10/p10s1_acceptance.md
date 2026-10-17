# P10-S1 — Director System contracts: ReferencePack + DirectorBrief (acceptance)

```yaml
status: S1 PASS 2026-10-03
scope: S1 ONLY (S2 MotionGrammar … S9 E2E NOT started)
code: hevi/creative/director_brief/{errors,codec,reference_pack,director_brief,__init__}.py
tests: tests/p10/test_p10_s1_director_brief.py (29) + tests/p10/test_p10_s1_vertical.py (5) = 34 green
gates: ruff check hevi/creative/director_brief tests/p10 PASS · mypy --strict hevi/creative/director_brief PASS
regression: tests/p10 102 passed + tests/creative_runtime 228 passed
```

## What S1 is

Two data contracts a director session is handed, nothing else:

- **ReferencePack** — which references were consulted (identity + `uri` / `retrieved_at` /
  `content_hash`) and the constraint ledger read off them. Each constraint carries an
  epistemic status so no downstream stage can confuse what was observed with what was decided:
  `observed` (needs provenance) · `inferred` (needs provenance + rationale) · `target`
  (needs a `measurable`) · `forbidden` (needs a reason, so it can be scoped later).
- **DirectorBrief** — source, reference pack, thesis/treatment pins, required visual + motion
  priorities, anti-patterns, and the approval/completeness state of that brief.

Deterministic serialization: `codec.canonical_json` (`sort_keys`, `ensure_ascii=False`,
`allow_nan=False` — NaN/non-JSON types raise instead of being stringified) plus
`canonical_hash` (sha256). `to_dict()` / `from_dict()` round-trip losslessly; unknown fields,
unknown schema versions, and bad enum values are rejected rather than dropped.

## Authority boundary (the point of the stage)

S1 adds **no** authority and **no** behaviour:

| concern | owner | S1 relationship |
|---|---|---|
| brief / thesis / treatment content | P10b `CreativeBrief` / `CreativeThesis` / `Treatment` | pinned by `brief_ref` / `thesis_ref` / `treatment_ref` (sha256) |
| reference + principle extraction | P10b `BenchmarkSet` | pinned by `ReferencePack.benchmark_ref` |
| revision lifecycle | P10a `Lifecycle` / `DirectionRepository` | `ApprovalRecord.state` reuses `Lifecycle`; revision pin record reused via `content_pins()` |
| NarrativeCanon / CreativeProgram | existing HEVI authorities | untouched, not imported, not re-modelled |
| motion grammar / compiler / review / revision impact | S2+ | not implemented |

No Director Agent, no orchestrator, no planner, no provider selection, no `async`, no IO in
the package — asserted by `test_s1_6_package_defines_no_authority_or_orchestration`
(AST scan of all five modules) and by the `Lifecycle` reuse assertion.

## Gates

| gate | claim | test |
|---|---|---|
| S1-1 | schema + fail-loud diagnostics, no defaulted identity (unpinned content hash, unpinned canon for narrative source, unknown payload field, unsupported schema, NaN/inf) | `test_s1_1_*` |
| S1-2 | the four epistemic classes are distinguished and each demands its own anchor; contradictions on one key, duplicate ids, empty pack | `test_s1_2_*` |
| S1-3 | provenance/reference identity retained and bound: constraint provenance must cite a declared reference; reference provenance must name that reference | `test_s1_3_*` |
| S1-4 | hash stability (equal constructions hash equal, content and declaration order are tracked) + lossless round-trip through JSON | `test_s1_4_*` |
| S1-5 | completeness is diagnosed, not silently filled; must-priorities and anti-patterns must be grounded in constraints; approval must be attested + pinned and cannot be edited in place (`APPROVAL_VOID`) | `test_s1_5_*` |
| S1-6 | authority boundary + vocabulary locked to P10a/P10c | `test_s1_6_*` |

## Vertical contract test (real, not mocked)

`tests/p10/test_p10_s1_vertical.py` runs the real P10-S spike artifacts
(`docs/p10/p10_s/{benchmark,thesis,treatment,signature_shot}.json`) through:

```
real artifacts -> real P10b content objects (validated) -> real content hashes
  -> ReferencePack (observed/inferred/target/forbidden read off the real benchmark + signature shot)
  -> DirectorBrief pinned to those hashes, APPROVED
  -> real P10a revision dir on disk via the existing P10b pin record (content.json)
  -> file round-trip -> drift refused at both boundaries (APPROVAL_VOID)
```

Evidence claims it makes, all asserted: the S1 pins equal the real P10b `content_hash` values;
the pack provenance `content_hash` is the sha256 of the real `benchmark.json` bytes; the target
constraint's `measurable` is the real `scale_change_ratio 0.65-0.75` from
`signature_shot.json`; `state.json` carries no creative content; editing one measurable after
approval is refused by both `validate_for_approval()` and `verify_content_pins()`.

## Known unrelated failure

`tests/p10/test_p10d_verify.py::test_d7_frozen_run_replayed` fails in this worktree because
`artifacts/p10_s/20261003T002838Z/` is a local run output that is not tracked by git and exists
only in the main checkout. Pre-existing; unrelated to S1.