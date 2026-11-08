# Admission disclosure (2026-11-04, 3O conformance Batch 4)

This package was admitted to git from the previously untracked
worktree directory. Admission-time state, recorded here rather than
by rewriting the dated notes below:

- `oskill/shotprompt.py` is DEFERRED and NOT in this tree: its fate is
  a separate owner decision (its `compile_shot_prompt` is legislated
  LEGACY by `tests/test_prompt_compiler_single_entry.py`). The
  worktree source copy keeps the LEGACY-marked file. Callers
  (`omodul/sequence_plan.py`, `omodul/storyboard_enrich.py`)
  lazy-import it; those paths raise ModuleNotFoundError until the
  decision lands. `oskill/__init__.py` does not export it.
- `oskill/timeline.py` persistence moved: `save_timeline` /
  `load_timeline` are implemented in `obase/timeline_io.py` and
  re-exported from `oskill/timeline.py` (oskill owns no IO).
- omodul envelope gap (KNOWN, not conformant to SPEC v3.0 section 6):
  omodul functions here raise `ValueError` on bad input, return no
  status/error envelope, and declare no `_enabled_pillars`. The
  envelope adapter pattern lives in
  `hevi/capabilities/omodul_contract.py` and applies when these
  functions are registered as capabilities; until then, do not cite
  this package as section-6-conformant.
- `tests/test_avcraft_3o.py`, referenced in the P0 notes below, did
  not exist at admission: no test files were admitted with this
  package. Its 5 quick tests + 1 E2E remain unwritten in-tree.

# avcraft → canonical 3O 回流记录

本包为 hevi 自研，按 3O 分层组织；以下元素均为通用能力，日后可回流 `/data/soffy/projects/veya/platform/3O` 对应层。未从任何开源项目拷贝代码（仅思路，见 docs/3O_CAPABILITY_PLAN.md）。

## 2026-10-20 P0
### obase（建议回流 obase.ffmpeg / obase 新增 asr、llm_local）
- `obase/media.py`：`ffmpeg_bin/ffprobe_bin`（env HEVI_FFMPEG/HEVI_FFPROBE → PATH → /home/soffy/.local/bin）、`probe_duration`、`has_video`、`parse_silencedetect`（末尾未闭合静音补到时长）、`run_silencedetect`、`render_keep_ranges`（select/aselect + setpts/asetpts，filter 写入脚本文件以支持上百区间）。
- `obase/asr_runtime.py`：`transcribe_words`（faster-whisper，device=cpu，int8，VAD，词级时间戳；默认模型 /data/soffy/models/faster-whisper-base，env HEVI_WHISPER_MODEL/HEVI_WHISPER_THREADS）。
- `obase/llm_local.py`：`ollama_generate`（仅本地 HEVI_OLLAMA_URL，默认模型 llama3.2:3b，env HEVI_AVCRAFT_LLM；不读取任何云 key）。
### oskill（纯函数，建议回流 oskill）
- `oskill/timeline.py`：schema `avcraft.timeline/v1`；`build_pause_timeline`（margin 防吞字、min_pause、keep_pause_max 保留节奏、min_speech 去咔哒）、`keep_ranges`、`timeline_set_keep`、`save/load_timeline`。
- `oskill/subtitle.py`：`segment_sentences`（句末标点/停顿间隙/长度/时长切分 + 碎句合并，CJK/拉丁自适应）、`translate_cues`（批量 8 句 + 前文上下文 + JSON 输出解析 + 逐句兜底 + 术语表确定性替换；llm 注入）、`to_srt`（src/tr/bilingual）、`to_ass`（Src/Tr 双样式）。
### omodul（建议回流 omodul）
- `omodul/pause_cut.py`：`pause_cut`、`export_timeline`，CLI `python -m hevi.avcraft.omodul.pause_cut`。
- `omodul/bilingual_subs.py`：`bilingual_subtitles`，CLI `python -m hevi.avcraft.omodul.bilingual_subs`。
### 测试
- `tests/test_avcraft_3o.py`：5 个快测（纯函数 + ffmpeg 合成音视频端到端）+ 1 个 E2E（HEVI_AVCRAFT_E2E=1）。

## 2026-10-20 P1（无新模型、CPU、零付费）
### obase
- `media.py` 新增：`burn_subtitles`（.ass→ass 滤镜保样式，其余→subtitles+force_style，fontsdir 自动指向 Noto CJK）、`mux_soft_subs`（mp4→mov_text，mkv→保留 srt/ass，多轨语言/默认轨）、`list_streams`、`parse_visual_detect`/`run_visual_detect`（一次解码跑 blackdetect+freezedetect+scdet，先缩到 320 宽）。
- `shot_table.py` 新增：schema `avcraft.shot_table/v1` + `validate_shot_table`（必填/景别枚举/人物场景引用/时长/一镜一事/continue_from 顺序）。
### oskill
- `timeline.py` 扩展（向后兼容 v1，可选 `cues/markers/ops`）：`timeline_from_cues`、`split_clips_at`、`set_region_keep`、`merge_cut_signals`（黑场剪；静止段剪但保护有声区±speech_pad；scene 只做切分点/markers）、`apply_ops`（delete/restore/retext/retime/drop/keep，可回放 op log，restore 精确回滚）、`map_time`、`render_cues`（源→成片时间映射，部分被剪自动裁切）。
- `subtitle.py` 新增 `repair_breaks`：规则化断句修补（术语不跨句、英文虚词/介词不结尾、数字+单位、大写专名链、中文“的/地/得”拉下句双字词、介词下移、数字+量词）；有译文的句子标 `tr_stale`，不调模型。
- `shotprompt.py` 新增（seedance-2.0 MIT 方法论，纯文本）：`compile_shot_prompt`（机位→画内→站位→续接末帧→动作→视线→背景→光→台词→末帧→lock line，超长先砍背景/台词，lock 永不砍）、`lock_line`、`new_bible`/`update_continuity_bible`（只记已接受片段事实）、`diagnose_retake`（问题→单一变量，已试过换下一个）、`apply_retake`（只改一个字段）、`retake_budget`（每镜/整片上限，超限给 split_shot/accept_best）。
### omodul
- `edit_session.py`：`init_session`（cues + 可选 pause 时间线 + 断句修补 + 画面信号）、`export_session`（成片 + src/tr SRT + 双语 ASS + 硬字幕 + mp4/mkv 软字幕 + 会话时间线），CLI init/ops/export。
- `sequence_plan.py`：`sequence_plan`/`record_take`/`prompts_markdown`，状态 `avcraft.sequence/v1`；下一镜仅在 continue_from 被接受后 ready，按已接受末帧续写；拒绝→单变量重拍+预算。
### 测试/样例
- `tests/test_avcraft_3o_p1.py`：8 个快测（纯函数 + ffmpeg 合成黑场/测试图/正弦音端到端）。
- `scripts/avcraft_p1_demo.py` → `output/avcraft_p1/`。
- 仍只借鉴思路，未 vendor 任何上游代码；未接 Seedance 或任何付费生成。

## 2026-10-20 P1 剩余项（无新模型、CPU、零付费）
### obase
- `vision.py`（新，依赖 .venv 的 cv2/numpy）：`audio_energy`（ffmpeg→s16le→RMS dBFS/窗）、`analyze_frames`（抽帧：帧差运动量+运动质心+人脸框；人脸检测仅用本机已有 YuNet `/data/soffy/models/opencv/face_detection_yunet_2023mar.onnx`（env HEVI_YUNET_MODEL）→ cv2 自带 Haar → 无；每张脸附嘴部区域帧差 mouth_act，作“谁在说话”的无模型近似）。
### oskill
- `highlight.py`（新）：`candidate_windows`（整句起止窗）、`score_highlights`（音量/语速/场景密度/运动/关键词+openshorts.virality.score_text 钩子/句子完整性，缺失信号权重归零重归一，非重叠 top-N，每段 `reasons[]`）、`highlights_to_timeline`（markers kind=highlight + 保留区 + 区外 cues 标删，字幕自动跟随）。
- `reframe.py`（新）：`crop_size`、`pick_targets`（脸→保持 hold_s→运动质心→中心；多脸按面积+连续性+说话活动）、`smooth_crop_path`（死区+EMA+限速）、`per_frame_x`、`sendcmd_script`、`path_stats`。
- `moderation.py`（新，seedance-2.0 方法论）：`moderation_prescreen`（12 类中英规则词表、严重度、改写建议；中文词中文改写、英文形容词形态改写；未成年+色情/暴力组合直接判不可提交；extra_terms/allow 项目自定义）。
- `shotprompt.compile_shot_prompt` 新增 `prescreen=True / auto_rewrite=False / moderation_opts`，结果附 `moderation`（向后兼容，新增键）。
### omodul
- `highlight_clips.py`（新）：信号采集→评分→高光时间线→每段成片+SRT+单段时间线（可选 `vertical` 竖版并删横版中间件），CLI。
- `reframe_vertical.py`（新）：抽帧检测→平滑轨迹→ffmpeg `sendcmd`+`crop`+`scale`→9:16；时间轴不变，cues 直接出竖屏 ASS 并烧录；输出 `avcraft.crop_path/v1`，CLI。
- `edit_session.init_session` 新增开放参数 `scene_threshold/still_sensitivity/still_min/black_min/visual_params` + `visual_detect_params()`；CLI `--scene-th --still-sens --still-min --black-min`。
- `sequence_plan.prompts_markdown` 显示 moderation 命中与提示。
### 测试/样例
- `tests/test_avcraft_3o_p1b.py`：8 个快测（高光对齐/理由/缺信号/写入时间线、说话人+平滑+回退、moderation 规则/改写/接入、init_session 开放参数 ffmpeg 合成端到端、竖版无脸回退端到端）。
- `scripts/avcraft_p1b_demo.py` → `output/avcraft_p1b/`（3.9M）。
- 仍只借鉴思路（VideoHighlighter、ClipsAI、seedance-2.0、Auto-Editor），未 vendor 上游代码。

## 2026-10-22 · Motion Prompt 接入（showheyohtaki/motion-prompt，MIT (c) 2026 Shohei Ohtaki）
- vendor 精简词条：`data/motion_prompt/{catalog.json,zh_alias.json,LICENSE,NOTICE.md}`（保留 MIT 声明；不含上游 Canvas 代码）。
- obase：`motion_catalog.py`（load/get/element_code，带 credit）、`text_layer.py`（Pillow 透明文字层 + char_x）。
- oskill：`motion.py`（`motion_search` 中英日检索、`shot_vocab_inject`/`vocab_line`、`motion_spec_to_ffmpeg` 22 个动效→ffmpeg 近似：title/vf/xfade）；`shotprompt.compile_shot_prompt` 遇 `shot["vocab"]` 追加 `Terms:` 行，超长时压成仅术语名保底（向后兼容）。
- omodul：`title_card.py`（标题卡 CPU 合成，pop-in/typewriter/mask-reveal/fade-in 实测可用；pop-in 修正极小缩放时高度=0）、`storyboard_enrich.py`（分镜表→术语充实+提示词，CLI）。
- 测试 `tests/test_avcraft_3o_motion.py`（10 项）；样例 `output/avcraft_motion/`。
