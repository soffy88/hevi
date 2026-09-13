# HEVI Narrative Intelligence

Narrative Intelligence is an optional deterministic planning boundary:

`Narrative Intelligence → Screenwriting Intelligence → SceneBlueprint → Shot Intelligence → ShotPlan → Production Runtime → Qualification`

The narrative object flow is:

`NarrativeProject → StoryBible → DramaturgyPlan → SceneBlueprint → ShotIntent → ShotPlan`

The canonical objects contain IDs, versions, revisions, source references and
continuity constraints. The narrative layer never imports a renderer, model
server, CUDA, or provider implementation. `NARRATIVE_INTELLIGENCE_ENABLED`,
`NARRATIVE_CONTINUITY_ENABLED`, and `NARRATIVE_REVISION_ENABLED` default to
off; existing production paths therefore remain unchanged.

LLM output is a proposal. It must pass schema, continuity, provenance and
quality validation before persistence. Persistence uses a temporary file,
fsync, atomic replacement and read-back validation.

Authority boundaries:

- `StoryBible` is the narrative canonical authority.
- `Character Graph` is a projection of `StoryBible.characters`.
- Scene state is a scene snapshot/projection.
- `ShotPlan` is a downstream execution plan.
- Renderers have no narrative authority and cannot mutate the StoryBible.
