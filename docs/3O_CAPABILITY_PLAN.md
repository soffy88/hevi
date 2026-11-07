# hevi 3O 能力内化计划（2026-10-20）

原则：不安装/不 vendor 开源整仓，只借鉴思路与算法，按 3O 分层写成 hevi 自有代码。GPL/AGPL 项目零拷贝。
约束：仅 CPU；零付费 API（禁 OpenAI/DashScope/MiniMax）；模型只用小号（faster-whisper base/small int8、Ollama ≤3B 已装）；/data 余量约 18G（df）但按 5G 预算控制。
落点：新域包 `hevi/avcraft/{obase,oskill,omodul}`（obase=外部运行时适配，oskill=纯函数技能，omodul=编排入口）。
变更记录：`hevi/avcraft/UPSTREAM-3O.md`（供日后回流 canonical 3O `/data/soffy/projects/veya/platform/3O`）。

## 现状（hevi 已有，可复用，不重复造）
- ffmpeg 7 静态：响度归一 / silencedetect（verdict/silence_probe.py、layer4_legacy/review/oprim_impl/audio.py，仅做质检，未用于剪辑）。
- ASR：hevi/analysis/transcribe.py、ingest/video_transcript.py（faster-whisper，输出 SRT；无断句/翻译/双语）。模型 /data/soffy/models/faster-whisper-base。
- 字幕后处理/术语：ingest/subtitle_polish.py、ingest/video_localize.py、creative/layer4/translation.py（含 glossary）。
- 配音：dub/{translate,_synth,_mux}.py、OpenVoice CPU :8091、VOICEBOX。
- 说话人：ingest/speakers.py（pyannote 依赖，CPU 重）。
- 短视频/高光：openshorts/{clip_engine,virality}.py、oskill highlight_detection_algorithm、oprim crop_video_to_portrait（中心裁切，无说话人跟随）。
- 时间线导出：editable/{capcut_cli,jianying}.py（导出剪映，非 Agent 可改的通用时间线）。
- 本地 LLM：Ollama 实际只有 llama3.2:3b、xiaoya-cpm5-2b（**qwen2.5:7b 未安装**，4.7G，受空间限制本轮未拉）。

## 缺口 → 能力映射表
| # | 缺口 | 借鉴来源（许可证） | 层 | 函数名 | CPU 可行性 | 优先级 | 状态 |
|---|---|---|---|---|---|---|---|
| 1 | 按音量剪停顿，输出可编辑时间线并导出 | Auto-Editor（Unlicense）思路 + BaoCut 时间线 | obase | `run_silencedetect` `parse_silencedetect` `render_keep_ranges` `probe_duration` | 高（纯 ffmpeg） | P0 | ✅ 本轮 |
| | | | oskill | `build_pause_timeline` `keep_ranges` `timeline_set_keep` `save/load_timeline` | 高 | P0 | ✅ |
| | | | omodul | `pause_cut` `export_timeline`（CLI） | 高 | P0 | ✅ |
| 2 | ASR→断句→翻译→双语 SRT/ASS | VideoCaptioner（GPL-3，仅思路）/ VideoLingo（Apache-2.0，思路） | obase | `transcribe_words`（faster-whisper int8）`ollama_generate`（仅本地） | 中（base 模型约 0.3–1×实时，视负载） | P0 | ✅ 本轮 |
| | | | oskill | `segment_sentences` `translate_cues`（批量+上下文+逐句兜底+术语强制）`to_srt` `to_ass` | 高 | P0 | ✅ |
| | | | omodul | `bilingual_subtitles`（CLI） | 中 | P0 | ✅ |
| 3 | 按运动/画面变化剪（静止画面、黑场） | Auto-Editor motion 思路 | obase `run_scene_motion`（ffmpeg `freezedetect`/`scdet`/`blackdetect`）；oskill 时间线合并多信号 `merge_cut_signals` | 高 | P1 | 已做 2026-10-20（obase run_visual_detect/parse_visual_detect；oskill merge_cut_signals，有声区保护） |
| 4 | LLM 语义断句 + 字幕校正（错字/标点/术语） | VideoLingo、VideoCaptioner 思路 | oskill `semantic_resegment` `proofread_cues`（注入 llm，长句才调用） | 中（3B 本地，慢） | P1 | 部分：规则化断句修补 oskill repair_breaks 已做 2026-10-20；LLM 语义断句/校对待做 |
| 5 | Agent 逐句编辑时间线（删句/改字/重排→重新导出），字幕与剪辑同一时间线 | BaoCut（思路） | oskill `timeline_from_cues` `apply_ops(tl, ops)`（delete/trim/move/retext，可回放 op log）；omodul `edit_session` | 高 | P1 | 已做 2026-10-20（oskill timeline_from_cues/apply_ops/render_cues/map_time；omodul edit_session） |
| 6 | 字幕烧录/软挂 | VideoCaptioner 合成思路 | obase `burn_subtitles`（ffmpeg subtitles/ass 滤镜）`mux_soft_subs` | 高 | P1 | 已做 2026-10-20（obase burn_subtitles/mux_soft_subs） |
| 7 | 多信号高光 + 入选理由 | VideoHighlighter（思路） | oskill `score_highlights`（音量峰、语速、关键词、场景切、笑声近似）返回 `reasons[]`；复用 openshorts/virality | 中 | P1 | 已做 2026-10-20（obase vision.audio_energy/analyze_frames；oskill highlight.score_highlights/highlights_to_timeline，整句边界+reasons；omodul highlight_clips） |
| 8 | 转录找片段 + 横转竖跟随说话人 | ClipsAI（MIT，思路） | oskill `find_clips_by_transcript`；obase `face_track_cpu`（OpenCV Haar/YuNet 小模型）；oskill `smooth_crop_path`；omodul `reframe_vertical` | 中（YuNet CPU 可） | P1 | 已做 2026-10-20（obase vision YuNet→Haar→无 + 嘴部帧差说话人近似；oskill reframe.pick_targets/smooth_crop_path；omodul reframe_vertical，sendcmd crop→9:16，字幕兼容）；转录找片段并入 score_highlights |
| 9 | 说话人分离（轻量） | pyVideoTrans（GPL-3，仅思路） | obase `speaker_embed_cpu`（resemblyzer/ECAPA 小模型，需评估体积）；oskill `cluster_speakers` | 中低（模型体积待评估） | P2 | 待做 |
| 10 | 分角色配音 + 时长同步（atempo/对齐） | pyVideoTrans、VideoLingo 配音思路 | oskill `fit_duration_plan`（按 cue 时长算语速/截断）；omodul `dub_by_speaker`（复用 dub/、OpenVoice :8091） | 中（OpenVoice CPU 慢） | P2 | 待做 |
| 11 | 分镜提示词编译（shot table：机位/画内/视线/动作/他人/光/末帧 → 提示词） | Emily2040/seedance-2.0（MIT，仅方法论，**不接 Seedance 付费生成**） | obase `ShotTable` schema；oskill `compile_shot_prompt` | 高（纯文本） | P1 | 已做 2026-10-20（obase shot_table；oskill compile_shot_prompt） |
| 12 | 每镜 lock line（重复光/人/站位保证跨镜一致）+ continuity bible、按已接受片段续写 | 同上 | oskill `lock_line` `update_continuity_bible`；omodul `sequence_plan`（多片段编排、基于已接受片段续写） | 高 | P1 | 已做 2026-10-20（oskill lock_line/update_continuity_bible；omodul sequence_plan） |
| 13 | retake protocol（单变量重拍 + 次数预算）与 moderation 预筛 | 同上 | oskill `diagnose_retake`（一次只改一个变量）`retake_budget` `moderation_prescreen`（本地规则+小模型）；omodul 并入 `sequence_plan` | 高 | P1 | 部分：diagnose_retake/apply_retake/retake_budget + sequence 并入已做；moderation_prescreen 已做 2026-10-20（oskill moderation，规则词表+改写，接入 compile_shot_prompt/prompts_markdown）；小模型复核未做 |

## 许可证备注
- GPL-3：VideoCaptioner、pyVideoTrans —— 只读文档/思路，hevi 代码为独立实现，未复制任何源码。
- Auto-Editor（Unlicense）、VideoLingo（Apache-2.0）、ClipsAI（MIT）、seedance-2.0（MIT）：本轮仍只借鉴思路，未 vendor。
- VideoHighlighter、BaoCut：许可证未逐一核实，按“仅思路”处理。

> 2026-10-20 补：init_session 开放参数 scene_threshold / still_sensitivity(0–1|low/medium/high→freezedetect -70..-40dB) / still_min / black_min / visual_params（omodul edit_session.visual_detect_params，CLI --scene-th --still-sens --still-min --black-min）。

## 2026-10-22 补：Motion Prompt 动效词汇（MIT，vendor 精简词条）
| # | 能力 | 来源 | 落点 | 状态 |
|---|---|---|---|---|
| 14 | 动效/运镜/光线标准术语检索 + 注入分镜提示词 | showheyohtaki/motion-prompt（MIT (c) 2026 Shohei Ohtaki） | obase motion_catalog；oskill motion.motion_search/shot_vocab_inject；shotprompt `Terms:` 行；omodul storyboard_enrich | 已做 2026-10-22 |
| 15 | 标题卡动效（pop-in/typewriter/mask-reveal/fade-in）+ 质感/转场 ffmpeg 近似 | 同上（hevi 自写 ffmpeg 表达式） | obase text_layer；oskill motion_spec_to_ffmpeg；omodul title_card | 已做 2026-10-22（CPU；未做 node-canvas 逐帧原样渲染） |
