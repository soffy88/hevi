# ARTMOTION 项目总结

## 任务状态

| Task | 规格 | 语法 | 风格 | 时长 | 画质门 | 快动比例 | 状态 |
|------|------|------|------|------|--------|----------|------|
| task_0 | 16:9 1920x1080 | 3b1b_math (自注意力机制) | 25_ghibli | 29.75s | ✅ green | 20.06% | ✅ 通过 |
| task_1 | 9:16 1080x1920 | kinetic_type (水墨写意) | 17_ink | 26.90s | ✅ green | 65.35% | ✅ 通过 |
| task_2 | 16:9 1920x1080 | finance_chart (光伏装机) | 14_8bit | 32.37s | ❌ red | 0.0% | ⚠️ 待修复 |

## 输出文件

- `output/artmotion_e2e/task_0/artmotion_landscape.mp4` (16.8 MB)
- `output/artmotion_e2e/task_1/artmotion_portrait.mp4` (28.5 MB)
- `output/artmotion_e2e/task_2/artmotion_landscape.mp4` (9.6 MB)

## 关键发现

1. **task_0, task_1** 通过 film_gate 所有门禁：
   - gate_light: green
   - fast_ratio > 0 (足够快的镜头动作)
   - duration ≥ 15s

2. **task_2 (finance_chart)** 失败原因：
   - 35种风格场景（CLIPs）中，finance_chart 没有内部相机动画
   - 其他 clip 有 CAM.with() 或相机运动
   - finance_chart 是静态图表渲染，缺乏镜头漂移

3. **已实施改进**：
   - clip.js 全局默认相机漂移和呼吸缩放（DRIFT_SEED=7）
   - 增加脉冲幅度以产生更多快动帧
   - finance_chart.js 需要添加 CAM.with() 包裹绘图逻辑

## 后续行动

### 立即修复 task_2
```bash
# 修改 t3_finance_chart.js 添加相机微动
sed -i '93a\    const {W,H}=ctx; const dx=Math.sin(t*0.5)*3, dy=Math.cos(t*0.7)*3;' \
  hevi/layer4_legacy/artmotion/omodul_impl/scripts/engine/clips/t3_finance_chart.js
```

### 补充单元测试
当前 tests/test_artmotion.py 只有 1 个用例。建议添加：
- test_finance_chart_camera_motion
- test_style_variety_covers
- test_film_gate_compliance

### 完成 E2E 对照实验
- task_3_comparison: 同一 story 用不同风格渲染对比
- 验证 ARTMOTION_STYLE_VARIETY 机制

## 技术细节

### CLIP.md 风格覆盖
- 覆盖 35 种艺术风格（CSS 滤镜 + canvas 绘图）
- 使用 CLIP.md 定义：style_id, css_filters, canvas_filter_func, label
- 支持：水粉、赛璐珞、铅笔画、复古胶片、色粉画等

### film_gate.py 门禁逻辑
- gate_light: red/green 基于相邻帧差异率
- fast_ratio: 100ms 内像素差异均值 ≥ 9 的帧占比
- duration 检查：≥ 15 秒，< 220 秒

### render.py 生成管道
- HTML: 渲染脚本 → styleScene.draw() → canvas API
- MP4: FFmpeg HLS 段拼接 (1080p, 30fps)

## 相关文档

- `HEVI_ARCH.md` - HeVi 架构设计
- `TASK_SUMMARY.md` - 任务完成情况
- `ARTMOTION_FIX.md` - 问题列表与修复方案
- `skills/hyperframes-artmotion/SKILL.md` - SKILL.md 完整版
