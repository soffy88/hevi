# HEVI P6.5.2 — Grammar Compatibility Repair

> Closes the **G-14** structural blocker. With P6.5.1, this unblocks P6.6.

---

## 1. What was wrong

P6.3/P6.4 shipped vocabularies whose coherence intersection was a **perfect
diagonal**:

|  | documentary_realism | dramatic_reconstruction | educational_clarity | commercial_clean |
|---|---|---|---|---|
| `documentary_realism` | Y | . | . | . |
| `archival_history` | . | . | . | . |
| `educational_clarity` | . | . | Y | . |
| `cinematic_drama` | . | Y | . | . |
| `future_tech` | . | . | . | . |
| `corporate_clean` | . | . | . | . |

**3 of 24.** Four shipped artefacts were dead: `archival_history`, `future_tech`,
`corporate_clean` and P6.4's `commercial_clean` — the grammar meant for exactly
the commercial work P6.5 exists to do.

## 2. Why it happened

The old rule was **equality across three shared channels at once**. The channels
are correlated across the two phases — each style's `(motion, lighting)` pair maps
to exactly one grammar — so demanding agreement on two of them reproduces the
diagonal no matter how the rules are worded. I tried hard-gating both motion and
lighting and measured **0/24**, worse than before.

## 3. The constraint model

`hevi/production/p6/compatibility_policy.py`. Single-channel rules with an
explicit severity:

| kind | meaning | severity |
|---|---|---|
| `AGREE` | the two layers must declare the same value on this channel | blocking |
| `EXCLUDE` | value-specific: this value cannot pair with any other | blocking |
| `FLEX` | values may differ; the intent is marked flexible | advisory |
| `UNSET` | the channel does not constrain — declared explicitly | — |

**Only motion gates hard.** It is the one channel where disagreement is a
contradiction rather than extra work: `MotionLanguage` means the same thing in
both layers, so a restrained look under an energetic strategy is two different
intentions, not one stated twice.

Lighting and composition are *work*, not incoherence — a natural-light look can be
lit for, a documentary frame can carry a performer-centred shot. Those are
advisory. The single absolute exclusion is `infographic`, where the two framing
logics have no common room.

## 4. Result

| | before | after |
|---|---|---|
| coherent pairs | 3/24 | **6/24** |
| dead styles | 3 | **0** |
| dead grammars | 1 | **0** |

New matrix:

|  | documentary_realism | dramatic_reconstruction | educational_clarity | commercial_clean |
|---|---|---|---|---|
| `documentary_realism` | ALLOW | DENY | DENY | DENY |
| `archival_history` | DENY | ALLOW* | DENY | DENY |
| `educational_clarity` | DENY | DENY | ALLOW | DENY |
| `cinematic_drama` | DENY | ALLOW | DENY | DENY |
| `future_tech` | DENY | DENY | DENY | ALLOW* |
| `corporate_clean` | ALLOW* | DENY | DENY | DENY |

`*` = flexible (advisory). The three G-14 dead zones are back, verified
end-to-end against the real recipe corpus:

| pairing | recipe retrieved |
|---|---|
| `future_tech` + `commercial_clean` | `EMOTIONAL.SOLITUDE_HOLD` |
| `archival_history` + `dramatic_reconstruction` | `CAMERA.COMBINED_MOVEMENT` |
| `corporate_clean` + `documentary_realism` | compiles; refused later by the narrative table, a separate valid gate |

## 5. Constraints, not a whitelist

A whitelist is a pair list: 24 entries today, and every new style or grammar means
auditing it against every other. It also encodes no *reason*. A constraint says
why and composes — adding a fifth composition value cannot silently invalidate
rules about lighting, because no rule mentions lighting.

Tests enforce this structurally: no rule key may name an artefact or a product,
and no dict literal anywhere in the module may be keyed by an artefact id.

## 6. Two bugs found by writing the tests

**Advisory blocked.** The first wiring appended advisory messages to `errors`,
which made "flexible" refuse the pair — silently defeating the entire model.
Advisories are now carried on `VisualIntent.flexible_channels` and never raised.

**The exclusion guard never fired.** `add()` checked `self._rules` for a clash key,
but `_rules` is keyed by rule key, so the key could never match. Exclusions are
now tracked in a dedicated set.

And one inherited defect: `AGREE` rules that pinned a value reported **N**
conflicts per mismatched pair instead of 1. `AGREE` now refuses to pin a value at
all, and a test pins that refusal.

## 7. Deliberately invented

Two vocabularies, both required by grammars that P6.4 already ships and neither
of which existed in P6.3: `EditingLanguage` and `CameraLanguage`. They live in
P6.4's module because camera/editing are its own contribution. **No other new
visual vocabulary** — a test asserts every value any rule can express already
exists in a P6.3 or P6.4 enum.

## 8. Gate

```
COMPATIBILITY_MODEL=PASS        pair matrix computed from rules, not stored
NO_PRODUCT_BRANCHING=PASS       60 tests, incl. injected-branch mutation
NO_GRAMMAR_DEAD_ZONE=PASS       0 dead styles, 0 dead grammars
REGRESSION=PASS                 P0-P5 and P6.0-P6.5.1 unchanged
```

**P6.6 is unblocked, with one caveat carried forward:** G-13's 0.30 semantic term
still needs the one-line P5.3 change. P6.6 should not ship to production without
it.
