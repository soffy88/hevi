# HEVI × ArcReel v0.30 — Capability-by-Capability Deep Gap Audit

> READ-ONLY AUDIT. No production code changed. No ledger status changed. No tests/evidence altered.
> No ArcReel source, prompt, skill, template, or fixture copied. WHAT-only recommendations.
> Full machine-readable mapping: `arcreel_v030_hevi_gap_audit.json` (same directory).

## 0. Baselines

| Item | Value |
|---|---|
| HEVI_SHA | `fbe9827863414f8407928e7564ee73e606f7823d` |
| BRANCH | `closure/3o-v3-architecture-creative-baseline` |
| WORKTREE_CLEAN | YES (0 porcelain lines at audit start; only `artifacts/research/*audit*` added by this report) |
| CAPABILITY_LEDGER_PATH | `docs/research/inkos_capability_ledger.yaml` |
| CAPABILITY_TOTAL | **39** (all `status: QUALIFIED`; primary comparison axis, untouched) |
| ARC_REEL_BASELINE | `v0.30.0` (commit `7fb395c`, 2026-09-10, AGPL-3.0) |
| ARC_CAPABILITY_COUNT | **115** observable capabilities (domains A–T, behavior-counted, not file-counted) |
| ArcReel evidence checked | README, PRODUCT.md, CONTEXT.md (ubiquitous-language, code-mapped), website `dev/architecture`, `guide/workflows`, `guide/providers`, `guide/jianying-export`, releases v0.26→v0.30, v0.30.0 tag tree `server/ + lib/ + tests/` symbol presence (read-only clone in /tmp, not imported) |

ArcReel CONFIDENCE split: 108× `VERIFIED_CODE_AND_TEST`, 4× `VERIFIED_CODE`, 3× `DOCUMENTED`
(A04 brief, D03 4K-gate, S05 tenancy-posture). No `ISSUE_ONLY` item drives a gap verdict.

## 1. Verdict totals

| HEVI_STRONGER | HEVI_PARITY | HEVI_PARTIAL | HEVI_MISSING | NOT_APPLICABLE | UNVERIFIED |
|---|---|---|---|---|---|
| 2 | 20 | 73 | 15 | 0 | 5 |

| P0 | P1 | P2 | P3 |
|---|---|---|---|
| 3 | 20 | 64 | 1 |

## 2. Status map (115 → 39 ledger)

Format: `ARC_ID status → hevi capability`. Rationale/evidence/tests per item: see JSON.

**A input/project:** A01 PARTIAL→import_continuation/material_library · A02 PARTIAL→script_runtime ·
A03 UNVERIFIED→material_library · A04 PARTIAL→longform_production/policy_packs ·
A05 PARTIAL→length_governance (duration doesn't govern volume, G1 quirk) ·
A06 PARITY→production_storyboard/export · A07 PARTIAL→style_intelligence/genre_system

**B content:** B01 PARTIAL→observation_delta/longform · B02 PARITY→longform_production (season planner, G1) ·
B03 PARITY→canonical_state/observation_delta (quote_id red-line) · B04 PARTIAL→script_runtime ·
B05 PARTIAL→review · B06 PARITY→script_runtime/production_storyboard ·
B07 PARTIAL→script_runtime · B08 PARTIAL→short_fiction/script_runtime

**C canon/assets:** C01 PARTIAL→canonical_state/production_storyboard · C02 PARTIAL→production_storyboard ·
C03 PARTIAL→production_storyboard/material_library · C04 UNVERIFIED→material_library ·
C05 PARITY→canonical_state · **C06 MISSING→canonical_state (H2)** · C07 PARTIAL→material_library ·
**C08 MISSING→canonical_state/production_storyboard**

**D storyboard:** D01–D03 PARTIAL→production_storyboard · D04 UNVERIFIED · D05–D08 PARTIAL
(D05→revision/production_storyboard, D06→revision/run_snapshots, D07→production_storyboard, D08→production_storyboard/model_routing)

**E video:** E01 PARITY · E02 PARITY (both →production_storyboard/model_routing) ·
E03 PARTIAL→model_routing · E04 PARTIAL→model_routing · E05 PARTIAL→background_runs/run_snapshots ·
**E06 MISSING→background_runs** · E07 PARTIAL→revision/review · **E08 MISSING→run_snapshots/background_runs (H5)** ·
E09 PARTIAL→model_routing (H10)

**F speech:** F01 PARITY→model_routing · F02–F04 PARTIAL→canonical_state/script_runtime (H8) ·
F05–F06 PARTIAL→export/analytics

**G presentation: G01 MISSING→export/studio (H1, P0)**

**H subtitles:** H01–H03 PARTIAL→export

**I export:** I01 STRONGER→export (S4) · I02 PARTIAL→export (H6) · I03 PARTIAL→backup_restore/export

**J artifact authority:** J01 PARTIAL→export · **J02 MISSING→export/revision/run_snapshots (H9, P0)** ·
J03 PARTIAL→export · J04 PARTIAL→revision/run_snapshots · **J05 MISSING→export** · J06 PARTIAL→run_snapshots

**K plan:** K01 PARTIAL→production_harness · **K02 MISSING→production_harness/longform_production** ·
K03 PARTIAL→production_harness · K04 PARITY→longform_production · K05 PARTIAL→run_snapshots

**L tasks:** L01 PARITY · L02 PARTIAL→run_snapshots · L03 PARTIAL→run_snapshots ·
L04/L05/L06 PARITY→background_runs (+model_routing for L06) · L07 PARTIAL→run_snapshots

**M providers:** M01–M05 PARTIAL→model_routing · M06 PARTIAL→model_routing (H4) · **M07 MISSING→model_routing**

**N cost:** N01 PARITY · N02 PARITY (both →analytics) · N03 UNVERIFIED→analytics ·
N04 PARTIAL→analytics · **N05 MISSING→analytics (H3)** · **N06 MISSING→analytics (H3)**

**O HITL:** O01–O03 PARTIAL→review/revision/run_snapshots · **O04 MISSING→revision (H9)** · O05 PARTIAL→revision

**P agent:** P01 PARTIAL→production_harness · P02 PARTIAL→skills/production_harness · P03 PARITY→skills ·
P04–P07 PARTIAL→production_harness/review/skills

**Q memory: Q01 MISSING · Q02 MISSING · Q03 MISSING (all →memory_retrieval, H7)**

**R studio:** R01 PARTIAL→studio · R02 PARITY→background_runs · R03 PARTIAL→analytics ·
R04 PARTIAL→model_routing/studio · R05 UNVERIFIED→studio · R06 PARTIAL→studio

**S security:** S01–S04 PARTIAL→concurrency/model_routing/skills/export · S05 STRONGER→concurrency (S1)

**T ops:** T01 PARITY · T02 PARITY · T03 PARTIAL→backup_restore · T04 PARTIAL→run_snapshots · T05 PARITY

## 3. Hypotheses H1–H10 / S1–S5

- **H1 Presentation Read Model — CONFIRMED MISSING (P0).** No selector symbol; 4 disjoint paths/tests.
- **H2 Character Derivative — CONFIRMED MISSING (P1).** Single appearance; wardrobe uploads carry no variant identity.
- **H3 Call-level Usage — CONFIRMED MISSING (P1).** Aggregates only; no rows/KPI/detail/orphan-reconcile.
- **H4 Declarative Endpoint — CONFIRMED PARTIAL-gap (P1).** Declaration exists; submit/poll/test-runner/preview/market missing.
- **H5 Download Resume — CONFIRMED MISSING (P0).** Whole-file downloads; job id not durable → interrupt re-bills.
- **H6 Jianying — CONFIRMED PARTIAL (P1).** 3-track draft real; transitions + presentation-binding missing.
- **H7 Agent Memory — CONFIRMED MISSING (P1).** Two disconnected stores; no prefs/conventions/cross-session/editing in runtime. Veya ≠ memory.
- **H8 Voice+Appearance — CONFIRMED PARTIAL (P1).** Co-location without unified authority/ownership/admission.
- **H9 Staleness — CONFIRMED MISSING (P0 for J02/O04 via currency).** Fail-closed opposites tested; stale-but-usable absent.
- **H10 Failure Transparency — CONFIRMED PARTIAL (P1).** Video path transparent; generic LLM path redacts to UNKNOWN.
- **S1 Multi-user — HEVI STRONGER** (owner checks + IDOR 404 + isolation tests vs single-admin by design).
- **S2 Production Graph — MIXED:** graph depth stronger; plan/next-action surfacing missing (K02, P1).
- **S3 3O Modularity — NO blanket verdict;** interchangeability observed, no controlled comparison ran.
- **S4 Local Engines — SCOPED STRONGER** (I01 composition/post + h3_local/Echo/Manim real outputs).
- **S5 Security Adversarial — NOT stronger;** S03 P2 (ad-hoc containment only).

## 4. TOP 15 (detail: JSON `top15`)

1. G01 Presentation Read Model — MISSING, P0, HEVI_LAYER4 — preview/export divergence.
2. J02 Currency 4-state — MISSING, P0, OBASE — duplicate billing, lost paid work.
3. E08 Remote + download resume — MISSING, P0, OSERVI — interrupt re-bills.
4. N05 Call-level records + KPI — MISSING, P1, OSERVI/LAYER4 — cost blindness.
5. N06 Call detail + orphan reconcile — MISSING, P1, OSERVI — unreconcilable spend.
6. M07 Endpoint lifecycle + market — MISSING, P1, OPRIM — provider onboarding blocked.
7. C06 Character derivative — MISSING, P1, OBASE — continuity breaks on transformation plots.
8. K02 Plan + next action — MISSING, P1, LAYER4 — stalled productions, agent guesswork.
9. E06 Batch admission — MISSING, P1, OSKILL — unbounded batch spend.
10. C08 Rename cascade + blocking — MISSING, P1, OMODUL — ref rot + wasted generations.
11. I02 Jianying draft — PARTIAL, P1, LAYER4 — lossy editor handoff (no transitions).
12. Q01/Q02 Agent memory — MISSING, P1, OBASE/LAYER4 — agent amnesia tax.
13. O04 Stale reuse — MISSING, P1, OSKILL — paid media unusable after drift.
14. M06 Custom provider depth — PARTIAL, P1, OPRIM — declarations stall at routing.
15. F04 Speech ownership — PARTIAL, P1, OBASE — wrong-voice drama delivery.

## 5. Final questions

**Q1 — Truly missing:** G01, J02, E08, N05, N06, M07, K02, E06, C06, C08, Q01–Q03, O04, J05 (§5-Q1 list; 15 items).

**Q2 — Present but weaker:** regen/version/rollback, TTS/voice consistency, Jianying, subtitles,
failure transparency (LLM path), provider backends/lifecycle, cost rollups, agent orchestration/session,
storyboard lifecycle, plan surfacing (see JSON `Q2_weaker_but_present`).

**Q3 — HEVI stronger:** I01 composition+post (VSR/RIFE/native remix, green ledgers);
S05 multi-user isolation; production-graph depth (DAG/constraints/repair/provenance);
local-generation option (H3/Echo/Manim real outputs); quote_id/is_performative provenance red-line.

**Q4 — Not worth adopting:** single-admin posture; ad post-VO doctrine (adopt only version-choice mechanic);
grid-first consistency (adopt split/versioning, not dense grids); upload-copy compression doctrine
(adopt visible-clamping rule only); full market apparatus (local endpoint registry suffices).

**Q5 — Top 5:** (1) G01 → export+studio · (2) J02 → export/revision/run_snapshots ·
(3) E08+L02/L03 → run_snapshots+background_runs · (4) N05/N06 → analytics ·
(5) M06/M07 → model_routing.

**Q6 — Ledger mapping, no new taxonomy:** all five land as depth inside existing capabilities
(read-model over export/studio; states over artifacts; job durability inside snapshots/runs;
ledger depth inside analytics; endpoint lifecycle inside model_routing). 39 unchanged.

**Q7 — New 3O vs Layer4:** canonical — OBASE manifest-currency extension; OSERVI durable
provider plane + usage ingest; OPRIM endpoint adapter runtime; OSKILL admission/currency evaluators.
Layer4-only — G01 assembly, K02 projection, R03 dashboard, Q03 settings, I02 transitions,
H03/O02/S/P-session UX pieces (see JSON `Q7_new_3o_vs_layer4`).

**Q8 — Invariants:** YES — 39 taxonomy, single source (G01 is derived, not second source),
3O v3 boundaries, one production authority (no rival orchestrator), clean-room WHAT-only.

## 6. Terminal summary

```text
HEVI_SHA=fbe9827863414f8407928e7564ee73e606f7823d
ARC_REEL_BASELINE=v0.30.0
HEVI_LEDGER_TOTAL=39
ARC_CAPABILITY_COUNT=115
HEVI_STRONGER=2
HEVI_PARITY=20
HEVI_PARTIAL=73
HEVI_MISSING=15
NOT_APPLICABLE=0
UNVERIFIED=5
P0_GAPS=3
P1_GAPS=20
P2_GAPS=64
P3_GAPS=1
TOP_5=
1. G01 Presentation Read Model (MISSING/P0 → creative.export+creative.studio)
2. J02 Currency 4-state (MISSING/P0 → creative.export/revision/run_snapshots)
3. E08 Remote+download resume (MISSING/P0 → creative.run_snapshots/background_runs)
4. N05/N06 Call-level ledger+detail (MISSING/P1 → creative.analytics)
5. M06/M07 Declarative endpoint lifecycle (PARTIAL+MISSING/P1 → creative.model_routing)
NEW_3O_ASSETS_RECOMMENDED=OBASE manifest-currency ext; OSERVI durable provider plane + usage ingest; OPRIM endpoint adapter runtime; OSKILL admission/currency evaluators
LAYER4_ONLY_RECOMMENDATIONS=G01 assembly; K02 plan projection; R03 dashboard; Q03 memory settings; I02 transitions; H/O/S/P UX pieces
LEDGER_TAXONOMY_CHANGED=NO
CODE_CHANGED=NO
WORKTREE_CLEAN=YES (report files only)
AUDIT_CLASSIFICATION=READ-ONLY CLEAN-ROOM OBSERVABLE-BEHAVIOR AUDIT
```
