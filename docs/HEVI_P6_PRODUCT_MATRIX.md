# HEVI P6 — Ten-Product Matrix

One compiler, one runtime, ten products. Artefacts:
`artifacts/qualification/p6_7/<product>.json` plus `_index.json`.

## Capability requirements (data, not routing)

| product | required | optional |
|---|---|---|
| P01_AVATAR_EXPLAINER | PRESENTER, NARRATOR | BRAND, DOCUMENT |
| P02 / P03_HISTORICAL_REENACTMENT | CHARACTER, WORLD | EVIDENCE, NARRATOR |
| P03_DOCUMENTARY | EVIDENCE | NARRATOR, DOCUMENT |
| P04_CHARACTER_DOCUMENTARY | CHARACTER, EVIDENCE | WORLD |
| P05_DOCUMENTARY | EVIDENCE | NARRATOR, DOCUMENT |
| P06_NARRATIVE_STORY_FILM | CHARACTER, WORLD | EVIDENCE, ASSET |
| P07_CINEMATIC_KNOWLEDGE | MOTION, EVIDENCE | NARRATOR, DOCUMENT |
| P08_COMMERCIAL | — | BRAND, PRESENTER |
| P09_TUTORIAL | INSTRUCTION | PRESENTER, DOCUMENT |
| P10_SHORT_FORM | ASSET | BRAND, PRESENTER |

`required` can block a run; `optional` never can. Conflating them is how a
"may require" quietly becomes a hard gate, so they are separate sets and a test
asserts optional capabilities never block.

## Structural proof: product ≠ pipeline

| pair | shared | divergence |
|---|---|---|
| P01 / P04 | narrative, presenter, style, visual grammar, recipe | identity only |
| P03 / P05 | narrative, presenter, style, visual grammar, recipe | identity only |
| P02 / P10 | narrative, style, visual grammar, recipe | identity only |

At least two pairs are byte-identical outside `product_profile_id`, asserted by
comparing the hashed compiled layers rather than by inspection.

## Ten products, seven grammar shapes

The reduction from 10 products to fewer shapes is the load-bearing number: it is
what makes "one product is not one pipeline" measurable rather than rhetorical.

## Honest status per product

Every artefact records:

```json
"provider": {
  "credentials_present": [],
  "gpu_available": false,
  "real_render_qualification": "BLOCKED_BY_PROVIDER",
  "mock_used": false,
  "reason": "no provider credentials configured and CUDA reports no device"
}
```

Compile → validate → bind → delegate completed for all ten. Rendered production did
not, and no artefact claims otherwise.
