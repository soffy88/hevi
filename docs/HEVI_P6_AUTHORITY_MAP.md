# HEVI P6 — Authority Map

One owner per concern. No duplicate authority exists.

| concern | owner | module | P6.6/P6.7/P6.8 role |
|---|---|---|---|
| Product profile (canonical, `id@version`, embedded grammars) | P6.0 | `hevi.production.p6.registry` | untouched |
| Product profile (commercial catalogue, `id`, grammar references) | P6.5 | `hevi.production.p6.product_profiles` | consumed |
| Product type vocabulary | P6.0 | `hevi.production.p6.schema.ProductType` | consumed |
| Narrative grammar | P6.1 | `hevi.production.p6.narrative.registry` | compiled |
| Presenter grammar | P6.2 | `hevi.production.p6.presenter_registry` | compiled |
| Visual style | P6.3 | `hevi.production.p6.visual_style.registry` | compiled |
| Style / grammar compatibility | P6.5.2 | `hevi.production.p6.compatibility_policy` | consulted |
| Visual grammar (camera, editing) | P6.4 | `hevi.production.p6.visual_grammar` | compiled |
| Product compilation | P6.5 | `hevi.production.p6.product_compiler` | the single compiler |
| Shared semantic vocabulary | P6.5.1 | `hevi.production.semantic_contract` | supplies `semantic_id` |
| **Semantic scoring** | **P5.3** | `hevi.production.p5_3.retrieval` | untouched by P6 |
| **Recipe selection / ranking** | **P5.3** | `hevi.production.p5_3.library.rank_candidates` | untouched by P6 |
| Capability requirements | P6.6 | `hevi.production.p6.production_runtime` | validated |
| Runtime boundary (port) | P6.0 | `hevi.production.p6.runtime` | completed, not replaced |
| Runtime boundary (adapter) | P6.6 | `hevi.production.p6.production_runtime` | delegates only |
| **ShotPlan** | **P0** | `hevi.production.p0_pipeline` | P6 defines none |
| **MotionPlan** | **P0** | `hevi.production.p0_pipeline` | P6 defines none |
| Visual beat request type | P1 | `hevi.production.p1_types.VisualBeat` | P6 consumes |
| **Assets** | **P5.2 / existing** | `hevi.production.shot_readiness` | P6 imports none |
| **Renderer** | **existing** | `hevi.renderers.base` | P6 imports none |
| **QA / verdict** | **existing** | `hevi.verdict`, `hevi.quality` | P6 imports none |
| Providers / TTS | P3 | `hevi.providers` | P6 imports none |

## Uniqueness proofs

| check | method | result |
|---|---|---|
| one `ProductCompiler` | class count across all P6 modules | 1 |
| one `rank_candidates` | regex over `hevi/` | 1 |
| one `_semantic_match` | regex over `hevi/` | 1 |
| no P6 `ShotPlan`/`MotionPlan`/`ShotPreparation` | AST class scan, incl. aliases | 0 |
| no product id in P6 control flow | AST `if`/`match`/dict-dispatch scan | 0 |
| no P6 → execution authority import | AST import scan | 0 |

## The two registries, and why both exist

P6.0's `PRODUCT_PROFILE_REGISTRY` keys `id@version` and requires profiles to carry
*embedded* grammars — `register()` rejects a reference-only profile
(`DECLARED_BUT_ABSENT`). P6.5's `COMMERCIAL_PRODUCT_REGISTRY` keys `id` and carries
grammar *references*, which is the pattern P6.1–P6.4 established. They are
structurally incompatible, so they are siblings rather than duplicates, and
`assert_no_id_collision()` fails loudly if they ever drift into a shared id.
