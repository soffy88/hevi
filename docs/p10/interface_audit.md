# P10 Gate 0 Interface Audit

- **版本**: G0.1 正式稿（冻结真实 HEVI 接口事实，不设计 P10，不冻结 P10 schema）
- **日期**: 2026-10-02
- **禁令**: 不创建 `hevi/creative/*`，不冻结 CreativeDirection / CueMap / CompliancePlan schema，不实现 Direction Compiler。违反即架构缺陷。

## Status

```text
G0 STATUS: NOT PASSED

Reason:
P10 Creative Direction Runtime depends on interfaces
that are currently missing or ambiguous.

No P10 creative schema may be frozen.
No hevi/creative implementation may start.
```

---

# 0. Audit Scope

审计对象：

```text
HEVI existing runtime
```

审计目的：

验证 P10 假设：

```text
Creative Direction
        ↓
Creative Program
        ↓
ShotIntent
        ↓
ShotPlan
        ↓
Timeline
        ↓
Artifact Evidence
```

是否具备真实落点。

方法：每条结论附代码位置（file:line）；凡属工程判断处明说。A1–A8 含子代理核实 + 本轮直接复核；A9–A14 本轮 grep/read 核实。

---

# 1. Existing Authority Map

## 1.1 Narrative Authority

### Existing

```text
hevi/layer4_legacy/obase_support/creative.py:271 class NarrativeCanon
```

职责：

```text
story / narrative related representation
```

Canonical narrative authority；projections cannot be committed here。经 `hevi.obase.creative` 被 `hevi/creative/layer4/narrative.py:12-24` 消费。

当前状态：

```text
EXISTS
```

缺口：Canon 本体无统一 version/hash 查询接口（与 Style registry 不对称）；Revision 侧有 `canon_hash_before/after`（`hevi/creative/layer4/revision.py:112-113,488-509`），但非 Canon 自身 pin 能力。

### P10 Rule

禁止：

```text
hevi/creative/narrative.py
```

新增：

```text
CreativeNarrative
StoryCanon
NarrativeTruth
```

原因：

会形成：

```text
Narrative Authority
        +
Creative Narrative Authority
```

双源。

### P10 Usage

允许：

```text
CreativeDirection
        |
        v
reference Narrative Authority
```

禁止：

```text
CreativeDirection
        |
        v
modify narrative truth
```

---

## 1.2 Visual Style Authority

### Existing

```text
hevi/production/p6/visual_style/model.py:132 class VisualStyleGrammar
```

已有：

```python
VisualStyleGrammar
```

职责：

```text
mood
palette
composition
texture
motion
lighting
```

并明确：

```text
no renderer
no provider
no asset
no timeline
no shot
```

Pin 范本（全仓唯一完整）：`registry.py:193-277` 支持 `id@version`（`_split_ref/get/resolve/validate/list_versions`），`compiler.py:203 resolve_style`，`model.py:175 id@vVersion`。

### Decision

Status:

```text
AFFECTED: NO
```

P10 integration:

```text
CreativeDirection
        |
        v
VisualStyleGrammar reference
```

不是：

```text
CreativeDirection owns VisualStyleGrammar
```

---

## 1.3 Asset Authority

### Existing

```text
hevi/production/p7/asset_intelligence.py:74 class AssetDecisionAuthority

hevi/production/p7/asset_decision.py:92 class AssetDecision
```

已有：

```text
asset decision layer
```

并有：

```text
no second selector
```

约束（`asset_decision.py:18-20` 明文禁止第二选择器）。

### Decision

P10 可以保存：

```yaml
asset_intent:
  emotional_role:
  visual_role:
  required_property:
```

例如：

```text
"需要体现孤独感的远景素材"
```

但是不能：

```python
choose_asset()
rank_assets()
```

Status:

```text
HOLDS
```

缺口：Asset 无统一 version/hash pin（见 A13）。

---

## 1.4 Provider Authority

### Existing

```text
hevi/providers/registry.py:8,21
```

以及：

```text
obase.provider_registry
```

职责：

```text
provider registration
capability
routing
execution
```

能力查询：`hevi/video/capability_guard.py:174`、`hevi/ops/p5_1_providers.py:40,256,300,396`；renderer 矩阵 `hevi/renderers/__init__.py:58 renderer_capability_matrix()`。

P10:

允许：

```yaml
required_capability:
  cinematic_camera_motion
  voice_emotion
```

禁止：

```python
CreativeProviderSelector()
```

Status:

```text
HOLDS
```

缺口：粒度到 renderer/provider 名，无 camera-movement 级结构化能力（见 A12）。

---

## 1.5 Timeline Authority

### Existing

发现：

至少四处时间模型：

### A

```text
hevi/studio/timeline.py:41 TimelineClip, 61 Timeline
```

特点：

```text
float seconds (start_s/duration_s), export_timeline -> nle_recut
```

落盘 `data/timelines/*.json`，`to_dict/from_dict`。

### B

```text
hevi/tongjian/schemas.py:165 Timeline (audio_segments/gaps)
```

### C

```text
p0_pipeline.py:68 TimelineLock (Immutable timeline bound to AudioLock)
```

### D

```text
narrative/models.py:114 TimelineEvent (+ legacy creative.py:198 TimelineState)
```

### Problem

P10 原设计：

```text
Anchor
   |
   v
ResolvedCue
   |
   v
Timeline
```

但是当前不存在：

```python
resolve_anchor()
```

无 frame↔timecode 运算，仅 caption 级 `keyword_anchors`（`hevi/digital_human/layer4/atoms.py:139`）。

### Risk

如果 P10 创建：

```text
creative/timeline.py
```

立即形成：

```text
Timeline Authority #5
```

### Decision

必须新增：

```text
Anchor Resolver Interface
```

而不是：

```text
New Timeline Model
```

目标：

```python
resolve_anchor(
    anchor,
    runtime_state
)
```

输出：

```yaml
ResolvedTime:
 frame:
 timestamp:
 confidence:
 evidence:
```

Status:

```text
FAIL
BLOCKER
```

---

## 1.6 Approval Authority

存在：`hevi/ops/p5_approval.py:38 ApprovalStore,176 ApprovalRuntime` + `hevi/ops/p5_types.py:143 ApprovalRequest,166 ApprovalPolicySet` + `hevi/ops/p5_1_session.py:252 RevisionSessionRunner`（single promotion authority）。

非 Authority：`hevi/director/gate_log.py:1-121` 只是 lint log（"Write errors never block"）；`hevi/production/creative_ledger.py:160 CreativeLedger` 是 variety/去重记忆，不是 approval ledger。

P10 复用 ApprovalStore 语义（scope pin 到 content_hash、auto 审计、human-approved 不可覆盖），禁止第二套 approval ledger。

## 1.7 Revision Authority

存在：`hevi/creative/layer4/revision.py:265 RevisionEngine`（proposal-first，never mutates canon）+ `hevi/narrative/revision.py:15 RevisionStore + StaleRevisionError` + legacy `creative.py:518,870,885`。

P10 复用"proposal → commit，新 revision 不可变"语义，不得增加第四套 revision 存储。底座选型（layer4 RevisionEngine + narrative stale 语义）待 G0.3 确认。

## 1.8 Artifact Authority

存在：`hevi/artifact_store/object_store.py:19-98`（`StoredObject(uri,sha256,byte_size)`，`LocalObjectStore` 按 `sha256[:2]/sha256` 内容寻址）+ Minio 后端 + 各层 `idempotency_key` 唯一索引。

P10 对象库若建设必须落在 artifact_store 之上；原子写沿用 `mkstemp(prefix="."+name)` 模式（narrative/persistence:23、mpt_adapter:63、fulfill:49）。

## 1.9 Verdict Authority

存在：机器证据 `hevi/video_intelligence/models.py:1`（语义 adapter 只可提议 label、不可改 timestamps）+ `analysis.py/probe.py/boundaries.py/transcript.py`；单镜 `hevi/director/verdict_checks.py:41 ShotVerdict`；终审 `hevi/verdict/final_review.py:41` + `delivery_gate.py` + `aesthetic_canon.py:31`；执行 receipt `hevi/execution/models.py:134 ProductionReceipt`（bytes + digest + ValidationResult）。

P10 Creative Compliance 是新维度（意图 vs 观测），以 adapter 挂接，不替代 Technical/Final verdict。

---

# 2. Interface Assumption Audit

---

## A1 — ShotIntent Extensibility

### Assumption

P10 增加：

```yaml
creative_direction_ref
decision_refs
cue_refs
```

不会破坏现有调用。

### Evidence

```text
hevi/cinematic/shot_intelligence/models.py:67-80 frozen dataclass
```

现状：新字段均有默认值；消费者 `selector.py:24`、`integration.py:21,32`、`sequence.py:22`、`hevi/narrative/adapters/shot_intelligence.py:9-20`（keyword 构造）；`scripts/shot_intelligence_smoke.py`、`tests/test_shot_intelligence.py:22-24`（positional 构造）。

并且：尾部追加带默认值字段兼容 keyword 调用者；仅中间插入破坏 positional 调用者。

### Result

```text
PASS
```

### Action

允许扩展 `ShotIntent`，但必须尾部追加 + 带默认值（backward compatible）。

---

## A2 — BeatCue Stable Identity

### Assumption

每个 Beat/Cue 可被引用。

### Current

BeatCue (`hevi/cinematic/shot_intelligence/models.py:39-42`):

```python
time_s
kind
strength
```

缺少：

```python
cue_id
beat_id
```

### Impact

无法：

```text
Decision
 ↓
Cue
 ↓
Shot
 ↓
Artifact
```

CueMap provenance（P10.1 §9.2）无挂接点。

### Decision

增加（非替换，兼容旧 caller）：

```python
cue_id: str = ""
```

保持 `time_s/kind/strength` 不变；`creative_cue_ref` 由 adapter 回指。

### Result

```text
FAIL
LOW FIX
```

---

## A3 — Script Stable Unit IDs

### Assumption

Script line/sentence 有稳定身份。

### Current

发现：

```text
hevi/director/pipeline_schemas.py:37-65
hevi/director/screenplay.py:248-288
```

主要依赖：

```text
list index
```

问题：revision 中：

```text
insert sentence
```

导致：

```text
index shift
```

有 ID 的是下游（`ShotListItem.shot_id:451`、`SceneBeat.beat_id:523-530`），Screenplay 层无 `line_id/utterance_id`。

### Required

新增：

```yaml
ScriptUnit:

id:
scene_id:
text:
source_ref:
```

要求稳定跨 revision（文本改写时 ID 继承规则需定义）。

### Result

```text
FAIL
BLOCKER (MEDIUM effort)
```

### Owner

Narrative layer（Director pipeline owner）。

---

## A4 — TTS Word Alignment

### Assumption

TTS 可以提供：

```text
word
phrase
timestamp
```

### Current

```text
hevi/audio/edge_tts_custom.py:130-207
```

已经调用：

```text
oprim.edge_tts_word_boundary
```

但是结果丢弃，只返回 WAV path。`speech_platform.py:136` 仅广告能力；词级时间只在 ASR/verify 侧（`asr_verify.py:77-86`、`funasr_verify.py:56-88`）。

Current artifact:

```text
wav path only
```

### Required

Audio artifact:

```yaml
alignment:

words:
  text
  start_ms
  end_ms

phrases:
  id
  start_ms
  end_ms
```

整数毫秒（禁浮点秒）。

### Result

```text
FAIL
BLOCKER (MEDIUM effort)
```

---

## A5 — Anchor Resolver

### Assumption

语义事件可以解析为 frame/time。

### Current

Timeline（`hevi/studio/timeline.py:327-329`）:

```text
float seconds
```

Missing:

```python
resolve_anchor()
```

### Required

Example input:

```yaml
anchor:
 type:
   after_dialogue

target:
 script_unit_id

offset:
 500ms
```

Output:

```yaml
frame:
12340

time:
411233ms

confidence:
0.96
```

要求：resolver（无状态接口），不是新 Timeline model（见 §1.5 方案 A+B）。

### Result

```text
FAIL
BLOCKER (M-L effort, HIGH importance)
```

---

## A6 — Provider Capability

### Assumption

P10 可查询 provider 能力。

### Current

Exists:

```text
hevi/video/capability_guard.py:174
obase.provider_registry + hevi/ops/p5_1_providers.py
hevi/renderers/__init__.py:58 renderer_capability_matrix()
```

### Result

```text
PASS
```

（粒度缺口见 A12：到 renderer/provider 名，无 camera-movement 级。）

---

## A7 — Video Intelligence Output

### Assumption

Artifact 可以被观察。

### Current

Existing:

```text
hevi/video_intelligence/models.py
analysis.py:25-60 analyze_reel()
boundaries.py / probe.py / transcript.py
```

支持：

```text
reel
shots
boundaries
motion
transcript
```

### Result

```text
PASS
```

（VLM 观测归 Class M，置信度封顶，见 P10.1 §12.5。）

---

## A8 — Stem Export

### Assumption

Audio 可以拆分：

```text
voice
music
foley
ambience
```

### Current

```text
hevi/tongjian/assemble.py:267-284 mix_sfx_master
```

输出：

```text
single master
```

全仓无 multitrack 音频导出（grep 命中均为 `Path.stem` 噪声）；`verdict/delivery_gate.py:136-186` 静音检测在 master 上用绝对 `-35dB`，ffmpeg 版本未 pin。

Missing:

```text
multitrack artifact
```

### Required

AudioArtifact:

```yaml
master:

stems:

 voice
 music
 foley
 ambience
```

或明确声明相关检查 `NOT_EVALUABLE`（不得静默 PASS）。

### Result

```text
FAIL
BLOCKER FOR SOUND COMPLIANCE (MEDIUM effort)
```

---

## A9 — Shot Cache

### Status

经核实：**FAIL（不存在）**，非 PENDING。

幂等键存在于 mission/task/case 层（`missions/p3_types.py:201`、video_tasks/video_cases 唯一索引、production_graph 唯一索引、`creative/layer4/provider_execution.py:126`），但**无以内容哈希为键的 per-shot 缓存**（ShotIntent/ShotPlan/生成产物均无 `request_hash → artifact` 复用表）。

要求：不能因为 camera change 导致 script regeneration；early cutoff 与 preserved 证明不可行时退化为全量重跑。

应对（二选一，需 G0.3 拍板）：新建 per-shot 内容哈希缓存，或 P10a 接受全量重跑、P10c 再补缓存。

```text
FAIL (no per-shot content-hash cache; full rerun fallback)
```

---

## A10 — Receipt / Provenance

### Status

经核实：**PARTIAL**，非 PENDING。

存在：`hevi/execution/models.py:134 ProductionReceipt`（bytes + digest + ValidationResult）+ `hevi/constraints/compiler.py:66 CompilationReceipt` + `hevi/narrative/models.py:279 RevisionReceipt` + `ReceiptLedger` + artifact_store/narrative/VI provenance。

缺口：无 P10 creative receipt（compile/run receipt：pinned 哈希、validators、auto 审计、DegradeEvent、检测器版本）。

P10 不允许新增 creative receipt ledger；允许扩展现有 receipt（`export-prov` 只做导出器，不做存储）。

```text
PARTIAL (mechanisms exist; P10 creative receipt missing; extend, don't fork)
```

---

## A11 — Review / Verdict

### Existing Candidates

```text
hevi/director/verdict_checks.py:41 ShotVerdict
hevi/verdict/final_review.py:41 FINAL_REVIEW_CHECKS
hevi/video_intelligence/models.py
hevi/ops/p5_1_review.py:59 ReviewInputPackage -> VideoReview
```

Risk：形成 Creative / Technical / Video 三个 verdict 系统。

Decision：必须建立 Verdict adapter 而不是 P10 Verdict；H 类 attest surface 待 Q4 拍板（谁、在哪、是否双人）。

```text
PARTIAL (exists; Creative dimension + attest surface missing)
```

---

## A12 — Render Capability

### Required

验证：frame accurate export、metadata preservation、artifact hash。

经核实：**PARTIAL**。`renderer_capability_matrix()` + `renderers/base.py:259` 匹配排序 + `p5_3/retrieval.py` + `shot_readiness.py:299` 存在；但能力到 renderer 名粗粒度，无 camera-movement 级；`hyperframes render` 有超时记录（`hevi/qualification/providers/hyperframes.py:5`），声明与可用有差距。

应对：negotiation 先按 renderer 名粗粒度；细粒度需 ProviderRegistry 补字段（上游工作）。

```text
PARTIAL (matrix exists; camera-level granularity missing)
```

---

## A13 — Authority Pinning

### Required

所有 creative decision 必须 pin：

```yaml
authority:

 narrative_version:
 visual_style_version:
 asset_version:
 provider_version:
```

经核实：**PARTIAL**。Style 完整（`id@version` + resolve/validate）；Canon/Asset 无统一 version/hash 查询；Provider 有 `model_version`（VI repo）但非统一 pin 接口；`canonical_hash`（`ops/p5_1_types.py:71`）是 evidence 指纹，非 authority pin。

影响：入向失效（§13.5）无法统一实现。

```text
PARTIAL (Style complete; Canon/Asset/Provider pin missing)
```

---

## A14 — Storage Model

### Current Risk

P10 原设计：

```text
events.jsonl

objects/<sha256>
```

已有：`artifact_store` 内容寻址 + 原子写 + jsonl 追加（`director/gate_log.py → .gates.jsonl`）；`RevisionStore`、`ApprovalStore` 存在。

禁止新增：`CreativeEventStore` / `CreativeApprovalLedger` / `CreativeRevisionDB`。

决定：P10 对象库/事件若建设，落在 artifact_store + 原子写 + jsonl 模式之上；新后端需选型（A14 假设），默认不建。

```text
PARTIAL HOLD (reuse artifact_store; no new backend)
```

---

# 3. Gate 0 Final Matrix

| Category             | Result  |
| -------------------- | ------- |
| Authority boundary   | PASS    |
| ShotIntent extension | PASS    |
| Provider interface   | PASS    |
| VI interface         | PASS    |
| Beat identity        | FAIL    |
| Script identity      | FAIL    |
| TTS alignment        | FAIL    |
| Anchor resolver      | FAIL    |
| Stem export          | FAIL    |
| Shot cache           | FAIL    |
| Storage reuse        | PARTIAL HOLD |
| Receipt reuse        | PARTIAL (extend, don't fork) |
| Revision reuse       | PARTIAL (no 4th store) |
| Verdict reuse        | PARTIAL (adapter, no new verdict) |
| Authority pinning    | PARTIAL (Style only) |
| Render capability    | PARTIAL (coarse only) |

---

# 4. G0 Decision

```text
G0 = FAIL
```

原因：核心链：

```text
Script ID
 ↓
TTS Alignment
 ↓
Anchor Resolver
 ↓
CueMap Evidence
```

不存在。

正式结论：

```text
P10 architecture: ACCEPT DIRECTION

P10 implementation: BLOCKED

Blocking layer:
Temporal + Alignment Infrastructure
```

---

# 5. Allowed Before G0 Pass

允许：

```text
interface audit
dependency analysis
spike experiments
effort estimation
```

禁止：

```text
hevi/creative implementation

CreativeDirection models freeze

CueMap schema freeze

Direction Compiler

Creative Compliance Engine
```

---

# 6. Next Action

进入 `docs/p10/g0_2_spike_spec.md`：G0.2 Interface Repair Spike（三个最小验证）。通过后才进入 P10-S（30 秒真实视频：1 Thesis + 1 Treatment + 1 Benchmark + 1 SignatureShot + 1 Cross-modal Cue + 1 Explain provenance）。

## 附录：关键证据索引

| 主题 | 文件 |
|------|------|
| ShotIntent/BeatCue | `hevi/cinematic/shot_intelligence/models.py:39-80` |
| Screenplay 无稳定 ID | `hevi/director/pipeline_schemas.py:37-65`、`screenplay.py:248-288` |
| TTS 丢弃 word-boundary | `hevi/audio/edge_tts_custom.py:130-207`、`speech_platform.py:136` |
| Timeline float 秒 | `hevi/studio/timeline.py:41-66,327-363`、`hevi/tongjian/schemas.py:157-165` |
| Provider/Renderer 能力 | `hevi/video/capability_guard.py:174`、`hevi/renderers/__init__.py:58` |
| VI 输出 | `hevi/video_intelligence/models.py`、`analysis.py:25-60` |
| Master 混音/静音检测 | `hevi/tongjian/assemble.py:267-284`、`hevi/verdict/delivery_gate.py:136-186` |
| Style pin 范本 | `hevi/production/p6/visual_style/registry.py:193-277` |
| Receipt/Review/Revision | `hevi/execution/models.py:134`、`hevi/verdict/final_review.py:41`、`hevi/creative/layer4/revision.py:265`、`hevi/ops/p5_approval.py:38` |
| 存储 | `hevi/artifact_store/object_store.py:57-98` |
| Authority | `creative.py:271 (Canon)`、`asset_intelligence.py:74`、`providers/registry.py:8` |

*判断声明：成本量级与 Owner 推断属工程判断，待 G0.2/G0.3 推翻。*
