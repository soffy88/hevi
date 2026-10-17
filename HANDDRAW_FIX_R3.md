# HANDDRAW_FIX_R3 — 独立核验 R2 未通过（2026-10-15 06:00）

证据：audit/handdraw/verify_r2/（measurements.json、cue_alignment.json、asr_*.json、negative_tests.json、frames/），复现脚本 .tmp/vr2/（drv.py run.sh ana.py neg.py cue.py asr.py）。
已通过（不要回退）：12 次渲染 0 崩溃；完整片 -15.7~-16.0 LUFS、TP ≤ -2.0；字号横 56 / 竖 60；删产物自检红灯；NOTICE 署名；pytest 30 passed；3O lint = 基线 4。

## 阻断项
B1 主题被模板替换（R1 的 F3 未修好）
- 复现：渲染主题「小兔子学会分享」→ 实际是「小狐狸一起玩球」轮流模板，旁白无"分享"。kids_storyboards.select_kids_storyboard 对不匹配关键词的主题一律落到狐狸模板；「小猫学会过马路」「为什么要洗手」只换标题，L_17 音频与 L_1 完全相同。
- 期望：故事、主角、旁白都按用户主题生成（CPU 本地，可用模板库+槽位填充，但主角/动作/主题词必须来自输入）。主题不适合幼儿（复利、巴菲特等）必须拒绝（422/明确错误），不得套模板出片。
- 必须新增测试：4 个不同幼儿主题，旁白含主题关键词且两两旁白不同、音频 sha 不同；成人主题被拒。
B2 画面残留成人模板标签「深入机制分析」
- 来源 pipeline.py:496 默认 note；每页都出现。删除/改为幼儿化，并让 kids 检查覆盖画面文字（所有上屏文本过禁用词/成人词表）。新增测试：渲染后 OCR 或检查 timeline 上屏文本不含该类词。
B3 字幕同步与切分
- ASR 测 cue 起点 p95 0.35–0.41s，末句「下次你想和谁一起玩球呢？」字幕早于语音 1.08s。期望：每条 cue 起点误差 ≤0.25s（p95），末句也算。
- 词中切分（「牙齿上有小 / 小的碎屑」「大家都能 / 玩。」）。期望：按词/语义断行（jieba 等本地分词），不在词中断开。新增测试覆盖。
B4 preview 响度与 gate 空过
- 2 秒 preview -14.2 LUFS；kids gate 中 preview 的 audio_lufs 为 null 被空过。期望：preview 也 -16±1 LUFS、TP ≤ -1.5；短片用适合短时长的测量方式；gate 遇到 null 必须红灯而非跳过。

## 次要项（尽量一起修）
- 删 inputs/narration/master.wav 后 verify_job 仍绿灯 → 应红灯。
- 风格 8「水墨写意」看不出墨晕/飞白，补墨晕/飞白笔触。
- piper length_scale=3.0 硬拉慢致 ASR 误识（积木→金木、碎屑→碎蟹）：改用更自然的放慢方式（句间停顿+适度 length_scale），语速仍 ≤3.5 字/秒。
- CosyVoice 服务不在线时如实回退 piper 已 OK；若在线需验证 CosyVoice 路径。

## 规则
遵守 KIDS_ANIME_DIRECTION.md 与 HANDDRAW_FIX.md 全部硬规则：不改主 checkout，只在本 worktree，临时文件 .tmp；CPU-only，不调用付费 API；不删 worktree 外任何东西、不清理磁盘；/data <5G 写 DISK_FULL_NOTE.md 停止；单进程渲染；禁止 mock/硬编码通过。阶段性 commit，不 push。完成后在 HANDDRAW_DONE.md 末尾追加实测结果并单独一行写：
DONE HANDDRAW-R3
