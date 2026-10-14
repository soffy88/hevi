# AMFX_DONE — morph/材质转场 + 运动模糊/多画幅渲染工程 (Unit C) 交付报告

Worktree: `/data/soffy/projects/hevi-amfx`  
分支: `feat/aimotion-fx`  
基线: `7087c24a`  
状态: **R2 修复完成，独立核验问题全项清零，真实执行验证通过**

---

## 1. 交付成果总览 (AMFX-R1 -> AMFX-R2)

落地 `AIMOTION_EVAL.md` 单元 C：全新独立包 `hevi/motion_fx/` 及自动化测试、文档与样片生成流水线，并在 R2 全面完成 H1-H4 专项修复与加固。

| 模块 | 核心能力 | R2 修复要点 | 交付文件 |
| :--- | :--- | :--- | :--- |
| **转场系统** | 3 个全新 morph/材质转场（线条转结构、水面涟漪、玻璃折射扫掠） | **H3**: 水面涟漪波前动态长宽比展宽，进度摊至整段 $p \in [0, 1]$；**H4**: 玻璃折射色散默认 $0.012$ 且硬截断 $\le 0.015$ | `hevi/motion_fx/transitions/` |
| **节拍网格** | `snap_to_grid(t, bpm, division)`，支持任意全音符/二分/四分/八分/十六分卡点 | 保持严密对齐（最大偏离 $5\times 10^{-7}\text{ s}$） | `hevi/motion_fx/beat.py` |
| **运动模糊渲染** | Playwright + HTML `draw(t)` 无状态纯时间函数，参数化 subframe ($N=4\sim 6$) 快门积分平均，支持 ffmpeg `tmix`，60fps/30fps | 保持拉普拉斯方差下降 $65.81\%$，万级平滑过渡像素 | `hevi/motion_fx/subframe.py` |
| **9:16 智能裁摆** | CPU-only YuNet 人脸检测 + 发言人运动能量加权 + 双人包容裁窗 + 时序中值背景消减 + 双向零相位平滑 + 镜头内速度硬限幅 | **H1**: 人脸优先跟人，相框墙误判清零，访谈片主体在窗率 $\ge 90\%$（实测 $98.23\%\sim 100\%$）；**H2**: 镜头内位移 $p95 \le 8\text{ px}$，$\max \le 20\text{ px}$，切点允许跳 | `hevi/motion_fx/reframe.py` |
| **自动化测试** | 全链路单元测试覆盖时长、编码、中间帧差异、抽帧对比、裁窗边界、主体占比与网格卡点 | 扩充至 **26 项测试全部 PASS**，测试内硬断言 H1 独立在窗率 $\ge 90\%$ 与 H2 $p95 \le 8\text{ px}$ | `tests/motion_fx/` |
| **工程文档** | 接口参数手册、5 个参考作品 Case ID 署名（无源码侵入）、并入 `hevi-xfadepack` 的转场注册方案 | 更新 R2 人物优先追踪、双向滤波平滑与色散上限契约 | `docs/MOTION_FX.md` |
| **真实样片** | 3 支 9:16 转场样片 + 2 支 9:16 reframe 真实样片、抽帧、6 帧 contact sheet 与裁窗画框图 | 全部重渲验证，SHA256 与 FFprobe 重新打卡 | `samples/aimotion_fx/` |

---

## 2. 真实样片验收数据 (FFprobe + SHA256)

样片存放在 `samples/aimotion_fx/`（遵循不提交 mp4/jpg 规则，真实文件经哈希校验）：

### 2.1 转场样片（9:16 竖屏，≤8s，H.264 yuv420p）

#### 1. `sample_line_to_structure.mp4`
- **转场类型**: `line_to_structure`（线条描绘→结构体形变接下一镜）
- **参考来源**: Case #9 `2109174851412119558` by Nick (@heyiamnick)
- **文件路径**: `samples/aimotion_fx/sample_line_to_structure.mp4`
- **SHA256**: `5f25b7b235ff6de42ba82ff16de6abb7e5bd302f2fac02a576c6810c7fad26d4`
- **中段抽帧路径**: `samples/aimotion_fx/sample_line_to_structure_mid.jpg`
- **FFprobe 规格**:
  ```text
  codec_name=h264
  width=720
  height=1280
  pix_fmt=yuv420p
  r_frame_rate=25/1
  duration=5.840000
  size=704700
  bit_rate=965342
  ```

#### 2. `sample_water_ripple.mp4` (AMFX-R2 H3 修复重渲)
- **转场类型**: `water_ripple`（水面涟漪/折射位移过渡 + 焦散高光）
- **参考来源**: Case #13 `2102786378282987591` by Aurelien (@Aurelien_Gz)
- **修复说明**: 重新计算波前动态视口半径，将折射位移与混合进度均匀摊展至整段过渡时长。$p=0.48$ 时实测与 A 差异 $40.10$、与 B 差异 $59.97$、与 50/50 叠化差异 $39.78$，彻底解决后半程提前失效问题。
- **文件路径**: `samples/aimotion_fx/sample_water_ripple.mp4`
- **SHA256**: `b1488f69fdda2750dbfb2bd31d8023fd6b171dffe01f672e8e75a009e7237011`
- **中段抽帧路径**: `samples/aimotion_fx/sample_water_ripple_mid.jpg`
- **FFprobe 规格**:
  ```text
  codec_name=h264
  width=720
  height=1280
  pix_fmt=yuv420p
  r_frame_rate=25/1
  duration=5.840000
  size=519620
  bit_rate=711808
  ```

#### 3. `sample_glass_refract.mp4` (AMFX-R2 H4 修复重渲)
- **转场类型**: `glass_refract`（透明/折射材质扫过 + RGB 微色散 + Fresnel 边缘高光）
- **参考来源**: Case #12 `2109257723246501895` by Ann Nguyen (@ann_nnng)
- **修复说明**: 默认色散系数调低为 `0.012` 并硬限幅 $\le 0.015$，彻底杜绝廉价 RGB Split 质感。
- **文件路径**: `samples/aimotion_fx/sample_glass_refract.mp4`
- **SHA256**: `2675fecca5d63edc6f5a893aae49c79ffca71a94505f6fbb2ec54c7a20e13564`
- **中段抽帧路径**: `samples/aimotion_fx/sample_glass_refract_mid.jpg`
- **FFprobe 规格**:
  ```text
  codec_name=h264
  width=720
  height=1280
  pix_fmt=yuv420p
  r_frame_rate=25/1
  duration=5.840000
  size=318483
  bit_rate=436278
  ```

---

### 2.2 9:16 Reframe 样片（对仓库内已有 16:9 真实素材重新裁摆）

#### 1. `sample_reframe_interview_9x16.mp4` (人物访谈 — H1, H2 重构)
- **输入素材**: `./artifacts/real_video/20261005T160434Z/artifacts/scene_interview_720p.mp4` (1280x720, 16:9 人物访谈)
- **输出文件**: `samples/aimotion_fx/sample_reframe_interview_9x16.mp4`
- **SHA256**: `c93c1633ef98b01d0f7de848b03f5c658af7b07a026a23800bfa48d07bd37740`
- **FFprobe 规格**:
  ```text
  codec_name=h264
  width=404
  height=720
  pix_fmt=yuv420p
  r_frame_rate=25/1
  codec_name=aac
  duration=6.037007
  size=749990
  bit_rate=993856
  ```
- **主体跟踪与平滑实测数值**:
  - **独立人脸/人体检测主体在窗内帧占比 (`subject_in_window_ratio`)**:
    - **6s 剪辑样片**: **`100.00%`** (152 / 152 帧，全部完全落在窗内)
    - **22.6s 完整全片**: **`98.23%`** (555 / 565 帧，断言 $\ge 90\%$ **PASS**)
  - **同镜头内帧间位移 (`displacement`)**:
    - **6s 剪辑样片**: `p50 = 2.00 px/帧`, `p95 = 4.00 px/帧`, `max = 6.00 px/帧`
    - **22.6s 完整全片**: `p50 = 2.00 px/帧`, `p95 = 7.00 px/帧`, `max = 8.00 px/帧`
    - 严格满足 $p95 \le 8.0\text{ px/帧}$ 与 $\max \le 20.0\text{ px/帧}$ 门禁要求
  - **镜头切换点**: 检测到 `[54, 98, 116, 151, 176, 186, 199, 348, 354, 399, 541]`，仅在切点允许瞬时跳跃。
  - **视觉证据产物**:
    - 6 帧 Contact Sheet: `samples/aimotion_fx/sample_reframe_interview_9x16_sheet.jpg`
    - 裁窗画在原片上的画框图: `samples/aimotion_fx/reframe_interview_windows.jpg`
  - `上下空带`: **无**（$H_{crop} = 720$，满高裁切）

#### 2. `sample_reframe_broll_9x16.mp4` (太空科学 ISS 空镜 — H2 重构)
- **输入素材**: `./artifacts/real_video/20261005T160434Z/artifacts/scene_broll_720p.mp4` (1280x720, 16:9 空镜/工作区)
- **输出文件**: `samples/aimotion_fx/sample_reframe_broll_9x16.mp4`
- **SHA256**: `b9924f2b3de87646c2682a12da1399dd94e96b51f4aae1aced9958d1d613ba61`
- **FFprobe 规格**:
  ```text
  codec_name=h264
  width=404
  height=720
  pix_fmt=yuv420p
  r_frame_rate=25/1
  codec_name=aac
  duration=6.037007
  size=474819
  bit_rate=629211
  ```
- **主体跟踪与平滑实测数值**:
  - **独立检测主体在窗内帧占比 (`subject_in_window_ratio`)**: **`100.00%`**
  - **同镜头内帧间位移 (`displacement`)**:
    - **6s 剪辑样片**: `p50 = 0.00 px/帧`, `p95 = 1.00 px/帧`, `max = 2.00 px/帧`
    - **14.0s 完整全片**: `p50 = 0.00 px/帧`, `p95 = 6.00 px/帧`, `max = 7.00 px/帧`
    - 从 R1 时代的 $p95 = 64\text{ px/帧}$（左右剧烈颠簸）彻底下降为 $p95 = 1.0\sim 6.0\text{ px/帧}$，全段极度丝滑稳定。
  - **镜头切换点**: 原片无切镜头 (`cuts = []`)，全片连续平滑运镜。
  - **视觉证据产物**:
    - 6 帧 Contact Sheet: `samples/aimotion_fx/sample_reframe_broll_9x16_sheet.jpg`
    - 裁窗画在原片上的画框图: `samples/aimotion_fx/reframe_broll_windows.jpg`
  - `上下空带`: **无**（$H_{crop} = 720$，满高裁切）

---

## 3. Subframe 运动模糊实测对比数值

对同一 1200 px/s 高速运动高对比度卡片场景分别以 $N=1$（单帧瞬间采样）与 $N=6$（6 个子帧偏移平均采样）渲染，计算定量边缘清晰度与模糊拖影指标：

| 指标 | $N=1$（单帧无模糊） | $N=6$（6 子帧运动模糊） | 变化幅度与分析 |
| :--- | :--- | :--- | :--- |
| **拉普拉斯边缘方差 (`laplacian_var`)** | `265.358` | `90.707` | **下降 65.81%**。高频阶跃边缘被平滑，有效消除频闪与断阶感 |
| **边缘梯度均值 (`sobel_mean`)** | `4.191` | `4.245` | 能量保持恒定，无整体变暗 |
| **过渡灰度像素数 (`intermediate_pixels`)** | `0` | `10,560` | **由 0 暴增至 10,560**。从严格二值硬边扩展为真实的平滑光学运动拖影 |
| **过渡像素占比 (`intermediate_ratio`)** | `0.00%` | `4.58%` | 形成符合快门开角 180° 的自然动态模糊区 |

---

## 4. 转场中段帧与首尾帧真实差异抽检

对三个转场的起始帧（$t=0$）、中段帧（$t=mid$）、结束帧（$t=end$）进行逐像素绝对均值差（Mean Absolute Difference）实测：

| 转场 | 中段帧与起始帧差异 $\Delta(start, mid)$ | 中段帧与结束帧差异 $\Delta(mid, end)$ | 判定结论 |
| :--- | :--- | :--- | :--- |
| `line_to_structure` | `80.63 / 255` | `81.65 / 255` | ✅ 显著独立，呈现图纸与结构形变 |
| `water_ripple` (R2) | `40.10 / 255` | `59.97 / 255` | ✅ 显著独立，全长波纹位移扩散，vs叠化差异 39.78 |
| `glass_refract` (R2) | `70.15 / 255` | `79.82 / 255` | ✅ 显著独立，厚玻璃折射柱面扫掠，微色散硬截断 0.015 |

---

## 5. Pytest 测试用例结果 (26 passed)

执行命令：
```bash
PYTHONPATH=$PWD JWT_SECRET=test-secret-local .venv/bin/python -m pytest tests/motion_fx/ -v
```

执行结果：
```text
tests/motion_fx/test_beat.py::test_parse_division PASSED                 [  3%]
tests/motion_fx/test_beat.py::test_get_grid_step PASSED                  [  7%]
tests/motion_fx/test_beat.py::test_snap_to_grid_quarter_notes PASSED     [ 11%]
tests/motion_fx/test_beat.py::test_snap_to_grid_eighth_notes PASSED      [ 15%]
tests/motion_fx/test_beat.py::test_snap_to_grid_clamped PASSED           [ 19%]
tests/motion_fx/test_beat.py::test_generate_beat_grid PASSED             [ 23%]
tests/motion_fx/test_reframe.py::test_detect_subject PASSED              [ 26%]
tests/motion_fx/test_reframe.py::test_reframe_crop_bounds_and_coverage PASSED [ 30%]
tests/motion_fx/test_reframe.py::test_reframe_render_output PASSED       [ 34%]
tests/motion_fx/test_reframe.py::test_reframe_passthrough_for_vertical PASSED [ 38%]
tests/motion_fx/test_reframe.py::test_render_multi_aspect_parallel PASSED [ 42%]
tests/motion_fx/test_reframe.py::test_reframe_interview_face_containment_and_smoothness PASSED [ 46%]
tests/motion_fx/test_reframe.py::test_reframe_broll_smoothness PASSED    [ 50%]
tests/motion_fx/test_subframe.py::test_subframe_blur_comparison PASSED   [ 53%]
tests/motion_fx/test_subframe.py::test_subframe_fps_parameterization PASSED [ 57%]
tests/motion_fx/test_subframe.py::test_tmix_motion_blur PASSED           [ 61%]
tests/motion_fx/test_transitions.py::test_transitions_duration_and_encoding[line_to_structure] PASSED [ 65%]
tests/motion_fx/test_transitions.py::test_transitions_duration_and_encoding[water_ripple] PASSED [ 69%]
tests/motion_fx/test_transitions.py::test_transitions_duration_and_encoding[glass_refract] PASSED [ 73%]
tests/motion_fx/test_transitions.py::test_transition_middle_frame_differs[line_to_structure] PASSED [ 76%]
tests/motion_fx/test_transitions.py::test_transition_middle_frame_differs[water_ripple] PASSED [ 80%]
tests/motion_fx/test_transitions.py::test_transition_middle_frame_differs[glass_refract] PASSED [ 84%]
tests/motion_fx/test_transitions.py::test_transition_with_bpm_snapped_start PASSED [ 88%]
tests/motion_fx/test_transitions.py::test_unknown_transition PASSED      [ 92%]
tests/motion_fx/test_transitions.py::test_water_ripple_middle_progress_difference PASSED [ 96%]
tests/motion_fx/test_transitions.py::test_glass_refract_dispersion_ceiling PASSED [100%]

============================= 26 passed in 25.61s ==============================
```
**总计 26 项测试全部绿灯通过。**

---

## 6. Lint 门禁检查 (3O v3 Lint)

- 检查命令：`PYTHONPATH=$PWD .venv/bin/python scripts/ci/run_3o_v3_lint.py`
- 执行结论：
  ```text
  [PASS] check_obase_no_reverse_dep.py
  [PASS] check_oservi_injection.py
  [PASS] check_async_contract.py
  failed: check_no_sibling_call.py, check_omodul_signature.py, check_enabled_pillars.py, check_oprim_keyword_only.py
  ```
- **门禁结论**: 失败项仍为基线既有的 4 项，**未增加任何新失败项**。
- **H4 合规**: `lint_before.txt` 与 `lint_after.txt` 已通过 `git rm --cached` 从版本库完全解纳并加入 `.gitignore`，本仓库绝不提交任何日志文件。

---

DONE AMFX-R2
