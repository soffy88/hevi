# RFC-013 Production IR Schema v1 and Migration

- Status: Accepted for v1
- Date: 2026-08-25

## Schema

Director IR kinds: `concept`, `screenplay`, `design_list`, `scene_stage`,
`shot_list`. Each `director_documents` row stores `schema_version`,
`content_json`, and `content_hash`. Current v1 fields are those in
`hevi.director.pipeline_schemas`.

## Migration rule

A bump of `schema_version` must ship a pure function that reads vN JSON and
writes vN+1 JSON without calling a provider. Locked revisions keep the
version they were stored with; compilers accept the stored version or
migrate in memory.

## Compatibility

Unknown fields are preserved in JSON. Removing a required field is a major
IR version and requires a dual-read window.
