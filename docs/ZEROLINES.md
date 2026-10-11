# Zero-cost line engine (`hevi.zerolines`)

CPU-only, no GPU, no paid API engine for 11 canonical Studio lines
(merged from the standalone `hevi-zero` prototype, 2026-10).

| | |
|---|---|
| Lines | kinetic_promo, explainer, cinematic, director_pipeline, history_scene, character_animation, talking_head, avatar_spokesperson, shorts_clip, podcast_repurpose, reference_adapt |
| Legacy only | documentary_montage, localization_dub |
| Inputs | Piper local TTS, Pexels free-licence stock (`PEXELS_API_KEY`), procedural 2D (PIL), user source media, faster-whisper (local CPU), procedural BGM |
| Output | `<out>/<line>.mp4` (+ `shorts_clip_NN.mp4`), `record.json` (`hevi.zerolines.record/1`), `contact_sheet*.jpg` |

## 3O layout

| Layer | Path | Contents |
|---|---|---|
| oprim | `hevi/layer4_legacy/zerolines/oprim_impl/specs.py` | `ZERO_LINES`, `LINE_SPECS` (resolution, required inputs, QA thresholds), `ZeroLineRequest`, `resolve_engine` |
| oskill | `hevi/layer4_legacy/zerolines/oskill_impl/` | `audio_math` (BGM synthesis, RMS -> visemes), `captions` (ASS, kinetic plan), `shots` (camera filters, xfade graph, director shot list, beat placement), `qa` (verdict from measured stats), `puppets` (PIL presenter / caveman) |
| omodul | `hevi/layer4_legacy/zerolines/omodul_impl/` | `_media` (ffmpeg/ffprobe, Piper, Pexels, whisper, measure, contact sheet), `_lines` (11 producers), `runtime.zero_line_workflow(config, input_data, output_dir, *, on_step)` with `_enabled_pillars = {report, cost, decision_trail}` |
| facade | `hevi/zerolines/{,oprim,oskill,omodul}` | compatibility shims only |

## Selecting the engine

Default is unchanged (`legacy`). Precedence: order slot `engine` > env `HEVI_LINE_ENGINE` > `legacy`.

```python
await produce(line_id="explainer", execute=True, slots={
    "engine": "zero", "title": "...", "script_lines": ["...", "..."], "queries": ["b-roll query", "..."],
})
```

Slots read by the zero engine: `script_lines`, `queries`/`broll_queries`, `title`, `topic`, `language` (zh|en),
`media_path`/`reference_path`/`source`, `offsets` (reference_adapt), `labels` (explainer headings / history years),
`zero_extras` (`cta`, `source_lang`, `clips`, `show`, `subtitle`, `shot_overrides`).
`talking_head`/`avatar_spokesperson` with `renderer="talkcraft"` always use the photoreal talkcraft host (Wav2Lip).

## Fail-closed

* missing/invalid input -> `blocked` (no invented copy, no substitute asset)
* producer error or any failed measured gate (motion, static ratio, blank, black/dark ratio, resolution, duration, audio presence/volume) -> `failed`
* success additionally passes the canonical Studio media gate (`_verified_video_manifest`) and the final truth gate.

Per-line threshold relaxations are declared in `LINE_SPECS` (cinematic letterbox black <= 0.25, reference_adapt orbital night black <= 0.35,
podcast audiogram dark-backdrop check not applicable but motion >= 0.5, character_animation motion >= 0.4, talking_head motion >= 0.3)
and are reported in every `record.json`.

## Qualification

```bash
PYTHONPATH=. HEVI_ASSET_ROOT=<repo with data/workspace/assets> \
  python scripts/qualify_autonomous_production.py --engine zero --host-renderer zero --lines <zero lines>
python scripts/acceptance_matrix.py --zero-root <output>/runs     # Z1-Z4
```

Inputs: `scripts/qualification/zero_line_briefs.json`.
