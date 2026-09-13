# HEVI Video Intelligence

Video Intelligence is an optional, CPU-first observer of rendered artifacts.
It does not become a second orchestration authority and never mutates upstream
canonical state.

```text
Narrative Intelligence
        ↓
SceneBlueprint
        ↓
Shot Intelligence
        ↓
ShotPlan
        ↓
Production Runtime
        ↓
Artifact
        ↓
Video Intelligence
  ├─ Machine Evidence (ffprobe/ffmpeg)
  ├─ Reel Analysis
  ├─ Optional Understanding
  ├─ Temporal Retrieval
  └─ Intent/Artifact Comparison
        ↓
QualityReport
        ↓
RevisionFeedback (proposal only)
```

Authority is explicit: StoryBible is narrative authority; SceneBlueprint is
scene-intent authority; ShotPlan is planned visual authority; the artifact is
rendered reality; ReelAnalysis is observed evidence; QualityReport is a
projection; RevisionFeedback is a proposal. No evaluator writes back into a
StoryBible or ShotPlan.

The core is CPU-only and uses immutable machine fields for time ranges,
duration, frame rate and motion evidence. Semantic visual understanding is an
optional provider and is not required for core readiness.
