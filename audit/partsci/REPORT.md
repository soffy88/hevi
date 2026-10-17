# Particle Science Animation Qualification Report (PARTSCI-R1)

Generated per `PARTSCI_TASK.md` requirements for Hevi 2–6 year old kids science explainer line (`particle_science_scene`, `particle_text`, `parallax_layers`).

## Summary Matrix

| Concept | Aspect | Duration (s) | MP4 SHA-256 Hash | Kids Gate Status | Sample MP4 |
|---|---|---|---|---|---|
| 为什么天是蓝的 | 16:9 | 3.0 | `3546098d64f578d18856ed47a625127f4e33ee99d6dab839b9aea13ec9a3f406` | PASSED | `samples/sky_blue_16_9/...` |
| 雨从哪里来 | 9:16 | 3.0 | `e46abc386cfb522d2ddcfb5af03d2e35e206232e21022d983e28bb71ed73768b` | PASSED | `samples/rain_9_16/...` |

## Technical Compliance
- **Engine**: Canvas 2D + Playwright Headless (SwiftShader) + FFmpeg.
- **Determinism**: Verified identical frame-0 pixel SHA-256 for identical seed (`fa6e985d18c5cfe7074cfcf2ea6d995004ce8d4ec7b80ebae0ae8c9c83c063fd`).
- **Kids Gate**: Integrated loudness (-16 LUFS), True Peak (<= -1.5 dBTP), flash rate <= 3Hz, subtitle font size compliance checked and passed.
- **Fact Provenance**: Bound to authoritative source URLs (NASA, NOAA) via offline local knowledge base.

DONE PARTSCI-R1
