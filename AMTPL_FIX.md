# AMTPL_FIX — 独立核验不通过（R1 → R2）

核验时间 2026-10-14 CST，核验对象 `feat/aimotion-templates` @ 9e3a4e91（DONE AMTPL-R1）。
证据：Hark 项目工作区 `audit/aimotion/verify_amtpl/`（contact sheet、整帧截图、ffprobe/sha JSON）。

## 已核实为真（不用返工）
- 12 支样片 sha256 全部与 AMTPL_DONE.md 一致；ffprobe 1080×1920 / 1920×1080、30fps、h264 yuv420p、10.000s；kinetic 3 支 aac 音轨 mean −17.8 dB。
- 在 CPU headless（--disable-gpu）下用 CLI 重渲 `morph_ui_studio_ops` 9:16，51 s 出片，sha256 与报告逐字节相同（确定性成立）。
- pytest tests/motion_templates 33 passed；3O lint 仍为基线 4 项；新增文件与 awesome-ai-motion 无逐行雷同。
- kinetic 的主视觉事件落在 120BPM 网格上（主 onset 0.5/1.0/1.5/2.0/3.0… 误差 0 ms）。

## 必须修复
### H1 16:9 版本排版全面崩坏（阻断）
全分辨率抽帧亲眼确认（见 `timeline169_t9.5_crop.jpg`、`kinetic169_t3.4_crop.jpg`、`morph169_t5.0.jpg`、`morph169_t8.33.jpg`）：
- `timeline_ai_video_evolution_16_9`：标题「AI 视频模型技术演进史」压在小标题/英文副标题上；每张卡片里年份行、中文标题、英文副标题、正文四行互相重叠，正文横向溢出卡片和画面右边。
- `kinetic_bpm_beat_drop_16_9`：前一句「节点 点亮」与「全链 贯通」整行叠在一起；字号过大，上方小标签被大字压住；「零阶 / 跃失 / 纯粹」三行互叠。
- `morph_ui_hevi_pipeline_16_9`：t≈5.0 s「原子镜头规划就绪」与大号「18」重叠；t≈8.3 s 柱状图的橙色柱子压住标题「算力调度与并行渲染」。
根因（推断）：字号和水平尺寸按 `sScale = width/1080` 放大（16:9 时是 1.78），竖直间距却按 `vScale = height/1920` 缩小（0.56），两套比例混用。修法：统一用 `min(width/1080, height/1920)` 之类的单一比例（或按画幅分别布局），16:9 和 1:1 要有自己的版式参数，保证行高 ≥ 字号 × 1.2，容器高度按内容实测撑开。

### H2 文字安全区测试是空测（阻断）
`tests/motion_templates/test_text_safe_area.py` 只断言 canvas 宽是 1080、`maxContentWidth == 920`，再用测试里自己写的一段折行逻辑测一句写死的文本。它不读模板实际画出来的字，所以 H1 这么明显的重叠也能全绿。改成真实测量：
- 在模板里给每次 `fillText` 记录包围盒（如 `window.__textBoxes.push({x,y,w,h,text})`，只在测试开关打开时记录，不影响 draw(t) 纯函数性），测试在 9:16、16:9、1:1 三种画幅、每个模板 2 个 spec、每 0.5 s 采样一次，断言：(a) 所有包围盒都在安全区内；(b) 同一时刻不透明度 > 0.5 的文字包围盒两两不相交；(c) 文字包围盒不越出所在容器。
- 用当前 16:9 产物先跑一遍，必须能抓到 H1 的重叠，修好以后才能变绿。

### H3 竖屏正文字号过小（中）
`timeline_*_9_16` 卡片正文约 15 px（1080 宽画布），手机上读不清，卡片下半部分大面积空白。正文 ≥ 32 px、标题 ≥ 44 px（1080 宽基准），卡片高度按折行后的实际行数计算。

### H4 中文拆词（中）
kinetic 样片出现「多宽 / 高比」（应为「多 / 宽高比」）、「零阶 / 跃失」这类断词。spec 的分词要按词边界切，模板换行不要拆开一个词；在 spec 校验测试里加一条：每个 token 都不能把常见词切开（至少对两个示例 spec 人工给出正确分词并断言）。

### H5 杂项（低，顺手修）
- `lint_before.txt` / `lint_after.txt`（各 1569 行）被 commit 进了仓库，违反「不提交日志」。改为 `git rm --cached` 并加进 .gitignore。
- kinetic spec 引用的 `assets/audio/beat_120bpm_10s.wav` 被 .gitignore（`*.wav`）忽略，没进仓库，别的 clone 无法复现。在 render/CLI 里加一个用 ffmpeg lavfi 现场生成 120BPM click 的脚本（或在 spec 缺音频时自动生成），并在 docs 里写清楚。
- morph_ui 容器四周带彩色外发光（蓝/红 shadow halo），接近禁项「霓虹辉光」。改为中性、低不透明度的投影。

## 验收（写进 AMTPL_DONE.md，附真实输出）
- 4 个模板 × 2 个 spec × 9:16，加上每个模板 1 个 16:9 和 1 个 1:1，全部重渲，给 ffprobe、sha256、每支 6 帧 contact sheet。
- 新的安全区/重叠测试：先对旧 16:9 产物报 FAIL（贴输出），修完后 PASS；pytest 总条数；lint_after 仍为 4 项。
- 最后一行写 `DONE AMTPL-R2`。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-amtpl；不 push；不调付费 API；不要把 lint 日志提交进仓库。完成后在 AMTPL_DONE.md 最后一行写 DONE AMTPL-R2。
