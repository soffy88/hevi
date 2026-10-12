# Worked Example — The One Who Stayed (Grandmother & Cat)

> Original worked example by jnMetaCode (MIT). The 5-stage structure
> applied to **emotional narrative** — an elderly woman living alone, a
> stray cat, and the quiet years they keep each other company while her
> children are far away. Companion to
> [pet-lifetime-narrative.md](./pet-lifetime-narrative.md) and
> [family-recipe-farewell.md](./family-recipe-farewell.md).
>
> Concept: the ache is solitude (an empty-nest grandmother, a silent
> phone); the cat is the one who stays. Time marked by season + light +
> the photos on the wall; the warm grade never changes. Restrained
> ending (Rule 6) — the cat on the windowsill and the cardigan over the
> chair do the crying.
>
> 🎬 **Rendered example:** this story, condensed to 3 shots and rendered
> with [OpenShorts](https://github.com/jnMetaCode/openshorts) —
> [case page, prompts & what fell short](https://github.com/jnMetaCode/openshorts/tree/main/docs/cases/drama-grandma-cat) (zh).
>
> **[中文版 →](./elderly-cat-companion.zh.md)**

---

## The complete prompt (copy-paste ready)

### 1 · Core theme
`warm nostalgic family film | an empty-nest grandmother and the stray who stays | quiet companionship across seasons | gentle realism | no melodrama, no music-video gloss`

### 2 · Character & scene

**Grandmother (subject 1, throughout):** Reference uploaded photo.
Features / face / hair 100% preserved. No beautification. A small,
slightly stooped elderly woman; silver hair in a low bun, soft lined
face, kind tired eyes. Imperfections: a hand-knit cardigan with one
mended elbow, slow careful hands with prominent veins, a hearing aid,
reading glasses on a cord; she moves a little slower as the film goes on.

**Cat (subject 2, throughout):** A lean grey-and-white short-haired
stray, one ear notched at the tip, slightly matted fur that grows
glossier once cared for. Same cat throughout — wary newcomer → settled
companion → older, one eye clouding, sleeping more. A little limp in one
back leg from its stray days.

**Scene:** One modest old apartment and its small balcony / window onto a
courtyard, returned to across the years — same worn armchair, same enamel
feeding bowl by the door, same window onto the road. On the sideboard, a
phone propped upright and framed photos of grown children and
grandchildren far away. Outside the window the season changes; inside,
the lamplight stays warm.

### 3 · Atmosphere & quality
Shot on ARRICAM with Cooke S4 vintage primes, Kodak Vision3 250D 35mm
film stock. Warm low lamplight, low contrast, soft organic film grain,
dust motes in a shaft of window light. **Keep one warm filmic grade
across every shot** — mark time only through the season outside the
window, the photos on the wall, and the angle of the light, never by
changing the color tone.

### 4 · Camera rules
Edited across shots (multi-shot narrative). Mostly static or slow shot
sizes, eye-level with the woman and the cat; one or two slow push-ins on
faces; an insert on the silent propped-up phone and the feeding bowl.
Each cut lands on the same room so time reads clearly.
- *Breathing:* "Handheld shot. Throughout, maintain an extremely subtle,
  breath-like camera float to enhance presence."
- *Sound:* No score. Production audio only — a kettle, a clock ticking,
  rain on the courtyard, a soft purr, the scrape of the feeding bowl, a
  phone buzzing once on the sideboard and going quiet.

### 5 · Storyboard (7 shots)

```
Shot 1 — At the door (autumn dusk)
  Mid-wide of the small kitchen, warm low light, leaves blowing in the
  courtyard. Static. The grandmother eats alone at a table set for one.
  At the open door, a thin wary stray cat with a notched ear watches
  from the threshold. She notices; neither moves.

Shot 2 — Letting it in (winter)
  Low shot by the door, cold blue outside, warm lamp inside. Slow
  push-in. She sets down the enamel bowl; the cat eats fast, flinching,
  then stays. She lowers herself slowly into the armchair and watches it,
  the faint beginning of a smile.

Shot 3 — The silent phone (spring)
  Mid-shot on the sideboard, soft morning light. Static. The propped-up
  phone buzzes once and goes dark — a missed call, photos of grandchildren
  glowing on the screen. The grandmother, out of focus behind, talks
  quietly to the cat curled on the windowsill instead.

Shot 4 — Waiting together (summer)
  Wide through the window, bright high light, the empty road beyond the
  courtyard gate. Static. The grandmother and the cat sit at the window,
  both looking down the road. Nothing comes. She rests a veined hand on
  the cat's back; it leans into her.

Shot 5 — Slowing down (autumn again)
  Interior mid-shot, golden low afternoon light. Very slow push-in. The
  grandmother dozes in the armchair, cardigan over her knees; the older
  cat — grey muzzle, one clouded eye — curls warm in her lap. Both
  breathing slow. The clock ticks.

Shot 6 — The cardigan on the chair (winter)
  Wide of the room, cold light from the window, the armchair empty, the
  hand-knit cardigan folded over its back. Static. The cat sits alone on
  the windowsill, watching the road, the full enamel bowl untouched by
  the door. A knock, somewhere off.

Shot 7 — Someone at the gate (golden hour)
  Eye-level through the window, low golden light, hold long. No dialogue.
  No music. No flashback montage. A grown grandchild stands at the
  courtyard gate at last, looking up at the window. On the sill, the old
  cat slowly turns its head toward them — and the warm lamp is still on
  behind it.
```

### Negative prompt (Seedance / Kling — paste into the dedicated field)
```
blurry, low resolution, soft focus, watermark, text overlay, subtitles, logo, distorted face, asymmetric eyes, extra limbs, deformed paws, melting/morphing geometry, the cat changing color or markings between shots, the woman changing identity or face between shots, oversaturated colors, plastic skin, glossy CG render, video-game look, 3D cartoon, anime shading, flat even studio lighting, frame flicker, ghosting, jarring hard cuts, lifeless locked-off camera, sappy lens flare, on-screen heart symbols
```

---

## Why it's built this way

- **The silent phone carries the ache without a word.** One buzz, one
  missed call, grandchildren glowing on a screen no one picks up — the
  absence is shown, never explained. That restraint is the whole point.
- **The cat is the emotional throughline.** Wary → settled → old keeps it
  the *same* cat (notched ear, back-leg limp, greying muzzle are the
  consistency lock) and tracks the passing years on its own body.
- **Restrained ending (Rule 6).** The empty armchair, the folded
  cardigan, the full untouched bowl, the cat turning its head — no
  reunion melodrama, no score. The *cat keeping the warm spot* does the
  crying; whether the visit came too late is left for the viewer.

**Usage**: generate Shot 1 and Shot 7 first to lock the cat's look, the
woman's face, and the warm grade — then fill the middle. Pet + elderly
pieces fail most often by swapping in a different cat or relighting each
shot. Generate each shot 5–10s separately, stitch in post.

**Model**: Kling 2.x is steadiest on cats and slow human motion (use it
as the workhorse); Seedance is safe for this IP-free slice-of-life but
keep single shots ≤10s.
