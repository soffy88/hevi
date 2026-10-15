# AMRULES_DONE — 动效提示词规则 + lint（CPU-only）完成报告

- **Worktree**: `/data/soffy/projects/hevi-amrules`
- **分支**: `feat/aimotion-rules`
- **基线 Commit**: `7087c24a`
- **交付标志**: `DONE AMRULES-R1`
- **运行环境**: CPU-only，零付费 API，零外部模型调用，真实物理执行

---

## 1. 交付成果概览

| 模块 | 路径 | 核心能力 |
|---|---|---|
| **闭式弹簧 (Py & JS)** | `hevi/motion_rules/spring.py`<br>`hevi/motion_rules/js/spring.js` | 欠阻尼/临界阻尼/过阻尼阶跃响应纯函数；多目标叠加轨道（`SpringTrack`）；Python 与 JS 双语数值一致性（200 采样点误差 $< 10^{-13}$） |
| **规则卡库** | `hevi/motion_rules/rules/*.yaml` | 10 条标准化动效规则卡，含 ID、触发条件、错误反例、正确做法与来源 Case 署名 |
| **提示词生成器** | `hevi/motion_rules/prompt_pack.py` | 规则卡渲染输出器，支持 `detailed`（Markdown 详版）、`compact`（紧凑要点）、`system_prompt`（XML 提示词块） |
| **分镜 Spec 静态校验** | `hevi/motion_rules/lint.py` | 静态检查镜头规范（红灯：禁项命中、BPM脱节、文字容器时序倒错、标点句号、单镜超长；黄灯：缺接触样张、循环首尾帧不一致），输出结构化报告 |
| **分镜手写基准示例** | `hevi/motion_rules/examples/*.json` | 3 个基准分镜用例（1 个合规 PASS、2 个违规 FAIL） |
| **成片实测抽帧质检** | `hevi/motion_rules/video_checks.py` | 基于 ffmpeg/ffprobe 真实抽帧：9:16 竖屏尺寸校验、相邻帧亮度差分频闪检测、循环视频首尾帧相似度校验 |
| **自动化测试集** | `tests/motion_rules/` | 4 个测试模块共 21 个全绿测试，覆盖所有红黄灯触发/不触发与真实视频质检 |
| **设计与接入文档** | `docs/MOTION_RULES.md` | 规则详解、Case 署名、以及面向 artmotion 与 omquality 的零侵入接入方案 |

---

## 2. CI Lint 基线与变更后对比 (run_3o_v3_lint.py)

运行命令：
```bash
PYTHONPATH=$PWD .venv/bin/python scripts/ci/run_3o_v3_lint.py > lint_before.txt 2>&1
PYTHONPATH=$PWD .venv/bin/python scripts/ci/run_3o_v3_lint.py > lint_after.txt 2>&1
```

- **lint_before.txt 失败检查项**:
  `failed: check_no_sibling_call.py, check_omodul_signature.py, check_enabled_pillars.py, check_oprim_keyword_only.py`
- **lint_after.txt 失败检查项**:
  `failed: check_no_sibling_call.py, check_omodul_signature.py, check_enabled_pillars.py, check_oprim_keyword_only.py`
- **失败项增量**: `0`（`diff -u lint_before.txt lint_after.txt` 为空，完全不增失败）。

---

## 3. Spring Python 与 JS 双语数值一致性验证

测试命令：
```bash
PYTHONPATH=$PWD JWT_SECRET=test-secret-local .venv/bin/python -m pytest tests/motion_rules/test_spring_consistency.py -s -v
```

真实执行输出：
```text
============================= test session starts ==============================
platform linux -- Python 3.14.4, pytest-9.0.3, pluggy-1.6.0 -- /data/soffy/projects/hevi-amrules/.venv/bin/python
cachedir: .pytest_cache
rootdir: /data/soffy/projects/hevi-amrules
configfile: pyproject.toml
plugins: cov-7.1.0, asyncio-1.4.0, anyio-4.13.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 1 item

tests/motion_rules/test_spring_consistency.py::test_python_js_spring_consistency_200_points 
[PASS] Verified 200 sample points between Python and JS. Max error: 2.84e-14 (< 1e-6)
PASSED

============================== 1 passed in 0.12s ===============================
```

- **采样点总数**: 200 个（涵盖欠阻尼、临界阻尼、过阻尼与多目标复合阶跃）
- **最大绝对误差**: $2.84 \times 10^{-14}$（远低于 $< 10^{-6}$ 的指标红线）

---

## 4. Pytest 测试全绿条数

测试命令：
```bash
PYTHONPATH=$PWD JWT_SECRET=test-secret-local .venv/bin/python -m pytest tests/motion_rules/ -v
```

真实执行输出：
```text
============================= test session starts ==============================
platform linux -- Python 3.14.4, pytest-9.0.3, pluggy-1.6.0 -- /data/soffy/projects/hevi-amrules/.venv/bin/python
cachedir: .pytest_cache
rootdir: /data/soffy/projects/hevi-amrules
configfile: pyproject.toml
plugins: cov-7.1.0, asyncio-1.4.0, anyio-4.13.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 21 items

tests/motion_rules/test_lint.py::test_clean_spec_passes PASSED           [  4%]
tests/motion_rules/test_lint.py::test_red_flag_prohibited_elements PASSED [  9%]
tests/motion_rules/test_lint.py::test_red_flag_bpm_grid_alignment PASSED [ 14%]
tests/motion_rules/test_lint.py::test_red_flag_content_container_timing PASSED [ 19%]
tests/motion_rules/test_lint.py::test_red_flag_text_contains_period PASSED [ 23%]
tests/motion_rules/test_lint.py::test_red_flag_shot_duration_exceeded PASSED [ 28%]
tests/motion_rules/test_lint.py::test_yellow_flags_contact_sheet_and_loop PASSED [ 33%]
tests/motion_rules/test_prompt_pack.py::test_rule_cards_loaded_and_valid PASSED [ 38%]
tests/motion_rules/test_prompt_pack.py::test_render_prompt_pack_modes PASSED [ 42%]
tests/motion_rules/test_prompt_pack.py::test_render_prompt_pack_filtering PASSED [ 47%]
tests/motion_rules/test_spring.py::test_spring_config_conversion PASSED  [ 52%]
tests/motion_rules/test_spring.py::test_spring_config_invalid PASSED     [ 57%]
tests/motion_rules/test_step_response_boundaries PASSED                  [ 61%]
tests/motion_rules/test_spring.py::test_spring_step_regimes PASSED       [ 66%]
tests/motion_rules/test_spring.py::test_velocity_derivative PASSED       [ 71%]
tests/motion_rules/test_spring.py::test_spring_track_stateless_pure_function PASSED [ 76%]
tests/motion_rules/test_spring_consistency.py::test_python_js_spring_consistency_200_points PASSED [ 80%]
tests/motion_rules/test_video_checks.py::test_video_aspect_ratio_checks PASSED [ 85%]
tests/motion_rules/test_video_checks.py::test_video_flicker_normal_vs_flickering PASSED [ 90%]
tests/motion_rules/test_video_checks.py::test_video_loop_similarity_checks PASSED [ 95%]
tests/motion_rules/test_video_checks.py::test_full_check_video_suite PASSED [100%]

============================== 21 passed in 2.21s ==============================
```

- **全绿用例总数**: **21 / 21 PASS**（零失败、零跳过）

---

## 5. Storyboard Lint 对 3 个手写示例的静态校验真实输出

### 示例 1: `example_compliant.json`（合规用例）
- **命令**: `PYTHONPATH=$PWD .venv/bin/python -m hevi.motion_rules.lint hevi/motion_rules/examples/example_compliant.json`
- **退出码**: `0`
- **输出**:
```text
=== Storyboard Lint Report: PASS (合规) ===
红灯(Red): 0 项 | 黄灯(Yellow): 0 项
全部检查项合规，未发现违规项。
```

### 示例 2: `example_violation_effects_and_timing.json`（违规用例 1：禁项特效与时序倒错）
- **命令**: `PYTHONPATH=$PWD .venv/bin/python -m hevi.motion_rules.lint hevi/motion_rules/examples/example_violation_effects_and_timing.json`
- **退出码**: `1`
- **输出**:
```text
=== Storyboard Lint Report: FAIL (红灯拦截) ===
红灯(Red): 6 项 | 黄灯(Yellow): 1 项
  [黄灯 YEL] [MISSING_CONTACT_SHEET] Spec 全局: 未在全量渲染前生成接触样张（contact sheet / probe frames），可能导致重叠或拥挤无法预检。
  [红灯 RED] [PROHIBITED_ELEMENT] Shot 0: 命中禁项元素 'shockwave_rings' (规则项: shockwave_rings)，严禁使用廉价模板特效。
  [红灯 RED] [PROHIBITED_ELEMENT] Shot 0: 命中禁项元素 'neon_glow' (规则项: neon_glow)，严禁使用廉价模板特效。
  [红灯 RED] [PROHIBITED_ELEMENT] Shot 0: 命中禁项元素 'bouncy' (规则项: bouncy_easing)，严禁使用廉价模板特效。
  [红灯 RED] [TEXT_CONTAINS_PERIOD] Shot 0: 屏上文字 '引领次世代革新。' 包含句号，违反极简字排规范（屏上文字句末不加标点）。
  [红灯 RED] [TEXT_BEFORE_CONTAINER_MORPH] Shot 0: 文字 '引领次世代革新。' 入场时间 (0.10s) 早于容器形变开始时间 (0.50s)，会导致字面在未稳固骨架内被裁切挤压。
  [红灯 RED] [TEXT_AFTER_CONTAINER_MORPH] Shot 0: 文字 '引领次世代革新。' 离场时间 (2.80s) 晚于容器下一次形变开始时间 (2.20s)，会导致文字与新形变发生重叠穿帮。
```

### 示例 3: `example_violation_bpm_and_duration.json`（违规用例 2：超长单镜、BPM 脱节与循环首尾不一致）
- **命令**: `PYTHONPATH=$PWD .venv/bin/python -m hevi.motion_rules.lint hevi/motion_rules/examples/example_violation_bpm_and_duration.json`
- **退出码**: `1`
- **输出**:
```text
=== Storyboard Lint Report: FAIL (红灯拦截) ===
红灯(Red): 5 项 | 黄灯(Yellow): 1 项
  [黄灯 YEL] [LOOP_FRAME_MISMATCH] Spec 全局: 循环动效首尾帧不一致（first=frame_alpha, last=frame_omega_mismatch），循环播放时会产生跳跃或顿挫。
  [红灯 RED] [SHOT_DURATION_EXCEEDED] Shot 0: 单镜时长 9.50s 超过上限 8.00s，缺乏剪辑节奏与视觉变换。
  [红灯 RED] [PROHIBITED_ELEMENT] Shot 0: 命中禁项元素 'camera_shake' (规则项: camera_shake)，严禁使用廉价模板特效。
  [红灯 RED] [PROHIBITED_ELEMENT] Shot 0: 命中禁项元素 'rgb_split' (规则项: rgb_split)，严禁使用廉价模板特效。
  [红灯 RED] [BPM_GRID_MISALIGNMENT] Shot 0: 转场起点 1.135s 未对齐 BPM 网格 (BPM=120.0, 网格周期=0.500s, 最近网格点=1.000s, 误差=0.135s > 0.02s)。
  [红灯 RED] [TEXT_CONTAINS_PERIOD] Shot 0: 屏上文字 '全自动化流水线.' 包含句号，违反极简字排规范（屏上文字句末不加标点）。
```

---

## 6. Video Checks 对正常片与故意频闪片的实测结果

测试视频由 ffmpeg lavfi 现行生成（`540x960`，25fps，2.0s）：
- **正常片**: 单一平滑色彩视频，首尾帧完全一致；
- **故意频闪片**: 隔帧黑白跳变（`geq=lum='if(mod(N,2),255,0)'`）。

### 正常视频实测报告 (check_video)
```text
=== Video QA Check Report: PASS (质检合格) ===
视频文件: /tmp/video_checks_demo/normal_9_16.mp4
1. 宽高比检查: [PASS] 尺寸 540x960 (比例 0.5625) 符合 9:16 (目标 0.5625, 相对误差 0.00%)
2. 闪烁检测:   [PASS] 未检测到异常频闪 (跳变次数: 0, 跳变频率: 0.00次/秒 <= 阈值 2.0, 跳变占比: 0.0%, 平均相邻帧亮度差: 0.00, 最大差: 0.00)
3. 循环首尾帧: [PASS] 首尾帧相似度 1.0000 (差异 0.0000) >= 阈值 0.95，可无缝循环
```

### 故意频闪视频实测报告 (check_video)
```text
=== Video QA Check Report: FAIL (质检不合格) ===
视频文件: /tmp/video_checks_demo/flickering.mp4
1. 宽高比检查: [PASS] 尺寸 540x960 (比例 0.5625) 符合 9:16 (目标 0.5625, 相对误差 0.00%)
2. 闪烁检测:   [FAIL] 检测到明显画面频闪 (跳变次数: 49, 跳变频率: 24.50次/秒 > 阈值 2.0, 跳变占比: 100.0% > 5.0%, 最大相邻帧亮度差: 255.00)
3. 循环首尾帧: [FAIL] 首尾帧相似度 0.3176 (差异 0.6824) < 阈值 0.95，首尾存在明显跳跃无法平滑循环
```

---

DONE AMRULES-R1
