# P10-S Creative Direction Runtime Spike — SPEC（设计稿）

- **版本**: P10-S SPEC v0.1（只定设计与验收，不实现、不冻结 schema）
- **前置**: G0.2 PASS（A/B/C + A2 + probe；报告见 `docs/p10/spikes/`），G0 仍 NOT PASSED（待实施项见 G0.3）
- **禁令**: 不做全量 CreativeDirection、不冻结全部 schema、不做 Provider orchestration、不碰 `hevi/creative/*`（spike 对象以 spike-local JSON + 现有模型扩展字段承载）

## 0. 目标（一句话）

证明这条链真实跑通（30 秒真实视频，含一次"尺度揭示"）：

```text
Idea -> Direction -> Shot -> Audio -> Frame -> Evidence
```

## 1. 待验证假设

| ID | 假设 | 通过标准 | 失败含义 |
|----|------|----------|----------|
| H1 | ShotIntent 可扩展且不产生第二套 Authority | spike 的 `creative_direction_ref/decision_refs/cue_refs`（A1 模式）经现有 ShotPlanner 跑通，ShotPlan 无分叉 authority | P10 编译器无落点 |
| H2 | 锚点能穿过 TTS 对齐与 Timeline 解析 | Cue 的 anchor 经 `AudioAlignment` + `resolve_anchor` 得出真实 frame，render 后 Observed 落在容差内 | P10 时间模型不可用（退回 absolute 降级） |
| H3 | 运镜与静音在真实 MP4 上可验证 | 校准检测器对 spike MP4 的 pull_back + 320ms stem/混音静音给出 Expected-vs-Observed verdict（D 类为主） | Compliance 闭环不成立 |

## 2. 内容选题（§24 Q8 建议）

20–30 秒"黑洞尺度揭示"片段：一句导入（line1）+ 尺度揭示句（line2，anchor 目标）+ 收束（line3）。含 hard_requirement 示例：总时长 ≤ 30s（可检查）。

## 3. Spike 对象（最小集，spike-local 格式）

只建 6 件，每件一人可审：

```text
1 Thesis: {logline, central_question, emotional_arc, audience_effect}
1 Treatment: {structure(3 段), selected, rationale}（单候选 + 为何不做 K=3 的理由记录）
1 Benchmark: {1 reference + principle(BP) + transfer_mode=principle_only}
1 SignatureShot: 完整 CameraSpec（含 geometry_class, motivation, expected_magnitude）
1 Cross-modal Cue: {camera pull_back + music reduce + silence 320ms} 同一 anchor
1 Explain 输出: --at <t> 从 Observed 反查到 Thesis 的链
```

Thesis 事实性断言 pin Canon（若无对应 fact 则写"无事实断言"，由审批确认）。

## 4. 流水线（全走现有系统）

```text
Spike Thesis/Treatment/Cue(anchor=AFTER_DIALOGUE line2 +500ms)
  -> ShotIntent(+creative_direction_ref/decision_refs/cue_refs, A1 扩展字段)
  -> 现有 ShotPlanner -> ShotPlan (H1)
  -> TTS(synthesize_with_alignment, audio_id=tts:{unit_id}#r1) (G0.2-B)
  -> Timeline resolve_anchor -> frame (G0.2-C, H2)
  -> render (现有 renderer, 30s)
  -> shot-level 早验证 (运镜几何检查, H3 前半)
  -> ObservationSet 最小版 (镜头边界 + 转录 + 响度 + 静音图, 基于 VI 现有输出 A7)
  -> Compliance 最小版 (CompliancePlan 冻结一次: pull_back D/M + silence D + 时长 D)
  -> DirectionVerdict (规则引擎, LLM 不在 PASS 路径)
  -> explain --at (H3 后半 + §9.3 雏形)
```

审批：手动（`approval_policy.mode=manual`），1 个 gate（structure + cue 确认），Review Pack 为 6 件 + rerun 成本（全量重跑，A9 缓存缺失已接受）。

## 5. 检测器与校准（Spike 子集）

- 运镜：几何检测（程序化缩放/平移合成 fixture 区分 zoom vs 平移；dolly 视差 fixture 列为后续，本 spike 只断言 zoom-class 检测 + INCONCLUSIVE 回退存在）。
- 静音：`silence_probe` 已 PASS 的门限（320ms @ -60dB，stem 缺失时声明混音级 + `NOT_EVALUABLE` 边界，二选一在 spike 实施前拍板）。
- 未校准检测器一律 `ADVISORY_ONLY`（只能 INCONCLUSIVE）。

## 6. 测试与验收（含反向）

| # | 正向 | 反向（必须失败/被拒） |
|---|------|----------------------|
| S1 | 端到端产出 30s MP4 + verdict | 删任一 provenance 边 → `PROVENANCE_BROKEN` |
| S2 | 改运镜只重跑该镜头链（全量重跑亦接受，但须记录 scope=film 降级） | 改 motivation 文本触发 ShotPlan 重跑 → early-cutoff 缺失告警（A9 已知） |
| S3 | `explain --at` 在揭示点给出完整链 | 换 MP4 文件 → 旧 verdict 作废（hash 绑定） |
| S4 | 未审批 compile 被拒 | 绕过审批 compile → `APPROVAL_MISSING` |
| S5 | 容差内 PASS 由规则引擎得出 | 低置信度仍 PASS → 失败（须 INCONCLUSIVE） |

## 7. 产出物（spike 结束时）

```text
docs/p10/p10_s_report.md        # H1/H2/H3 裁决 + 全链耗时/成本
spike_thesis.json spike_treatment.json spike_benchmark.json
spike_cue.json spike_program.json spike_compliance_plan.json(frozen hash)
spike_verdict.json evidence/ spike.mp4(sha256) explain 输出
```

## 8. 退出条件

- H1+H2+H3 全 PASS → P10a（状态骨架）允许启动设计；G0 转 CONDITIONAL PASS（剩余 A3/A4/A5/A8/A9/A13 进入实施）。
- H2 FAIL → P10 降级为 absolute-time 模式，G16 禁用，P10c 重定范围。
- H3 FAIL → Compliance 设计返工，不得进入 P10d。

## 9. 非目标（重申）

全量 CreativeDirection 15 对象、全部 schema 冻结、Provider orchestration/capability negotiation 细粒度、Creative Memory、相似度护栏、多语言 Script ID、per-shot 缓存——一律不在 P10-S。
