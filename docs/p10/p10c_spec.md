# P10c — Time-Directed Layer SPEC（设计稿 v0.1）

- **范围**: Decision（结构化 change_set）+ BeatPlan + CueMap + Cinematography + SoundDirection
  + SignatureShot + adapters（CreativeCue→BeatCue、ShotIntent 扩展已存在）+ Compiler 骨架
  （validate→program→intent，不做 Provider orchestration 细粒度）。
- **前置**: P10b PASS（内容对象可用），P10a PASS（修订链可用），G0.2 A/B/C（锚点语义已验证）。
- **禁令**: 不做 Compliance verdict 引擎全量（P10d）、检测器校准全量（P10d）、Dependency/Impact 图
  全量（P10d）、Memory（P10d）；不冻结 P10d schema。

## 1. 对象

### 1.1 DirectionDecision（结构化变更，非自由文本）

```yaml
DirectionDecision:
  id, revision, category, proposition      # proposition 给人读
  change_set: [{node_ref, field_path, op: set|add|remove, value_hash}]  # 给机器用
  rationale, evidence: [principle_ref|observation_ref], alternatives
  impact_class: high|normal
  status: PROPOSED|APPROVED|REJECTED|SUPERSEDED|STALE
```

规则：无 `change_set` 的 Decision 不得进入 APPROVED（字段级影响分析的前置）；
`STALE` 只由上游 Authority/父 Decision 变更触发，不自动改写。

### 1.2 BeatPlan（锚点 + 可测量曲线）

```yaml
BeatPlan:
  beats: [{id, start: Anchor, end: Anchor, narrative_function, emotional_function,
           intensity, pacing, visual_energy, audio_energy, transition_in/out}]
  curves: [{name, samples: [{beat_id, value_0_1}], proxy}]  # 无 proxy 的曲线归 Class H
```

规则：beat 覆盖整片无间隙（`BEAT_COVERAGE_GAP`）；Anchor 坐标系必须注明（R-P10-01）。

### 1.3 CueMap（跨模态 + 冲突规则）

```yaml
Cue: {id, at: TimeBinding, until?, trigger, priority, beat_ref, decision_refs, rationale,
  actions: [{id, modality, intent, required: must|should|may,
             compose: override|additive, verification: {class, detector, tolerance_class}}]}
```

规则：同一 modality 时间重叠未声明 `compose` → `CUE_CONFLICT`；
每个 action 的验证规格在编译期展开进 CompliancePlan 条目（P10d 消费）。

### 1.4 CinematographyDirection（词表对齐检测器）

CameraSpec：shot_size/framing/angle/lens/depth/composition/lighting/blocking +
`movement: {type, geometry_class: extrinsic|intrinsic|mixed|subject_relative,
motivation, intensity, expected_magnitude}`。
规则：`zoom` 与 `push_in` 分开写；`intensity` 无 `expected_magnitude` 映射 → 该项降 Class H；
SignatureShot 唯一性（同 project camera 签名哈希不重复），数量上限为可配置工程默认。

### 1.5 SoundDirection（静音一等）

voice_intent（无 voice_id）/ music_intent（无曲目）/ `silence: [{id, at, duration_ms,
scope: [stems], allow: [ambience], kind, floor: {relative_to, drop_db}, reason}]` /
foley / ambience / transitions。规则：silence 缺 scope → 拒绝；stem 缺失时声明
`NOT_EVALUABLE`（P10-S 已验证混音级路径）。

### 1.6 Adapters（只做已有系统的桥）

- `CreativeCue → BeatCue`：一对多，BeatCue 带 `cue_id` + `creative_cue_ref`（A2 已就绪）；
  无 `creative_cue_ref` 的 BeatCue = legacy，合法但 Compliance 标 `UNDIRECTED`。
- `ShotIntent` 扩展字段已存在（H1）；adapter 只填充，不重实现 ShotPlanner。

### 1.7 Compiler 骨架（P10c 只到 Program + Intent）

```
pinned manifest → 批准校验 → 外部引用 pin → 确定性校验 → CreativeProgram
→ capability negotiation（粗粒度，A12）→ degrade policy（预批准才可降级）→ ShotIntent 集
```

规则：无匹配 degrade policy → `CAPABILITY_UNSATISFIED`（fail-loud，给修订建议）；
降级必须写 `DegradeEvent`；`compile_hash = H(manifest, pins, compiler_version)` 可重现。

## 2. 与 P10a/b 的挂接

- Decision/Cue/Beat 变更 = P10a `CREATE_REVISION`；`change_set` 定位到真实字段（P10d Impact 的前置）。
- Cue/Beat 引用 P10b 对象哈希（thesis/benchmark principles/selected treatment）。

## 3. 最小 acceptance（P10c 实施）

```text
C1 Decision change_set 可定位字段；无 change_set 不得 APPROVED
C2 Beat 覆盖无间隙；Anchor 坐标系注明；无 proxy 曲线标 H
C3 同 modality 重叠无 compose → CUE_CONFLICT；action 展开为 plan 条目
C4 zoom/push_in 分写；intensity 无 magnitude → 降 H；Signature 唯一
C5 silence 缺 scope 拒绝；stem 缺失声明 NOT_EVALUABLE
C6 adapter：CreativeCue→BeatCue 回指；legacy 标 UNDIRECTED；ShotPlanner 无分叉（H1 延伸）
C7 compiler：缺 approval/pin/校验任一 → fail-loud；同输入同 compile_hash；无 policy 降级 → CAPABILITY_UNSATISFIED
C8 端到端：P10-S 驱动复用本层对象重跑（对象替换 spike-local JSON，verdict 仍 PASS）
```

## 4. 非目标（P10d）

Compliance verdict 引擎、检测器注册+fixture 校准全量、字段级依赖图/early cutoff/rerun_plan、
Creative Memory、相似度护栏。
