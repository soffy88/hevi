# AMTPL_DONE — 确定性纯函数动效模板交付报告 (Unit B)

> Worktree: `/data/soffy/projects/hevi-amtpl`  
> Branch: `feat/aimotion-templates`  
> 基线: `7087c24a`  
> 标志: `DONE AMTPL-R1`  
> 环境: CPU-only / Playwright Headless Chromium (CPU 软件光栅) / ffmpeg libx264 yuv420p / pytest 9.0.3

---

## 1. 交付目标与完成概况

根据 `AMTPL_TASK.md` 与 `AIMOTION_EVAL.md` 单元 B（B1/B2/B4 优先，B3 可选）的要求，本工程落地了完全自主编写、不依赖任何外部未合并分支、不依赖 GPU、不调用付费 API 的确定性单 Canvas `draw(t)` 动效模板体系：

1. **闭式弹簧核心 (`hevi/motion_templates/lib/spring.js` & `spring.py`)**：
   - 二阶无状态阻尼谐振子阶跃响应解析解（$\zeta = 0.82, \omega_n = 14$）。
   - 线性时不变（LTI）多目标变迁解析叠加，无跨帧积分累积漂移，任意时间点 $t$ 可 Seek 求解。
2. **4 套单 HTML 纯函数 Canvas 模板**（9:16 原生排版，响应式支持 16:9 与 1:1）：
   - **B1 `morph_ui`**：一个几何形状通过 size/radius/color 连续形变串接 5–8 个 UI 状态，进出时序精确分离，附带形变短模糊与虚拟交互光标。
   - **B2 `timeline_explainer`**：线稿风技术蓝图时间轴/知识讲解，里程碑平滑下行展开，双语字幕，`ctx.measureText` 动态折行防破词，安全区零溢出；支持旁白 WAV 音频对齐。
   - **B4 `kinetic_lyrics`**：120 BPM 网格强对齐动态歌词/卡点字排，每拍一事件，微量超调冲击缩放，支持伴奏混音输出。
   - **B3 `layer_build`**：2.5D 等轴测多层建造揭示，Z 轴落位吸附与结构支柱对接。
   - **禁项严格遵从**：禁 shockwave、禁粒子爆发、禁 RGB split、禁镜头抖动、禁 lens flare、禁霓虹辉光、禁网格地板、禁闪烁背景、禁 bouncy easing、禁大面积蓝紫、**禁屏上中文句号（"。"）**。
3. **确定性渲染器与 CLI (`hevi/motion_templates/render.py`, `cli.py`)**：
   - Playwright 控制 Chromium 逐帧调用 `draw(t)` 截图管道注入 ffmpeg（H.264 / yuv420p）。
   - 渲染前先行生成 3×3 抽帧 Contact Sheet 网格图（`_contact.png`）。
   - CLI 支持 `--template`、`--spec`、`--out`、`--aspect 9:16|16:9|1:1`、`--fps`、`--audio`。
4. **8 个示例 Spec 与 12 支成片导出**（每模板 2 个 Hevi 题材 spec，各出 9:16 成片 + 16:9 版本，置于 `samples/aimotion/`，附 Contact Sheet 与 SHA256 校验）。
5. **完整自动化测试套件 (`tests/motion_templates/`)**：
   - 33 项测试全绿：含帧哈希确定性、文字安全区实际测量、ffprobe 媒体规格、Spec 不变量与闭式弹簧数学验证。
6. **架构与注册方案文档 (`docs/MOTION_TEMPLATES.md`)**：
   - 详细参数说明、参考来源 case id 署名、以及向 `hevi-fxreg`（Unified FX Registry）注册的实施方案。

---

## 2. 真实样片媒体规格与 SHA256 检验 (Real ffprobe Output)

所有 12 支样片均由 Playwright 真实渲染生成，并通过 `ffprobe` 与 `hashlib.sha256` 独立度量提取：

| 样片文件名 | 宽高 | 帧率 | 像素格式 | 时长(s) | 视频编码 | 音频 | 文件大小 | MP4 SHA256 | Contact Sheet 路径 | Contact Sheet SHA256 |
|---|---|---|---|---|---|---|---|---|---|---|
| `morph_ui_hevi_pipeline_9_16.mp4` | 1080×1920 | 30/1 | yuv420p | 10.00 | h264 | none | 243 KB | `902ba5d74c01ed9148dd3866701e34eb992251cdd5cc642b91506fdc25248eda` | `samples/aimotion/morph_ui_hevi_pipeline_9_16_contact.png` | `f79c99314fd26d3bfc185b59747e791528233b2cbd886ea7a9277fa761ad60b5` |
| `morph_ui_hevi_pipeline_16_9.mp4` | 1920×1080 | 30/1 | yuv420p | 10.00 | h264 | none | 300 KB | `bb6880671bf64e1929550e2089133d3a6b74a378714c811263e00038fd448d6f` | `samples/aimotion/morph_ui_hevi_pipeline_16_9_contact.png` | `5779af8e6b1ba74aa1af261487b1254708b542641f05b65753251ad3cefb3cb8` |
| `morph_ui_studio_ops_9_16.mp4` | 1080×1920 | 30/1 | yuv420p | 10.00 | h264 | none | 241 KB | `6269d152d170f9b39312a5b7e87d51a8a55e65d48f931df205d511f7de27dcc4` | `samples/aimotion/morph_ui_studio_ops_9_16_contact.png` | `0160cea62969776e115840a2970ccb6d3eaa73d4f8158999c2fcb3e70b20f362` |
| `timeline_ai_video_evolution_9_16.mp4` | 1080×1920 | 30/1 | yuv420p | 10.00 | h264 | none | 332 KB | `217adffc5da88d1d98df2bd2b342c4a91e554fc344118ede7fae40900418ca9e` | `samples/aimotion/timeline_ai_video_evolution_9_16_contact.png` | `e6172d5578ed06653a4301c034cfe3604dfb9f8364bc059e2d6c8222efd99e34` |
| `timeline_ai_video_evolution_16_9.mp4` | 1920×1080 | 30/1 | yuv420p | 10.00 | h264 | none | 600 KB | `705ad3320414cd44fed9516da0492b34da0ea3ed4dfbf8c0271064fb8e913a37` | `samples/aimotion/timeline_ai_video_evolution_16_9_contact.png` | `d16b6594f9b869226ac49b54ba25ce112e86061bf8d34736254819e280226bb7` |
| `timeline_hevi_milestones_9_16.mp4` | 1080×1920 | 30/1 | yuv420p | 10.00 | h264 | none | 308 KB | `04503251b887f33f5577b8f266284005034abf7aecec0287a197b0d82cb21180` | `samples/aimotion/timeline_hevi_milestones_9_16_contact.png` | `bfa2fbdc15f712a1d3f17def15bbc5e8fab6121eb126499a6b07df0f7d63c2b3` |
| `kinetic_bpm_beat_drop_9_16.mp4` | 1080×1920 | 30/1 | yuv420p | 10.00 | h264 | aac | 629 KB | `0b06c5e37e82863a95e67a5e34cfaab93c3a244f242aad5135fcd9add463cb04` | `samples/aimotion/kinetic_bpm_beat_drop_9_16_contact.png` | `366bb20740007cb50e3d9e82a8f1646ec7c3dce3c223fde4341f2542744405cb` |
| `kinetic_bpm_beat_drop_16_9.mp4` | 1920×1080 | 30/1 | yuv420p | 10.00 | h264 | aac | 1013 KB | `54b50a36081471246a4226461f0cff511d20301a0df09e2ffdad06d9c78d1734` | `samples/aimotion/kinetic_bpm_beat_drop_16_9_contact.png` | `e19eb405e3a25878191eae0201fa513c886e64195667d216f484a05801ae5ca7` |
| `kinetic_engine_tempo_9_16.mp4` | 1080×1920 | 30/1 | yuv420p | 10.00 | h264 | aac | 603 KB | `47f45bdc4537917caffa52b19374e82c9768439b2a72cb53b227c31c0eae9c35` | `samples/aimotion/kinetic_engine_tempo_9_16_contact.png` | `16159aa9f27f6b0941f8dae1063fa7357f66886a407f7ca5f78f2416c5e8d1d3` |
| `layer_build_pipeline_9_16.mp4` | 1080×1920 | 30/1 | yuv420p | 10.00 | h264 | none | 398 KB | `d6213b28dc5a12186a123d19400822ec2d23c7eb244466416015a804a6988337` | `samples/aimotion/layer_build_pipeline_9_16_contact.png` | `c9fab53bb0f0266dd24edc9ed5c86c76d8dede38c2810cedd9b8a79332edf7b9` |
| `layer_build_pipeline_16_9.mp4` | 1920×1080 | 30/1 | yuv420p | 10.00 | h264 | none | 503 KB | `adbeb7b49fc4b012cce981bd8784301162c346fb13f97af6cc61a2fa4e43cec1` | `samples/aimotion/layer_build_pipeline_16_9_contact.png` | `149ee0a65b3c0edb5ce8098937f11da2a645d2b6492ff6c5fbae669df00bbcc5` |
| `layer_build_datarun_9_16.mp4` | 1080×1920 | 30/1 | yuv420p | 10.00 | h264 | none | 411 KB | `34fdd777e8e98678ad158c264772c933672eff43ffc70cd003e5597a6f23fc66` | `samples/aimotion/layer_build_datarun_9_16_contact.png` | `57b9afe350bb7ff19f0033a809c433c57d6fa2a7e84ed4b6545bb81cb7f3bf64` |

---

## 3. 确定性渲染独立验证 (Determinism Verification)

通过 `test_frame_hash_determinism` 对四大模板（`morph_ui`, `timeline_explainer`, `kinetic_lyrics`, `layer_build`）分别在不同时间启动两次完全独立的渲染进程，逐帧收集 Canvas 截图的 SHA256 哈希值并进行严格相等比对：
```
Total frames tested per run: 22 (1.5s @ 15fps)
morph_ui:            hashes_run1 == hashes_run2 -> 100% Identical
timeline_explainer:  hashes_run1 == hashes_run2 -> 100% Identical
kinetic_lyrics:      hashes_run1 == hashes_run2 -> 100% Identical
layer_build:         hashes_run1 == hashes_run2 -> 100% Identical
```
**结论**：在纯函数 `draw(t)` 设计下，不存在跨帧累积浮点漂移或异步计时器干扰，确定性达到逐像素一致。

---

## 4. 自动化测试执行结果 (Pytest Results)

执行命令：
`PYTHONPATH=$PWD JWT_SECRET=test-secret-local .venv/bin/python -m pytest tests/motion_templates/ -v`

测试输出概要：
```
collected 33 items

tests/motion_templates/test_determinism.py::test_frame_hash_determinism[morph_ui-morph_ui_hevi_pipeline.json] PASSED
tests/motion_templates/test_determinism.py::test_frame_hash_determinism[timeline_explainer-timeline_ai_video_evolution.json] PASSED
tests/motion_templates/test_determinism.py::test_frame_hash_determinism[kinetic_lyrics-kinetic_bpm_beat_drop.json] PASSED
tests/motion_templates/test_determinism.py::test_frame_hash_determinism[layer_build-layer_build_pipeline.json] PASSED
tests/motion_templates/test_ffprobe_output.py::test_sample_ffprobe_invariants (12 samples) PASSED
tests/motion_templates/test_spec_validation.py::test_spec_structure_and_invariants (8 specs) PASSED
tests/motion_templates/test_spring_math.py::test_step_response_boundary_conditions PASSED
tests/motion_templates/test_spring_math.py::test_tiny_overshoot_underdamped PASSED
tests/motion_templates/test_spring_math.py::test_critically_damped_no_overshoot PASSED
tests/motion_templates/test_spring_math.py::test_multi_target_superposition PASSED
tests/motion_templates/test_spring_math.py::test_multi_target_statelessness PASSED
tests/motion_templates/test_text_safe_area.py::test_canvas_text_safe_area_no_overflow (4 templates) PASSED

======================== 33 passed in 94.95s ========================
```
**总通过条数**：33 passed / 0 failed / 0 skipped。

---

## 5. 代码质量与 Lint 对比 (Lint Before / After)

- **基线检查 (`lint_before.txt`)**：
  `3O_V3_LINT=FAIL (failed: check_no_sibling_call.py, check_omodul_signature.py, check_enabled_pillars.py, check_oprim_keyword_only.py)`，总计 1569 行。
- **完工检查 (`lint_after.txt`)**：
  `3O_V3_LINT=FAIL (failed: check_no_sibling_call.py, check_omodul_signature.py, check_enabled_pillars.py, check_oprim_keyword_only.py)`，总计 1569 行。
- **Diff 比对**：
  `diff -u lint_before.txt lint_after.txt` 为空，**新增代码引入的 Lint 违规数为 0**。
- **平坦命名空间校验**：`check_flat_namespace.py` 与 `check_no_project_prefix.py` 均保持 `[PASS]`。

---

## 6. 版权与开源边界合规

1. **Clean-room 实现**：未引入任何来自 `/data/soffy/refs/awesome-ai-motion` 的源码文件或素材切片。所有代码均为针对 Hevi 需求独立编写。
2. **规范署名**：在 `docs/MOTION_TEMPLATES.md` 中完整登记了案例编号（#2103483957266268381、#2103273003555402193、#2102554209166000267、#2102463796149440888、#2102606609574941028、#2109087249572749553、#2107548992640880755）及原作者署名。
3. **资产保护**：未向 Git 提交大尺寸 MP4 文件（`.gitignore` 已过滤 `*.mp4`），仅提交关键 3×3 Contact Sheet 视觉审计图（每张 ~100KB）。

---

DONE AMTPL-R1
