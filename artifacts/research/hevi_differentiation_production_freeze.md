# HEVI Differentiation — Production Freeze

**Freeze id:** `hevi-differentiation-production-qualified-2026-09-19`

## SHAs

- `HEVI_D4_UNCOMMITTED_SHA=46847a8` (D4 results were uncommitted at this SHA)
- `HEVI_D5_IMPLEMENTATION_SHA=13d659c`
- `WORKTREE_CLEAN=YES`
- `D5_IMPLEMENTATION_SHA` is the qualified release SHA (tag target).

## D5 results

| Wave | Result |
|------|--------|
| D5-A memory security | PASS |
| D5-B durability topology | PASS (`SINGLE_HOST_DURABLE`) |
| D5-C store integrity | PASS |
| D5-D claim matrix | PASS |
| D5-E release qualification | PASS |
| D5-F long-horizon E2E | PASS |

Security closure: `/authorities/memory` is owner-scoped with a
server-derived owner; cross-tenant reads/writes/anonymous are 0. Split-brain
authority across hosts fails closed (`SplitBrainAuthorityError`).

**Durability topology:** `single_host_durable` — one authoritative API
process group on one host, stores on that host's persistent volume. **NOT**
distributed / multi-node / HA durable (`MULTI_HOST_AUTHORITY_CLAIM=NOT_CLAIMED`).

## Claims

| Claim | Status |
|-------|--------|
| Persistent cross-project creative identity | VERIFIED |
| Continuity-aware production | VERIFIED |
| Self-healing production | VERIFIED |
| Multi-user isolation | VERIFIED |
| Creative memory | PARTIAL |
| Local / hybrid generation | BLOCKED |
| Lip-sync presenter | BLOCKED |

## Release qualification (from clean tree at 13d659c)

- `RUFF=PASS`; `MYPY=PASS` (strict, 1244 source files)
- Backend: **3219 passed / 29 skipped / 0 failed / 0 errors**
- Frontend: vitest **159 passed / 31 files**; `tsc --noEmit` PASS
- Creative regression / Studio E2E / fault injection / security adversarial: PASS
- D5 security gates: 42 passed
- `INKOS_CAPABILITY_TOTAL=39`, `QUALIFIED=39`, `0` partial/missing/unqualified
- `3O_ARCHITECTURE_ZERO=PASS` (canonical independent audit artifact)
- `LEDGER_TAXONOMY_CHANGED=NO`

## Known issues (explicit, not hidden)

- `legacy_3o_v3_lint` FAIL: the installed `oprim`/`omodul` packages in
  `.venv` have drifted. The identical failure reproduces at the pre-D2
  closure SHA `46847a8`; no tracked 3O code and no `scripts/ci` change in
  D2–D5. Pre-existing/environmental, out of scope for this release.
- D5-E discovered and fixed a latent bug: the linked-subject appearance
  continuity seam referenced a non-existent `FactSource.USER` member, so the
  write silently no-op'd. Fixed to `USER_CANON` with a regression test.

## Freeze decision

All required gates PASS from a clean worktree. The tag below is created only
after this report is committed and the tree is clean.

```
Persistent cross-project creative identity: VERIFIED
Continuity-aware production: VERIFIED
Self-healing production: VERIFIED
Lip-sync presenter: BLOCKED
Local GPU runtime: BLOCKED
durability topology: SINGLE_HOST_DURABLE
```
