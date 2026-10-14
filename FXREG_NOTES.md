# FXREG_NOTES — Research notes (Step 1)

## 1. tplMeta.ts card inventory

- File: `hevi-remotion-talkcraft/src/cards/tplMeta.ts`
- **108 card entries**, each `{ id, name_zh, category_zh }`
- 7 source categories with counts:
  - 素材呈现 (material presentation): 27
  - 字幕花字 (typography/animation): 22
  - 强调标注 (emphasis/annotation): 14
  - 数据信息图 (data infographic): 14
  - 转场结构 (transition structure): 13
  - 人物互动 (character interaction): 10
  - 运镜 (camera movement): 8
- **Category → registry mapping (4 targets):**
  - `transition`: 转场结构 (13) + xfade (58) = 71 entries
  - `character`: 人物互动 (10) = 10 entries
  - `style`: 运镜 (8) + 字幕花字 (22) + 素材呈现 (27) = 57 entries
  - `overlay`: 强调标注 (14) + 数据信息图 (14) = 28 entries
- Total talkcraft entries: 108, plus xfade (58) + sfx (5) = **171 total** (≥80 ✓)

## 2. gen-index.ts card registry

- `gen-index.ts` imports 127 cards (g0..g126) from `src/cards/gen/`
- tplMeta.ts covers 108 of those (remaining 19 are in `tplcards/` directory)
- Card definitions: `CardDef` interface with `id`, `name`, `category`, `kind`, `durationInFrames`, `component`, `schema`

## 3. Render pipeline

- Entry: `hevi-remotion-talkcraft/src/remotion/index.ts` → `Main` composition
- CLI: `node_modules/.bin/remotion render src/remotion/index.ts Main <out> --props=<json>`
- Talkcraft Python uses `_render()` in `hevi/layer4_legacy/talkcraft/omodul_impl/produce.py`:
  - Sets `PATH` to include node bin
  - Uses `--scale=2 --log=error`
  - Concurrency from env `HEVI_TALKCRAFT_CONCURRENCY` (default 1)
- Output is MP4; finished via `_finish_landscape()` (loudnorm) and optionally `_reframe_portrait()`

## 4. xfade transitions

- `ffmpeg -h filter=xfade` lists 58 transitions (IDs 0–57)
- Each has a name (e.g., `fade`, `wipeleft`, `dissolve`, `pixelize`, …)
- Will enumerate dynamically at registry load time

## 5. SFX assets

- Directory: `assets/audio/sfx/`
- Files: `chime.wav`, `ding.wav`, `impact.wav`, `pop.wav`, `whoosh.wav`
- 5 files, each gets a registry entry with `source=sfx`

## 6. API conventions

- Existing routers: `hevi/api/routers/templates.py` uses `APIRouter(prefix="/templates", tags=["templates"])`
- Registration: `app.include_router(router, prefix="/api")` in `hevi/api/main.py`
- Auth: `get_current_user` dependency for protected routes
- The fx router will be read-only, no DB dependency needed

## 7. Python environment

- `.venv` is symlinked to `/data/soffy/projects/hevi/.venv` (main checkout)
- Python 3.14.4, pydantic 2.13.4, fastapi 0.141.1
- ffmpeg/ffprobe at `/home/soffy/.local/bin/`
- node at `/home/soffy/.nvm/versions/node/v26.4.0/bin/`

## 8. Lint baseline

- `lint_before.txt`: 0 failures (script ran but .venv was a symlink, re-run needed)

## 9. Key constraints from task

- **Read-only** for: talkcraft source, `capabilities.py`, `explainer` router, assembler, etc.
- **New files only** in: `hevi/fx/`, `hevi/api/routers/fx.py`, `scripts/fx_preview.py`, `tests/test_fx_registry.py`
- **Modify only** `hevi/api/main.py` (import + include_router)
- No mocks/placeholders — real rendering, real ffprobe validation
- Preview: 2s MP4 (540x960 or 720x1280), 30fps, thumbnail JPG
- Batch render with `nohup setsid`, concurrency ≤2
- Contact sheet: `output/fx_previews/contact_sheet.png`, ≥4 per category

## 10. R2 motion metric (replaces the old 0-255 mean-diff)

The R1 "non-static" check used `tblend=difference` + `signalstats.YAVG` on the
0-255 luma scale and required `> 0.01` — which is only "not bit-identical"
(146/166 ok rows normalised below 0.01, so it checked essentially nothing).

R2 records, per preview, measured on the **foreground region** (talkcraft: the
centred 540x486 stage; xfade/sfx: the whole frame):

- `motion_frame_ratio` — fraction of frames with any pixel whose luma delta
  (``signalstats.YMAX`` after ``tblend=difference``) exceeds
  ``MOTION_PIXEL_THRESHOLD`` = 24/255 (~9.4% of full range). A static clip
  scores 0.0; a real animation scores well above 0.1. **Acceptance: ≥ 0.10.**
- `motion_peak_area` — largest single-frame fraction of the region whose luma
  moved by more than ``CHANGE_AREA_THRESHOLD`` = 16/255.
- `motion_mean_norm` — mean absolute luma delta / 255.
- `max_pixel_delta` — largest single-pixel luma delta seen (0-255).

Measured floors/ceilings on real files (this worktree):

| clip | motion_frame_ratio |
|---|---|
| synthetic pure-colour static (`color=0x223344`, 2s) | 0.000 |
| `tc:ink-underline` (short draw-on stroke) | 0.26 |
| `tc:strike-and-replace` | 0.11 |
| `tc:focus-dim-spotlight` | 0.20 |
| xfade previews | 0.41–0.49 |
| sfx previews (sweeping playhead) | 1.00 |

## 11. R2 talkcraft preview = full native duration, best 2s window

R1 rendered only the **first 60 frames** of each card, which mis-failed 5
"draw-on" cards whose stroke happens after 2s (native durations 2.97–3.63s).
R2 renders each card at its **full native duration**, measures the per-frame
changed-pixel area, and picks the 60-frame window with the most motion
(``_best_window_start``). Short cards (<2s) are looped as before. The stage is
scaled to *cover* 540x486 (foreground ≥50% of the 540x960 area, up from 540x304
= 31.6%) and cropped at a content-aware horizontal offset
(``_content_crop_x``) so the enlarged foreground does not clip the card's ink.