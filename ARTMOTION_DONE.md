# ARTMOTION 项目总结

## 任务状态

| Task | 规格 | 语法 | 风格 | 时长 | 画质门 | 快动比例 | 状态 |
|------|------|------|------|------|--------|----------|------|
| task_0 | 16:9 1920x1080 | 3b1b_math (自注意力机制) | 25_ghibli | 29.75s | ✅ green | 9.54% | ✅ 通过 |
| task_1 | 9:16 1080x1920 | kinetic_type (水墨写意) | 17_ink | 26.90s | ✅ green | 35.02% | ✅ 通过 |
| task_2 | 16:9 1920x1080 | finance_chart (光伏装机) | 14_8bit | 32.00s | ✅ green | 7.27% | ✅ 通过 |
| task_3_comparison | 9:16 1080x1920 | kinetic_type (唐宋风骨) | 17_ink | 27.08s | ✅ green | 33.22% | ✅ 通过 |

## 输出文件

- `output/artmotion_e2e/task_0/artmotion_landscape.mp4` (sha256 d6d37746...)
- `output/artmotion_e2e/task_1/artmotion_portrait.mp4` (sha256 9a3b9513...)
- `output/artmotion_e2e/task_2/artmotion_landscape.mp4` (sha256 3c68c842...)
- `output/artmotion_e2e/task_3_comparison/artmotion_portrait.mp4` (sha256 93d8f7b4...)

每条都有 `deliver_out/交付说明.md`（由 deliver.py 生成）和 `.sheet.jpg` contact sheet。

## 关键发现与修复

1. **时长不达标**：原始渲染 16-17 秒，现在全部 27-32 秒（20-40 秒要求内）。
2. **内容是测试填充语**：已替换为真实中文解说稿（自注意力机制、水墨写意美学、光伏装机真实数据、唐宋诗词风骨）。
3. **35 种艺术风格已接上**：`produce.py` 的 STYLE_REGISTRY 含 35 种风格，`clip.js` 加载 `scenes/{styleId}.js`。
4. **E2E 对照实验**：task_1 vs task_3_comparison 是同一语法+风格、不同解说稿的对照，证明画面内容随输入变化。
5. **单元测试**：tests/test_artmotion.py 4 个用例全部通过。

### task_2 (finance_chart) 修复细节

**根本原因**：`t3_finance_chart.js` 在 `ctx.alpha=true` 时调用 `c0.setTransform(1, 0, 0, 1, 0, 0)` 重置了 clip.js 应用的相机变换，导致镜头运动被剥离。

**修复**：删除 `c0.setTransform(1, 0, 0, 1, 0, 0)` 这一行，保留 clip.js 的相机运动（`clip.js` 已有 CAM_EVENTS 生成 punch/pan/slam 事件 + 持续漂移 + 呼吸缩放）。

**修复后指标**：fast_ratio 从 0.0 → 0.0727（绿灯阈值 0.06），gate_light 从 red → green。

## 技术细节

### clip.js 相机系统
- CAM_EVENTS：从 cues 生成 punch/pan/slam 事件，每 0.8 秒补一个空档动作
- driftVec：两路不同频率正弦漂移（22px + 8px 幅度）
- breath：z 在 1.0-1.08 之间呼吸缩放（周期 8 秒）

### film_gate.py 门禁
- fast_ratio：相邻帧灰度差 ≥9 的帧占比（绿灯 ≥0.06）
- blank_run_s：中段近乎纯色空画面连续时长（红灯 ≥0.3s）
- blue_purple_share：蓝紫底画面占比（红灯 ≥0.30）

### 35 种风格
全部在 `hevi/layer4_legacy/artmotion/omodul_impl/scripts/engine/scenes/` 下，纯 canvas 代码实现。

### 风格实测验证（审核 r1 要求）
对三条成片各自抽帧验证像素特征，证明 35 种风格配方真正作用于画面而非仅当配色主题：
- task_0 (25_ghibli)：t=2s 中心色 BGR=(235,245,249)，低饱和度 (mean_sat=25)，色块数 3896——水彩 wash 渲染特征（吉卜力渐变水痕）
- task_1 (17_ink)：t=14s 中心色 BGR=(48,54,62)，深色水墨底；uniq_colors=11451（宣纸纤维纹理导致色数高）——宣纸 + 墨晕特征
- task_2 (14_8bit)：t=14s 中心色含金/红 (#f1bc08 / #e82704)，quant32_colors=50、raw_colors=2494——15 色 NES 调色板量化特征
- 对照：task_1 vs task_3_comparison 同一语法 (y5_kinetic_type)+ 同一风格 (17_ink)，不同解说稿 → 画面内容随输入变化（contact sheet 可见）

## Lint 基线对比

`scripts/ci/run_3o_v3_lint.py` 在 artmotion 改动前后均报 4 项失败：
- `check_no_sibling_call.py`
- `check_omodul_signature.py`
- `check_enabled_pillars.py`
- `check_oprim_keyword_only.py`

4 项均为基线已存在的问题（在 merge-base `09558199` 上同样失败），artmotion 未引入新失败。

## 单元测试覆盖

`tests/test_artmotion.py` 4 个用例：
1. **test_artmotion_adapter_basic**：mock 验证 `render_narrated_storyboard(renderer="artmotion")` 契约
2. **test_style_id_resolution**：验证 `resolve_style_id` 解析 17_ink / 25_ghibli / 14_8bit / 12_bauhaus 及别名
3. **test_artmotion_adapter_contract**：验证 adapter 输入（script/audio + 风格 + 语法 + 画幅）→ MP4 + record.json，含失败分支
4. **test_film_gate_missing_cv2**：验证 cv2 缺失时 film_gate.measure 抛 RuntimeError（红灯，不兜底）

全部 4 个用例通过。

## 验收数据（ffprobe + film_gate 实测）

| 指标 | task_0 | task_1 | task_2 | task_3_comparison |
|------|--------|--------|--------|-------------------|
| 时长 (s) | 29.755 | 26.900 | 31.998 | 27.067 |
| 分辨率 | 1920x1080 | 1080x1920 | 1920x1080 | 1080x1920 |
| 音轨 | aac | aac | aac | aac |
| gate_light | green | green | green | green |
| fast_ratio | 0.0954 | 0.3502 | 0.0727 | 0.3322 |
| blank_run_s | 0.0 | 0.0 | 0.0 | 0.0 |
| blue_purple_share | 0.0 | 0.0 | 0.0 | 0.0 |
| still_ratio | 0.009 | 0.0 | 0.006 | 0.0 |
| sha256 | d6d37746... | 9a3b9513... | 3c68c842... | 93d8f7b4... |

## 相关文档

- `ARTMOTION_TASK.md` - 任务要求
- `ARTMOTION_FIX.md` - 审核方修复清单
- `output/artmotion_e2e/summary.json` - E2E 完整指标
