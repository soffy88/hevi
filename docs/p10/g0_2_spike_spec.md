# G0.2 — Interface Repair Spike SPEC（正式稿）

- **版本**: G0.2 正式稿
- **目标**: 不是修复全部生产代码，而是验证 P10 三个关键基础假设是否可落地。
- **禁令**: 不碰 `hevi/creative/*`；不冻结 P10 schema；不实现 CueMap / Compiler / Compliance。
- **通过条件**: A/B/C 任意一个失败 → G0 不通过 → P10 schema 不冻结。

```text
G0.2-A  Script Stable Identity Spike
G0.2-B  TTS Alignment Artifact Spike
G0.2-C  Anchor Resolver Spike
```

---

# G0.2-A — Script Stable Identity Spike

## Objective

验证：

> Script revision 后，文本单元是否拥有稳定身份，可以被 TTS / Cue / Shot 引用。

当前问题：HEVI 目前大量依赖 `list index / array position`（`hevi/director/pipeline_schemas.py:37-65`、`screenplay.py:248-288`），而 P10 要求 semantic identity。

## Required Interface

不引入完整 screenplay 重构，只做最小 adapter。新增概念 `ScriptUnitIdentity`。

## Data Contract

```yaml
ScriptUnit:
  unit_id:    {type: string, immutable: true}  # 如 scene1.line1 或 uuid，跨 revision 稳定
  scene_id:   {type: string}
  order:      {type: integer}                  # 顺序可变，身份不变
  text:       {type: string}
  source_ref: {type: string}
  revision:   {type: integer}                  # 文本改写 bump revision，不换 ID
```

落点文件（实施时）：`hevi/director/pipeline_schemas.py`（新增类型 + `ScreenplayDialogueLine.unit_id` 可选字段）→ `hevi/director/screenplay.py`（生成/解析/继承规则）。

## Identity Rules

### Rule 1 — 文本修改继承 ID

```text
old: "The black hole bends light"
new: "The black hole bends spacetime"
```

结果：same unit_id，new revision。拆分产生新 ID 并记录 `supersedes`。

### Rule 2 — 插入不漂移

before: A B C；insert X 后: A X B C → A/B/C 的 ID 不变，X 为新 ID。禁止 `B -> id+1, C -> id+1`。

### Rule 3 — 删除不复用

删除 B 后，`B.id` 永不复用。

## Spike Test

新增 `tests/p10/spike/test_script_identity.py`（G0.2 实施时创建；本 SPEC 只定契约）：

- **T1 Create**: 输入 `scene.md` → 生成 `[{unit_id: scene1.line1, ...}]`，PASS = 稳定。
- **T2 Insert**: revision 2 插入新行，`assert line2.id == old_line2.id`。
- **T3 Reorder**: 移动 `line3 line1 line2`，ID 不变。
- **T4 Cross reference**: `ScriptUnit` 可被 TTS / Cue / ShotIntent 引用（引用存在性，非全链跑通）。

## Acceptance

- PASS: `unit_id survives revision`。
- FAIL: `index based identity remains`。

## Output

`docs/p10/spikes/script_identity_report.md`：

```yaml
status: PASS | FAIL
current_owner: director-pipeline (narrative layer)
migration_cost: {files, tests, magnitude}
breaking_changes: [...]
```

---

# G0.2-B — TTS Alignment Artifact Spike

## Objective

验证 TTS 是否可以产生 `audio + word timing + phrase timing`。当前 `hevi/audio/edge_tts_custom.py:130-207` 调用 word-boundary 但 discard，只返回 wav path。

## Required Artifact

不改 TTS provider，先包装。对齐落盘（整数 ms，禁浮点秒）。

```yaml
audio_alignment:
  audio_id:
  duration_ms:
  words:
    - {token:, start_ms:, end_ms:}   # 例: black 1200->1450, hole 1450->1800
  phrases:
    - {phrase_id:, start_ms:, end_ms:}
```

落点文件（实施时）：`hevi/audio/edge_tts_custom.py`（保留边界并落盘）+ artifact 类型定义 + `tests/audio/test_tts_alignment.py`（或 `tests/p10/spike/` 下）。

## Spike Flow

```text
ScriptUnit -> TTS -> Audio -> Alignment Extractor -> Alignment Artifact
```

## Tests

- **T1 Word Coverage**: 输入 100 words，word timing 覆盖率 >= 95%。
- **T2 Duration Match**: `last_word.end_ms ≈ audio.duration`，允许 ±500ms。
- **T3 Revision Mapping**: 新旧 script 的 alignment 不得交叉污染（旧 alignment 不能用于新 artifact）。

## Acceptance

- PASS: `word timing survives as artifact`（真实合成，非 mock；key 缺失则标 BLOCKED，不用假数据）。
- FAIL: `only wav returned`；或用估计值冒充（必须报 `ALIGNMENT_UNAVAILABLE`）。

## Output

`docs/p10/spikes/tts_alignment_report.md`（同 A 格式：status / owner=audio-tts / migration_cost / breaking_changes）。

---

# G0.2-C — Anchor Resolver Spike

这是 P10 最大创新点。目标：验证 `semantic anchor -> frame` 是否真实。

## 禁止

不能 `anchor.time = 5.2`——那仍是 absolute timeline。

## Interface

新增 `resolve_anchor()`，不是 `timeline()`。Resolver 为无状态接口，选址 `hevi/studio/` 或基础设施层，**不在 `hevi/creative/`**，只读 Timeline 状态（方案 A+B）。

Input:

```yaml
Anchor:
  type: AFTER_DIALOGUE
  target: {script_unit_id: scene1.line4}   # 依赖 Spike A
  offset_ms: 500                            # 语义: line4 结束后 500ms；可为负；整数
```

Output:

```yaml
ResolvedAnchor:
  anchor_id:
  source: scene1.line4
  resolved: {time_ms: 42100, frame: 1263}
  confidence: 0.97
  evidence: [audio_alignment_hash, timeline_hash]
```

## Resolver Pipeline

```text
ScriptUnit -> TTS Alignment -> Dialogue End Event -> Anchor Resolver -> Frame
```

## Tests (`tests/p10/spike/test_anchor_resolver.py`，实施时创建）

- **T1 Dialogue Anchor**: `after line1 + 500ms` 输出 frame，与手工换算一致；fps 换算，容差下限 `1000/fps` ms。
- **T2 Revision Invalidation**: line1 duration 变化 → 旧 resolved anchor 失效，不得复用。
- **T3 Evidence**: 输出必须含 `why this frame?`（audio_alignment_hash + timeline_hash），否则不可审计；target 缺失 → `ANCHOR_ORPHANED`，无对齐 → `ANCHOR_UNRESOLVED`。

## Acceptance

- PASS: `semantic anchor resolves deterministically`（至少一例走真实 Timeline/对齐状态）。
- FAIL: `fallback to seconds only`。

## Output

`docs/p10/spikes/anchor_resolver_report.md`（同格式）。

---

# G0.2 附带项（同属 G0.2，不阻塞 A–C 并行）

- **A2 `cue_id` LOW fix**: `hevi/cinematic/shot_intelligence/models.py:39-42` 尾部追加 `cue_id: str = ""`；旧 positional 构造回归绿。
- **ffmpeg 能力探测（A8 前置）**: pin 版本 + 已知 320ms 静音片段探测；失败 → `SILENCE_PROBE_FAILED`，相关检查 `NOT_EVALUABLE`。

---

# G0.2 Exit Criteria

三个 Spike 完成后生成：

```text
docs/p10/spikes/
  script_identity_report.md
  tts_alignment_report.md
  anchor_resolver_report.md
```

Decision:

- **Case 1** — 三个 PASS → 进入 P10-S Creative Direction Spike。
- **Case 2** — A PASS / B FAIL → `Creative Direction possible but cross-modal compliance blocked`。
- **Case 3** — C FAIL → `P10 can only operate in absolute-time degraded mode; G16 disabled`。

任一 FAIL → G0 不通过 → P10 schema 不冻结（重申）。

---

# P10 当前依赖图更新

```text
                 Script ID
                    |
                    v
              TTS Alignment
                    |
                    v
             Anchor Resolver
                    |
                    v
              CueMap Runtime
                    |
                    v
        Creative Compliance Runtime
                    |
                    v
             P10 Production
```

---

# 下一阶段（预告，非本 SPEC 范围）

如果 G0.2 通过，进入 **P10-S Creative Direction Runtime Spike SPEC**，范围严格限制：30 秒视频（1 Thesis + 1 Treatment + 1 Signature Shot + 1 Cross-modal Cue + 1 Provenance Explanation），不做全量 CreativeDirection / 全部 schema / Provider orchestration。先证明：

```text
Idea -> Direction -> Shot -> Audio -> Frame -> Evidence
```

这条链真实跑通。
