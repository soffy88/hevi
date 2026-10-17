# HANDDRAW_FIX（R2）：独立核验 R1@6d989c51 不通过，逐项修复

核验人在干净副本（`git archive 6d989c51`，/data/tmp/hark_hd/src）重跑了 4 种风格 × 横竖屏共 8 条样片，以及能力契约、pytest、lint、CosyVoice。证据：Hark 审计目录 audit/handdraw/verify_r1/。以下每一项都必须修，并给出**可复现的证据**（不是自报 JSON）。

## 阻断项

### F1 渲染随机崩溃（干净环境 17 次里 8 次失败）
- 现象：`ValueError: Narration ranges must be finite, ordered, nonoverlapping and inside the master`（narration_master.load_master）。17 次渲染里 8 次失败：横屏 4/4 成功；竖屏 P_1 失败 2 次、P_10 失败 1 次、P_17 失败 2 次；`handdraw.full`（横屏）4 次里 3 次失败。
- 根因：`tts.py build_narration_master` 把 beat 的 start/end `round(...,4)`，最后一个 beat 的 end 向上舍入后超出 master 长度（例如 49.2954 > 49.295375+1/48000）。piper 每次时长不同，所以是随机失败。R1 的竖屏样片是靠 `scripts/handdraw_resume_portrait.py` 手工续跑出来的，掩盖了这个问题。
- 修法：时间戳按采样点整数计算，写入时向下取整（或者直接用样点数），end 不允许超过 `len(master)/SR`。加回归测试：随机 30 组 beat 时长都要能通过 `load_master`。验收：在干净副本里连续跑 8 条（4 风格 × 2 画幅）各 2 次，16/16 成功。

### F2 CosyVoice 实际上从来没用上，全片都是 piper
- `_synth_cosyvoice` 的超时是 20 秒；gen-engine 每个请求都会冷启动 cosy_worker，实测一句 3.24 秒的音频需要 84.4 秒和 86.7 秒（两次都一样慢，没有热路径）。所以每一句都会超时，然后回退到 piper。R1 日志里有 84 次 “CosyVoice unavailable or timed out”。每次超时后，容器里的推理还会继续跑，白白占内存。
- 修法：整篇旁白只请求一次 CosyVoice，或者按批请求（把多句放进同一个 script），超时设为 ≥300 秒；或者改用 gen-engine 的常驻模式。必须在 alignment/verification 里记录**每句实际使用的引擎**（cosyvoice/piper），不允许一部分句子用 cosy、另一部分用 piper（会混音色）。验收：gen-engine 在线时成片 100% 是 cosyvoice；离线时 100% 是 piper，并且报告里如实写出来。

### F3 主题 → 口播稿是假的；能力参数被忽略
- `handdraw.full` 传入 topic「小兔子学会分享」、duration=2 时，渲染出来的是 51.07 秒的「巴菲特/复利/资产几何级数」口播（证据：capability_full2s.json）。只要不是 anger 关键词，就一律走 compound_interest 剧本；`line.py` 的其他主题全部回落到写死的套话（`{topic[:10]}的底层运行机制` 等）。
- `duration` 被忽略（契约要求 2 秒 preview 时长要对得上）；`seed` 没有用上（同一个 seed 两次的 sha 不同）；`render()` 不做 schema 校验：缺 topic 会抛 KeyError 而不是 CapabilityError，jsonschema 的 ValidationError 也没有转换成 CapabilityError；line.py 收到非法 style/hand 时静默替换，不报错。
- 修法：口播稿必须由 topic/文章生成（本地 LLM 或规则模板都可以，但内容必须和主题相关），生成后走 kids 台词审查；`render()` 入口先调用 `validate_params`，所有错误统一转成 CapabilityError；`duration` 必须生效（preview ≤3 秒，实际时长误差 ≤0.1 秒）；同一个 seed 必须可复现（piper 固定 noise/seed，或者缓存旁白），用 sha 一致来证明。

### F4 4 种风格没有实质区别，不符合各自的风格配方
- 对比抽帧（styles_compare_L.jpg / styles_compare_P.jpg）可以看到：4 种风格的几何图形、线宽、平涂方式完全相同，区别只有底纸色和强调色。1「极简黑白」里有蓝衣服、肤色和黄灯泡；8「水墨写意」没有任何毛笔、墨晕或飞白；10「淡彩速写」没有铅笔线和透明水彩；17「墨线绘本」没有水彩纹理。竖屏插画还带一块浅蓝色方形底板，看起来像贴上去的图。
- 修法：每种风格在线条（笔刷、粗细变化、抖动）、填色（墨晕/水彩扩散/纸纹）和配色上都要按 STYLES.md 的 recipe 实现。验收：同一页 4 种风格的末帧两两比较，结构差异（SSIM）<0.85，并且由人看图能分辨出来。插画背景必须透明，不允许出现方形底板。

### F5 字幕：竖屏字号不达标、孤立标点换行、被手臂遮挡、与语音不同步
- 竖屏字幕 41px，横屏 38px；KIDS 要求竖屏 ≥56px。
- 竖屏出现长句，例如 23 字的「技能磨练和健康习惯同样受这一底层宇宙法则支配。」，句号单独掉到第二行（full_P_8_37s.png）。`split_text_into_cues` 的 15 字上限没有生效。
- 横屏 navy 手臂会盖住字幕开头（sheet_L_1 t=2.7s：「在生活中」被袖子遮住）。
- 同一个 beat 里的分句是按字数比例分配时间的，实测（whisper 字级对齐，cue_alignment.txt）字幕比语音最多晚 0.6–0.98 秒，每条片子有 2–6 句误差 >0.3 秒。任务要求 ≤0.2 秒。
- 修法：竖屏字号 ≥56，横屏 ≥48；每句 ≤12–14 字，按词边界切分，标点不能单独成行；字幕区设为手臂和笔的禁入区，或者把字幕放到最上层并保证手不经过；分句时间用 ASR 强制对齐或 TTS 字级时间戳。验收：cue 起点和 ASR 的误差 ≤0.2 秒（p95）。

### F6 测试是空测，删产物照样通过
- 在 worktree 产物副本上实测：删除 master.wav、review.json、drawing-plan.json、work/timeline.json 后仍然 8 passed；删除 work/assets 后 monotonic 测试被 skip（6 passed, 2 skipped），而不是失败；把 reveal map 打乱后 monotonic 仍然通过（这个测试检查的是“排序后 ≤t 的计数”，永远单调）；把 film.mp4 截成 1 秒，仍然 8 passed。
- 干净 checkout 里 deliverables 测试 4 failed（mp4 被 gitignore，inputs/ 没有入库），说明测试依赖本地未入库的文件。
- “对齐 ≤0.2 秒”测试只读 verification.json 的自报字段，没有测语音。
- 修法：测试要自己生成一个短样片（tmp_path 里跑 ≤6 秒的 2 beat job），然后从视频本身验证：ffprobe 时长/分辨率、音轨非静音、LUFS、按帧统计墨迹覆盖率随时间单调上升（直接从视频抽帧测，不读 npz）、cue 起点与音频能量起点误差 ≤0.2 秒。缺少任何产物都必须 FAIL，不允许 skip。契约 4 条测试（list / 非法参数 / 2 秒 preview 用 ffprobe 检查 / 删产物后失败）要真实执行 `handdraw.full` 的 preview 渲染。

### F7 违反 KIDS_ANIME_DIRECTION（优先级最高）
- 两个样片仍然是成人主题：「越生气越做错决定」里有“生死威胁/毁灭行为/成人的顶级智慧”，「复利效应」里有巴菲特（真实人名）、“暴利诱惑”。旁白语速 4.46–4.66 字/秒，上限是 3.5；LUFS 有两条只有 -17.2（L_8、L_17），要求 -16±1。
- 修法：E2E 改成幼儿向，横竖屏各 1 条，例如「小狐狸学会轮流」「为什么要刷牙」。结构按「问候 → 问题 → 尝试 → 解决 → 复述 → 告别 + 互动问句」；语速 ≤3.5 字/秒；LUFS -16±1，真峰值 ≤-1.5 dBTP；台词审查报告；字幕 ≥56px。

### F8 R1 引入的 pytest 回归
- `tests/test_studio_slate.py::test_twelve_production_lines_loaded` 在基线 7087c24a 上通过，在 R1 上失败：`assert 'handdraw' in {'ffmpeg','hyperframes','remotion'}`（新增的 handdraw.yaml 用了 render_runtime=handdraw，但 slate 只接受这三个 runtime）。修法：正式登记 handdraw runtime，并同步更新这个测试，不要只删断言。验收：全量 pytest 相对基线没有新增失败。

## 次要项（R2 一并修）
- 顶层 NOTICE 里没有 sweety-handdraw-video 的署名（vendored LICENSE、THIRD_PARTY_NOTICES 和 provenance ledger 已经保留，这部分没问题），请补一段。
- pipeline.py 和 resume 脚本里，review.json 的「content/visual/motion/audio: pass」以及 drawing-review 里的「实际看图核验」都是写死的通过文字，属于假自审。改成如实标注为「未经人工复核」，或者接入真实检查结果。
- 能力契约里的 `GET /api/capabilities` 和 `POST /api/capabilities/{name}/preview` 没有接上 registry（这部分以 webkit 为准，但 handdraw 的 preview 至少要能在 3 秒内产出视频）。
- 删掉 `scripts/handdraw_resume_portrait.py`，或者只作为调试工具使用；E2E 必须一次性从零跑通。

## 验收方式（核验人会复跑）
干净副本，以 soffy 用户运行，设置 JWT_SECRET=test-only，PATH 里有 ffprobe 和 node：
1. 4 种风格 × 2 种画幅各跑 2 次，16/16 成功；同一个 seed 两次 sha 一致。
2. 抽帧人工检查：逐笔描线、4 种风格能明显区分、无越界、无孤立标点、字幕不被遮挡。
3. ASR 检查：cue 误差 p95 ≤0.2 秒；引擎如实记录。
4. pytest 全过，删除任意产物都会失败；3O lint 失败项 ≤ 基线 4 项。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-handdraw；不 push；不调付费 API；不要把 lint 日志提交进仓库。完成后在 HANDDRAW_DONE.md 最后一行写 DONE HANDDRAW-R2。
