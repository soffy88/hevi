# AMFX_DONE — morph/材质转场 + 运动模糊/多画幅渲染工程 (Unit C) 交付报告

Worktree: `/data/soffy/projects/hevi-amfx`  
分支: `feat/aimotion-fx`  
基线: `7087c24a`  
状态: **全部功能交付完成，真实执行验证通过**

---

## 1. 交付成果总览

落地 `AIMOTION_EVAL.md` 单元 C：全新独立包 `hevi/motion_fx/` 及自动化测试、文档与样片生成流水线。

| 模块 | 核心能力 | 交付文件 |
| :--- | :--- | :--- |
| **转场系统** | 3 个全新 morph/材质转场（线条转结构、水面涟漪、玻璃折射扫掠），支持 BPM 节拍网格卡点 | `hevi/motion_fx/transitions/` |
| **节拍网格** | `snap_to_grid(t, bpm, division)`，支持任意全音符/二分/四分/八分/十六分卡点 | `hevi/motion_fx/beat.py` |
| **运动模糊渲染** | Playwright + HTML `draw(t)` 无状态纯时间函数，参数化 subframe ($N=4\sim 6$) 快门积分平均，支持 ffmpeg `tmix`，60fps/30fps | `hevi/motion_fx/subframe.py` |
| **9:16 智能裁摆** | CPU-only 频域残差显著性 + 运动能量加权分析，平滑跟踪，主体占比 $\ge 50\%$，无上下黑边，竖屏直接穿透；支持 9:16/16:9/1:1 并行导出 | `hevi/motion_fx/reframe.py` |
| **自动化测试** | 22 项全链路单元测试覆盖时长、编码、中间帧差异、抽帧对比、裁窗边界、主体占比与网格卡点 | `tests/motion_fx/` |
| **工程文档** | 接口参数手册、5 个参考作品 Case ID 署名（无源码侵入）、并入 `hevi-xfadepack` 的转场注册方案 | `docs/MOTION_FX.md` |
| **真实样片** | 3 支 9:16 转场样片 + 2 支 9:16 reframe 真实样片及中间抽帧 | `samples/aimotion_fx/` |

---

## 2. 真实样片验收数据 (FFprobe + SHA256)

样片存放在 `samples/aimotion_fx/`（遵循不提交 mp4 规则，真实文件经哈希校验）：

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

#### 2. `sample_water_ripple.mp4`
- **转场类型**: `water_ripple`（水面涟漪/折射位移过渡 + 焦散高光）
- **参考来源**: Case #13 `2102786378282987591` by Aurelien (@Aurelien_Gz)
- **文件路径**: `samples/aimotion_fx/sample_water_ripple.mp4`
- **SHA256**: `a30856ad94ecd4c90f75e1a8d853857fa486d83a567dd61166681e00b5e274c0`
- **中段抽帧路径**: `samples/aimotion_fx/sample_water_ripple_mid.jpg`
- **FFprobe 规格**:
  ```text
  codec_name=h264
  width=720
  height=1280
  pix_fmt=yuv420p
  r_frame_rate=25/1
  duration=5.840000
  size=414550
  bit_rate=567876
  ```

#### 3. `sample_glass_refract.mp4`
- **转场类型**: `glass_refract`（透明/折射材质扫过 + RGB 色散 + Fresnel 边缘高光）
- **参考来源**: Case #12 `2109257723246501895` by Ann Nguyen (@ann_nnng)
- **文件路径**: `samples/aimotion_fx/sample_glass_refract.mp4`
- **SHA256**: `302f0d9ac29488c4aa548a26eb654031a4ce581ef77b03e49412bdfa814402ce`
- **中段抽帧路径**: `samples/aimotion_fx/sample_glass_refract_mid.jpg`
- **FFprobe 规格**:
  ```text
  codec_name=h264
  width=720
  height=1280
  pix_fmt=yuv420p
  r_frame_rate=25/1
  duration=5.840000
  size=324968
  bit_rate=445161
  ```

---

### 2.2 9:16 Reframe 样片（对仓库内已有 16:9 真实素材裁摆）

#### 1. `sample_reframe_interview_9x16.mp4`
- **输入素材**: `./artifacts/real_video/20261005T160434Z/artifacts/scene_interview_720p.mp4` (1280x720, 16:9 人物访谈)
- **输出文件**: `samples/aimotion_fx/sample_reframe_interview_9x16.mp4`
- **SHA256**: `a2592d8f0487722f905f131bf0e8b80c62c790826d6ab98ea3b6b16f89f7d3e2`
- **FFprobe 规格**:
  ```text
  codec_name=h264
  width=404
  height=720
  pix_fmt=yuv420p
  r_frame_rate=25/1
  codec_name=aac
  duration=6.037007
  size=695132
  bit_rate=921161
  ```
- **主体跟踪实测数值**:
  - `subject_captured_mean`: `87.53%`
  - `window_occupancy_mean`: `90.29%`
  - `subject_coverage`: **`90.29%`** ($\ge 50\%$)
  - `上下空带`: **无**（$H_{crop} = 720$，满高裁切）

#### 2. `sample_reframe_broll_9x16.mp4`
- **输入素材**: `./artifacts/real_video/20261005T160434Z/artifacts/scene_broll_720p.mp4` (1280x720, 16:9 空镜/工作区)
- **输出文件**: `samples/aimotion_fx/sample_reframe_broll_9x16.mp4`
- **SHA256**: `d9d459a0cdd442832ffa96ad64ef8846468cd1c35b979de39820a45f490ce51c`
- **FFprobe 规格**:
  ```text
  codec_name=h264
  width=404
  height=720
  pix_fmt=yuv420p
  r_frame_rate=25/1
  codec_name=aac
  duration=6.037007
  size=608094
  bit_rate=805821
  ```
- **主体跟踪实测数值**:
  - `subject_captured_mean`: `97.81%`
  - `window_occupancy_mean`: `72.07%`
  - `subject_coverage`: **`97.81%`** ($\ge 50\%$)
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
| `water_ripple` | `86.44 / 255` | `56.18 / 255` | ✅ 显著独立，呈现强水面折射与焦散光斑 |
| `glass_refract` | `71.64 / 255` | `81.38 / 255` | ✅ 显著独立，呈现高对比棱镜扫掠与色散 |

---

## 5. Pytest 测试用例结果

执行命令：
```bash
PYTHONPATH=$PWD JWT_SECRET=test-secret-local .venv/bin/python -m pytest tests/motion_fx/ -v
```

执行结果：
```text
tests/motion_fx/test_beat.py::test_parse_division PASSED                 [  4%]
tests/motion_fx/test_beat.py::test_get_grid_step PASSED                  [  9%]
tests/motion_fx/test_beat.py::test_snap_to_grid_quarter_notes PASSED     [ 13%]
tests/motion_fx/test_beat.py::test_snap_to_grid_eighth_notes PASSED      [ 18%]
tests/motion_fx/test_beat.py::test_snap_to_grid_clamped PASSED           [ 22%]
tests/motion_fx/test_beat.py::test_generate_beat_grid PASSED             [ 27%]
tests/motion_fx/test_reframe.py::test_detect_subject PASSED              [ 31%]
tests/motion_fx/test_reframe.py::test_reframe_crop_bounds_and_coverage PASSED [ 36%]
tests/motion_fx/test_reframe.py::test_reframe_render_output PASSED       [ 40%]
tests/motion_fx/test_reframe.py::test_reframe_passthrough_for_vertical PASSED [ 45%]
tests/motion_fx/test_reframe.py::test_render_multi_aspect_parallel PASSED [ 50%]
tests/motion_fx/test_subframe.py::test_subframe_blur_comparison PASSED   [ 54%]
tests/motion_fx/test_subframe.py::test_subframe_fps_parameterization PASSED [ 59%]
tests/motion_fx/test_subframe.py::test_tmix_motion_blur PASSED           [ 63%]
tests/motion_fx/test_transitions.py::test_transitions_duration_and_encoding[line_to_structure] PASSED [ 68%]
tests/motion_fx/test_transitions.py::test_transitions_duration_and_encoding[water_ripple] PASSED [ 72%]
tests/motion_fx/test_transitions.py::test_transitions_duration_and_encoding[glass_refract] PASSED [ 77%]
tests/motion_fx/test_transitions.py::test_transition_middle_frame_differs[line_to_structure] PASSED [ 81%]
tests/motion_fx/test_transitions.py::test_transition_middle_frame_differs[water_ripple] PASSED [ 86%]
tests/motion_fx/test_transitions.py::test_transition_middle_frame_differs[glass_refract] PASSED [ 90%]
tests/motion_fx/test_transitions.py::test_transition_with_bpm_snapped_start PASSED [ 95%]
tests/motion_fx/test_transitions.py::test_unknown_transition PASSED      [100%]

============================= 22 passed in 13.34s ==============================
```
**总计 22 项测试全部绿灯通过。**

---

## 6. Lint 门禁比对 (lint_before vs lint_after)

- 基线检查：`PYTHONPATH=$PWD .venv/bin/python scripts/ci/run_3o_v3_lint.py > lint_before.txt 2>&1`
- 完工检查：`PYTHONPATH=$PWD .venv/bin/python scripts/ci/run_3o_v3_lint.py > lint_after.txt 2>&1`
- 比对结果：
  ```bash
  diff -u lint_before.txt lint_after.txt
  # 输出为空（0 行差异）
  ```
- 失败项数未增加，完全符合通用规则门禁。

---

DONE AMFX-R1
