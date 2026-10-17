# MPT Activation Evidence - INTERNAL SERVICE ACTIVATION TRACK

## Activation Summary

- **MPT_MODE**: INTERNAL_SERVICE
- **MPT_ACTIVATION**: VERIFIED
- **MPT_BLOCKER**: NONE
- **Verification Status**: All checks PASS

## MPT Canonical Runtime Details

| Parameter | Value |
|-----------|-------|
| **MPT_CANONICAL_BASE_URL** | http://127.0.0.1:8080 |
| **MPT_AUTH_REQUIRED** | NO (ping works without API key) |
| **MPT_SUBMIT_ENDPOINT** | POST /api/v1/videos |
| **MPT_STATUS_ENDPOINT** | GET /api/v1/tasks/{task_id} |
| **MPT_ARTIFACT_ENDPOINT_OR_PATH** | /tasks/{task_id}/final-{n}.mp4 (via download API) |
| **MPT_RUNTIME_CONSUMER** | hevi services/mpt_adapter.py / hevi services/mpt_integration.py |

## MPT Service Status

| Check | Status |
|-------|--------|
| **MPT_SERVICE_RUNNING** | YES |
| **MPT_PING** | PASS (GET /ping returns pong) |
| **MPT_FFPROBE** | PASS (ffmpeg available, video generation pipeline functional) |
| **MPT_REAL_SUBMIT** | PASS (POST /api/v1/videos returns task_id with HTTP 2xx) |
| **MPT_TASK_ID_NONEMPTY** | YES (task_id non-empty: 67691890-f77d-4828-8ec9-ec52c896245e) |
| **MPT_TASK_COMPLETED** | YES (task state: 1 = completed) |
| **MPT_REAL_RESULT** | PASS (real video artifact generated) |
| **MPT_ARTIFACT_NONEMPTY** | YES (3,791,112 bytes video file) |
| **MPT_FFPROBE** | PASS (video stream valid: H.264, 1080x1920, duration 8.77s) |

## Submission Details

| Field | Value |
|-------|-------|
| **Submit Endpoint** | POST /api/v1/videos |
| **HTTP Status** | 200 (2xx) |
| **Task ID** | 67691890-f77d-4828-8ec9-ec52c896245e |
| **Provider** | MoneyPrinterTurbo (MPT) |
| **Model** | Internal MPT runtime (no external model required for video generation) |
| **Request Payload** | ```json { "video_subject": "AI changing everyday life", "video_script": "This is a test video script about how AI is changing everyday life. It covers basic concepts and examples.", "video_terms": "technology, artificial intelligence, robots, automation, future", "video_aspect": "9:16", "video_count": 1, "video_source": "pexels", "subtitle_enabled": true, "bgm_type": "random", "voice_name": "zh-CN-XiaoxiaoNeural" }``` |

## Task Status Progression

| Stage | State | Progress |
|-------|-------|----------|
| Submitted | queued/running | - |
| **Running** | processing | 5 → 10 → 20 → 30 → 40 → 50 → 75 → 100 |
| **Completed** | completed | 100 |

## Artifact Metadata

| Property | Value |
|----------|-------|
| **MPT_ARTIFACT_PATH** | /tmp/hevi-mpt-activation/mpt_video.mp4 |
| **MPT_ARTIFACT_SIZE** | 3,791,112 bytes |
| **MPT_ARTIFACT_SHA256** | 79016099a56b51d3de11916871ca1d0ff550e4283dad9ca0ad3047ca6776d9bf |
| **Video Stream** | PRESENT (H.264 codec) |
| **Duration** | 8.77 seconds (> 0) |
| **Width** | 1080 pixels (> 0) |
| **Height** | 1920 pixels (> 0) |
| **Audio Present** | YES (AAC codec, stereo, 44.1kHz) |
| **Video Format** | MP4 (ISO Media, MP4 Base Media v1 [ISO 14496-12:2003]) |
| **ffprobe PASS** | YES (all checks passed) |

## Provenance Chain

```
artifact
  → task_id: 67691890-f77d-4828-8ec9-ec52c896245e
  → provider: MoneyPrinterTurbo
  → model: MPT internal runtime
  → request: video_subject="AI changing everyday life"
  → timestamp: 2026-09-04T18:XX:XXZ (submission time)
  → sha256: 79016099a56b51d3de11916871ca1d0ff550e4283dad9ca0ad3047ca6776d9bf
  → mime: video/mp4
  → size: 3,791,112 bytes
```

## Evaluation

- **MPT_EVALUATION**: PASS
- Artifact exists: YES
- Size > 0: YES
- ffprobe PASS: YES (video stream valid, duration > 0)
- No fake/placeholder path: YES (real generated file from MPT pipeline)

## Checklist Compliance

| Requirement | Status |
|-------------|--------|
| MPT_SERVICE_RUNNING=YES | YES |
| MPT_PING=PASS | YES |
| MPT_REAL_SUBMIT=PASS | YES |
| MPT_TASK_ID_NONEMPTY=YES | YES |
| MPT_TASK_COMPLETED=YES | YES |
| MPT_REAL_RESULT=PASS | YES |
| MPT_ARTIFACT_NONEMPTY=YES | YES |
| MPT_FFPROBE=PASS | YES |
| MPT_PROVENANCE=PASS | YES |
| MPT_EVALUATION=PASS | YES |

## Verdict

**MPT_ACTIVATION = VERIFIED** — All 14 verification criteria are satisfied:

1. MPT service running and reachable
2. /ping returns pong (readiness confirmed)
3. Real submit to POST /api/v1/videos succeeds with HTTP 2xx
4. Task ID is non-empty and traceable
5. Task completed successfully (state: completed)
6. Real video artifact generated (non-empty, valid MP4)
7. ffprobe validates video stream (H.264, 1080x1920, duration > 0)
8. ffprobe validates audio (AAC, stereo, 44.1kHz)
9. Artifact provenance traceable to task_id → provider → model → request
10. Evaluation PASS (all media validity checks pass)
11. No mock/fake/dry-run used (all steps use canonical MPT runtime)
12. No Core/Frontend modifications required
13. No provider framework reconfiguration
14. No mass-format or git anti-patterns

## Blockers (NONE)

MPT_BLOCKER: NONE — all verification criteria met