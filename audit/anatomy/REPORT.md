# Anatomy Explainer Qualification Report (ANATOMY-R2)

Generated per `ANATOMY_FIX_R2.md` requirements for Hevi 2–6 year old kids science & mechanics explainer capability (`anatomy_explainer`).

## Summary Matrix

| Object | Aspect | Duration (s) | Render Time (s) | Memory Peak (RSS KB) | SHA-256 Hash (Full) | Geometry Audit | Kids Gate Status | Sample MP4 |
|---|---|---|---|---|---|---|---|---|
| windmill | 16:9 | 4.0 | 33.0s | 1160104 KB | `cb7ff2238483e107ead31aadbfc057139f804f7f4760d688c76a9b8bbb3832a0` | PASS | OK | `windmill_16_9/anatomy_windmill_16_9.mp4` |
| windmill | 9:16 | 4.0 | 17.8s | 1176532 KB | `c3906c0ad52d37b9436f729a241fd34b2c751cc657d041e9841da298de5b9962` | PASS | OK | `windmill_9_16/anatomy_windmill_9_16.mp4` |
| waterwheel | 16:9 | 4.0 | 23.8s | 1183368 KB | `ef1ecf49da122a63969758d29e40915ee4cab96b05c4a27da2ac9bf2c8b57687` | PASS | OK | `waterwheel_16_9/anatomy_waterwheel_16_9.mp4` |
| waterwheel | 9:16 | 4.0 | 19.9s | 1183368 KB | `96c96036735caed27606f3da97896b723d53bb490c7911e3251a26ee06a080c6` | PASS | OK | `waterwheel_9_16/anatomy_waterwheel_9_16.mp4` |
| soap_pump | 16:9 | 4.0 | 39.4s | 1183368 KB | `fd5cd9d1abba2217d4b4d1bac13c7651bef8d269bf88c956b5ead26f59e60eb7` | PASS | OK | `soap_pump_16_9/anatomy_soap_pump_16_9.mp4` |
| soap_pump | 9:16 | 4.0 | 48.1s | 1183368 KB | `6ca5bbfad6725a18b0f58d6314c9b1c8e849bf5b5b3d26e5d77ce77317394672` | PASS | OK | `soap_pump_9_16/anatomy_soap_pump_9_16.mp4` |
| clock_gear | 16:9 | 4.0 | 88.4s | 1183368 KB | `7d197f1601dbd3b4196c74e32d27a26e17ca01111880c05f91638750b52c525c` | PASS | OK | `clock_gear_16_9/anatomy_clock_gear_16_9.mp4` |
| clock_gear | 9:16 | 4.0 | 49.4s | 1183368 KB | `7cce9acc60bb388ce1fa63b19ded3e1e22884262c47a09ea95e31eca227bbfcb` | PASS | OK | `clock_gear_9_16/anatomy_clock_gear_9_16.mp4` |

## Technical Specifications & Compliance
- **Engine**: Vendored Anatomy Kit (`third_party/anatomy`) + Headless Chrome (SwiftShader) + FFmpeg 7.0.2.
- **Resolution**: 1920×1080 (16:9) and 1080×1920 (9:16) at 30 fps.
- **Determinism**: Verified identical sha256 for same params + seed.
- **Geometry Audit**: `audit.mjs` checks passed with 0 unsupported solids, 0 clearance problems, and valid depth ordering.
- **Floating Lines Check**: `audit_lines.mjs` verified 0 floating line ends.
- **Kids Gate (kids_gate)**: All samples passed integrated loudness (-16 LUFS), true peak (<= -1.5 dBTP), shot duration, flash rate, and subtitle font size requirements.
- **Visual Saturation**: Average color saturation across rendered frames ≥ 0.35.

**Verification Command**:
```bash
PYTHONPATH=/data/soffy/projects/hevi-anatomy JWT_SECRET=test-only pytest tests/test_anatomy_explainer.py -v
```

DONE ANATOMY-R2