# HANDDRAW_FIX_R4 — 独立核验 R3 未通过（2026-10-15 08:35 CST）

证据：audit/handdraw/verify_r3/REPORT.md（及 measurements.json、cue_alignment.json、asr_*.json、word_breaks.json、gate_and_topic_probe.json、negative_tests.json、frames/）。复现脚本：.tmp/vr3/（run.sh drv.py ana3.py brk.py neg.py asr.py cue.py gate.py chain3.sh）。
已通过（不要回退）：B2 上屏无成人标签；B4 2s 预览 -16.0 LUFS / -2.8 dBTP 且 null/NaN 红灯；成人主题（复利效应、巴菲特的投资智慧）拒绝；删 master.wav 等 8 种破坏 verify_job 全红；完整片 -15.6~-16.3 LUFS、TP ≤ -1.95；字号横 56/竖 60；NOTICE 署名；pytest 27 passed；3O lint = 基线 4。

## 阻断项

### B1 主题仍是 5 个固定模板关键词路由，合法幼儿主题被拒或出不了片
- 复现：`PYTHONPATH=. python .tmp/vr3/gate.py`（select_kids_storyboard）→「小熊不怕黑」「小狗学会说谢谢」「小星星睡前故事」「小狐狸生气了怎么办」全部 UnsupportedKidsTopicError。完整渲染 `bash .tmp/vr3/run.sh`（drv.py 参数 `X_bear|小熊不怕黑|17|navy|16:9|0|5`）→ 拒绝。
- 复现 2：`L_1|小兔子学会分享|1|navy|16:9|0|1`、`P_10|小兔子学会分享|10|navy|9:16|0|3`、`L_10|收拾玩具|10|navy|16:9|0|3` 均失败：KIDS gate pace_within_3_5_chars_per_second=False（单拍 3.57 / 3.73 字/秒，见 runs/*/inputs/narration/alignment.json beat_characters_per_second）。
- 期望：KIDS_ANIME_DIRECTION 列出的主题族（分享/轮流、情绪识别 生气/害怕/难过、刷牙洗手、睡前、过马路、自然科学、勇气、说谢谢和对不起、家人朋友）都能 CPU 本地生成：主角取自输入（未给则默认 IP 角色），主题词出现在旁白，8 段结构完整；只有成人/危险主题拒绝。「小兔子学会分享」「小猫学会过马路」「为什么要洗手」「小熊不怕黑」四个主题都要出完整片，旁白含主题关键词（分享/过马路/洗手/黑或害怕）、主角对得上，两两旁白与 master.wav sha 不同。
- 语速：合成后若某拍 >3.5 字/秒，管线必须自动再放慢该拍（加停顿/调 length_scale）直至达标，不能把合法输入直接判失败。
- 必须新增测试：参数化上面 4 个主题 + 至少 3 个新主题族（害怕/睡前/说谢谢）生成成功且关键词/主角断言；成人主题拒绝；对「小兔子学会分享」「收拾玩具」做真实 TTS 后每拍 ≤3.5 字/秒的回归。

### B3 字幕起点与真实语音不同步（独立 ASR）
- 复现：`python .tmp/vr3/asr.py <film.mp4>,<transcript.srt>,<out.json>`（faster-whisper large-v3-turbo，CPU int8）后 `python .tmp/vr3/cue.py`。
- 实际：cue 起点误差 p95 P_1 0.834s、P_8/L_17 0.594s、L_8/P_17 0.447s；每片 5–8 条 >0.3s；末句「告诉身边的大人吧！」在 3 部片中 ASR 无法对上；P_8 末条 cue 为「呢？告诉身边的大人吧！」（上一句的「呢？」被拆到下一条）。DONE 自报 p95 0.042s 是用管线自己的 ASR 时间轴自测，不算独立证据。
- 期望：独立 ASR（不同于管线所用模型/参数，例如 large-v3-turbo word_timestamps）测得每片 cue 起点误差 p95 ≤0.25s，末句也算；标点不得被拆到下一条开头；不出现「朋友们在 / 等」「大家都能 / 玩」这类语义断行。
- 必须新增测试：用独立 ASR 模型对至少 2 部完整片测 p95 ≤0.25s 的验收脚本（可标 slow）；cue 不以标点开头、问句完整的单测。

## 次要项（尽量一起修）
- 风格 8「水墨写意」仍只有断续黑描边，没有灰度墨晕与干笔飞白（frames/L_8_37s.jpg、P_8_22s.jpg）。需看得见的墨色渐变/晕染和飞白纹理，并给抽帧证据。
- ASR 误识未改善：洗手→习手、积木→鸡樱目、点心→点醒、碎屑→碎些、信号→星号、真棒→正邦、告诉身边→高速深。改善发音清晰度（Piper 句读、停顿、避免过度 length_scale），目标独立 ASR 字准率 ≥90%。
- 角色是几何符号（C 形头 + 梯形身体），看不出小猫/小熊；P_1 第 20s 画面几乎全空（frames/P_1_20s.jpg）。至少让主角可辨认、每拍画面有主体。
- CosyVoice 不在线时如实回退 piper 已 OK。

## 规则
遵守 KIDS_ANIME_DIRECTION.md 与 HANDDRAW_FIX.md 全部硬规则：不改主 checkout，只在本 worktree，临时文件 .tmp；CPU-only，不调用付费 API；不删 worktree 外任何东西、不清理磁盘；/data <5G 写 DISK_FULL_NOTE.md 停止；单进程渲染；禁止 mock/硬编码通过。阶段性 commit，不 push。完成后在 HANDDRAW_DONE.md 末尾追加实测结果（含 4 风格×2 画幅 8 部完整片全部出片、独立 ASR p95 数字）并单独一行写：
DONE HANDDRAW-R4
