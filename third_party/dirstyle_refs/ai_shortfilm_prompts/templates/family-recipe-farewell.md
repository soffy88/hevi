# Worked Example — A Mother's Recipe, Handed Down

> Original worked example by jnMetaCode (MIT). The 5-stage structure
> applied to **family emotional narrative** — a mother, a child, and one
> handwritten recipe card across a lifetime. Companion to
> [pet-lifetime-narrative.md](./pet-lifetime-narrative.md); pairs the
> Romance/family block of [genre-camera-sop.md](./genre-camera-sop.md)
> with the [multi-shot-narrative.md](./multi-shot-narrative.md) skeleton.
>
> Concept: one dish, one kitchen, one recipe card — taught, learned, and
> handed down. Time marked by season + light + the card aging; the warm
> grade never changes. Restrained ending (Rule 6) — the empty chair and
> the stained card do the crying, not a flashback montage.
>
> **[中文版 →](./family-recipe-farewell.zh.md)**

---

## The complete prompt (copy-paste ready)

### 1 · Core theme
`warm nostalgic family film | a recipe handed down across a lifetime | time-lapse across seasons | gentle realism | no melodrama, no music-video gloss`

### 2 · Character & scene

**Mother (subject 1, throughout):** Reference uploaded photo. Features /
face / hair 100% preserved. No beautification. The same woman ages
naturally — black hair to grey, smooth hands to lined and slow. Same
warm eyes, same way of tucking hair behind one ear. Imperfections: flour
dusted on her hands and forearms, a small old burn scar on the inner
wrist, a faded apron with one scorched corner, reading glasses later that
slip down her nose, hands that tremble faintly by the end.

**Child (subject 2, throughout):** The same person from a small child on
a wooden stool to a grown adult — same eyes, same cowlick, a chip in the
same front tooth. As a kid: too short to see the counter, standing on the
stool. As an adult: the *same gesture* as the mother — the same way of
tasting from the spoon, the same hair-tuck. Imperfections: a flour
handprint on the cheek as a kid, a small kitchen-knife nick on a finger
later.

**Scene:** One modest home kitchen, returned to across the years — same
worn wooden counter, same chipped enamel pot, same window above the sink.
One handwritten recipe card on the wall, ageing through the film: crisp
and white at first, then grease-spotted, creased, the ink fading, a
corner torn and taped. Outside the window the season changes; inside, the
light over the stove stays warm.

### 3 · Atmosphere & quality
Shot on ARRICAM with Cooke S4 vintage primes, Kodak Vision3 250D 35mm
film stock. Warm golden kitchen light, low contrast, soft organic film
grain, gentle steam haze in the air. **Keep one warm filmic grade across
every shot** — mark time only through the season outside the window, the
ageing of the recipe card, and the softness of the light, never by
changing the color tone.

### 4 · Camera rules
Edited across shots (multi-shot narrative). Mostly static or slow shot
sizes, eye-level at the counter; a few slow push-ins on hands and faces;
inserts on the recipe card and the pot. Each cut lands on the same
kitchen so time reads clearly.
- *Breathing:* "Handheld shot. Throughout, maintain an extremely subtle,
  breath-like camera float to enhance presence."
- *Sound:* No score. Production audio only — oil sizzling, a wooden
  spoon against enamel, a child's stool scraping, the tap running, a lid
  settling, slower breathing near the end.

### 5 · Storyboard (7 shots, one lifetime)

```
Shot 1 — Too short to see (winter, morning)
  Low eye-level mid-wide in the kitchen, warm stove light, frost on the
  window. Static. A small child stands on a wooden stool, flour
  handprint on one cheek, watching the mother's hands work the dough.
  The recipe card on the wall is crisp and new.

Shot 2 — Learning (spring)
  Mid-shot at the counter, soft morning light. Slow handheld follow. The
  mother — younger, black hair — guides the child's hands around the
  spoon, both reaching into the same chipped pot. The child tastes,
  scrunches their face; the mother laughs.

Shot 3 — On their own (summer)
  Mid-wide, bright high window light. Static. A teenager now cooks the
  dish alone, brow furrowed, checking the recipe card — its first
  grease spots showing. The mother sits at the table behind, not
  helping, just watching, hands folded.

Shot 4 — Side by side (autumn)
  Two-shot at the counter, golden low afternoon light, leaves outside.
  Very slow push-in. The grown child and the greying mother cook
  together, easy and wordless, shoulders almost touching. The mother's
  hand rests a moment on the child's back.

Shot 5 — Hands that shake (winter rain)
  Close on hands at the counter, warm lamp, cold rain on glass. Static,
  breath-float. The mother's hands tremble now, reading glasses low on
  her nose; the adult child gently takes the spoon from her and finishes
  the stir. The mother watches the pot, then her child's face.

Shot 6 — The empty chair (spring again)
  Wide of the kitchen, soft morning light, the chair at the table empty.
  Static. The adult cooks the dish alone; the recipe card is creased,
  ink faded, one corner taped. They glance at the empty chair once, then
  keep stirring. Steam rises in the warm light.

Shot 7 — Handed down (golden hour)
  Low eye-level, the same counter, low golden light. Static,
  breath-float, hold long. No dialogue. No music. No flashback montage.
  The adult — now the parent — guides a small child's hands around the
  same spoon, into the same chipped pot, the same hair-tuck. Behind
  them, the old stained recipe card is propped up where it can be seen.
```

### Negative prompt (Seedance / Kling — paste into the dedicated field)
```
blurry, low resolution, soft focus, watermark, text overlay, subtitles, logo, distorted face, asymmetric eyes, extra fingers, deformed hands, melting/morphing geometry, the person changing identity or face between shots, the recipe card changing layout between shots, oversaturated colors, plastic skin, glossy CG render, video-game look, 3D cartoon, anime shading, flat even studio lighting, frame flicker, ghosting, jarring hard cuts, lifeless locked-off camera, sappy lens flare, on-screen heart symbols
```

---

## Why it's built this way

- **One object carries the whole arc.** The recipe card ages shot by
  shot (crisp → grease-spotted → creased → taped) — it's the clock and
  the heart at once, so you never need a "5 years later" title card.
- **The handed-down gesture is the consistency lock.** The same
  hair-tuck, the same taste-from-the-spoon, the same chipped pot — these
  keep it the *same* people across decades AND deliver the ending: the
  child becomes the mother. Lock these gestures in Shot 1 and Shot 7
  first.
- **Restrained ending (Rule 6).** Empty chair + stained card + the next
  small pair of hands. No flashback, no score, no slow-zoom on tears. The
  *empty chair* and the *repeated gesture* do the crying.

**Usage**: generate Shot 1 and Shot 7 first to lock both faces, the
kitchen, and the warm grade — then fill the middle. Family pieces fail
most often by drifting the mother's face or relighting each shot.
Generate each shot 5–10s separately, stitch in post.

**Model**: Kling 2.x is steadiest on faces and slow human motion (use it
as the workhorse); Seedance is safe for this IP-free slice-of-life but
keep single shots ≤10s. For the recipe-card inserts, lock the framing
with a first/last frame if your model supports it.
