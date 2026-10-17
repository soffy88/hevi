# DIRSTYLE_FIX r2 — 主审复核 fix-r1（HEAD aaf7e2be）仍不通过（2026-10-13 09:1x CST）

规则同 DIRSTYLE_FIX.md（CPU-only、无付费 API、禁止 mock、不删数据、**不 push、不合并**、lint 只允许基线 4 项、DONE 如实）。不要询问，直接执行到底。PATH 必须含 /home/soffy/.local/bin。
**注意：r1 完成报告写「7 文件已推送到 feat/director-styles」——不实，origin 上没有这个分支。不许 push，也不许写已推送。**

## r1 已修好（不要回退）
- 源片换成干净 NASA ISS 片段（无烧录字幕/水印）✓；contact sheet/字幕中文不再是豆腐块 ✓；Core message 已填 ✓；锁定块 Palette 一行已改为 3 个粉彩色 ✓；火柴人 9:16 样片已出 ✓；3O lint 基线 4 ✓。

## 仍阻断（每条都会被主审逐条复查）
### B2 四个导演风格 9:16 仍是同一个构图（未修）
四片 1080×1920 抽帧：16:9 画面都放在同一位置（上 1/3 偏中），下方大片纯黑 + 中间一个导演名小字。必须在 grade 管线（omodul_impl/grade.py）里实现**按风格的 9:16 重构图**，参数写进各风格 JSON（例如 `reframe_9x16: {fg_y, fg_width, bg_mode, bg_color, motion}`），不得硬裁切丢失主体。参考实现（ffmpeg filter_complex，CPU）：
- 背景层：源片 scale 到铺满 1080×1920 后 crop + boxblur=40 + 风格调色（或纯色场 color=）；前景层：完整 16:9 画面 scale 到 fg_width 宽，overlay 到 (x,fg_y)；
- wes_anderson：fg 宽 1080、竖向正中（y≈656）、背景为粉彩纯色场 + 上下对称色带（drawbox）；
- fincher：fg 宽 1080 放上三分之一（y≈260）、背景近黑模糊 + 暗角，缓慢推镜（zoompan 1.00→1.06 或 scale 随 t 变化）；
- wong_kar_wai：fg 宽 ≈960 偏心（x≈40, y≈1000 下半屏）、tmix=frames=4 拖影、背景青绿/琥珀模糊色带；
- zhang_yimou：fg 宽 1080 落竖向中轴偏下（y≈900）、背景高饱和红色纯色场。
- 加测试 tests/test_dirstyle_reframe.py：对 4 个成片中间帧求前景 bbox（与背景差分/非背景像素行列范围），断言 4 个 bbox 的 (y_top, height) 两两不同（|Δ|≥80px），且前景完整（宽高比≈16:9，无主体丢失）。
- 重渲 4 个 `<style>.mp4` 与 `<style>_subbed.mp4`，更新 record.json / SHA256SUMS / contact_sheet.png。删掉 worktree 里你产生的中间垃圾文件（check_wk.png 等）或不提交它们；*_clean.mp4、nasa_earth_clean.mp4 等中间件如保留须在 record.json 说明用途。
### B1 王家卫仍不够可辨识
现在与韦斯/芬奇差异不大。王家卫要：tmix 拖影（step-printing）+ 青绿暗部/琥珀高光分离 + 饱和度提升 + 颗粒。测试：wong_kar_wai.mp4 与源片中间帧 SATAVG 或 (UAVG,VAVG) 偏移超过阈值，且与 wes_anderson 中间帧的 (UAVG,VAVG) 距离 ≥3。
### B5 火柴人样片字幕出框
stickman_9x16.mp4 第 4–6 张抽帧，「背后有三个原因：脚垫敏感、高处刺激、3…」右侧被截断。字幕必须按像素宽度自动换行（左右各留 ≥90px 安全边距，最多 2 行），渲染后断言每行文本 bbox 在 [90, 990] 内（用 PIL font.getbbox 计算，写进测试）。另：火柴人动作要更明显（每 2–3 秒一个姿态/位置变化，可加上下移动、道具如桌子和被推下的杯子，线条风格保持 1A DNA）。
### F 提示词包（flow_pack_60s，以及若保留的 flow_pack_30s）仍严重不合格
- F1/F2（回退变坏）：旁白里被拼进了画面指令「，火柴人角色在画面中做出解释的手势，用简单线条表达这个概念，背景保持纯白…」——这不是旁白，而且出现「。，」脏标点。旁白只能来自输入素材的改写/重组（不编造事实数字），不能用画面描述凑字数。素材不够 6×45 字就**换一段更长的真实中文常识文**（≥300 字，放 tests/fixtures 或 data，DONE 里注明出处或自写）。节拍 [0–3s] 现在仍等于旁白原句、[7–10s] 是「transition from …」截断——三个节拍都要是**完整的、互不相同的画面动作描述**（火柴人做什么 + 镜头/构图怎么变），不得含旁白原句，不得截断（不准出现 "..."）。
- F3（未修）：Compiled generation prompt 仍包含「vivid red, electric blue, warm gold」和「16:9: stage action across left, center, and right, lateral tracking」以及韦斯「mechanical horizontal track」「pastel pink / mustard yellow / mint green / sky blue」。编译提示词只能有：目标画幅的构图句、最终 ≤3 强调色（与锁定块 Palette 一致）、导演横移翻译成竖向运动、去掉与 1A 负面冲突的「layered front-to-back depth」等。
- F5（未修）：锁定块没有具体配音档案。加一行 `Voice profile:` 逐字冻结具体值（例：「中文普通话女声，约 30 岁，温和清亮，中速约 4 字/秒，近讲干声，无混响」），每段逐字重复，pack.json 同步。
- F6（未修）：Segment Transitions 表里的「开头画面/结尾画面」填的是旁白句。必须是画面状态描述，段 i 结尾画面字符串 == 段 i+1 开头画面字符串，并写进每段 Clip 小节。
- 测试（tests/test_flow_pack.py 补强，别放水）：编译提示词不含 "16:9"、"left, center, and right"、"lateral"、"horizontal"、"vivid red"、"electric blue"；编译提示词与锁定块的颜色词集合一致且 ≤3；每段节拍三条互不相同、都不等于且不包含该段旁白、不含 "..." 和 "transition from"；旁白不含「火柴人」「画面」「背景」等画面指令词、不含「。，」；每段旁白汉字数 40–66；锁定块含 "Voice profile:" 且每段逐字一致；段 i closing == 段 i+1 opening 且都不是旁白句；输出数字 ⊆ 输入数字。

## 交付
- 阶段性 commit（只 add 自己的文件），不 push。
- DIRSTYLE_DONE.md 追加「FIX r2」节：逐条写怎么修的、测试命令与真实输出、所有成片 ffprobe+sha256；日期用 2026-10-13；最后一行写 `DONE FIX-R2`。如实写，不自评通过。
