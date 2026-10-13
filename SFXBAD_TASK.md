# SFXBAD_TASK — W4 音效库 + Q2 坏片回归集（分支 feat/sfx-badclips，只新增文件）

本单元**只新增文件**，不修改任何已有源码文件（例外：无）。

## A. W4 音效库
- 现状：`assets/audio/sfx/` 只有 5 个 wav（chime/ding/impact/pop/whoosh），不要改它们。
- 新增 `assets/audio/sfx/library/<type>/<id>.wav`（48kHz 或 44.1kHz，16bit，单/双声道统一）+ `assets/audio/sfx/library/manifest.json` + `assets/audio/sfx/library/manifest.schema.json`。
- 生成器 `scripts/sfx/gen_sfx_library.py`（numpy/scipy 或 sox/ffmpeg aevalsrc，固定随机种子，可复现）：参数化合成 whoosh/swoosh、riser、downer、hit/impact、boom、glitch、click/tick、pop、ding/chime、typewriter、camera-shutter、heartbeat、swipe、sparkle、bass-drop、notification 等类型的变体，**总数 ≥60**。可选：下载免费 CC0 音效（经代理能拿到就用，记录来源 URL 和许可；拿不到就全用合成，如实写）。
- manifest 每条：`id`、`file`、`type`、`mood`（如 tense/joyful/comic/epic/calm/tech）、`tags`、`duration_s`、`sample_rate`、`lufs_integrated`（实测，短于 0.4s 的写 null 并说明）、`true_peak_dbfs`、`source`（synth:<参数>|cc0:<url>）、`sha256`。
- 响度：时长 ≥0.5s 的统一到 −16 LUFS（ffmpeg loudnorm 两遍或自行增益），实测 ebur128 积分响度 −16±1.5；<0.5s 的用峰值归一，峰值 ≤ −1 dBFS；全部无削波（峰值 < −1 dBFS）。时长 0.1–4s。
- 测试 `tests/test_sfx_library.py`：≥60 文件、ffprobe 合法、时长范围、峰值、≥0.5s 的 LUFS 范围（真实 ffmpeg ebur128 测）、manifest 过 schema（jsonschema 若无则手写校验）、sha256 与文件一致、生成器重复运行 sha 稳定（可只抽 3 个重跑比对）。
- 不注册进 `hevi/fx`（T1 另一个单元会读你的 manifest.json）。不改 `hevi/api/routers/audio_library.py`。

## B. Q2 坏片回归集
- 参考配方（已上传到当前目录 `OMQUALITY_r4_make_bad_clips.sh`，来自 omquality r4 复核，11 条坏片：全噪声、局部 glitch、宏块 qp51、mpeg2 宏块、全绿屏、局部绿闪、下半灰块、黑+静音、音频静音空档、音频削波、click/pops）。它依赖 hevi-quoteimage 的真实 NASA 源片；fixture 版必须**不依赖其它 worktree**：默认用 lavfi 生成确定性基底（testsrc2 + 运动 + 正弦/噪声音轨混合，14s，1280x720，24fps），可选 `--base <mp4>` 用真实片。
- 新增 `tests/fixtures/qa_corpus/make_corpus.py`（或 .sh + py 包装）：再生 r4 的 11 条 + 新增 ≥6 条：字幕出框（drawtext 文字超出右/下边界）、字号过小（< 画高 2%）、ASR 错配（烧录字幕文本与音轨 TTS/音调不一致：用 manifest 记录"文稿"与真实内容不一致，若本机有 CPU TTS 如 espeak/piper 可用就用，没有就以文本元数据标注并写明）、冻帧（中段 3s 冻结 `tpad`/`loop`）、A/V 不同步 >120ms（音频 itsoffset 200ms）、黑边（pad 信箱/柱箱超标）。再加 1 条正常片 `good_clean.mp4`。共 ≥17 条坏片。
- 输出到 `${HEVI_QA_CORPUS_DIR:-/tmp/hevi_qa_corpus}`，**mp4 不入库**；入库 `tests/fixtures/qa_corpus/manifest.json`：每条 `id`、配方说明、`expected_failures`（如 ["visual.noise"], ["audio.silence_gap@3-11s"], ["av.desync>120ms"]…）、缺陷时间段、`sha256`（确定性编码：`-threads 1`、`-fflags +bitexact -flags:v +bitexact -flags:a +bitexact`、固定 x264 参数，使 sha 稳定；若某条在本机无法 bit 稳定，如实标 `sha_stable:false` 并说明原因）。
- 测试 `tests/qa_corpus/test_qa_corpus.py`（真实 ffmpeg，不 mock，也不依赖未合并的 omquality 审查模块）：
  - 再生 ≥17 条坏片 + 1 条正常片，ffprobe 合法；
  - sha 与 manifest 一致（sha_stable 的那些），连跑两次一致；
  - **物理验证每条缺陷真实存在**：如 blackdetect 检出黑段、silencedetect 检出静音段且时间匹配、astats 峰值 ≥ −0.1dBFS 判削波、freezedetect 检出冻帧、signalstats 判绿屏（U/V 均值）与灰块（下半区方差≈0）、噪声片 YDIF/熵高、宏块片 SSIM 对基底明显下降、A/V 偏移由 ffprobe start_time/互相关测得 ≥120ms、出框/黑边由像素统计测得；正常片这些检测全部不触发。
  - 测试标 `@pytest.mark.slow` 可选，但必须能跑完并在 DONE 里贴真实结果。

## 步骤
1. lint 基线；读 assets/audio/sfx 与参考配方。commit。
2. SFX 生成器 + 库 + manifest + 测试。commit。
3. qa_corpus 生成器 + manifest。commit。
4. qa_corpus 测试（物理验证）。commit。
5. lint_after；写 `SFXBAD_DONE.md`（含两部分的真实测试输出摘要、文件数、总大小），commit。
## 通用规则（必须遵守）
- 你在独立 worktree 里工作（当前目录），基线 `ac09c747`（origin/closure/3o-v3-architecture-creative-baseline）。**绝对不要碰主 checkout `/data/soffy/projects/hevi`**（只允许只读引用其 .venv / node_modules，已为你建好软链）。也不要改其它 hevi-* worktree。
- CPU-only（GPU 已坏）；不调用任何付费 API；不重建容器；不删任何数据；不 push、不合并。
- 禁止改动：`hevi/video/quality_profile.py`、`hevi/studio/*`、`hevi/prompt/style_presets.py`、`hevi/keyframe/**/style_presets.py`、`hevi/layer4_legacy/review/*`、`hevi/layer4_legacy/enhance/*`、`hevi/layer4_legacy/dirstyle/*`、`hevi/production/capabilities.py`、`hevi/api/routers/explainer.py`、`hevi/explainer/*`（这些有在途单元，只读）。
- 开工先跑 `.venv/bin/python scripts/ci/run_3o_v3_lint.py > lint_before.txt 2>&1` 记基线（基线允许 4 项失败），结束再跑 `lint_after.txt`，失败数不得多于 4。
- pytest 运行：`JWT_SECRET=test-secret-local .venv/bin/python -m pytest <你的测试> -q`。PATH 已含 /home/soffy/.local/bin（ffmpeg/ffprobe 在那里）。
- `output/` 被 .gitignore 忽略，需要提交的小产物（record.json、contact_sheet、index.json 等）用 `git add -f`。
- 每完成一步就 `git add <只加自己的文件> && git commit -m "feat/sfx-badclips: step N ..."`（不要 `git add -A`；不要提交 >20MB 文件、node_modules、.venv 软链、日志）。
- 长任务（批量渲染/E2E）用 `nohup setsid <cmd> > <log> 2>&1 &` 独立启动，sleep 轮询直到产物生成，不得在产物完成前结束。
- 禁止 mock/占位/写死产物；验收数据必须来自真实 ffprobe/抽帧/测试输出。DONE 里不得写未实测的数据，不得自称"独立验证通过"。
- 不要询问，直接执行到底。最后写 `SFXBAD_DONE.md`（做了什么、文件清单、接口、测试命令与真实结果、产物路径+ffprobe+sha256、lint 前后、已知限制），commit，最后一行写 `DONE SFXBAD-R1`。
