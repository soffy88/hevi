# HEVI Narrative Intelligence

Narrative Intelligence is an optional deterministic planning boundary:

`NarrativeProject → StoryBible → SceneBlueprint → ShotIntent → existing runtime`

The canonical objects contain IDs, versions, revisions, source references and
continuity constraints. The narrative layer never imports a renderer, model
server, CUDA, or provider implementation. `NARRATIVE_INTELLIGENCE_ENABLED`,
`NARRATIVE_CONTINUITY_ENABLED`, and `NARRATIVE_REVISION_ENABLED` default to
off; existing production paths therefore remain unchanged.

LLM output is a proposal. It must pass schema, continuity, provenance and
quality validation before persistence. Persistence uses a temporary file,
fsync, atomic replacement and read-back validation.
