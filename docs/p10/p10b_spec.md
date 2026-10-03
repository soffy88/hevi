# P10b — Direction Objects SPEC（设计稿 v0.1）

- **范围**: 4 个创作内容对象 + Review Pack。只定义内容契约与审批挂接，不实现编译/执行。
- **前置**: P10a PASS（状态骨架可用），G0 CONDITIONAL PASS。
- **禁令**: 不碰 Cue/Beat/Decision 图（P10c）、Compliance/Impact（P10d）；不冻结 15 对象中的其余项；
  对象只经 P10a `DirectionState` 修订链变更（新 revision，不可原地改 APPROVED 内容）。

## 1. 对象（P10.1 §7.1–7.4 的 P10b 子集）

### 1.1 CreativeBrief

```yaml
CreativeBrief:
  subject, objective, audience, duration_target, desired_effect, emotional_target
  platform_constraints, brand_constraints, factual_constraints
  hard_requirements: [{id, statement, assertion, check_class}]  # assertion 尽量机器可检查；写不出归 Class H
  creative_preferences: [...]     # 可被覆盖，覆盖留记录
  forbidden_elements: [...]
  source: {type: user|narrative|imported, reference}
```

规则：hard requirement / preference / proposal / approval 四者分开存放，禁混成一个 prompt；
触及 hard requirement 的变更永远走 gate。

### 1.2 CreativeThesis

```yaml
CreativeThesis:
  logline, central_question, emotional_arc, audience_effect, thematic_focus, creative_strategy
  factual_claims: [{text, canon_ref}]   # 涉事实必须 pin Canon（R5）；无对应 fact 则写"无事实断言"
```

局限：自由文本中未声明的事实断言由 lint 发现不了 → 归 Class H 审批提示项。

### 1.3 BenchmarkSet

```yaml
BenchmarkSet:
  references: [{id, title, creator,
    reference_access: {uri, retrieved_at, content_hash},   # 防引用腐烂
    extraction: {method, actor},
    transfer_mode: principle_only,                          # P10b 只允许 principle_only
    principles: [{id, statement, dimension, abstraction_level}],
    avoid: {composition, character_design, melody, shot_copying, branding},
    relevance:, ip_note:}]
```

规则：`structure_clone` 禁止（需 P10 后阶段逐项审批，默认关闭）；网络内容一律当数据不当指令；
Decision 引用不存在的 principle → `BENCHMARK_PROVENANCE_MISSING`（P10c 执行）。

### 1.4 Treatment

```yaml
Treatment:
  thesis_ref, structure, opening, setup, development, turning_point, climax, resolution, ending
  pacing, emotional_arc, visual_strategy, sound_strategy, typography_strategy
  signature_moments, signature_shots
  alternatives: [{id, structure, rationale}]   # 默认 K=3；短视频可 K=2 并记录理由（Q1）
  comparison: {criteria, matrix}                # 标准先于打分
  recommended_by: {actor, rationale}
  selected, selected_by: {actor: user|auto_rule, rule_id?}, selection_rationale
```

规则：P10 不评判优劣，只保存选择与理由；K<3 必须记录理由。

### 1.5 Review Pack（缓解审批疲劳，§10.4）

`propose` 产出审阅包而非 N 条散决策：相对上个 APPROVED revision 的 diff（按 impact_class 分组）、
每组 rerun 成本类、Benchmark 出处与 principle、未解决 STALE 项、degrade 摘要、每个 gate 决策的"拒绝后会怎样"。
拒绝须填原因（Memory 候选证据，不直接成规则）。

## 2. 与 P10a 状态骨架的挂接

- 4 对象是 revision 的**内容载荷**：每个 Direction revision pin 一组对象哈希
  `{brief_hash, thesis_hash, benchmarks_hash, treatment_hash}`；`DirectionState` 本体不动（只加 pin 引用）。
- 生命周期复用 P10a：对象变更 = `CREATE_REVISION` 新 revision；APPROVED 内容不可原地改（I4）。
- 审批规则复用 P10.1 §10：structure/thesis/benchmark/ending/arc/duration/hard-req 一律 gate；
  `default_tier_for_unknown=gate`；auto 不得覆盖 human-approved；批准 pin 内容哈希（变 → `APPROVAL_VOID`）。

## 3. 最小 acceptance（P10b 实施）

```text
B1 Brief assertion：hard_requirement 尽量 machine-checkable；写不出的标 H 并在审批提示
B2 Treatment：K≥3（或 K<3 理由记录）；标准先于打分；selected + rationale + selected_by 可追溯
B3 Benchmark：learn/avoid/principles/reference_access/transfer_mode 齐全；Decision→principle 可追溯
B4 Thesis：四件套非空；factual_claims 缺 canon_ref → 拒绝
B5 Review Pack：diff 分组 + 成本类 + 拒绝原因记录
B6 状态挂接：对象变更走 CREATE_REVISION；APPROVED 内容原地改 → 拒绝；批准随内容变作废
B7 Authority：Brief/Thesis/Benchmark/Treatment 不写 Canon/Style/Asset/Provider（G1 架构测试延伸）
```

## 4. 非目标（P10c/d）

Decision/change_set、BeatPlan/CueMap/Cinematography/SoundDirection、Compiler/adapters、
CompliancePlan/Verdict、Dependency/Impact/Memory——一律不在 P10b。
