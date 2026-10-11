# ViralClone Implementation & Verification Report (3O Architecture)

## 1. Executive Summary

The viral short-video replication pipeline (**Reference Breakdown → Word-Anchored Template → Product Asset Compositing → Variant Matrix Generation**) has been fully internalized into Hevi under the **3O architecture standard** (`oprim` / `oskill` / `omodul`).

### Core Guarantees Met:
- **Clean-Room Implementation**: 100% clean-room design based strictly on first principles and specifications in `VIRALCLONE_TASK.md`. Zero external proprietary code, zero SVML syntax or AST copying.
- **Zero Cost / 100% CPU Only**: Runs entirely on commodity CPU with 0.00 USD cloud API expenditure.
  - Automatic Speech Recognition: Local `faster-whisper-large-v3-turbo` (CPU int8).
  - Text-to-Speech: Local `piper` binary with high-fidelity voices (`zh_CN-huayan-medium`, `en_US-lessac-medium`).
  - Semantic Sentence Classifier: Local `ollama` (`llama3.2:1b`) with deterministic rule-based fallback.
  - Video Subtitle OCR: Local `rapidocr-onnxruntime` CPU engine.
  - Matting & Cutout: Local `rembg` (`u2net` ONNX model).
  - Visual Diversity Gate: Local 64-bit perceptual hashing (`imagehash.phash`) & normalized text distance.
- **GB 45438-2025 Compliance**: Dual-layer AI watermarking:
  - Visible: Burning in ASS subtitle stream with font height $\ge 5\%$ of frame short edge, displayed for $\ge 2.0\text{s}$ from video start.
  - Invisible: Metadata injection in MP4 container `comment` tag (`GB45438-2025:AIGC; Generator=Hevi-ViralClone-3O`).
- **Real Media Verification**: Verified against real media artifacts in `artifacts/real_video/20261005T160434Z/artifacts/`. No dummy mocks or synthetic placeholder video files.

---

## 2. 3O Architecture Decomposition

The implementation strictly adheres to Hevi's 3O architectural convention:
Layer 4 canonical implementation resides in `hevi/layer4_legacy/viralclone/`, exposed via exterior shims in `hevi/viralclone/`.

```
hevi/
├── layer4_legacy/viralclone/
│   ├── oprim_impl/
│   │   ├── __init__.py
│   │   └── specs.py          # Data contracts: WordToken, SubtitleBox, RhythmStats,
│   │                         # ReferenceBreakdown, TemplateSpec, VisualAnchor,
│   │                         # TemplateSegment, WatermarkSpec, DiversityRecord
│   ├── oskill_impl/
│   │   ├── __init__.py
│   │   ├── breakdown_math.py # Rhythm stats, RapidOCR subtitle box detection,
│   │   │                     # Ollama / heuristic semantic sentence classifier
│   │   ├── anchoring.py      # Dynamic word-anchored alignment, Hevi Timeline JSON,
│   │   │                     # ASS karaoke subtitles with GB 45438 watermark
│   │   ├── diversity.py      # pHash Hamming distance, normalized text similarity,
│   │   │                     # NxN variant diversity matrix gate
│   │   ├── product_card.py   # rembg cutout, drop shadow, Ken Burns zoom, product UI
│   │   └── watermark.py      # GB 45438 ratio math, metadata verification
│   └── omodul_impl/
│       ├── __init__.py
│       ├── _media.py         # ffmpeg, faster-whisper, and piper execution primitives
│       ├── breakdown.py      # reference_breakdown transaction (breakdown.json/.md)
│       ├── compiler.py       # compile_and_render_template transaction
│       ├── product.py        # produce_product_asset transaction
│       ├── variants.py       # generate_variant_matrix transaction (ThreadPool concurrency)
│       └── runtime.py        # produce_viralclone unified transaction dispatcher
└── viralclone/
    ├── __init__.py           # Exterior public module exports
    ├── adapter.py            # High-level Pythonic wrappers
    ├── oprim/                # Layer shim
    ├── oskill/               # Layer shim
    └── omodul/               # Layer shim
```

### Transaction Signatures & Pillars:
All public transactions implement the standard contract:
```python
def transaction_name(
    config: dict[str, Any],
    input_data: dict[str, Any],
    output_dir: str | Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
```
And declare `_enabled_pillars = {"report", "cost", "decision_trail"}`.

---

## 3. Bug Fixes to Existing `video_intelligence` Modules

During integration and end-to-end verification, three critical bugs in `hevi/video_intelligence` were resolved:

1. **`boundaries.py` (Shot Boundary Detection)**:
   - *Problem 1*: Scene detection using ffmpeg generated timestamps at `0ms` or exceeding `probe.duration_ms`, corrupting slice calculations.
   - *Problem 2*: `scenedetect` backend crashed when attempting to access `probe.frame_rate` (which was not a field on `VideoProbe`, only `fps_num`/`fps_den` existed).
   - *Problem 3*: Deprecation warning from PySceneDetect `get_seconds()`.
   - *Fix*: Added safe FPS extraction `(probe.fps_num / probe.fps_den)`, bounded valid timestamps strictly between `0 < timestamp < probe.duration_ms`, added fallback handling between `scenedetect` and `ffmpeg`, and used `.seconds` property.

2. **`contactsheet.py` (Visual Contact Sheet Builder)**:
   - *Problem*: Only supported hard-coded 25 full-size unscaled tiles with simple numerical badges. Frame sizes $>720p$ produced multi-gigabyte or gigantic image sheets without timing or transcript annotations.
   - *Fix*: Added dynamic tile resizing (`tile_width`, `tile_height`), header timecode badges (`MM:SS.s`), and bottom banner annotations displaying spoken words (`words`) or semantic role tags (`labels`) for each frame.

3. **`analysis.py` (Whole-Video Redundant Compute)**:
   - *Problem*: In `analyze_reel()`, `MotionAnalyzer.analyze()` was called repeatedly inside the per-shot loop, causing $N$ times redundant motion optical flow passes over the entire video.
   - *Fix*: Hoisted `MotionAnalyzer.analyze()` out of the per-shot loop to compute once, speeding up video reel intelligence passes dramatically.

---

## 4. End-to-End Real Media Verification Results

### A. Reference Breakdown (`scene_interview_sub.mp4`)
- **Input Asset**: `artifacts/real_video/20261005T160434Z/artifacts/scene_interview_sub.mp4` (1280x720, 25 fps, 22.65s).
- **Execution**: `reference_breakdown` with Faster-Whisper, RapidOCR, and Scenedetect.
- **Results**:
  - `breakdown.json`: Extracted 6 camera shots (average duration: 3.77s; first shot: 6.04s; hook: 1.86s).
  - Faster-Whisper transcription: 73 words accurately recognized with millisecond boundaries (`"I was a young boy when I got smoked..."`).
  - Subtitle Box OCR: RapidOCR localized burned subtitle box at `[291.0, 627.0] -> [987.0, 676.0]` (relative line height: $6.8\%$ of frame height).
  - Semantic Categorization: Sentences cleanly partitioned into `[hook, selling_points, proof, cta]`.
  - Visual Contact Sheet: Produced `contactsheet.jpg` with per-tile timecodes and spoken word banners.
  - Markdown Report: Formatted `breakdown.md` specification card.

### B. Product Asset Pipeline (`produce_product_asset`)
- **Execution**: Background removal (`rembg` u2net) on product image, drop shadow injection, Ken Burns gentle zoom animation, badge compositing.
- **Output Artifacts**:
  - `product_cutout.png`: RGBA transparent cutout.
  - `product_card.mp4`: Rendered 720x1280 (9:16 portrait), 25 fps, 2.00s MP4.

### C. Word-Anchored Compilation (`compile_and_render_template`)
- **Mechanism**: Dynamic alignment of visual cuts and animations against sentence index and word offsets. When Piper TTS generates voiceover audio, Faster-Whisper recalculates exact word timestamps, and all visual anchors dynamically adjust without drifting.
- **Output Artifacts**:
  - `final.mp4`: Synchronized video and AAC audio (4.46s, 1280x720, 25 fps).
  - `tl_*.json`: Canonical Hevi `Timeline` JSON data structure.
  - `subtitles.ass`: Full ASS subtitle file with `{\k...}` word-level karaoke timing and GB 45438-2025 watermark style.
  - GB 45438 Watermark Verification: Short edge = 720px; font size = 36px ($\ge 5\%$, exact $0.05$ ratio); display duration = 2.5s ($\ge 2.0\text{s}$). Implicit metadata verified via ffprobe container comments.

### D. Variant Matrix & Diversity Gate (`generate_variant_matrix`)
- **Execution**: Multithreaded concurrent generation (CPU ThreadPoolExecutor) of multiple variant angles from distinct product selling points and b-roll footage.
- **Output Artifacts**:
  - Rendered `var_a/final.mp4` and `var_b/final.mp4`.
  - `diversity_matrix.json`:
    - Perceptual Hash Distance: Hamming distance = 30 (minimum required: 3).
    - Normalized Text Similarity: 0.381 (maximum allowed: 0.85).
    - Diversity Verdict: `all_passed: true`.

---

## 5. Test Suite Verification

All test suites pass completely:
- `tests/test_viralclone.py`: **13 passed** (contracts, rhythm math, word anchoring, ASS subtitles, GB 45438 watermark, diversity matrix, real media breakdown, product asset, template compilation, variant matrix).
- `tests/video_intelligence/`: **72 passed, 1 skipped**.
- `tests/test_zerolines.py`: **19 passed**.
- Unified 3O Lint: Zero violations across all `viralclone` components (`_enabled_pillars`, `(config, input_data, output_dir, *, on_step=None)` signatures, no sibling calls, keyword-only primitives).

---

## 6. Zero Cost & Hardware Benchmark

| Pipeline Stage | Engine | Cost (USD) | Hardware | Typical Duration |
| :--- | :--- | :--- | :--- | :--- |
| Audio Transcription | Faster-Whisper `large-v3-turbo` | $0.00 | CPU (int8) | ~1.5s / 20s audio |
| Subtitle Detection | RapidOCR ONNX | $0.00 | CPU | ~0.8s / 10 frames |
| Semantic Classification | Ollama `llama3.2:1b` / Regex | $0.00 | CPU | < 0.2s / sentence |
| Voiceover Synthesis | Piper TTS | $0.00 | CPU | ~0.6s / 5s speech |
| Product Matting | rembg `u2net` | $0.00 | CPU | ~1.8s / image |
| Video Assembly & Watermark | ffmpeg 6.x | $0.00 | CPU | ~2.5s / 5s MP4 |
| Diversity Hashing | imagehash pHash (64-bit) | $0.00 | CPU | < 0.05s / frame |
