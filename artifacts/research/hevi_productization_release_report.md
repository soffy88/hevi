# HEVI Productization Release — rc1 (2026-09-19)

**Release id:** `hevi-productization-rc1-2026-09-19` (release candidate, not 1.0)

## SHAs

- `HEVI_START_SHA=480d51a`
- `D6_IMPLEMENTATION_SHA=a586a71`
- `WORKTREE_CLEAN=YES`

## What shipped

The verified differentiators are now product flows a normal user can complete
without knowing internal terms:

- **角色库** — create / save-to-library / use-in-project / version pin /
  upgrade-available / archive (history-safe).
- **连续性检查** — inline before generation: PASS, WARN (audited override),
  BLOCK (refuses paid generation), with provenance on demand.
- **制作问题** — auto-recovered / needs-confirmation (cost + preserved shown) /
  manual action, with a verified repair timeline.
- **制作状态** — one server-derived project health status + next action.
- **创作数据** — analytics from canonical metrics only.
- **快速开始 + 示例项目** — safe defaults; advanced options optional; demo clearly
  labelled and not production evidence.

Backend product projections added without a second source of truth:
project health reads currency/plan/incidents/continuity; the next action is
server-derived (`FRONTEND_STATE_RECOMPUTATION=0`).

Backend hardening included in D6: auto-detected incidents now carry the owner
(they were previously invisible), `verify` no longer reads another tenant's
task, subject deletion no longer leaves a dangling identity link.

## Gates

All D6 wave gates and E2E-P1..P5 PASS. See
`hevi_productization_release_report.json` for the full matrix.

## Quality

- Backend: **3233 passed / 29 skipped / 0 failed / 0 errors**
- Frontend: **181 passed / 37 files**; `tsc --noEmit` PASS; `npm run build` PASS
  (with the deploy env `NEXT_PUBLIC_DEPLOY_ENV=production NEXT_PUBLIC_API_BASE=…`)
- `RUFF=PASS`; `MYPY=PASS` (strict, 1245 files)
- `3O_ARCHITECTURE_ZERO=PASS`; ledger `39/39 qualified`; taxonomy unchanged
- Performance baseline captured in `hevi_d6_performance_baseline.json`
  (P50 ≈ 4–5 ms, P95 ≈ 5–6 ms on the local test runtime; no absolute SLA)

## Known limitations (explicit)

- Lip-sync presenter **BLOCKED**; local GPU runtime **BLOCKED** (no GPU).
- Creative memory remains **PARTIAL** (API + limited UI).
- D6-I accessibility is verified for the new surfaces only; no repo-wide
  accessibility audit.
- Project identity remains a free string; no first-class project registry.
- Pre-existing (not changed): several `/api/authorities/*` routes ignore the
  authenticated owner — recorded in the surface audit as a follow-up.
- 3O lint drift is `ENVIRONMENTAL_NON_BLOCKING` (local `.venv`; reproduces at the
  pre-D2 SHA; canonical 3O audit PASS).

## Tag message content

```
Persistent cross-project creative identity: VERIFIED
Continuity-aware production: VERIFIED
Self-healing production: VERIFIED
Lip-sync presenter: BLOCKED
Local GPU runtime: BLOCKED
durability topology: SINGLE_HOST_DURABLE
```
