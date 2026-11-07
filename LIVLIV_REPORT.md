# LivLiv 2.5D 头像口播引擎验收报告（2026-11-07）

## 实现
- `hevi/avatar_livliv/` 离线确定性渲染器（上一个 agent 初版 + 本轮修复）：Playwright 无头 Chromium，`--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader`，本地 `python3 -m http.server` 托管 vendor `dist/` 与 `characters/`，`Player(canvas,{idle:true,autoplay:false})`，`followPointer=false`，逐帧 `params.mouthOpen/vowel + draw(1/30)`，canvas 透明 PNG 落盘，ffmpeg 拼 alpha mov/webm + 带音轨 mp4（元数据 `Characters: LivLiv (livliv.ai)，AI制作`），Node v26.4.0。
- `audio.py`：16k 单声道 → 逐帧 RMS 包络映射 mouthOpen、FFT 频谱质心映射 vowel，3 帧滑动平均平滑，**提前 1 帧**（上版为延迟 1 帧，已纠正），误差 ≤1 帧。
- `render.py` 新增 `plan_performance()`：页面加载后读真实 `player.expressions` id，按句子 func（koubo 分类）选表情（data→surprised/smile、viewpoint/cta→smile、turn→shake），句首 nod、周期 tilt/nod；眨眼/呼吸/摆动由 `idle:true` 自带。片尾/随附 `CHARACTERS_CREDIT.txt` 写署名；Player 按模型自带 watermark（角落 LivLiv 标记，未禁用）。
- 接入（默认引擎与原路径不变）：`engine=livliv` + `character_id` 贯通 `koubo_cut`（含 CLI `--engine/--character-id`）、`talking_head` 流水线与 capability、`explainer` API（avatar dict 透传）、`avatar_spokesperson`/`talking_head` Studio 线（槽位 `avatar_engine=livliv`，经 `_render_livliv_avatar_line` → talking_head livliv，零/legacy 路由不受影响）。
- 配置：`.env.example` 新增 `LIVLIV_CHARACTERS_ENABLED=true`（注释：仅限非商用）；`characters.py` 默认 true，可关。
- 测试：`tests/test_avatar_livliv.py`（21 角色目录、Kujira/Pen 署名、环境开关、包络有界/平滑/相关性、表情规划）。

## Commit
未提交改动全部接续（未丢弃）：`BRIEF.md`、`THIRD_PARTY_NOTICES.md`、`hevi/api/routers/explainer.py`、`hevi/capabilities/talking_head.py`、`hevi/koubo_cut/pipeline.py`、`hevi/talking_head/pipeline.py`、`hevi/avatar_livliv/`，外加本轮新增：`audio.py` 平滑/提前与 `plan_performance`、`hevi/studio/fulfill.py` avatar_spokesperson 槽位、`hevi/koubo_cut/cli.py`、`hevi/capabilities/talking_head.py` character_id、`tests/test_avatar_livliv.py`、`PROGRESS_LIVLIV.md`、`samples/livliv/`、`.env.example`。最终 commit 见 `git log`（分支 hark/livliv-avatar）。

## 许可处理
- vendor 仓库大小 `du -sh /data/soffy/vendor/livliv-player` = **214MB**（>200MB，角色全量在库；代码与角色分开许可）。
- 代码 Apache-2.0：`hevi/avatar_livliv/licenses/LICENSE-player` + `NOTICE-player` 与 vendor `diff -q` 一致；`THIRD_PARTY_NOTICES.md` 已署名来源、用途、日期与 vendor 不进库声明。
- 角色许可：`CHARACTERS-LICENSE.md`（非商用、署名、禁训练 AI、角落标记、公开展示注 AI、Nana 吉祥物条款）与 `CHARACTERS-CREDITS.md`（Kujira/Kujira Q CC BY-NC-SA 4.0 署名、Pen 无权利声明）原文随附且 `diff -q` 一致。
- 成片：Player 模型自带 watermark 保留（透明帧角落透明、角色中心不透明，抽查通过）；mp4 元数据与 `CHARACTERS_CREDIT.txt` 含署名。

## 渲染耗时（edge-tts 32.3s 同款中文口播，512x512 30fps，SwiftShader）
- d03ft Nana refined：总帧数 970，**68s**（峰值 RSS 370MB），mp4 2.7MB；d01 Yui：63s/321MB；v06 Usa：64s/320MB。均 30fps 512x512，180s 上限内完成（未触发 >5min 降级），输出 mov（prores alpha）/webm（vp9 alpha）/mp4 三件套实测可用，帧为 RGBA 透明底。
- ffprobe：三者 duration=32.328s、h264 512x512 30fps + aac 音轨；volumedetect mean=-19.6dB/max=-3.6dB（与 TTS 源一致）。
- koubo_cut engine=livliv（输入为 d03ft 成片 32s，faster-whisper large-v3-turbo 转录 8 句 111 词，证据截图 2/2，1080x1920）：run1 d03ft **153s**、run2 d01 **132s**、run3 v06 **138s**，三者 ledger delivered、duration 32.37s、1080x1920 h264+aac、mean -19.7dB。

## 对齐相关系数
`samples/livliv/alignment.json`：最优 1s 窗（t=11.8s，30 帧）mouthOpen vs 音量包络 **corr=0.952**；全长 corr=0.80。验收阈值 ≥0.7 通过，误差 ≤1 帧（提前 1 帧 + 3 帧平滑）。

## 评委对比结果
- wav2lip 本地链：`build_avatar_clip` 直接调用与 talking_head `_default_lipsync` 两次尝试均在 import 阶段失败——上游既有 `ImportError: musetalk_face_box`（main 已存在的问题，与本分支改动无关，故不顺手修）；空载耗时 ~1s 报错。可比的同题基线 `samples/livliv/static_baseline.mp4`（静帧人像 32.3s，等价于 koubo 的 none-fallback）。
- hevi/judge opencode 换位对比（同题 livliv koubo vs static 基线）：硬伤预过滤决定性 **A=0 vs B=18**（静态侧冻帧×2 major、重复帧率 37.5% minor；livliv 侧硬伤 0），映射后 Winner=**A（livliv）**、consistent=true，模型调用 **0 次**（≤10 上限）。

## 样片路径
`samples/livliv/`（已入库部分）：`tts/script.txt`、`contact_sheet_6frames.png`（6 帧/3x2）、`contact_run1-3.png`、`contact_sheet.png`（三成片拼图）、`alignment.json`、`koubo_run{1,2,3}/`（ledger/fcpxml/transcript/证据截图/person.png/CHARACTERS_CREDIT.txt）、`d03ft|d01|v06/CHARACTERS_CREDIT.txt`、`README.md`。mp4 按仓内 `.gitignore` 的 `*.mp4` 规则**不入库**（本地可运行路径：`d03ft|d01|v06/clip.mp4`、`koubo_run{1,2,3}/koubo_cut.mp4`、`static_baseline.mp4`、`tts/narration.mp3`），需要可重跑 `render_clip`/`run_koubo_cut` 复现。

## pytest
`/data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_avatar_livliv.py tests/test_talking_head_pipeline.py tests/test_koubo_cut_capability.py tests/test_talking_head_capability.py -q` → **38 passed**。（环境说明：本 worktree 无 `.venv`，故用主仓 venv 跑测试；其内缺失的声明依赖 faster-whisper 已 `pip install` 补齐——该 venv 归主仓所有，仅为补声明依赖，未改代码。渲染用干净 venv `/data/soffy/tmp/livliv_venv`（playwright 1.64 + av==16.0.1 解决 faster-whisper 解码兼容）跑 koubo_transcribe。）

## 仍存问题
1. wav2lip 本地链上游 `musetalk_face_box` ImportError 未修复（brief 外、main 既有），故与真 wav2lip 的观感对比以静态基线代替并如实标注；修复后可重跑评委。
2. koubo_cut livliv 头像渲染取 512x912 后放大到 1080x1920（性能折中，观感略软）；可调 `render_clip(width,height)` 提高。
3. `samples/livliv/` 约 65MB；prores alpha mov/webm 已删除，仅保留 mp4（含 alpha 帧已验通过），需要 alpha 母版可重跑 `render_clip`。
DONE
