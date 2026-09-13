# HEVI line qualification summary

Total: 13

| Line | Status | Code | Runtime | Production | Real E2E | Quality gate | Provider | Artifact | Blockers |
|---|---|---:|---:|---:|---|---|---|---|---|
| kinetic_promo | PRODUCTION_COMPLETE | 86% | 67% | 100% | True | PASS | hyperframes | True | — |
| shorts_clip | BLOCKED_PROVIDER | 86% | 67% | 17% | False | BLOCKED | media_source | False | media_source=BLOCKED_NETWORK:HTTP_403 |
| history_scene | BLOCKED_PROVIDER | 86% | 67% | 17% | False | BLOCKED | llm, remotion | False | llm=BLOCKED_SECRET:required configuration/secret absent |
| localization_dub | BLOCKED_PROVIDER | 86% | 67% | 17% | False | BLOCKED | media_source, tts | False | media_source=BLOCKED_NETWORK:HTTP_403 |
| explainer | BLOCKED_PROVIDER | 86% | 67% | 17% | False | BLOCKED | llm, media_source, remotion, tts | False | llm=BLOCKED_SECRET:required configuration/secret absent; media_source=BLOCKED_NETWORK:HTTP_403 |
| documentary_montage | BLOCKED_PROVIDER | 86% | 67% | 17% | False | BLOCKED | llm, media_source, remotion, tts | False | llm=BLOCKED_SECRET:required configuration/secret absent; media_source=BLOCKED_NETWORK:HTTP_403 |
| podcast_repurpose | BLOCKED_PROVIDER | 86% | 67% | 17% | False | BLOCKED | llm, media_source, remotion | False | llm=BLOCKED_SECRET:required configuration/secret absent; media_source=BLOCKED_NETWORK:HTTP_403 |
| reference_adapt | BLOCKED_PROVIDER | 86% | 67% | 17% | False | BLOCKED | llm, media_source, remotion | False | llm=BLOCKED_SECRET:required configuration/secret absent; media_source=BLOCKED_NETWORK:HTTP_403 |
| character_animation | BLOCKED_PROVIDER | 86% | 67% | 17% | False | BLOCKED | llm, remotion | False | llm=BLOCKED_SECRET:required configuration/secret absent |
| director_pipeline | BLOCKED_HARDWARE | 86% | 67% | 17% | False | BLOCKED | h3_local, llm, remotion | False | h3_local=BLOCKED_HARDWARE:nvidia-smi/CUDA unavailable; llm=BLOCKED_SECRET:required configuration/secret absent |
| cinematic | BLOCKED_HARDWARE | 86% | 67% | 17% | False | BLOCKED | h3_local, llm, remotion, tts | False | h3_local=BLOCKED_HARDWARE:nvidia-smi/CUDA unavailable; llm=BLOCKED_SECRET:required configuration/secret absent |
| talking_head | BLOCKED_HARDWARE | 86% | 67% | 17% | False | BLOCKED | h3_local, llm, remotion, tts | False | h3_local=BLOCKED_HARDWARE:nvidia-smi/CUDA unavailable; llm=BLOCKED_SECRET:required configuration/secret absent |
| avatar_spokesperson | BLOCKED_HARDWARE | 86% | 67% | 17% | False | BLOCKED | h3_local, llm, remotion, tts | False | h3_local=BLOCKED_HARDWARE:nvidia-smi/CUDA unavailable; llm=BLOCKED_SECRET:required configuration/secret absent |

## Counts

- BLOCKED_HARDWARE: 4
- BLOCKED_PROVIDER: 8
- FAILED: 0
- PARTIAL: 0
- PRODUCTION_COMPLETE: 1
- QUALIFIED: 0
