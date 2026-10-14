# AMTPL_DONE — 确定性纯函数动效模板交付报告 (Unit B · R2 修复闭环)

> Worktree: `/data/soffy/projects/hevi-amtpl`  
> Branch: `feat/aimotion-templates`  
> 基线: `7087c24a`  
> 标志: `DONE AMTPL-R2`  
> 环境: CPU-only / Playwright Headless Chromium (CPU 软件光栅) / ffmpeg libx264 yuv420p / pytest 9.0.3

---

## 1. R2 修复目标与完成概况 (H1–H5 全闭环)

针对独立核验（`AMTPL_FIX.md`）指出的 5 项缺陷，本工程在无外部分支依赖、无付费 API、无 Mock 的硬约束下完成了彻底修复：

1. **H1 16:9 / 1:1 响应式排版彻底重构（阻断项）**：
   - **根因根除**：废除导致横纵拉伸失调的 `sScale = width/1080` 与 `vScale = height/1920` 混用机制，统一采用单一基准尺度 `fScale = min(width, height) / 1080`；在 1080p 标准分辨率下无论 9:16、16:9 或 1:1 均保持一致物理字重与视觉层次。
   - **自适应多画幅布局参数**：
     - `timeline_explainer`: 16:9 切换为横向多卡片流线蓝图布局，卡片按内容实测尺寸撑开，行高严格 $\ge 1.35 \times$ 字号；9:16 与 1:1 保持竖向坐标轴，节点垂直居中。
     - `kinetic_lyrics`: 字号、冲拳盒子、双行间距（`split_box` 间距根据字号动态计算 $\ge 1.7 \times$ 字号）与滚动词栈（`ticker_stack` 间距 $\ge 1.45 \times$ 字号）全部绑定单一标度，彻底解决双行重叠与小标签被大字压盖问题。
     - `morph_ui`: 约束容器高度与内边距，大号指标数字与标题垂直间距扩大到安全距离（间距 $\ge 62\text{px}$）；柱状图柱体上限严格锁定在标题基线下方，绝不越界。
     - `layer_build`: 右侧技术卡片行高由绝对字号驱动，标签、标题与统计行垂直间隙充足（$\ge 1.4 \times$ 字号）。
2. **H2 文字安全区与防重叠真实物理测量测试（阻断项）**：
   - 彻底废除旧版只断言 `canvas.width == 1080` 的空测代码。
   - 在模板底层装配基于 W3C Canvas 2D 标准规范的物理墨水包围盒探针（基于 `actualBoundingBox*`，结合 `getTransform()` 屏幕坐标系变换），通过 `window.setRecordText(true)` 动态采集，默认状态完全关闭，不改变 `draw(t)` 纯函数像素。
   - 测试覆盖 4 套模板 × 2 个 spec × 3 种画幅（9:16 / 16:9 / 1:1），每 0.5s 采样一次，同时断言：(a) 所有文字包围盒在安全区内；(b) 同一时刻不透明度 $>0.5$ 的文字包围盒两两无交集；(c) 文字包围盒不越出其容器。
   - **旧 16:9 产物实测报 FAIL**（见后文第 4 节对比日志），修完后 **24 / 24 全部转绿 PASS**。
3. **H3 竖屏正文与标题字号提升（中）**：
   - `timeline_*_9_16`: 标题提升至 $\ge 44\text{px}$（实设 44px），正文提升至 $\ge 32\text{px}$（实设 32px，1080 宽基准）。
   - 卡片高度根据折行后实际行数实测撑开，卡片下部空白均匀收紧为优雅呼吸间距。
4. **H4 中文断词与规范分词（中）**：
   - 纠正 `kinetic_bpm_beat_drop.json` 的断词 `"零阶", "跃失"` 为专业术语 `"阶跃响应", "纯粹", "函数", "渲染"`。
   - 纠正 `kinetic_engine_tempo.json` 的断词 `"多宽", "高比"` 为标准分词 `"多画幅", "宽高比", "自动", "适配"`。
   - 编写 `test_spec_validation.py`：新增常见词防截断算法校验（`COMMON_WORDS` 词库遍历），并对两个示例 spec 进行了分词金标逐词断言。
5. **H5 杂项清理与自给自足（低）**：
   - `lint_before.txt` 与 `lint_after.txt` 已从 Git 索引彻底移除并加入 `.gitignore`。
   - `morph_ui` 彩色外发光已替换为中性低不透明度阴影（`rgba(0,0,0,0.45)`, blur 14px, offsetY 6px），无任何禁项霓虹辉光。
   - 编写 `scripts/gen_motion_template_audio.py` 并集成进 `render.py`：在遇到 `.gitignore` 过滤缺失的 WAV 音频时，自动调用 ffmpeg lavfi `aevalsrc` 现场合成确定性 120BPM click 音轨，并在 `docs/MOTION_TEMPLATES.md` 中完整登记。

---

## 2. 真实样片媒体规格与 SHA256 检验 (Real ffprobe Output · 16 Clips)

交付包含 **4 模板 × 2 spec × 9:16（8 支）+ 每个模板 1 支 16:9（4 支）+ 每个模板 1 支 1:1（4 支）= 共 16 支完整成片**。所有成片均重新由 Headless Chromium 渲染输出，附带 6 帧（3 列 × 2 行）Contact Sheet 视觉审计图：

| 样片文件名 | 宽高 | 帧率 | 像素格式 | 时长(s) | 视频编码 | 音频 | 文件大小 | MP4 SHA256 | Contact Sheet 路径 | Contact Sheet SHA256 |
|---|---|---|---|---|---|---|---|---|---|---|
| `morph_ui_hevi_pipeline_9_16.mp4` | 1080×1920 | 30/1 | yuv420p | 10.00 | h264 | none | 236 KB | `fd2a943a0527d0dcfae8f5a66645ed2c763e29fcd340d43390ca01f539ab0978` | `samples/aimotion/morph_ui_hevi_pipeline_9_16_contact.png` | `38a922628c0980b39c31ae84bd14c0f9bc366a6f16fba9b4383f34c4ff46a2fa` |
| `morph_ui_studio_ops_9_16.mp4` | 1080×1920 | 30/1 | yuv420p | 10.00 | h264 | none | 229 KB | `90c728723333576184a871c77bc996783db1f17a0c92acae029339bd8b598ff0` | `samples/aimotion/morph_ui_studio_ops_9_16_contact.png` | `54dd3410590800659fb6892763aac8a8e2377d57c7a42c84ae1a8a2f02ee562e` |
| `morph_ui_hevi_pipeline_16_9.mp4` | 1920×1080 | 30/1 | yuv420p | 10.00 | h264 | none | 252 KB | `75d7056af2438b671519004d81e0fe644c7dde18721eac148669b405a10187a0` | `samples/aimotion/morph_ui_hevi_pipeline_16_9_contact.png` | `820d4198ad0b9a3bf1002392f075ab947ae8bd44f5167f978e97223b5f41b12d` |
| `morph_ui_hevi_pipeline_1_1.mp4` | 1080×1080 | 30/1 | yuv420p | 10.00 | h264 | none | 170 KB | `2bcf1615ffce1c717454f154b2a380b47ffe1e47e7fb2aaf9f473896ccd30c94` | `samples/aimotion/morph_ui_hevi_pipeline_1_1_contact.png` | `323f2f9210bd0bbeb4208dc3272ea7d3084ce3e25f57b57c51be0eac1f6e990b` |
| `timeline_ai_video_evolution_9_16.mp4` | 1080×1920 | 30/1 | yuv420p | 10.00 | h264 | none | 634 KB | `dbbecadc718324f003d6fab8cf68ba092a83e844f6eeb53e6afb9b991918bcb3` | `samples/aimotion/timeline_ai_video_evolution_9_16_contact.png` | `2e69d5b990a40f3d5d139319e85a00e50a76446d47032907b6bd18c11f965bd4` |
| `timeline_hevi_milestones_9_16.mp4` | 1080×1920 | 30/1 | yuv420p | 10.00 | h264 | none | 587 KB | `c458295be156e5719b92c79e835ebf3d3cdd7fa73d385db662bbd2e51e3a5bdf` | `samples/aimotion/timeline_hevi_milestones_9_16_contact.png` | `6c2a085bd55b7377377751172e4ee238d3386c03e05a1944b23d44a93cb34401` |
| `timeline_ai_video_evolution_16_9.mp4` | 1920×1080 | 30/1 | yuv420p | 10.00 | h264 | none | 387 KB | `f443deec0e105e2df4d80b0fe893f1890cf3786e07b756cee075c07ca23786fd` | `samples/aimotion/timeline_ai_video_evolution_16_9_contact.png` | `e49058705b7450502ee33a8292140960fbb71b726f5f3a65666565304035e99e` |
| `timeline_ai_video_evolution_1_1.mp4` | 1080×1080 | 30/1 | yuv420p | 10.00 | h264 | none | 375 KB | `2f3a81fef3ee950a81e9a8e03335e9ff30fe83902e044c3f1ef74c3209942202` | `samples/aimotion/timeline_ai_video_evolution_1_1_contact.png` | `d05b96e83794fcffc0dc692f27f43a8cee4e409902d0e45779ec8505082cf46e` |
| `kinetic_bpm_beat_drop_9_16.mp4` | 1080×1920 | 30/1 | yuv420p | 10.00 | h264 | aac (-23.5 dB) | 509 KB | `0fbc31855c85569e42fdfc38258be5ab29809779e164012301da0eccd5a23fc0` | `samples/aimotion/kinetic_bpm_beat_drop_9_16_contact.png` | `7b24b84f9f406b86a9ba1ff0db7229f55b6efc33729a811718dc2fde0b5dca48` |
| `kinetic_engine_tempo_9_16.mp4` | 1080×1920 | 30/1 | yuv420p | 10.00 | h264 | aac (-23.5 dB) | 486 KB | `3fbe1b49d3c133133aba9fd952725b45e709b44a477da3024ddb55ee31d7a4de` | `samples/aimotion/kinetic_engine_tempo_9_16_contact.png` | `5b5ca87ec79d5d8c70c4009737f47564093ff36b3f4eb180b4493f3482139d35` |
| `kinetic_bpm_beat_drop_16_9.mp4` | 1920×1080 | 30/1 | yuv420p | 10.00 | h264 | aac (-23.5 dB) | 483 KB | `3ea1ca1cd01b7054cd1c559293065b55a6717c9238bba398d176de10ab6ba8b7` | `samples/aimotion/kinetic_bpm_beat_drop_16_9_contact.png` | `09b05eb2f7af16d0308a0320667d5bb63ff834749907219c7db9ceb874a0c3df` |
| `kinetic_bpm_beat_drop_1_1.mp4` | 1080×1080 | 30/1 | yuv420p | 10.00 | h264 | aac (-23.5 dB) | 507 KB | `a0074b3502b2dff5439c151be4bc8d572fb8f1fe11ae564e008a383d7bf90338` | `samples/aimotion/kinetic_bpm_beat_drop_1_1_contact.png` | `015a1621fcc3a7c2dac880b164bcb0c468a2a949bc68ca573030e249b1a88503` |
| `layer_build_pipeline_9_16.mp4` | 1080×1920 | 30/1 | yuv420p | 10.00 | h264 | none | 364 KB | `471c40f6ed6617e5c1f88f8903a3986ebe6ce8acfe54dc031b214b99d9b919a1` | `samples/aimotion/layer_build_pipeline_9_16_contact.png` | `29b5856d5f8ba44794c2fe5aa935d734a7047952704b967199bad2ad8a0aef9e` |
| `layer_build_datarun_9_16.mp4` | 1080×1920 | 30/1 | yuv420p | 10.00 | h264 | none | 377 KB | `4fe8e631c475c38c4862a38784eeee870fc6c3f193199e96a1b6d399c6a7a3dd` | `samples/aimotion/layer_build_datarun_9_16_contact.png` | `cf3ad38e869c0989f6aba150d77351d485c6398ad667e081cb2589d4ec3ffad2` |
| `layer_build_pipeline_16_9.mp4` | 1920×1080 | 30/1 | yuv420p | 10.00 | h264 | none | 371 KB | `489e5dbcbe2005cc67f87261c324e3af02111f2572ff83f9ce4ed33a8c92eec9` | `samples/aimotion/layer_build_pipeline_16_9_contact.png` | `3215d397803f229e91ffe83f7f957f4d5c52a3fbb2247bd6be7ffbc5f28bf3ec` |
| `layer_build_pipeline_1_1.mp4` | 1080×1080 | 30/1 | yuv420p | 10.00 | h264 | none | 369 KB | `51f6ad0f06821da6290bcf525804b510043d5844e361d3d135f469239f3305a8` | `samples/aimotion/layer_build_pipeline_1_1_contact.png` | `eeae6243ad07b10af30a526caf3fe2bee48abd310563d1964718f00aa4e3ff9d` |

---

## 3. 确定性渲染独立验证 (Determinism Verification)

通过 `test_frame_hash_determinism` 对四大模板（`morph_ui`, `timeline_explainer`, `kinetic_lyrics`, `layer_build`）在完全独立的两次 Chromium 无头进程中渲染并提取各帧 SHA256：
```
Total frames tested per run: 22 (1.5s @ 15fps)
morph_ui:            hashes_run1 == hashes_run2 -> 100% Identical
timeline_explainer:  hashes_run1 == hashes_run2 -> 100% Identical
kinetic_lyrics:      hashes_run1 == hashes_run2 -> 100% Identical
layer_build:         hashes_run1 == hashes_run2 -> 100% Identical
```
**结论**：在纯函数 `draw(t)` 设计下，不存在跨帧累积浮点漂移或异步计时器干扰，确定性达到逐像素一致。

---

## 4. 自动化测试执行结果 (Pytest Results · 61 Items)

### 4.1 新文字安全区与重叠测试对 R1 旧产物的实测 FAIL 输出 (Evidence)

在将新测试施加于未修复的 R1 模板代码（通过 fallback 原型链注入物理包围盒探针）时，**24 个用例中出现了 17 个失败**，真实捕获了 H1 指出的所有严重问题：

```
=========================== short test summary info ============================
FAILED tests/motion_templates/test_text_safe_area.py::test_text_safe_area_and_no_overlap[morph_ui.html-morph_ui_hevi_pipeline.json-16:9-1920-1080]
FAILED tests/motion_templates/test_text_safe_area.py::test_text_safe_area_and_no_overlap[morph_ui.html-morph_ui_hevi_pipeline.json-1:1-1080-1080]
FAILED tests/motion_templates/test_text_safe_area.py::test_text_safe_area_and_no_overlap[morph_ui.html-morph_ui_studio_ops.json-16:9-1920-1080]
FAILED tests/motion_templates/test_text_safe_area.py::test_text_safe_area_and_no_overlap[morph_ui.html-morph_ui_studio_ops.json-1:1-1080-1080]
FAILED tests/motion_templates/test_text_safe_area.py::test_text_safe_area_and_no_overlap[timeline_explainer.html-timeline_ai_video_evolution.json-16:9-1920-1080]
FAILED tests/motion_templates/test_text_safe_area.py::test_text_safe_area_and_no_overlap[timeline_explainer.html-timeline_ai_video_evolution.json-1:1-1080-1080]
FAILED tests/motion_templates/test_text_safe_area.py::test_text_safe_area_and_no_overlap[timeline_explainer.html-timeline_hevi_milestones.json-16:9-1920-1080]
FAILED tests/motion_templates/test_text_safe_area.py::test_text_safe_area_and_no_overlap[timeline_explainer.html-timeline_hevi_milestones.json-1:1-1080-1080]
FAILED tests/motion_templates/test_text_safe_area.py::test_text_safe_area_and_no_overlap[kinetic_lyrics.html-kinetic_bpm_beat_drop.json-16:9-1920-1080]
FAILED tests/motion_templates/test_text_safe_area.py::test_text_safe_area_and_no_overlap[kinetic_lyrics.html-kinetic_bpm_beat_drop.json-1:1-1080-1080]
FAILED tests/motion_templates/test_text_safe_area.py::test_text_safe_area_and_no_overlap[kinetic_lyrics.html-kinetic_engine_tempo.json-9:16-1080-1920]
FAILED tests/motion_templates/test_text_safe_area.py::test_text_safe_area_and_no_overlap[kinetic_lyrics.html-kinetic_engine_tempo.json-16:9-1920-1080]
FAILED tests/motion_templates/test_text_safe_area.py::test_text_safe_area_and_no_overlap[kinetic_lyrics.html-kinetic_engine_tempo.json-1:1-1080-1080]
FAILED tests/motion_templates/test_text_safe_area.py::test_text_safe_area_and_no_overlap[layer_build.html-layer_build_pipeline.json-16:9-1920-1080]
FAILED tests/motion_templates/test_text_safe_area.py::test_text_safe_area_and_no_overlap[layer_build.html-layer_build_pipeline.json-1:1-1080-1080]
FAILED tests/motion_templates/test_text_safe_area.py::test_text_safe_area_and_no_overlap[layer_build.html-layer_build_datarun.json-16:9-1920-1080]
FAILED tests/motion_templates/test_text_safe_area.py::test_text_safe_area_and_no_overlap[layer_build.html-layer_build_datarun.json-1:1-1080-1080]
17 failed, 7 passed in 18.95s
```

具体重叠实测佐证（摘录）：
- `timeline_explainer.html @ 16:9`:
  `t=0.00s OVERLAP area=13591.3px2 'TIMELINE EXPLAINER // LINE-ART ARCHITECTURE' <-> 'AI 视频模型技术演进史'`
  `t=1.00s OVERLAP area=7920.0px2 '时空解耦注意力机制突破' <-> 'Spatio-Temporal Decoupled Attention'`
- `kinetic_lyrics.html @ 16:9`:
  `t=3.40s OVERLAP area=9240.2px2 '节点 点亮' <-> '全链 贯通'`
  `t=7.00s OVERLAP area=4180.5px2 '零阶' <-> '跃失'`
- `morph_ui.html @ 16:9`:
  `t=5.00s OVERLAP area=2180.0px2 '原子镜头规划就绪' <-> '18'`

### 4.2 修复后完整自动化测试全绿 (R2 Final Test Suite)

执行命令：
`PYTHONPATH=$PWD JWT_SECRET=test-secret-local .venv/bin/python -m pytest tests/motion_templates/ -v`

测试输出概要：
```
collected 61 items

tests/motion_templates/test_audio_generation.py::test_beat_click_track_is_deterministic_and_valid PASSED [  1%]
tests/motion_templates/test_determinism.py::test_frame_hash_determinism[morph_ui-morph_ui_hevi_pipeline.json] PASSED [  3%]
tests/motion_templates/test_determinism.py::test_frame_hash_determinism[timeline_explainer-timeline_ai_video_evolution.json] PASSED [  4%]
tests/motion_templates/test_determinism.py::test_frame_hash_determinism[kinetic_lyrics-kinetic_bpm_beat_drop.json] PASSED [  6%]
tests/motion_templates/test_determinism.py::test_frame_hash_determinism[layer_build-layer_build_pipeline.json] PASSED [  8%]
tests/motion_templates/test_ffprobe_output.py::test_sample_ffprobe_invariants (16 samples) PASSED [ 34%]
tests/motion_templates/test_spec_validation.py::test_spec_structure_and_invariants (8 specs) PASSED [ 47%]
tests/motion_templates/test_spec_validation.py::test_kinetic_tokens_do_not_split_common_words (2 specs) PASSED [ 50%]
tests/motion_templates/test_spec_validation.py::test_hand_verified_kinetic_tokenization PASSED [ 52%]
tests/motion_templates/test_spring_math.py::test_step_response_boundary_conditions PASSED [ 54%]
tests/motion_templates/test_spring_math.py::test_tiny_overshoot_underdamped PASSED [ 55%]
tests/motion_templates/test_spring_math.py::test_critically_damped_no_overshoot PASSED [ 57%]
tests/motion_templates/test_spring_math.py::test_multi_target_superposition PASSED [ 59%]
tests/motion_templates/test_spring_math.py::test_multi_target_statelessness PASSED [ 60%]
tests/motion_templates/test_text_safe_area.py::test_text_safe_area_and_no_overlap (24 cases: 4 tpl x 2 specs x 3 aspects) PASSED [100%]

======================== 61 passed in 96.97s ========================
```
**总通过条数**：61 passed / 0 failed / 0 skipped。

---

## 5. 代码质量与 Lint 对比 (Lint Before / After)

- **基线检查 (`scripts/ci/run_3o_v3_lint.py`)**：
  `3O_V3_LINT=FAIL (failed: check_no_sibling_call.py, check_omodul_signature.py, check_enabled_pillars.py, check_oprim_keyword_only.py)`。
- **完工检查 (`scripts/ci/run_3o_v3_lint.py`)**：
  `3O_V3_LINT=FAIL (failed: check_no_sibling_call.py, check_omodul_signature.py, check_enabled_pillars.py, check_oprim_keyword_only.py)`。
- **违规增量**：0 项。
- **日志隔离**：`lint_before.txt` 与 `lint_after.txt` 已通过 `.gitignore` 过滤并未提交入库。

---

## 6. 版权与开源边界合规

1. **Clean-room 实现**：全代码自主编写，未引入任何外部未合并分支或侵权素材。
2. **规范署名**：保留 `docs/MOTION_TEMPLATES.md` 中全部来源案例 ID 与原作者署名。
3. **资产自给自足**：音轨由 ffmpeg 现场确定性合成，无外部依赖风险。

---

DONE AMTPL-R2
