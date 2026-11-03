# hevi.image.brushpaint — procedural brush-stroke painting engine

A zero-cost, offline, CPU-only image route for hevi. A scene is a JSON
spec of layered *field primitives*; the engine samples the fields on a
seeded jittered grid and turns the answers into a few thousand short
brush strokes. It renders:

- a **still PNG** at any reveal progress (`progress=1` is the finished
  painting), and
- a **paint MP4**: the picture painting itself stroke by stroke, with a
  hold tail where swirl/water strokes keep swaying.

Deterministic: same spec + same seed → identical strokes and bytes.

## Scene spec (LLM-fillable)

```json
{
  "name": "my_scene",
  "seed": 7,
  "step": 14,
  "background": "#0d1730",
  "layers": [
    {"type": "swirl_sky", "palette": ["#131f42", "#2d4a7a"], "horizon": 0.64,
     "vortices": [{"x": 0.4, "y": 0.27, "r": 0.21, "s": 1.7}]},
    {"type": "moon", "x": 0.78, "y": 0.15, "r": 0.068},
    {"type": "water", "from": 0.68, "palette": ["#1d3d5c", "#101f38"],
     "reflect_x": 0.78}
  ]
}
```

Layers paint back-to-front (later layers win overlaps) and reveal in
layer order unless a layer pins `"order": [lo, hi]`.

Layer types and their key parameters (colours are `#rrggbb` lists):

| type | paints | key params |
|---|---|---|
| `swirl_sky` | flowing sky bent by vortices | `palette`, `horizon`, `vortices:[{x,y,r,s}]`, `base_flow`, `wave`, `sway` |
| `moon` | ring-field disc + halo (moon or sun) | `x`, `y`, `r`, `palette`, `halo_palette` |
| `stars` | small ring-field stars | `count`+`region` or `points:[{x,y,r}]`, `seed` |
| `hills` | rolling silhouette band | `base`, `amp`, `freq`, `phase`, `palette` |
| `water` | horizontal water + light column | `from`, `palette`, `reflect_x`, `reflect_width`, `glitter_palette` |
| `cypress` | flame-shaped dark tree | `x`, `base`, `height`, `width`, `bend`, `palette` |
| `tree` | round canopy + trunk | `x`, `base`, `canopy_r`, `canopy_h`, `palette` |
| `house` | walls + pitched roof + lit windows | `x`, `base`, `w`, `h`, `roof_h`, `wall_palette`, `roof_palette` |
| `meadow` | foreground grass + flowers | `from`, `palette`, `flower_density`, `flower_palette` |
| `clouds` | soft horizontal blobs | `palette`, `blobs:[{x,y,rx,ry}]` |

Bundled templates (also in `examples/`): `pond_night`, `meadow_dawn`,
`river_dusk`, `village_night`.

## Use

```bash
python -m hevi.image.brushpaint templates
python -m hevi.image.brushpaint still --template pond_night -o pond.png
python -m hevi.image.brushpaint paint --scene scene.json -o paint.mp4 --seconds 24
```

Capability: `image.brush_scene` (import `hevi.capabilities.brushpaint`
to register). Storyfilm route: `run_story_film(..., image_provider="brush")`
or one-click `--preset brush` — each beat's text is keyword-routed to a
template and painted at $0 instead of a GPT image call.

## Honest limits

Stylised storybook landscapes and backgrounds only: no characters, no
text, no photorealism, compositions come from the primitive vocabulary
above. For character shots or realistic scenes use the GPT/rig routes.
