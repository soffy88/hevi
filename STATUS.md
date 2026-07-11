# Hevi · STATUS

> Canonical project status. Read at the start of any non-trivial task.
> Last updated: 2026-07-11
> Sources: git log, `.claude` project memory (tongjian-pipeline-handoff, deploy-topology, e2e-local-llm-json-blocker, gpu-pcie-fallen-off-bus).
> This file tracks *what's true now*, not design. Specs live in `docs/specs/`.

---

## 🔒 Never (hard constraints — do not violate)

- **Never reboot this shared host without asking soffy.** ~90 containers from unrelated projects (aegis/aii/helios/mneme/stratum-aii…) share one RTX 3080. RTX 3080 Xid 79 (GPU fell off PCIe bus) recurs almost every boot even with `pcie_aspm=off` — likely hardware, not a hevi bug.
- **Never route json2video/flux-schnell to character/portrait generation.** Confirmed 2026-07-08: technically succeeds but generates unrelated buildings/landscapes for Chinese person prompts. `hevi/image/json2video_scene_service.py` is scene-background-only (no-character). Keep it out of `resilient_image_gen` person fallback chains.
- **Never let dialogue exist without provenance.** Tongjian/cinematic台词 must be either paraphrased from `chapter_ir.quotes` (has `quote_id`) or explicitly `BeatDialogue.is_performative=True`. "Neither quote_id nor is_performative" = violation. This is the史实 red-line CG2.5 gate enforces — preserve that check in any edit.
- **Never rebuild main branch state blindly after a PR merge.** ff-merge `origin/main` into local `main` after each merge or the working tree drifts into a stale superposition. (see memory: git-sync-main-after-merge)
- **Never assume merging a PR / applying a migration updates the public site.** `hevi.uex.hk` is the `hevi-cftunnel` docker-compose stack (build-time image snapshot). Must `build` + `up -d` `hevi-api hevi-web` after code/migration. DB-ahead-of-image migration set → API crash-loop. Production op — confirm before running.
- **Never swap the SDXL fp16 VAE back to the official one** (`_sdxl_worker.py` uses `madebyollin/sdxl-vae-fp16-fix`; official needs fp32, no VRAM headroom). And never merge the IP-Adapter vs plain-txt2img code paths without re-testing (attention-slicing + IP-Adapter crashes).

---

## 🔄 In Progress

- **SPEC-001 短剧/漫剧通道 — FROZEN, 阶段 1 in progress.** Eval + 4 settled decisions at `docs/specs/SPEC-001-shortdrama-eval.md` (2026-07-11). Decisions: (1) drop Subject3D, rest on 2D CLIP lock; (2) build B0 by generalizing tongjian L0-L2; (3) 剧集规划器 is a new planning layer (not Producer ext); (4) LLM via `qwen_cloud` (already wired + verified). **阶段 1 min-loop** (eval §5): B0 story graph → SeasonPlan splits 3 episodes → reuse Director/L1 per-episode → read-only Season Board. G1 gate: short novel → 3 episodes → cross-episode identity consistent (identity_distance ok via 2D CLIP).
  - ✅ **Step 1 — B0 story parsing done.** New module `hevi/storygraph/` (schemas + extract), novel-general generalization of tongjian L0. Reuses tongjian's deterministic span/ID/hallucination-guard machinery (imports `_find_span`/`_call_llm_json` from `chapter_ir`, the established shared-helper convention). StoryGraph per SPEC §2.3 (relationships/arcs structured but deferred to阶段 2). Selects `qwen_cloud` LLM explicitly. `tests/test_storygraph.py` 4/4 green; tongjian no regression. Not yet committed.
  - ✅ **Step 2 — Episode Planner (剧集规划器) done.** New module `hevi/season_planner/` (schemas + planner), a new planning layer (not Producer ext). `build_season_plan(story, target_episodes)` mirrors tongjian L1: LLM splits timeline into N episodes (best-of-N + LLM-judge), code deterministically assembles characters_present/locations/beats from StoryGraph. `gate_season_plan()` = SPEC §3.4 pre-gen self-critique (all deterministic): event coverage/no-dup/no-orphan, per-episode beat completeness (no all-过场 episode), episode-count feasibility, character non-discontinuity (主角凭空消失). Reuses tongjian `GateResult` + `_call_llm_json`. Selects `qwen_cloud`. `tests/test_season_planner.py` 8/8 green. Not yet committed.
  - ✅ **Step 3 — dispatch to existing Series/Director done.** New adapter `hevi/season_planner/dispatch.py` (does NOT modify `series_service`). `dispatch_season(plan, story, series_service, subject_id_map, style_pack_id, spec)`: creates one Series (season = series, char group from subject_id_map, StylePack locked), then per EpisodePlan calls existing `create_episode(topic=brief)`. `episode_brief()` reduces the rich EpisodePlan → a narrative topic text the existing Director consumes (title + emotion arc + present characters+descriptions + ordered event summaries with beats + own-episode 原文 quotes). Cross-episode identity rests on Series subject_ids (2D CLIP lock per decision 1). `tests/test_season_dispatch.py` 4/4 green; `test_series.py` no regression. Not yet committed.
  - **Data flow now wired end-to-end (skeleton):** 小说手稿 → `storygraph` → `season_planner` → Series + N episode-tasks → existing Director/L1. Real run (spend) needs: built Subjects for characters (subject_id_map) + generation infra (GPU/cloud video). Deferred per convention until soffy triggers.
  - ✅ **Step 4 — read-only Season Board frontend done** (committed `adaaa99`). `hevi-web/src/components/season/SeasonBoard.tsx` + route `/season-board` + TopNav entry (短剧) + `.hevi-sb*` styles. Read-only: 季(Series) list → 角色组/StylePack/进度 panels → 集卡片 (status badge, live SSE progress via `useSSEProgress`+`taskApi.progressUrl`, expand → cover-poster video). Pure reuse of `seriesApi`/`taskApi`.
  - ✅ **Step 4b — 幕/镜 drill-down (migration-free)**, PR #21 follow-up. 幕: dispatch stashes `EpisodePlan` into `task.config_json["episode_plan"]` via create_episode overrides (JSONB round-trip, no migration); board renders beat chips. 镜: new read-only `GET /api/tasks/{id}/shots` (owner-auth + existing `repo.get_shots`, projects shot_index/status/consistency/passed/diagnosis); board fetches on expand and renders per-shot cards. **Bug fixed in Step 4:** episodes endpoint returns raw `video_tasks` rows so task id = `ep.id` (not `ep.task_id`); board now uses `ep.task_id ?? ep.id` for video/cover/progress/shots. Backend `test_tasks.py` +2 (51 passed subset); tsc + lint clean. Not yet committed.
  - ⏳ **G1 acceptance** (eval §5): real short novel → 3 episodes → per-episode output → cross-episode identity consistent (identity_distance via 2D CLIP). Needs Subjects + spend.
- **HEVI-EXEC-01 M3 (场景生成闭环)** — code complete + mock full-chain verified 2026-07-09, zero real spend. New module `hevi/cinematic/` (scene_adapt/shot_planning/video_gen/platform_binding). Not yet: real `vidu_reference_to_video` call (never smoke-tested — costs money, awaits soffy `--real`), lip-sync (explicitly not implemented). Next per handoff: M4.

---

## ✅ Done

- **Tongjian pipeline L0–L8** — full 9-layer 资治通鉴→video pipeline, each layer + gate, committed (`a0478a7`…`e97e374`). Self-media explainer channel + Tongjian console shipped (`5306070`). json2video cloud provider for character-free scene backgrounds (`da92410`).
- **HEVI-EXEC-01 M1** (vault MinIO+pgvector asset store, `2aa0ec8`).
- **HEVI-EXEC-01 M2** (identity pack pipeline, `6ce6796`) — 智伯/韩康子/段规 all `lifecycle=validated`, `stability_check=3/3`, vault `identity/*@0.1.2`. Built on local CPU, $0.00 spend.
- **Audio real-path bugs fixed** — vibevoice export monkeypatch in worker subprocess (`cff2722`), `reference_audio`→`voice_samples` kwarg translation (`976c4f1`), CosyVoice2 provider (`7a75596`). Real synthesis verified (non-silent, non-clipped audio).
- **Vidu Reference-to-Video provider** (`04217ac`) — real REST client, registered `video/vidu`. Mock-tested only; real API never called.
- **Env fixed:** ffmpeg/ffprobe + CJK font (wqy-zenhei) installed to `~/.local/` (no root). Tests 702 pass / 0 skip. **Re-do if this environment is rebuilt** — user-level installs, not persisted.

---

## 🚨 Needs Human

**SPEC-001 freeze decisions — all 4 settled 2026-07-11** (see `docs/specs/SPEC-001-shortdrama-eval.md` §6). Nothing pending here; LLM prerequisite resolved via `qwen_cloud` (the prior `e2e-local-llm-json-blocker` memory is now stale — updated with resolution).

**Standing infra blockers** (any one unblocks GPU/cloud re-runs):
- Local GPU needs host reboot to recover (shared host — can't reboot without soffy).
- fal.ai account balance exhausted (2026-07-08, 403 Exhausted balance) — needs top-up.
- CosyVoice "default seed voice" chicken-and-egg is worked around (identity_pack default tts_fn now uses edge_tts), but真实高质量 default voice still needs a human voice sample if desired.
