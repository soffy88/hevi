# DIRSTYLE_FIX r3 — 主审核验 fix-r2b（HEAD be8f4245）仍不通过（2026-10-13 14:1x CST）

规则同 DIRSTYLE_FIX.md / DIRSTYLE_FIX_R2.md：CPU-only、无付费 API、禁止 mock/占位/写死产物、**不 push、不合并**、lint 只允许基线 4 项失败、DONE 如实（不得自评"通过"/"已推送"）。不要询问，直接执行到底。PATH 必须含 /home/soffy/.local/bin。
**硬规则（新增）**：绝对不要删除当前 worktree 以外的任何文件；不要"清理磁盘空间"、不要 rm 任何已跟踪文件或 artifacts/、output/ 目录；若磁盘满（`df /data` 剩余 <5G）立即停止，写 `DISK_FULL_NOTE.md` 说明进度后退出。只 `git add` 自己改的文件，不要 `git add -A`。

## 现状（不要回退）
- B2 四风格 9:16 构图已各不相同 ✓（reframe_9x16 参数在各风格 JSON，grade.py 实现）。
- CJK 字体、Core message、lint 基线 4 ✓。
- 已有未跟踪成果已由主审 WIP 提交：tests/test_dirstyle_reframe.py、tests/fixtures/long_zh_source.md（约 420 字猫推东西常识文，可作 F2 旁白素材）。

## 第一优先：硬前置（不完成这两项，后面全部作废）
### B3 干净源片（回退了，第 2 次）
当前 4 个风格片的源又是**带烧录中文字幕 + "SHOT 02" 水印的长城片**。必须换成**干净源**：
- 优先：CPU 自生成源（ffmpeg `testsrc2`/`mandelbrot`/`life`/`cellauto` + `drawbox` 运动几何、或 PIL 逐帧渲染一个有主体（人形剪影/物体）在场景中移动的 16:9 画面，≥8s，1920×1080），或一个确认 CC0/NASA 公有领域、**画面内无任何文字/字幕/水印/台标**的片段（若需联网下载且失败，就用自生成）。
- **严禁使用长城片或任何带烧录字幕/水印的素材**。源文件放 `output/dirstyle_e2e/source_clean.mp4`，record.json 写明来源与生成命令。
- 测试：对源片 0.25/0.5/0.75 三帧做 OCR-free 检查——底部 25% 区域与顶部角落不应出现高对比细横向笔画密集区（可用 Sobel 水平边缘密度阈值，或对比源片生成方式断言 record.json `source.kind` ∈ {generated, cc0}，并断言文件名/路径不含 "长城"/"greatwall"/"shot"）。
### F5 配音档案（第 3 次失败）
flow_pack_60s 的锁定块（Lock block）必须有一行 `Voice profile:`，逐字冻结具体值（例：「中文普通话女声，约 30 岁，温和清亮，中速约 4 字/秒，近讲干声，无混响」），**每一段（segment）的提示词里逐字重复同一行**，pack.json 每段同步同字段。

## 第二批：阻断项
### B5 火柴人样片
- 字幕按像素宽自动换行：左右各留 ≥90px 安全边距，最多 2 行；渲染后用 PIL `font.getbbox` 断言每行 bbox 落在 [90, 990]（写进测试）。重渲 `stickman_9x16.mp4`，抽帧亲看第 4–6 帧确认「背后有三个原因…」不再出框。
- 姿态/动作 **>2 种**（≥4 种不同姿态：站立、指向、推杯子、跳/蹲等），每 2–3 秒一个姿态或位置变化，可加道具（桌子、被推下的杯子），保持 1A 线条风格。测试：相邻姿态段骨架关键点不同，姿态种类数 ≥3。
### F1 节拍
- 每段 3 条节拍（[0–3s]/[3–7s]/[7–10s]）都是**完整、互不相同**的画面动作描述（火柴人做什么 + 镜头/构图怎么变），各段之间也不得相同（Clip01 与 Clip02 现在节拍相同✗）。不得含旁白原句、不得截断（不准 "..."、"transition from"）。
- 火柴人风格**不得出现**面部/表情类方向（face、facial、expression、眼神、表情、微笑等）和横向运动方向（horizontal、lateral、left to right、横移、左右平移等）——火柴人是 9:16 竖屏线条，用竖向/推拉/位置变化表达。
### F2 旁白
每段旁白汉字数 40–66（现在 7–35 ✗）。旁白只能来自输入素材改写/重组（可用 tests/fixtures/long_zh_source.md），不得拼入画面指令（火柴人/画面/背景/镜头等词），不得「。，」脏标点，不得编造数字（输出数字 ⊆ 输入数字）。
### F3 编译提示词
Compiled generation prompt 的配色 = 导演风格锁定块 Palette（≤3 强调色，两处颜色词集合完全一致）；不得含 "16:9"、"2.39:1"、"left, center, and right"、"lateral"、"horizontal"、"vivid red"、"electric blue"、"mechanical horizontal track"；**编译提示词末尾不得追加中文旁白**（现在 prompt 尾部拼了旁白/中文句✗——prompt_en 里不得出现任何 CJK 字符，prompt_zh 里也不得出现旁白原句）。
### F6 衔接
- Segment Transitions 表必须完整写出全文（不得截断、不得 "..."），列：段号 / 开头画面 / 结尾画面 / 衔接方式。
- 每段 Clip 小节写 `First frame:` 与 `Last frame:` 画面状态描述（不是旁白）；段 i 的 Last frame == 段 i+1 的 First frame（逐字）；同一段的 First frame ≠ Last frame。
### 王家卫 reframe 测试
`tests/test_dirstyle_reframe.py::TestStyleReframeRendering::test_mid_frame_foreground_present[wong_kar_wai]` 失败。查明原因（tmix 拖影/偏心 fg 导致 bbox 检测阈值不适配，或 fg 真的丢了），**修实现或修正检测方法使其真实反映前景存在**，不得简单放宽到无意义或 skip。
### 产物一致性
用干净源重渲 4 个 `<style>.mp4` + `<style>_subbed.mp4` + stickman，然后**最后一步**重新生成 `output/dirstyle_e2e/SHA256SUMS`（`sha256sum -c` 必须全 OK）、`record.json`（每片 ffprobe 实测）、`contact_sheet.png`（来自新成片），并 commit（单文件 >20MB 不提交，写在 record.json 里说明）。

## 测试补强（tests/test_flow_pack.py，不准放水）
在现有基础上加断言，覆盖 F1–F6：
- F1：每段 3 节拍两两不同、跨段不同、不等于/不包含该段旁白、不含 "..."/"transition from"；stickman 风格节拍不含 face/facial/expression/表情/眼神/horizontal/lateral/横移/左右。
- F2：每段旁白汉字数 ∈ [40, 66]；不含「火柴人」「画面」「背景」「镜头」；不含「。，」；数字 ⊆ 输入。
- F3：编译提示词颜色词集合 == 锁定块 Palette 集合且 ≤3；不含禁用词表；prompt_en 无 CJK。
- F5：锁定块含 "Voice profile:"，每段逐字一致，pack.json 同步。
- F6：transition 表行数 == 段数-1（或==段数），无 "..."；Last(i) == First(i+1)；First(i) != Last(i)；均不等于旁白句。
- 另加 B3 源片检查测试与 B5 字幕 bbox / 姿态数测试。
运行：`JWT_SECRET=test-secret-local .venv/bin/python -m pytest tests/test_flow_pack.py tests/test_heartbeat5.py tests/test_dirstyle_*.py -q`，全部通过（不得 skip 新加用例）。

## 交付
- 每完成一项就 commit（`feat/director-styles: fix-r3 <项>`），只 add 自己的文件，不 push。
- 最后跑 `.venv/bin/python scripts/ci/run_3o_v3_lint.py > lint_after_r3.txt 2>&1`（失败 ≤4 项）。
- DIRSTYLE_DONE.md 追加「FIX r3」节：逐条（B3/F5/B5/F1/F2/F3/F6/王家卫测试/产物）写怎么修的、测试命令与真实输出、所有成片 ffprobe + sha256、源片来源；日期 2026-10-13；如实写，不自评通过；最后一行写 `DONE FIX-R3`。
