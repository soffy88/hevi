# HEVI line qualification summary

Total: 13

| Line | Status | Code | Runtime | Production | Real E2E | Quality gate | Provider | Artifact | Blockers |
|---|---|---:|---:|---:|---|---|---|---|---|
| avatar_spokesperson | BLOCKED_HARDWARE | 86% | 67% | 17% | false | BLOCKED | h3_local, llm, remotion, tts | false | h3_local=BLOCKED_HARDWARE:GPU_HARDWARE |
| character_animation | PRODUCTION_COMPLETE | 86% | 67% | 100% | true | PASS | llm, remotion | true | — |
| cinematic | BLOCKED_HARDWARE | 86% | 67% | 17% | false | BLOCKED | h3_local, llm, remotion, tts | false | h3_local=BLOCKED_HARDWARE:GPU_HARDWARE |
| director_pipeline | BLOCKED_HARDWARE | 86% | 67% | 17% | false | BLOCKED | h3_local, llm, remotion | false | h3_local=BLOCKED_HARDWARE:GPU_HARDWARE |
| documentary_montage | PRODUCTION_COMPLETE | 86% | 67% | 100% | true | PASS | llm, media_source, remotion, tts | true | — |
| explainer | BLOCKED_HARDWARE | 86% | 67% | 17% | false | BLOCKED | llm, media_source, remotion, tts | false | CosyVoice=BLOCKED_HARDWARE:GPU_HARDWARE |
| history_scene | BLOCKED_HARDWARE | 86% | 67% | 17% | false | BLOCKED | llm, remotion | false | wan_local=BLOCKED_HARDWARE:GPU_HARDWARE |
| kinetic_promo | PRODUCTION_COMPLETE | 86% | 67% | 100% | true | PASS | hyperframes | true | — |
| localization_dub | PRODUCTION_COMPLETE | 86% | 67% | 100% | true | PASS | llm, media_source, tts | true | — |
| podcast_repurpose | PRODUCTION_COMPLETE | 86% | 67% | 100% | true | PASS | llm, media_source, remotion | true | — |
| reference_adapt | BLOCKED_HARDWARE | 86% | 67% | 17% | false | BLOCKED | llm, media_source, remotion | false | CosyVoice=BLOCKED_HARDWARE:GPU_HARDWARE |
| shorts_clip | PRODUCTION_COMPLETE | 86% | 67% | 100% | true | PASS | media_source | true | — |
| talking_head | BLOCKED_HARDWARE | 86% | 67% | 17% | false | BLOCKED | h3_local, llm, remotion, tts | false | h3_local=BLOCKED_HARDWARE:GPU_HARDWARE |

## Counts

- BLOCKED_HARDWARE: 7
- BLOCKED_PROVIDER: 0
- FAILED: 0
- PARTIAL: 0
- PRODUCTION_COMPLETE: 6
- QUALIFIED: 0
