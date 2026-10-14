# AMTPL_FIX — 独立核验不通过（R2 → R3）

核验时间 2026-10-14 CST，核验对象 `feat/aimotion-templates` @ efe3e700（DONE AMTPL-R2）。
证据：Hark 项目工作区 `audit/amtpl/verify_r2/`（VERDICT.md、6 帧抽帧图、`tpl_probe.json` 实际文字包围盒与折行结果）。
方法：直接从 samples 里的 mp4 抽帧；另外用 playwright 打开模板、`setRecordText(true)`，每 0.5 s 取一次所有不透明度 > 0.5 的文字行和包围盒高度（墨迹高度，CJK 约等于字号 × 0.9）。

## 已核实为真（不用返工）
- H1 16:9 重叠：timeline / kinetic / morph_ui 三个模板 16:9 在 t=1.5/3.4/5.0/6.5/8.33/9.5 抽帧，没有任何文字互压，morph 柱状图不再压标题。
- H2 安全区测试：模板里所有 `fillText` 都经过 `ft()` 记录真实包围盒，测试读的是实际画出来的字。核验方把 R1（9e3a4e91）的三个模板放进 `AMTPL_TEMPLATES_DIR` 跑同一测试，16:9 三个用例全部 FAIL，说明测试能抓到 R1 的问题。
- H3 timeline 9:16：正文墨迹高 32 px、标题 44 px 以上，达标。
- kinetic 两个 spec 的分词已改对（「阶跃响应 / 纯粹 / 函数 / 渲染」「多画幅 / 宽高比」）。
- H5：lint_before/after 已移出版本库；音频缺失时 render 会用 ffmpeg lavfi 现场生成 120BPM click，docs 有写；morph 外发光已改为中性阴影。
- 带 ffprobe 的 PATH 跑 pytest tests/motion_templates：61 passed；3O lint 仍是基线 4 项。

## 必须修复
### H1 模板折行仍然拆词、标点出现在行首（阻断，R2 的 H4 没修完）
R2 只改了 kinetic 的 spec，timeline 模板的 `wrapText()` 仍是逐字切分（CJK 每个字一个 token，宽度一超就换行），实际折行结果（`tpl_probe.json`）：
- 9:16 `timeline_ai_video_evolution`：「…潜空间**帧** / **间**连贯性…」「…物理世界**动** / **力学**仿真…」「…彻底摆脱**外** / **部**后期…」
- 9:16 `timeline_hevi_milestones`：「…自动化**管** / **线**基础框架」「…检测等**严** / **苛**品控指标」
- 16:9 `timeline_ai_video_evolution`：「…实现**零** / **幻觉**…」；第 3 张卡第二行以「**，**彻底摆脱…」开头（行首标点）
- 16:9 `timeline_hevi_milestones`：「…奠定**短** / **视频**自动化…」
修法：
- 换行用词边界：在 spec 里提供分词（例如 `desc_tokens`），或者用浏览器 `Intl.Segmenter('zh', {granularity: 'word'})` 切词，再按词换行；一个词放不下才允许在词内断。
- 加中文禁则：「，。、；：！？）》」』」不能在行首，「（《「『」不能在行尾（行尾挤进或把前一个字带到下一行）。
- 测试：对所有 timeline spec × 9:16/16:9/1:1，读 `__textBoxes` 里的实际行，断言 (a) 没有行以禁则标点开头；(b) 相邻两行的接缝不切开一个词——至少对两个示例 spec 给出金标折行（或金标词表，含 帧间、动力学、外部、管线、严苛、零幻觉、短视频），断言接缝不落在这些词中间。先对当前代码跑出 FAIL，再修到 PASS。

### H2 竖屏字号：morph_ui / layer_build 仍然过小（中）
实测 9:16（1080 宽）最小中文墨迹高：morph_ui 卡片标题「启动智能成片引擎」「脚本解析与分镜语义分解」24 px，顶栏 20 px；layer_build 各层标题「数据底座与素材接入层」等 20 px；kinetic 角标「代码律动 // 纯函数动效」16 px。手机竖屏上读不清，画面大面积空着。
修法：9:16 下主文字（卡片标题、层标题）≥ 44 px、次级文字 ≥ 32 px、角标/辅助标签 ≥ 24 px（1080 宽基准）；容器尺寸随字号撑开，morph 卡片在竖屏要占到画面宽度的 80% 左右。把这些下限写进安全区测试，对 9:16 断言每个模板的最小 CJK 墨迹高 ≥ 22 px（≈24 px 字号），主文字 ≥ 40 px。

### H3 timeline 16:9 版面空、字小（低）
16:9 正文墨迹高只有 20 px，四张卡片下面约 2/3 是空的，画面下方 1/4 也空着（`sheet_timeline_ai_video_evolution_16_9.jpg`）。正文提到 ≥ 28 px，卡片高度按实际行数撑开，整体垂直居中。

## 验收（写进 AMTPL_DONE.md，附真实输出）
- 重渲 timeline 两个 spec × 9:16/16:9/1:1、morph_ui 与 layer_build 的 9:16 和 16:9，给 ffprobe、sha256、每支 6 帧 contact sheet。
- 贴出新折行测试先 FAIL 后 PASS 的输出；贴出每个模板 × 画幅的最小 CJK 墨迹高。
- pytest 总条数（运行时 PATH 要包含 ffprobe）；lint_after 仍为 4 项。不要提交 mp4/png/日志。
- 最后一行写 `DONE AMTPL-R3`。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-amtpl；不 push；不调付费 API；不要把 lint 日志提交进仓库。完成后在 AMTPL_DONE.md 最后一行写 DONE AMTPL-R3。
