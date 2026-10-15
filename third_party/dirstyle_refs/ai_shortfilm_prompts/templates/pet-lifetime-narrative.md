# Worked Example — Pet × Family, A Lifetime of Companionship

> Original worked example by jnMetaCode (MIT). Demonstrates the 5-stage
> structure applied to **emotional narrative** (not action/transformation)
> — proving the method carries across genres. Pairs the Romance block of
> [genre-camera-sop.md](./genre-camera-sop.md) with the
> [multi-shot-narrative.md](./multi-shot-narrative.md) skeleton.
>
> Concept: one dog, from clumsy puppy to old age, across a person's
> whole life. Single subject throughout; time marked by season + light,
> never by changing the color grade. Restrained ending (Rule 6).
>
> **[中文版 →](./pet-lifetime-narrative.zh.md)**

---

## The complete prompt (copy-paste ready)

### 1 · Core theme
`warm nostalgic family film | a lifetime of companionship | time-lapse across seasons | gentle realism | no melodrama, no music-video gloss`

### 2 · Character & scene

**Person (subject 1, throughout):** Reference uploaded photo.
Features / face / hair 100% preserved across all shots. No
beautification. Same person ages naturally from a small child to an
adult — same eyes, same smile, same mole. Imperfections: scraped knees
as a kid, a faded scar on the hand later, faint tired lines by the end.

**Dog (subject 2, throughout):** A medium yellow short-haired mongrel,
one ear that folds at the tip. Same dog throughout — clumsy puppy →
strong adult → aged, muzzle and eyebrows turning grey, eyes clouding,
gait slowing. Worn red collar, scratched buckle, frayed webbing; a
little mud always on the paws.

**Scene:** One modest family home and its small yard, returned to across
the years — same wooden doorstep (paint wearing thinner each season),
same worn rug, same window. Outside the window the season changes;
inside, the light stays warm.

### 3 · Atmosphere & quality
Shot on ARRICAM with Cooke S4 vintage primes, Kodak Vision3 250D 35mm
film stock. Warm golden natural light, low contrast, soft organic film
grain. **Keep one warm filmic grade across every shot** — mark time only
through the season outside the window and the angle/softness of light,
never by changing the color tone.

### 4 · Camera rules
Edited across shots (multi-shot narrative). Mostly static or slow shot
sizes, eye-level with dog and person; one or two slow push-ins on faces.
Each cut lands on the same spot in the home so time reads clearly.
- *Breathing:* "Handheld shot. Throughout, maintain an extremely subtle,
  breath-like camera float to enhance presence."
- *Sound:* No score. Production audio only — puppy yelps, rain on the
  window, an old dog's slow breathing, a leash clip, wind in the yard.

### 5 · Storyboard (7 shots, one lifetime)

```
Shot 1 — First day (early spring)
  Low eye-level wide. Static. A cardboard box on the worn doorstep,
  soft morning light from the left. A small child crouches; a clumsy
  puppy with the folded ear tumbles out and licks the child's scraped
  knee. Both unsteady, both new.

Shot 2 — Growing up (summer)
  Mid-wide in the yard, bright high sun, dappled shade. Slow handheld
  follow. The child, taller now, runs; the young dog bounds alongside,
  mud on paws, red collar bright and new. They crash into the grass,
  laughing and barking.

Shot 3 — Waiting (autumn)
  Wide through the front window, golden low afternoon light, leaves
  outside. Static. The adult dog lies on the doorstep, head on paws,
  watching the empty road. The person — a teenager now — appears at the
  far end; the dog's tail thumps once, twice, then it scrambles up.

Shot 4 — The long night (winter rain)
  Interior mid-shot, warm lamp inside, cold rain on glass. Very slow
  push-in. The young adult sits on the floor, head down, tired. The dog
  rests its greying muzzle on their knee, unmoving. The person's hand
  finds the worn collar.

Shot 5 — Slowing down (spring again)
  Low close on paws and feet on the same doorstep, soft morning light.
  Static, breath-float. The old dog rises slowly, hind legs stiff, grey
  eyebrows, clouded eyes. The person's hand — a faded scar across it now
  — slides under to help it up. They walk out together, slowly, the same
  way they always have.

Shot 6 — The empty spot (summer dusk)
  Wide, the doorstep, warm dusk light raking low. Static. The doorstep
  is empty. The worn red collar lies on the wood where the dog used to
  lie. The person sits beside it, doesn't pick it up, just rests a hand
  near it. A warm breeze moves the leaves.

Shot 7 — Closing (golden hour)
  Eye-level wide, the yard, low golden light. Static, breath-float, hold
  long. No dialogue. No music. No flashback montage. Just the person at
  the yard gate in warm light, looking down the road for a moment — and
  a single yellow leaf drifting down to rest on the empty doorstep
  behind them.
```

### Negative prompt (Seedance / Kling — paste into the dedicated field)
```
blurry, low resolution, soft focus, watermark, text overlay, subtitles, logo, distorted face, asymmetric eyes, extra limbs, deformed paws, melting/morphing geometry, the dog changing breed or color between shots, oversaturated colors, plastic skin, glossy CG render, video-game look, 3D cartoon, anime shading, flat even studio lighting, frame flicker, ghosting, jarring hard cuts, lifeless locked-off camera, sappy lens flare, on-screen heart symbols
```

---

## Why it's built this way

- **Time marked by season + light, grade locked warm.** Emotional pieces
  break when every shot wears a different filter. Inverting it — "season
  changes outside, light stays warm inside" — carries time without
  wrecking the multi-shot edit.
- **Restrained ending (Rule 6).** Empty doorstep + faded collar + one
  falling leaf. No flashback, no score, no slow-zoom on tears. The
  *empty spot* does the crying.
- **Two imperfection anchors per subject** (dog: worn collar / grey
  muzzle / muddy paws; person: scraped knee → scar → tired lines) — these
  double as the consistency lock that keeps it the *same* dog and person.

**Usage**: generate Shot 1 and Shot 7 first to lock the dog's look and
the warm grade, then fill the middle — pet pieces fail most often by
swapping in a different dog mid-sequence. Generate each shot 5–10s
separately, stitch in post.

**Model**: Kling 2.x is steadiest on pets and emotional motion (use it as
the workhorse); Seedance is safe for this IP-free slice-of-life but keep
single shots ≤10s.
