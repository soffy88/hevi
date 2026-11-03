# hevi.image.genart — seeded generative art

Zero-cost, offline, CPU-only generative art for hevi: abstract
stills (posters, cover beds, title backgrounds) and seamlessly
looping MP4s (intro/atmosphere beds, music visualisation).

## Algorithms

- **flowfield** — particles advected through a static multi-octave
  value-noise flow field; trails composited additively for the
  classic glow. Video loops are *exact*: the field is static,
  particle ages wrap on a lifetime that divides the frame count,
  and the brightness pulse is periodic with the loop, so frame F is
  byte-identical to frame 0.
- **julia** — escape-time Julia-set fractal coloured through the
  same palettes. For video, the constant `c` orbits a small circle
  with the loop period.

## Determinism

Everything derives from `numpy.random.default_rng(seed)` streams and
closed-form fields: same `(spec, seed)` → same pixels, every run.
Palettes: `ember`, `abyss`, `sakura`, `verdant`, or a custom list of
hex colours in the spec (`colors`).

## Use

```bash
python -m hevi.image.genart --algorithm flowfield --seed 7 \
    --palette abyss --mode video --seconds 10 --out flow.mp4
```

Or via the capability registry as `image.generative_art`
(see `hevi/capabilities/generative_art.py`).

## Provenance

The seeded-algorithmic-art approach follows Anthropic's
`algorithmic-art` skill (Apache-2.0; archived at
`~/workspace/references/algorithmic-art`, installed in the
Claude/Codex skill directories). This engine is an original
numpy/PIL implementation — no upstream p5.js code is used.
