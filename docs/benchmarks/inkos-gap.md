# InkOS capability gap audit

This is a clean-room classification of observable capabilities, not a source
port. Detailed evidence and per-capability status live in
`docs/research/inkos_capability_ledger.yaml`.

| Category | HEVI decision |
| --- | --- |
| Existing narrative, shot, production, artifact, and quality contracts | ALREADY_HAVE; preserve and bridge through typed envelopes |
| Canonical narrative state, context governance, observation, forecast, audit, and revision | ADAPT into HEVI `obase`/`oprim`/`omodul` contracts |
| Script, storyboard, interactive film, play, translation, import, and export | ADOPT observable capability, independently implemented |
| External InkOS agent/runtime, prompts, skills, tests, fixtures, templates, and UI assets | REJECT as implementation dependencies |
| Advanced product UI and provider-specific behavior | DEFER until the corresponding HEVI production service has real evidence |
