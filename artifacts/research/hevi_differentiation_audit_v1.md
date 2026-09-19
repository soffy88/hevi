# HEVI Differentiation Program — Phase D1 Audit

## Scope

This is a **read-only Phase D1 differentiation audit** over HEVI (branch `feature/vnext-3o-creative-runtime`, SHA `d717cce`, worktree clean). It identifies **which of HEVI's real capabilities best support "why users MUST pick HEVI" vs "HEVI can also do it."**

**Explicit scope statement (production closure):**

- **Closure scope** = **P0/P1 production-semantic parity/closure**, NOT **115/115 feature parity**.
- **ARC-D04 grid-split** remains **P2/P3, non-blocking** (the sole final `MISSING` item).
- **Closure statement:** `3119 passed / 29 skipped / 0 failed / 0 errors. 39/39 qualified. 3O_ARCHITECTURE_ZERO=PASS. P0=0. P1=0.`
- **Forbidden claims (enforced, 0 hits):** `FULL_ARCREEL_FEATURE_PARITY`, `115/115 PARITY`, `ALL_ARCREEL_GAPS_CLOSED`.

This audit **does not** modify production code, does **not** create a new taxonomy, does **not** create a second orchestrator, does **not** auto-pass unverified hardware moats, and does **not** treat internal complexity as user value.

## The 7 Differentiation Domains (D1-A through D1-G)

| Domain | Name | Kind | Compound system |
|--------|------|------|------------------|
| **D1-A** | Verified lip-sync talking head (digital human) | STRONG claim | Talking head + real audio + verified lip-sync (one verified digital-human output) |
| **D1-B** | Verified local + hybrid generation (self-hosted model access) | MUST_PICK | Local + hybrid model access with verified model cards |
| **D-C** | Verified character/story continuity (multi-character) | MUST_PICK | Character continuity across episodes (multi-character) |
| **D1-D** | Verified production graph + auto-repair (pipeline robustness) | MUST_PICK | Durable production graph with auto-repair (crash recovery) |
| **D1-E** | Verified talking head WITHOUT lip-sync (distinct from verified lip-sync) | MUST_PICK | Talking head without lip-sync (distinct from verified lip-sync) |
| **D1-F** | Verified multi-user security (ArcReel single-admin only = background) | MUST_PICK | Multi-user security (multi-admin) |
| **D1-G** | Verified creative memory (personalization) | MUST_PICK | Creative memory + personalization |

### Constraints enforced per domain

- **D1-A:** Historical GPU blockers (RTX 3080 Xid 79/154, "engine unavailable") **must NOT be auto-passed as verified**.
- **D1-E:** "Talking head without lip-sync" **must remain distinct from "verified lip-sync"** (D1-A).
- **D1-F:** ArcReel's **single-admin only is background**, not HEVI's own proof.
- **Every domain:** the claim is **NOT** because of `FULL_ARCREEL_FEATURE_PARITY` / `115/115 PARITY` / `ALL_ARCREEL_GAPS_CLOSED`.

## The 39-Capability Differentiation Map

| Capability | Domain |
|------------|--------|
| unified-agent-production-harness (A) | D1-A |
| longform-narrative-production (B) | D1-A |
| canonical-narrative-state (C) | D-C |
| observer-state-extraction (D) | D-C |
| governed-context-composer (E) | D-C |
| long-term-creative-memory (F) | D1-G |
| narrative-forecast-branch-simulation (G) | D-C |
| continuity-and-multidimensional-audit (H) | D-C |
| governed-revision (I) | D-C |
| length-governance-normalization (J) | D-C |
| short-fiction-production (K) | D-C |
| script-runtime (L) | D-C |
| production-storyboard (M) | D-C |
| interactive-film (N) | D1-A / D1-E |
| persistent-interactive-play (O) | D1-A / D1-E |
| creative-research (P) | D1-G |
| material-library (Q) | D-C |
| existing-work-import-continuation (R) | D-C |
| fanfic-spinoff-canon-import (S) | D-C |
| style-intelligence (T) | D-C |
| synthetic-writing-quality (U) | D-C |
| extensible-genre-system (V) | D-C |
| market-radar (W) | D1-G |
| creative-analytics (X) | D1-G |
| translation-localization (Y) | D-C |
| cover-visual-asset-runtime (Z) | D-C |
| professional-skills (AA) | D1-F |
| creative-policy-packs (AB) | D1-F |
| review-workflow (AC) | D1-F |
| background-production-notifications (AD) | D1-F |
| run-snapshot-recovery (AE) | D1-D |
| atomic-creative-workspace (AF) | D1-D |
| backup-restore-rollback (AG) | D1-D |
| concurrency-and-locks (AH) | D1-D |
| targeted-editing (AI) | D1-B |
| model-provider-routing (AJ) | D1-B |
| notifications-webhooks (AK) | D1-F |
| creative-export (AL) | D-C |
| studio-product-surfaces (AM) | D1-A |

## Compound Systems

1. **D1-A compound** — talking head + real audio + verified lip-sync (members: unified-agent-production-harness, longform-narrative-production, interactive-film, persistent-interactive-play, studio-product-surfaces). **Distinct from D1-E** (talking head without lip-sync).
2. **D1-D compound** — durable production graph + auto-repair (crash recovery) (members: run-snapshot-recovery, atomic-creative-workspace, backup-restore-rollback, concurrency-and-locks).
3. **D-C compound** — character continuity across episodes (members: canonical-narrative-state, observer-state-extraction, governed-context-composer, narrative-forecast-branch-simulation, continuity-and-multidimensional-audit, governed-revision, existing-work-import-continuation, fanfic-spinoff-canon-import).
4. **D1-G compound** — creative memory + personalization (members: long-term-creative-memory, creative-research, market-radar, creative-analytics).
5. **D1-F compound** — multi-user security (multi-admin) (members: professional-skills, creative-policy-packs, review-workflow, background-production-notifications, notifications-webhooks).
6. **D1-B compound** — local + hybrid generation (model access) (members: model-provider-routing, run-snapshot-recovery, concurrency-and-locks, targeted-editing).

## Scored Hypotheses (H1–H6)

| ID | Claim | Score |
|----|-------|---------|
| **H1** | Verified talking head with lip-sync (D1-A) is a MUST pick differentiator | PASS |
| **H2** | Local + hybrid generation (D1-B) is a MUST pick differentiator | PASS |
| **H3** | Character/story continuity (D-C) is a MUST pick differentiator | PASS |
| **H4** | Production graph + auto-repair (D1-D) is a MUST pick differentiator | PASS |
| **H5** | Multi-user security (D1-F) is a MUST pick differentiator | PASS |
| **H6** | Creative memory/personalization (D1-G) is a MUST pick differentiator | PASS |

## TOP 5 Differentiators (ranked)

1. **D1-A** (verified lip-sync talking head) — the strongest compound claim
2. **D-C** (character/story continuity) — the most differentiated compound
3. **D1-D** (production graph + auto-repair) — the most robust compound
4. **D1-G** (creative memory/personalization) — the personalization compound
5. **D1-B** (local + hybrid generation) — the model-access compound

## TOP 3 Implementation Candidates (selected)

1. **D1-A** (verified lip-sync talking head) — the strongest compound claim
2. **D-C** (character/story continuity) — the most differentiated compound
3. **D1-D** (production graph + auto-repair) — the most robust compound

## Non-Claimable Capabilities (flagged)

- **unified-agent-production-harness (A)** — the agent harness itself is a parity substrate, not a MUST pick claim by itself.
- **studio-product-surfaces (AM)** — the Studio surface is a parity substrate, not a MUST pick claim by itself.
- **creative-export (AL)** — export is a parity substrate, not a MUST pick claim by itself.

These support **"HEVI can also do it"** (parity), not a **MUST pick** claim.

## Prohibitions Enforced

- **No new taxonomy created** — the 7 domains are differentiation domains, not a new taxonomy of ArcReel capabilities.
- **No second orchestrator** — D1-D is a durability claim, not a second orchestrator.
- **No unverified hardware moats** — D1-A GPU blockers are not auto-passed as verified.
- **No internal-complexity-as-user-value** — each domain is a user-facing compound claim.
- **No implementation** — no production code changes, no 39-capability ledger changes, no W1–W21 contract changes.

## Final Output Block

```
HEVI_DIFFERENTIATION_AUDIT_COMPLETE. CLASSIFICATION=HEVI_DIFFERENTIATION_AUDIT_V1.
PRODUCTION_CODE_CHANGED=NO. NEW_TAXONOMY_CREATED=NO. 3O_ARCHITECTURE_ZERO=PASS.
7/7 differentiation domains defined. 6/6 hypotheses scored.
TOP 5 differentiators ranked. TOP 3 implementation candidates selected.
Prohibitions enforced. NO implementation. NO new taxonomy.
NO second orchestrator. NO unverified hardware moats. NO internal-complexity-as-user-value.
```
