# CSK 18 套逐套实拍验真矩阵（B4）

日期：2026-10-31。实跑环境：ubuntu26，`.venv` Python 3.14 + Playwright
1.62.0，Chromium headless，ffmpeg/ffprobe 在位。渲染入口：
`video.hyperframes_styled_render`（默认 `capture=screenshot`、`sound=true`，
即本次新接的声音线）。产物在 ubuntu26 的 `/data/soffy/b4-matrix/` 下，
不在本仓内；本文件只登记结果与路径。

## 方法（同一输入，逐套可比）

- 同一 beats 输入（schema 正确；list 项一律 `[label, value]` 对）：
  chapter `{num: 01, title: 风格测试, sub: Style Test}`、
  stat `{value: 87.6, suffix: %, unit: 一次通过, note: 示例数据 · <em>零样本</em>}`、
  list `{head: 要点, items: [[第一点, 12], [第二点, 34], [第三点, 56]]}`。
- 每套：fps 4 渲染 → ffprobe 流检查 → 抽 3 帧（0.5s / 中点 / 时长−0.5s）
  → 每帧 Laplacian 方差（270×480 灰度，数值越高越锐；仅作相对参考，
  非门禁阈值）→ 首末帧平均绝对差。
- 目视抽查：8 张 PNG 取回本地目视（含 dark-keynote、instrument-panel、
  frosted-aurora、data-journal 的关键帧）；其余 10 套只看量化指标，
  未逐张目视——见“局限”。
- “末帧”采样注意（已实证）：时长−0.5s 的采样常落在最后一帧的出场/
  遮罩过渡上（dark-keynote 末帧全糊、instrument-panel 末帧近空白），
  与 0.01–0.03s 之前的 hold 帧（清晰）形成对照。末帧低方差不单独
  判 style 不可用；判据以 hold 帧（中点＋跟进采样）为准。

## 结果总表（18/18 渲染成功，0 套不可用）

| 风格 |  verdict | 时长 s | 大小 B | 音频流 | cue 数/对齐误差 | 字体子集 | LV 早/中/晚 | 首末帧差 |
|---|---|---|---|---|---|---|---|---|
| dark-keynote | OK（见注 1） | 13.53 | 787965 | h264+aac | 5 / 0.0s | 3 | 5.04 / 1103.44 / 5.20 | 2.838 |
| swiss-grid | OK | 12.13 | 163287 | h264+aac | 5 / 0.0s | 4 | 195.81 / 1003.17 / 751.25 | 86.423 |
| editorial-paper | OK | 11.42 | 2708077 | h264+aac | 5 / 0.0s | 5 | 95.46 / 632.30 / 663.19 | 10.326 |
| warm-notebook | OK | 13.16 | 413942 | h264+aac | 5 / 0.0s | 3 | 92.10 / 754.24 / 1425.58 | 6.956 |
| poster-kinetic | OK | 13.82 | 750223 | h264+aac | 5 / 0.0s | 4 | 1390.14 / 995.19 / 795.90 | 201.135 |
| dev-console | OK | 9.93 | 144207 | h264+aac | 5 / 0.0s | 2 | 154.34 / 847.16 / 530.49 | 4.389 |
| data-journal | OK（见注 2） | 12.77 | 183716 | h264+aac | 5 / 0.0s | 4 | 463.84 / 830.96 / 736.30 | 5.670 |
| paper-figure | OK | 12.62 | 202806 | h264+aac | 5 / 0.0s | 5 | 57.70 / 961.55 / 520.93 | 1.749 |
| manim-morph | OK | 16.74 | 350924 | h264+aac | 5 / 0.0s | 4 | 100.29 / 1130.19 / 683.86 | 1.445 |
| blueprint | OK | 13.45 | 1905375 | h264+aac | 5 / 0.0s | 4 | 203.57 / 761.77 / 691.22 | 4.616 |
| benchmark-hud | OK | 12.50 | 338901 | h264+aac | 5 / 0.0s | 4 | 481.80 / 781.47 / 809.14 | 5.100 |
| particle-field | OK | 15.03 | 412818 | h264+aac | 5 / 0.0s | 3 | 114.55 / 572.72 / 784.81 | 2.326 |
| frosted-aurora | OK（见注 3） | 15.74 | 1879368 | h264+aac | 5 / 0.0s | 3 | 7.25 / 911.30 / 636.39 | 8.089 |
| isometric-stack | OK | 12.37 | 438873 | h264+aac | 5 / 0.0s | 4 | 337.02 / 792.11 / 625.00 | 19.592 |
| bauhaus-geometry | OK | 12.44 | 176977 | h264+aac | 5 / 0.0s | 4 | 252.70 / 786.35 / 796.43 | 6.757 |
| ink-wash | OK（见注 3） | 15.60 | 2093052 | h264+aac | 5 / 0.001s | 4 | 5.13 / 824.28 / 512.48 | 18.800 |
| clay-serif | OK（见注 3） | 14.66 | 279153 | h264+aac | 5 / 0.0s | 5 | 10.02 / 810.25 / 492.50 | 2.723 |
| instrument-panel | OK（见注 1） | 11.51 | 148176 | h264+aac | 5 / 0.0s | 4 | 333.16 / 898.44 / 82.44 | 11.110 |

- 音频：18 套全部有 aac 音频流，cue 数均为 5，峰值对齐误差最大
  0.001s（ink-wash；其余 0.0s，fps 4 下合 0.0 帧）。kit 的
  sound-layer 响度/真峰/画面同步 QA 未跑、未宣称（见声音线一节）。
- 字体：18 套全部正常子集化（每套 2–5 个 woff2，见产物
  `<style>/project/csk/fonts/`），无缺字体失败。
- 不可用套数：0。无 scaffold 失败、无渲染失败、无声音线失败。
  环境问题（缺字体等）：本次实跑中无。

## 逐套注记

- 注 1（dark-keynote / instrument-panel）：末帧采样为出场过渡帧，
  不代表 hold 帧质量。跟进采样：dark-keynote t=13.0s hold 帧清晰
  可读（“要点”+01/02/03 三项，末项高亮为风格的强调态），stat 拍
  87.6% 完全清晰；instrument-panel t=11.0s hold 帧清晰（标题+三张
  卡片）。两套的 list 数值（12/34/56）在目视帧中均未 visibly 渲染
  （模板只写 `data-v` 属性，该风格布局不显示数值槽）；不是错误值，
  是布局不展示——调用方如需数值可见，须另选 data-journal 类风格。
  另：dark-keynote 的 blur-in 动效在过渡帧上确实全程发虚（深审
  §4 复现），且“两次截图 hash 一致即 settled”的判定拦不住它：
  paused 时间线停在 blur 中间值时截图本身就是静态一致的。这是
  已知的渲染器局限（见残留），不是本次输入或某套独有的问题。
- 注 2（data-journal）：深审 §4 的“list 三项全显示 0”在本次
  schema 正确输入下已不存在：目视末帧三项右侧清晰显示 12 / 34 /
  56。根因是输入（裸字符串项）而非风格；裸字符串输入现由 beats
  schema 门给出警告（`bare_string_item`），不再静默出 0。
- 注 3（frosted-aurora / ink-wash / clay-serif）：0.5s 早帧方差极低
  是开场 blur-in 过渡帧（frosted-aurora 目视确认：01 与标题正在
  淡入），中/晚帧方差正常、清晰。不是缺陷。
- 其余 13 套：三拍量化指标均正常（中/晚帧方差数百、音频齐全），
  无异常记录；未逐张目视，见局限。

## 声音线（B2）实跑证据

- warm-notebook 独立复核（既有深审产物）：`run_sound_pass` 在已有
  无声 mp4 上实跑，5 cue、对齐误差 0.0s / 0.0 帧，ffprobe 复核
  h264 + aac 双流。产物：
  `/data/soffy/hf-deepdive/warm-notebook/sounded-test.mp4`。
- B4 全量：18 套 `qa["audio"].status == "mixed"`，报告见各产物
  `<style>/project/audio/hevi_sound_pass.json`（mix wav 同目录）。
- 未做的声明：kit `sound_pass.py` / sound-layer `mix.py` / `qa.py`
  （uv、响度、真峰、画面同步 QA）均未运行；报告如实记
  `kit_sound_pass: "not_run"`。无 cue/缺 cue 音频时渲染失败
  （单元测试覆盖），不静默出无声片。

## BeginFrame 原子捕获（④）实跑证据

- 探针（Playwright 1.62.0 + Chromium headless-shell 1248）：
  必须同时加 `--enable-begin-frame-control` 与
  `--run-all-compositor-stages-before-draw`；`interval` 单位是毫秒
  （16.666），`frameTimeTicks` 省略。缺任一开关时 CDP 报错；
  参数按秒传（0.016）时只回 `hasDamage`、无截图数据（静默失败，
  已在模块文档中记下）。`Page.captureScreenshot` 在 beginFrame
  之后会挂死，本实现永不在 beginFrame 模式下调用它。
- warm-notebook（CSK 真实项目）两次 `capture=beginframe` 渲染：
  各 53 帧，逐帧 sha256 **53/53 一致**；换 seek 则 hash 不同
  （探针：同 seek 四次一致、换 seek 即变）。保留帧 blur 数值：
  frame_0000 LV 9.4（开场）、frame_0026 LV 734.3（hold 清晰）、
  frame_0052 LV 0.0（末帧纯色遮罩，见方法注记）。
- 糊帧判定：`capture_frame_settled` 要求同 seek 两次原子捕获 hash
  一致，不一致即拒收（不交付半绘帧）；离线的
  `frozen_picture_gate.check_blur_settle` 未被喂入发明的分数，
  本矩阵只报实测 Laplacian 方差。
- streamingEncoder：只做到契约层（`beginframe_capture.
  streaming_encoder_contract()`，`implemented: false`）；当前编码
  仍为 PNG 序列 + ffmpeg，未宣称流式编码已实现。
- 产物：`/data/soffy/b4-matrix/beginframe-run1/` 与
  `/data/soffy/b4-matrix/beginframe-run2/`（各含 `styled.mp4` 与
  保留帧目录 `project_frames/`），对照文件
  `/data/soffy/b4-matrix/beginframe_comparison.json`。

## 产物路径（ubuntu26）

- 每套 mp4：`/data/soffy/b4-matrix/<style>/styled.mp4`
  （project/声音报告/字体子集同目录）
- 抽帧：`/data/soffy/b4-matrix/frames/<style>-{early,mid,late}.png`
- 机器可读结果：`/data/soffy/b4-matrix/results.json`
- 跟进采样：`/data/soffy/b4-matrix/followup/{dark-keynote,instrument-panel}/`

## 局限（未掩盖）

- 只用 1 组 beats 输入、fps 4、每套 3 个采样时刻；16:9、旁白绑定、
  任意 HTML composition 均不在 CSK kit 能力内，本次未验（kit 天花板，
  见深审 §5.6）。
- 目视只覆盖 8 张帧；其余风格的“OK”以量化指标（渲染+音频+方差）
  为据，未逐张目视。
- list 数值槽的可见性只在 dark-keynote、instrument-panel、
  data-journal 三套上目视确认；其余 15 套未确认数值是否显示。
- 深审 §4 提到的 warm-notebook list 拍“橙色矩形贴纸压住卡片”
  在本次 3 采样中未复核（未在该时刻采样），不宣称已消失。
