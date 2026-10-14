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

Production (`deploy/docker-compose-cftunnel.yml`, since 2026-10-11) sets `HEVI_LINE_ENGINE=zero`, so the 11 zero lines
default to the zero engine there; Piper lives in the API image at `/opt/piper/bin/piper`, voices are mounted read-only at
`/opt/piper/voices`, whisper is `/models/faster-whisper-large-v3-turbo`, cache is the `hevi-zero-cache` volume.
Override per deploy with `HEVI_LINE_ENGINE=legacy` in the env file, or per order with slot `engine`.

Talkcraft presenter lines in production (since 2026-10-11): `talking_head` / `avatar_spokesperson` orders with
`renderer="talkcraft"` render inside the API image. `deploy/Dockerfile.api` installs `hevi-remotion-talkcraft`
from its own `package-lock.json` (`npm ci --omit=dev`, registry `HEVI_NPM_REGISTRY`, default npmmirror) because the host
`node_modules` is a symlink outside the build context; Chrome Headless Shell 149.0.7790.0 is copied from the compose
`additional_contexts.talkcraft_browser` (`HEVI_TALKCRAFT_BROWSER_DIR`, default the host vendor runtime's
`node_modules/.remotion`) and checked offline at build time, so nothing downloads a browser at run time.
Compose sets `HEVI_TALKCRAFT_REMOTION=/app/hevi-remotion-talkcraft`, `HEVI_TALKCRAFT_AVATAR_MODELS=/models/wav2lip`,
`HEVI_TALKCRAFT_WHISPER=/models/faster-whisper-large-v3-turbo`, `HEVI_NODE_BIN=/usr/bin`, `HEVI_TALKCRAFT_THREADS=2`.

Host write access: the API runs as uid 999 and bind-mounts `/home/soffy/projects/hevi/{data,output,assets}`
(= `/data/soffy/projects/hevi/...`, owned by soffy 755). Grant it with ACLs instead of chown:
`setfacl -R -m u:999:rwX,u:1000:rwX <dir> && setfacl -R -d -m u:999:rwX,u:1000:rwX,u::rwX,g::rX,o::rX <dir>`.

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
