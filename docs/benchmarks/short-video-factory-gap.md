# short-video-factory clean-room regression study

The following are HEVI-owned regression names derived from public behavior
descriptions. They are not copied implementation or test data:

| case | HEVI check |
|---|---|
| MEDIA_METADATA_CACHE | stable metadata cache key includes content hash |
| LARGE_LIBRARY_DURATION_PROBE | duration probing is bounded and batched |
| TTS_METADATA_FAILURE | missing TTS metadata fails closed with a typed error |
| VOICE_TRUNCATION_AFTER_NORMALIZATION | normalization cannot truncate valid voice |
| BGM_MATCHING | matching uses declared metadata and duration |
| MISSING_BGM | absent BGM is an explicit non-success result |
| UNICODE_SENTENCE_SEGMENTATION | Unicode boundaries remain intact |
| NON_CHINESE_SUBTITLE_BOUNDARY | non-Chinese text is segmented without Chinese-only assumptions |
| BATCH_RENDER | batch failures remain attributable to one job |

No AGPL source, media, or project-specific implementation is used.
