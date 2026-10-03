# P10d — Close the Loop SPEC（设计稿 v0.1）

- **范围**: Compliance verdict 引擎 + 检测器注册/校准 + ObservationSet + 字段级依赖/影响图
  （early cutoff + rerun_plan + 入向失效）+ Creative Memory。相似度护栏为可选项（默认关）。
- **前置**: P10c PASS（plan 条目可展开），P10-S PASS（端到端证据链已验证），G0.2 探测 klaar。
- **禁令**: 不重造 Video Intelligence / verdict authority（adapter 挂接）；检测器只注册**已校准**
  项为 PASS/FAIL 签发者，未校准一律 ADVISORY_ONLY；Memory 不得降低 gate 等级、不得自动批准。

## 1. 对象与引擎

### 1.1 ObservationSet（一次观测，多次查询）

```yaml
ObservationSet:
  artifact_hash, produced_by, produced_at
  shot_boundaries: [{shot_id, start_ms, end_ms}]
  transcripts: [{text, start_ms, end_ms, source: asr|declared}]
  loudness_curve, silence_map, subtitle_spans, motion_summaries
```

规则：Compliance 评估器只查 ObservationSet，不临时调 VLM 重看；按 artifact_hash 缓存；
VLM 来源观测一律 Class M 且置信度封顶（无几何/确定性佐证不得超封顶）。

### 1.2 DirectionEvidence + DirectionVerdict（规则引擎，无 LLM）

```yaml
DirectionEvidence: {decision_id, check_id, expected, observed(+单位),
  observed_by: {detector_id, version, calibration_ref}, confidence,
  artifact_hash, locator: {time_range_ms, frame_range, audio_ref, transcript_ref}}
DirectionVerdict: {artifact_hash, compliance_plan_hash,
  status: PASS|PASS_WITH_WARNINGS|REVISE|FAIL|INCONCLUSIVE, checks[], violations, suggested_revision}
```

聚合规则（确定性）：
1. 任一 `must` FAIL → FAIL（产物无效）或 REVISE（改 Direction 可修）；
2. 任一 `must` INCONCLUSIVE/NOT_EVALUABLE → 整体 INCONCLUSIVE，不得 PASS；
3. `must` 级 H 无 attestation → INCONCLUSIVE；
4. 仅 should/may 未过 → PASS_WITH_WARNINGS；
5. 无可用检测器不得静默跳过 → NOT_EVALUABLE + receipt。

### 1.3 检测器注册与校准（QA 的 QA）

```yaml
Detector: {id, version, class, supported_checks, runtime_requirements,
  calibration: {fixture_set, metrics: {precision, recall}, threshold_theta, calibrated_at},
  status: ENABLED_FOR_PASS|ADVISORY_ONLY}
```

Fixture 构造即真值（程序化运镜/已知静音/已知声画偏移/无变化对照；zoom-vs-dolly 需带视差分层场景，
R-P10-03：fixture 内容必须非周期）。未校准签发 PASS/FAIL → 实现拒绝（测试锁死）。

### 1.4 依赖/影响图（字段级 + early cutoff + rerun_plan + 入向失效）

- 节点 = P10 对象 + 生产产物；边带字段掩码（未声明掩码 → 保守整节点 + `IMPACT_CONSERVATIVE_EDGE` 告警，lint 清零）。
- `compute_revision_impact(base, new, graph)`：field_diff → 种子 → 传递闭包（上界）→ earliest stage
  → preserved（输入哈希未变证明）→ rerun_plan（stage × scope × cost_class）。
- Early cutoff：重算后输出哈希未变 → 传播停止；报告记录 `upper_bound` 与 `actually_rebuilt`（后者 ⊆ 前者）。
- 入向失效：Canon/Style/Asset/Provider 变更 → 引用方 STALE 并阻塞 compile；未受影响保持 APPROVED。

### 1.5 Creative Memory（证据晋升 + 作用域 + 退役）

```yaml
MemoryEntry: {id, kind: approved|rejected|preference|outcome,
  statement: {category, pattern, context_tags}, evidence: [...] (≥1, 禁无证据条目),
  support_count, scope: project|user (global 默认关), status: candidate|active|retired}
```

规则：candidate→active 需 ≥2 独立证据（用户显式声明可在 user 域直达）；被新批准决策推翻 → retired；
长期未确认 → 降级 candidate；只作 suggestion（带 memory_ref），不降 gate、不自动批准；连续被拒衰减。
优先级：APPROVED revision > Canon/Style 约束 > Memory suggestion > LLM default。

## 2. 与 P10a/b/c 的挂接

- verdict 引用 `compliance_plan_hash`（编译期冻结，P10-S 已验证）+ `artifact_hash`（换文件作废）。
- Decision.stale / approval-void 复用 P10a 修订链 + P10b pin 校验。
- H 类 attestation surface（Q4）在实施前拍板：谁、在哪、是否双人。

## 3. 最小 acceptance（P10d 实施）

```text
D1 verdict 聚合：must FAIL→REVISE/FAIL；must INCONCLUSIVE→整体 INCONCLUSIVE；无 attestation 的 H→INCONCLUSIVE
D2 未校准检测器只能 INCONCLUSIVE（签发 PASS/FAIL 被拒）；fixture 含视差 zoom/dolly、最短静音、已知偏移、对照
D3 ObservationSet 缓存：同 hash 复用；artifact 换 hash → verdict/evidence 作废
D4 影响分析：改运镜只失效该镜头链（哈希证明保留集）；仅改 motivation 文本 → early cutoff 不重跑下游
D5 入向失效：改 Style 词汇/Asset → 引用 Decision STALE 并阻塞 compile；未受影响保持 APPROVED
D6 Memory：无证据条目被拒；晋升需阈值；suggestion 不绕 gate；退役保留
D7 端到端：P10-S 驱动接入本层 verdict 引擎重跑仍 PASS（含聚合规则与 NOT_EVALUABLE 路径）
```

## 4. 非目标（P10 之后）

相似度护栏默认关（可选实现）；多语言 Script ID；per-shot 缓存生产化（A9）；Q4 双人之外的组织流程。
