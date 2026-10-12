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

## 相关文档

- `ARTMOTION_TASK.md` - 任务要求
- `ARTMOTION_FIX.md` - 审核方修复清单
- `output/artmotion_e2e/summary.json` - E2E 完整指标
