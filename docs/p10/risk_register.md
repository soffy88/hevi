# P10 永久风险记录（实施期实证，非假设）

## R-P10-01 — local anchor ≠ film anchor

- **发现**: P10-S 实施。`resolve_anchor` 输出是相对 line 音频起点的时刻（4038ms），必须叠加 seg 偏移才是 film 时刻（10502ms → frame 315）。首次端到端以行内锚点直接冻结 plan，导致 silence 检查错窗。
- **规则**: 任何 anchor 在进入 CompliancePlan 前必须注明坐标系（`line-local` / `film-global`）；plan 只接受 film-global。resolver 保持纯函数，偏移叠加由供给侧（Timeline）完成。
- **状态**: 已在 spike 修复；P10a resolver 供给设计必须包含坐标系字段。

## R-P10-02 — zoompan -loop semantics

- **发现**: P10-S 实施。`-loop 1` 输入下 zoompan 对每输入帧再产出 d 帧，`on` 计数失控；必须用单 still 输入 + `d=FRAMES`。
- **规则**: 所有程序化运镜 fixture/render 参数必须经"帧数守恒"断言（输出帧数 == 预期帧数），否则运镜 profile 不可信。
- **状态**: 已在 spike 修复；检测器 fixture 构造规范的一部分。

## R-P10-03 — periodic-texture NCC false peak

- **发现**: P10-S 实施。testsrc2 周期图案在错误尺度（0.55）给出 0.94 假峰；换 PIL 非周期纹理后真值 0.667 → 测得 0.675。
- **规则**: **不得把视觉指标的高数值直接当成真实视觉事件证据。** 几何检测器的校准 fixture 必须含非周期内容；置信度必须与"内容可区分性"挂钩，单一 NCC 峰值不足以签发 PASS（必要时 INCONCLUSIVE）。
- **状态**: 已在 spike 修复；P10d 检测器校准的强制条目。
