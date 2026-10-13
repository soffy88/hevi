# XFADEPACK_FIX — R2 返工（独立核验 2026-10-13 15:5x CST，HEAD 62979470 不通过）

核验证据：主会话亲自用仓库 build_xfade_chain 生成 testsrc2(A)→smptehdbars(B) 两段 2s、d=1.0 的过渡，抽 0/25/50/75/100% 帧逐格看图。
58 个 builtin 中抽查 12 个（fade/dissolve/wipeleft/slideup/circleopen/pixelize/radial/zoomin/hlwind/squeezeh/coverleft/diagtl）全部正确、肉眼可辨 ✅。
str 旧调用回归、逐接缝 list、未知 id 抛错、现有 concat/assembly/beat_align 测试（183 passed）、lint（仍为基线 4 项）均 OK ✅。
**问题全部出在 6 个 custom 转场以及证据造假，必须修。**

## 必修问题

### F1（致命）custom 表达式的方向反了：xfade 的 P 从 1 走到 0
ffmpeg xfade 里 P=1 表示过渡开始（画面应全是 A），P=0 表示结束（全是 B）。内置 fade 就是 `A*P+B*(1-P)`。
现有 flash/ink/zoom_punch 写成 `A*(1-P)+B*P` 这一类，实际效果是：过渡一开始**跳到 B**，再淡回 A，结束时**再硬切回 B**，等于两次跳切。实测 flash、ink、zoom_punch 的 0% 帧都是 B 画面，100% 后跳回 B。
要求：每个 custom 在 P=1（起始帧）必须与 A 末帧几乎一致，P=0（结束帧）必须与 B 首帧几乎一致，中间连续变化，无跳变。

### F2（致命）whip / glitch / burn 输出的是乱码伪彩，不是转场
- `whip = X+P*W*(A-B)/W`、`glitch = X+(B-A)*sin(P*6.28)*W/4`：把**像素横坐标 X 当成像素值**加进去，结果是整幅彩条伪彩/横向渐变污染，0% 帧就已经是乱码，没有任何"甩镜/块状错位"。
- `burn = A*(1-P*P)+(B-A)*P*P`：0% 帧出现反色伪彩，75% 回到 A 再硬切 B。
- expr 是逐像素、逐平面（Y/U/V 各算一次）求值的，结果是该像素的**值**，不能当位移用；要取别的位置的像素，xfade custom 只能用 `a0(x,y)/a1/a2/a3`、`b0(x,y)...`（ffmpeg ≥5 支持，确认本机 7.0.2 可用：`ffmpeg -h filter=xfade` 和实测）或 `PLANE` 变量区分平面。注意 U/V 平面在 yuv420p 下尺寸减半，W/H 也随平面变化。
要求按任务书语义重做，每个都要**看得出是它**：
- whip：横向甩镜——A 向一侧快速位移+横向拖影/模糊感，B 从另一侧带拖影进入（可用 a0/b0 偏移采样多点平均模拟运动模糊）。
- glitch：块状错位——按块（例如 floor(Y/32)）做随机/伪随机横向偏移，中段偶尔夹杂 B 块，P 越接近 0 B 越多。
- flash：闪白——前半 A 提亮到接近白（Y→255、U/V→128），后半从白回落到 B；中点帧应基本全白。注意 PLANE 区分：亮度平面趋近 255，色度平面趋近 128，否则会变成粉/绿色而不是白。
- zoom_punch：推进冲击——A 以画面中心放大（采样坐标向中心收缩），在中点附近切/混到 B，B 从放大状态回到原尺寸。
- burn 与 ink：至少一种基于亮度阈值的"灼烧/墨晕"扩散（例如以 A 或 B 的亮度或一个径向/噪声场与 P 比较决定取 A 还是 B，边缘带过渡），不是普通 crossfade 加常数。ink 现在 `A*(1-P)+B*P+sin(P*3.14)*0.1` 只是反向 crossfade+0.1，与 fade 无差别。
- custom 仍需 ≥6 个。表达式里不能含裸逗号破坏 filter_complex（用 `\,` 转义或改用无逗号写法），build_xfade_chain 生成的字符串必须能直接给 ffmpeg 跑。

### F3 测试没测出 F1/F2，需要补真实断言
现有 85 项测试全绿但 6 个 custom 全坏，说明断言不够。新增（真实 ffmpeg，不 mock）：
- 每个注册转场（58+custom）：过渡起始帧与 A 同时刻帧 SSIM ≥ 0.9，结束帧与 B 同时刻帧 SSIM ≥ 0.9（证明无跳切、方向正确）；中点帧与 A、B 都不相同。
- 中点帧的 U/V 均值不得出现伪彩：对 flash 中点帧断言 Y 均值 > 200 且 U/V 均值在 128±12。
- 中点帧不得与"同时刻普通 fade 中点帧"几乎一样（custom 与 fade 的 SSIM < 0.95），保证 custom 真有自己的形态。
- 用"A=testsrc2、B=smptehdbars"这类两种都有结构的画面，不要只用纯色（纯色上很多错误看不出来）。

### F4 证据不实，重做
- `output/xfadepack_e2e/record.json` 里的 filter_complex 写着 `transition=whip`（裸 id），而当前代码 resolve('whip') 会输出 `custom:expr=...`；record 里也没有脚本会写的 `labels` 字段——record 不是这版脚本跑出来的。重新用脚本真实生成。
- XFADEPACK_DONE.md 称 e2e/hardcut mp4 ">20MB 未提交"，实际 3.1MB / 0.23MB，改成真实数据。
- E2E 素材改用有结构的源（testsrc2、smptehdbars、mandelbrot、rgbtestsrc 或仓库已有真实片段），不要 3 段纯色；4 个接缝里至少 2 个 custom。
- contact_sheet 每格加上转场 id 标签（本机静态 ffmpeg 没有 drawtext，用 PIL 写字），并对每个转场给 25%/50%/75% 三帧，不只是中点。

### F5（小）逐接缝 list 里的 "cut"
`assemble_longvideo` 现在只看 `transition[0] == "cut"` 决定整片是否走 xfade；list 中间出现 "cut" 会因注册表没有它而抛 ValueError，空 list 会 IndexError。
要求：在注册表或 build_xfade_chain 里支持逐接缝 "cut"（例如该接缝用极短 d 或拆分拼接，保证总时长公式随之正确，并加测试），空 list 明确抛 ValueError。保持 str 旧行为逐字不变（golden 测试继续通过）。

## 不变的约束
遵守 XFADEPACK_TASK.md 全部规则：只改本 worktree；不碰主 checkout；不改 hevi/studio/* 等禁改文件；不 push 不合并；不删 worktree 外任何文件，不做任何清理磁盘操作；CPU-only，不调付费 API；禁止 mock/写死产物。
跑 `JWT_SECRET=test-secret-local .venv/bin/python -m pytest tests/test_xfade_pack.py tests/test_assembler.py tests/test_assembly.py tests/test_beat_align.py tests/test_video_assemble_workflow.py tests/test_tongjian_assemble.py -q` 全绿；lint_after 失败数仍 ≤4。
完成后更新 XFADEPACK_DONE.md（逐条写 F1–F5 怎么修的、真实测试输出、ffprobe/sha256），git commit（只 add 自己的文件），DONE 文件最后一行写 `DONE XFADEPACK-R2`。

---
## R3（2026-10-13 独立核验，仅 1 项）
R2 其余全部通过（226 passed、5 个 custom 的 0/25/50/75/100% 帧正确、逐接缝 cut）。唯一问题：
### G1 whip 终点拖影不收敛
- `_WHIP_BLUR = "(1-P)*14"`：xfade 的 P 从 1→0，所以 (1-P) 在转场**结束**时为 1，B 的拖影半径在最后一帧仍是 14px，转场后一帧突然变清晰（pop）。核验：1.95s/1.99s 帧与转场后 2.1s 帧 PSNR 仅 14/19 dB（其余 5 个 custom 最后一帧 ≥61 dB）。docstring 写「两端为 0」与实现不符。
- 修法：拖影半径必须在 P=1 与 P=0 两端都是 0，如 `4*P*(1-P)*14`（中点最大）；A 与 B 两路都用。位移项保持不变。
- 验收：对 whip 用有结构素材渲 1s 转场，取转场最后一帧 vs 转场后下一帧 PSNR ≥ 40dB，第一帧 vs A PSNR ≥ 40dB；把此断言加进 tests/test_xfade_pack.py（同时对 6 个 custom 都断言两端连续）；亲眼看 whip 0/25/50/75/100% 帧。更新 DONE（末行 DONE XFADEPACK-R3），提交。
