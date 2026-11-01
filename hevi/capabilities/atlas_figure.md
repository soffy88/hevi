# physics.atlas_figure — interactive physics-figure scene specs

Clean-rewrite of the Atlas of Physics *method* (interactive 3D physics
textbook idiom) for hevi. No code, text, question or number is copied from
the reference work; the bundled reference figures use self-chosen
parameters, and every model formula is stated from the public physics law
it encodes.

## What it does

A declarative `PhysicsFigureSpec` (plain JSON) is verified fail-closed,
its invariant checks are executed by independent recomputation, and
`generate_scene()` emits a deterministic Three.js scene JSON. The
capability produces **no pixels**: rendering, scroll driving, picking and
label overlay are the host player's job (see pending items below).

## Spec fields

| Field | Meaning |
|---|---|
| `id`, `title`, `language` | Figure identity; `language` is `zh` or `en`. |
| `provenance` | `{source, license}` labels. hevi capabilities had no prior provenance convention; this module defines this minimal label and requires it. |
| `model.parameters[]` | `{name, value, unit}` — SI quantities, the only free numbers. |
| `model.derived[]` | `{name, formula, value, unit}` — `value` must equal the formula recomputed from parameters/earlier derived (tolerance 1e-9). |
| `model.functions[]` | `{name, expression, variables, unit}` — pure functions of `t` (default) over parameters/derived. Expressions run through a whitelisted AST evaluator (numbers, parameter names, `+ - * / ** %`, unary minus, `sqrt sin cos tan asin acos atan atan2 hypot exp log log10 abs min max`, `pi`, `e`). No `eval`/`exec`, no attributes, no subscripts, no lambdas. |
| `model.caveat` | Non-empty statement of assumptions (min 10 chars): what is ignored, where the analogy stops. |
| `scene.assemblies[]` | `{id, title, sub}` — picking/lighting/explode units. Every part belongs to one assembly. |
| `scene.parts[]` | `{id, kind, assembly, position, rotation?, explode?, material, label?}`. Kinds: `paper_solid` (`shape` box/cylinder/sphere/cone + positive `dims`), `arrow` (`vector: {tail, components[3 expressions], sample_t}`), `axis` (`direction, length, ticks`), `graph` (`function` ref, `t_range`, `samples`), `strobe` (`function_x/y/z?`, `times[]`), `polyline` (`points[]`). Material: `{palette, tone, opacity}` — palettes `paper/base/dark/ink/red/blue/board` (each a top/light/dark triple), tones `faint/lo/mid/hi/lit` (line/shade weights). |
| `breakdowns[]` | `{id, target, kind, title, text, facts[]}` — click-to-break-down. Kinds: `vector_components` (target needs an arrow), `graph_slope_area` (target needs a graph), `explode` (target needs a non-zero explode vector), `assembly`. Facts reference parameters/derived by name; values resolve at generation. |
| `cameras[]` | `{page, title?, target[3], az, el, dist, focus_assembly?}` — one per page: pages strictly increasing from 0 with no gaps, `az` in [-180, 180], `el` in [-4, 85], `dist` > 0. The host interpolates between page cameras as the reader scrolls. |
| `checks[]` | At least 2. Each `{id, quantity, tolerance, path_a, path_b, compare?}` computes the same quantity two ways; `path_a.method` must differ from `path_b.method`, and at least one check must use an independent method. Methods: `sample` (evaluate at `t`/`t_expr`), `closed_form` (evaluate once), `integrate` (Simpson over `from`/`to`, optional `offset`), `finite_diff` (central difference at `t`/`t_expr` with `h`), `root` (bisection for the `t` where expression equals `target`, optional `scale`). Bounds/`scale`/`offset` accept numbers or `{"expr": ...}`. `compare: "abs"` compares magnitudes. |

## Verification gate

`verify_figure_spec()` lists every failure; nothing passes by default:
schema completeness, model closure (every referenced quantity declared),
derived self-consistency, breakdown reference closure + kind compatibility,
camera sequence monotonicity and ranges, check count/method discipline,
caveat presence, provenance labels. `generate_scene()` refuses to emit
when verification fails or any check fails.

## Output scene JSON

`{schema_version, id, title, language, provenance, model, assemblies,
parts[], cameras[], breakdowns[], checks, meta}`. Parts resolve materials
to tone triples + weights; arrows resolve sampled components; graphs carry
sampled points plus slope-at-midpoint and area-under-curve (both recomputed
from the model function); strobes carry sampled positions; breakdown facts
carry resolved values. `scene_to_json()` serializes with sorted keys, so
the same spec always yields byte-identical JSON.

## Division of labour with blender_mcp

| | `hevi.creative.layer4.blender_workflow` | `physics.atlas_figure` |
|---|---|---|
| Output | Deterministic bpy script + Blender render + ffmpeg assembly | Deterministic Three.js scene JSON (spec only) |
| Strength | Offline precision rendering, cinematic shots | Interactive Web 3D: hover/pick/breakdown, scroll cameras |
| Cost | Blender binary + GPU/CPU render time | ~0 (pure Python spec generation) |
| When | Final video frames | Interactive lessons, previews, explainers |

Neither replaces the other: a figure spec can drive a Web preview first
and hand its verified model to the Blender line for final frames.

## Pending (host side, not this capability)

1. Three.js host player: paper-shading material + normal/depth ink-edge
   pass, assembly hover-light, picking (raycast + padded-outline fallback),
   explode springs, camera by target/az/el/dist.
2. Scroll driver: page-turn + camera interpolation, deep links
   (`figure#page`), keyboard paging, reduced-motion support.
3. Label overlay anchored to 3D points; breakdown plate with facts table.
4. Practice-question layer per page (answers recomputed by the same
   check discipline, not stored strings).
