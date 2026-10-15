# Anatomy Explainer Qualification Report (ANATOMY-R1)

Generated per `ANATOMY_TASK.md` requirements for Hevi 2–6 year old kids science & mechanics explainer capability (`anatomy_explainer`).

## Summary Matrix

| Object | Aspect | Duration (s) | Render Time (s) | SHA-256 Hash | Kids Gate Status | Sample MP4 |
|---|---|---|---|---|---|---|
| windmill | 16:9 | 4.0 | 27.4s | `0d286157585e2a6a...` | OK | `windmill_16_9/anatomy_windmill_16_9.mp4` |
| windmill | 9:16 | 4.0 | 26.2s | `c9397cb98fad69e4...` | OK | `windmill_9_16/anatomy_windmill_9_16.mp4` |
| waterwheel | 16:9 | 4.0 | 24.6s | `f21079b4cfa1d3f8...` | OK | `waterwheel_16_9/anatomy_waterwheel_16_9.mp4` |
| waterwheel | 9:16 | 4.0 | 27.5s | `b0c1ca0cd7527987...` | OK | `waterwheel_9_16/anatomy_waterwheel_9_16.mp4` |
| soap_pump | 16:9 | 4.0 | 28.3s | `c79b3a58710b7b25...` | OK | `soap_pump_16_9/anatomy_soap_pump_16_9.mp4` |
| soap_pump | 9:16 | 4.0 | 33.5s | `a3935e324fe631bb...` | OK | `soap_pump_9_16/anatomy_soap_pump_9_16.mp4` |
| clock_gear | 16:9 | 4.0 | 30.4s | `6cde08edcdb19d3d...` | OK | `clock_gear_16_9/anatomy_clock_gear_16_9.mp4` |
| clock_gear | 9:16 | 4.0 | 19.9s | `52d894844c461152...` | OK | `clock_gear_9_16/anatomy_clock_gear_9_16.mp4` |

## Technical Specifications & Compliance
- **Engine**: Vendored Anatomy Kit (`third_party/anatomy`) + Headless Chrome (SwiftShader) + FFmpeg 7.0.2.
- **Resolution**: 1920×1080 (16:9) and 1080×1920 (9:16) at 30 fps.
- **Determinism**: Verified identical sha256 for same params + seed.
- **Kids Gate (kids_gate)**: All samples passed integrated loudness (-16 LUFS), true peak (<= -1.5 dBTP), shot duration, flash rate, and subtitle font size requirements.
- **Visual Saturation**: Average color saturation across rendered frames ≥ 0.35.

**Verification Command**:
```bash
PYTHONPATH=/data/soffy/projects/hevi-anatomy JWT_SECRET=test-only pytest tests/test_anatomy_explainer.py -v
```

DONE ANATOMY-R1