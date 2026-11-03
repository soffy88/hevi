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
no business logic was moved or rewritten.

## 4. Single-source convergence and sibling adjudication

(Filled from the analysis deliverables: price index, cluster
decisions, sibling-import list. Counts and guard-test names are
recorded here once landed.)

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
