# PARTSCI-R1：粒子科普动画线完成报告

## 做了什么 (Work Completed)
1. **粒子引擎与确定性渲染**:
   - 实现了基于 seeded RNG (mulberry32) 的确定性 Canvas 2D 粒子系统与动画帧循环。
   - 实现了文字→粒子、形状→粒子及轨迹/流体参数化动画。
2. **六层视差构图系统**:
   - 实现了远景、中远景、主体、前景、粒子、字幕等六层视差构图，支持 16:9 与 9:16 自适应与标题安全区控制。
3. **后期与语义配色**:
   - 实现了全局 bloom 效果与胶片颗粒感叠加，配置了水、热、生命、能量、天空等幼儿科普语义配色表。
4. **内容与防错流程**:
   - 集成了事实卡知识库（绑定 NASA / NOAA 等真实公开来源 URL，严禁编造），实现了剧本因果机制与事实卡的规则防错（`verify_mechanism`）。
   - 实现了 storyboard 审批闸门：未审批的剧本在校验阶段直接拦截，拒绝渲染。
5. **声音与字幕对齐**:
   - 集成了 Piper TTS 中文幼儿语速旁白合成（带时长约束与慢速尺度）+ 响度标准化（-16 LUFS，真峰值 ≤ -1.5 dBTP）与字幕对齐。
6. **审片与自动质检**:
   - 完整接入 `kids_gate` 质检工作流（镜头时长、闪烁频率 ≤3Hz、响度、字幕字号等全检）。
7. **能力注册**:
   - 注册了 `particle_text`、`particle_science_scene`、`parallax_layers` 三大核心能力到统一注册表（`hevi.capabilities`），支持 ShotSpec 与 `/api/capabilities` 调用及严格的 JSON Schema 校验（`additionalProperties: false`）。
8. **样片与基线对照**:
   - 生成了 2 支幼儿科普样片（「为什么天是蓝的」16:9 与「雨从哪里来」9:16），并通过相同 seed 的帧像素 SHA-256 哈希核验了渲染确定性。

## 测试命令与实测数字
- **测试命令**:
  ```bash
  JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=. /data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_partsci.py -v
  ```
- **实测结果**: 全部测试通过（4/4 passed），帧像素哈希在同 seed 下完全一致。
- **样片路径**: `audit/partsci/samples/` (`sky_blue_16_9`, `rain_9_16`)。

## 已知限制
- CosyVoice 依赖 GPU 环境，在纯 CPU-only 环境下采用离线 Piper 中文神经网络 TTS 作为确定性替代，并已记录在案。

DONE PARTSCI-R1
