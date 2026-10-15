# Multi-Shot Project Planner — Lock Consistency Before You Generate Shot 1

> Original worksheet by jnMetaCode (MIT). Multi-shot pieces fail most
> often not because any single shot looks bad, but because the *subject
> quietly changes* across shots — a different scar, a swapped Portrait
> number, a motion direction that doesn't rhyme with the previous cut.
> Those failure modes are already named in
> [multi-shot-narrative.md](./multi-shot-narrative.md)'s Debugging tips
> and in the Skill's emotional-narrative rules — this file turns them
> into a worksheet you actually fill in, instead of a tip you remember
> too late.
>
> **How to use**: copy this file (or just the tables) into your project
> notes. Fill it out **before** writing your first shot prompt. Re-check
> it before every new shot — not just once at the start.
>
> **[中文版 →](./project-planner.zh.md)**

---

## 0 · Is this worksheet for you?

Skip it for single-shot pieces (15s-transformation, atmosphere-only
pieces) — nothing to keep consistent across shots. Use it for anything
edited from **3+ shots**: multi-shot narrative, emotional/pet/family
pieces, movie trailers, micro-drama, MVs.

---

## 1 · Subject registry (fill before Shot 1)

One row per subject that appears in more than one shot. This *is* the
consistency lock — every shot's Character & Scene section must restate
these exact details, not a rephrased approximation.

| Portrait # | Role | Face / features (100% preserved wording) | Clothing / props (material-first) | ≥2 imperfection anchors (must recur every shot) |
|---|---|---|---|---|
| Portrait1 | e.g. protagonist | | | |
| Portrait2 | e.g. companion / animal | | | |
| Portrait3 | e.g. scene reference | | | |

**Rule**: Portrait numbering is fixed for the whole project. Portrait1
is always the same role in every shot's prompt — never renumber or
swap mid-project (see `multi-shot-narrative.md` Debugging tip #4).

**Tip**: generate the **first and last shot first** to lock the look
before filling the middle (this is how `pet-lifetime-narrative.md` and
`family-recipe-farewell.md` were built) — it's cheaper to notice a
drifted face on shot 1-of-2 than on shot 5-of-7.

---

## 2 · Atmosphere lock (must stay identical across every shot)

Fill this once. Paste the same wording into every shot's Stage 3 —
don't rephrase it shot-to-shot; that's the #1 cause of color-drift in
edited pieces.

```
Core theme tags: {{3–6 tags, | separated}}
Camera + lens combo: {{e.g. Sony Venice + Canon K-35 / IMAX + Panavision C-series}}
Color & tone: {{one locked description — write it once, copy verbatim}}
Grain / style core: {{}}
```

**Rule**: if you find yourself writing a *slightly* different color
line for shot 4 than shot 1, stop — that's exactly what breaks a
multi-shot edit in post. Go back and paste the Section-2 wording
verbatim.

---

## 3 · Shot list (fill as you plan, check as you generate)

The **Exit** and next row's **Entry** columns must agree — motion
reads as one continuous action across the cut only when they rhyme
(`multi-shot-narrative.md` Debugging tip #2).

| Shot # | Shot size / composition | Camera move | Content (subject does X → Y happens) | Exit direction / state | Next shot's Entry (must match) |
|---|---|---|---|---|---|
| 1 | | | | e.g. exits frame-right | — |
| 2 | | | | | must enter frame-right ✓/✗ |
| 3 | | | | | |
| … | | | | | |

**Rule of thumb**: 3–8 shots per edited piece; each shot generated
independently at 5–10s, stitched in post (don't attempt one 30s+
generation — reroll success collapses past ~15s, see `cheatsheet.md`).

---

## 4 · Pre-flight checklist (before generating Shot 1)

- [ ] Every subject that recurs has a Section-1 row with ≥2 imperfection anchors
- [ ] Section-2 atmosphere wording is finalized — you will copy-paste it, not rewrite it, into every shot
- [ ] Shot list drafted with exit/entry directions checked for rhyme
- [ ] You've budgeted rerolls realistically — see "Reroll & budget expectations" in [cheatsheet.md](../cheatsheet.md) (roughly 5–10× your final shot count in generations, industry-reported)
- [ ] You know which shot you're generating **first** to lock the look (usually shot 1, sometimes shot 1 + last shot together)

Less than full pass = you'll likely hit consistency drift by shot 3–4.
Fill the gaps first.

---

## See also

- [multi-shot-narrative.md](./multi-shot-narrative.md) — the shot skeleton + vocabulary this worksheet feeds into
- [genre-camera-sop.md](./genre-camera-sop.md) — camera-move phrasing by genre, once your shot list is drafted
- [cases.md](../cases.md) §3 "Motion & timing" — fixes if you're already mid-project and drift has happened
