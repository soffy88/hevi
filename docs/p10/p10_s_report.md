# P10-S Spike Report — 端到端竖切 PASS

```yaml
status: PASS (H1 + H2 + H3)
date: 2026-10-03
spec: docs/p10/p10_s_spike_spec.md
run: artifacts/p10_s/20261003T002838Z/ (spike.mp4 sha256 f608c9ce7285…, 17904ms)
driver: scripts/p10_s_run.py (deterministic: plan dd82f57d…, mp4 hash 跨跑一致)
```

## 裁决

| ID | 假设 | 结果 | 证据 |
|----|------|------|------|
| H1 | ShotIntent 可扩展且无第二 Authority | PASS | 3 ShotIntents(+`creative_direction_ref/decision_refs/cue_refs`) → 现有 `ShotSelector` 跑通，recipes `medium_dialogue×2 + cta` |
| H2 | 锚点穿过 TTS 对齐与 Timeline 解析 | PASS | dialogue ends `{4800, 3538, 4425}ms` → 行内锚点 4038ms → film 锚点 **10502ms frame 315**；Observed 静音段起点 10060ms vs 对白结束 10002ms（Δ58ms ≤ 250ms） |
| H3 | 运镜与静音在真实 MP4 可验证 | PASS | scale **0.675** ∈ [0.65, 0.75]（真值 0.667，conf 0.99）；静音窗 [10502, 10822]ms 被观测段 (10.06, 1.92s) 覆盖；verdict 由规则引擎得出，LLM 不在路径 |

CompliancePlan 在音频装配后、渲染前冻结（`dd82f57d…`）；verdict 绑定 artifact hash；music 声明 `NOT_EVALUABLE`（may 级 → 不影响 PASS）。

## 实施中发现并修复的真问题（3 个）

1. **行内锚点 vs film 锚点**：`resolve_anchor` 输出是相对 line 音频起点的时刻，必须叠加 seg 偏移才是 film 时刻。修后 plan 冻结点移到音频装配后（仍在渲染前，"期望先于观测"成立）。这是 P10a resolver 供给设计的输入。
2. **zoompan `-loop 1` 陷阱**：loop 输入下每帧再产出 d 帧，`on` 计数失控。改单 still 输入 + `d=FRAMES`。
3. **周期纹理 NCC 混叠**：testsrc2 在错误尺度给出 0.94 假峰。换 PIL 非周期纹理后真值 0.667 → 测得 0.675。教训：几何检测器的 fixture 必须用非周期内容（已记入检测器校准要求）。

## 生产化缺口（诚实清单）

- 片长 17.9s（非 30s；TTS 实际时长决定，无人工拉长——hard_requirement ≤30s 成立）。
- 配乐/混音 stem 缺失：music 与 stem 级静音记 `NOT_EVALUABLE`（A8 未解决）。
- `confidence=1.0`（resolver）与相似度匹配（spike 级）沿用 G0.2 局限。
- Per-shot 缓存缺失：全量重跑（A9 已知降级）。
- `explain` 为文本模板，非 API。

## Gate 影响

P10-S = PASS → **P10a（状态骨架）允许启动设计**；G0 转 CONDITIONAL PASS（A3/A4/A5/A8/A9/A13 进入实施，见 G0.3）。
