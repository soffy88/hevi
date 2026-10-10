# Talkcraft Internalization Report

## Capability Boundary
Talkcraft operates as the pure explainer engine, generating kinetic videos synced to voiceover with dynamic shot cards.
It has been fully integrated under Hevi's explainer capability.

## 3O Mapping
- **oprim contracts**: Defined in `hevi/talkcraft/oprim_contracts.py` as pure keyword-only dataclasses (`WordTimestamp`, `Beat`, `ShotSpec`, `Shotbook`, `TalkcraftRenderRequest/Result`).
- **oskill alignment and planning**: Ported pure algorithmic logic for ASR text-audio alignment (CPU whisper) and deterministic semantic shot matching.
- **omodul rendering**: High-level workflow components to wrap Remotion and perform QA gating.
- **hevi studio/production**: Registration logic hooking up to the standard pipeline.

## Licensing
PolyForm Noncommercial 1.0.0. The appropriate texts and dependencies have been marked. Commercial distribution strictly requires explicit permission from the author.
