# HEVI Director Contract V1

## 目标

将 `stickman-video-director` 中最有价值的导演能力内化为 HEVI 的 renderer-independent contract，而不是引入 Gemini 专用 prompt runtime。

本契约连接现有 HEVI 的：

- narrative/source authority
- `hevi.creative.direction_plan` 的 Beat/Cue/Camera 模型
- `hevi.creative.direction_state` 的 durable revision/approval lifecycle
- renderer qualification / artifact QA

## Canonical pipeline

```
SourceBundle
  -> ClaimGraph
  -> StoryPlan
  -> DirectorProposal
  -> explicit approval
  -> ProductionPlan
  -> renderer adapter
  -> RenderArtifact
  -> Artifact QA
  -> Publish
```

Director 是语义与时间结构 authority；renderer 只能实现已批准的 ProductionPlan。

## Canonical objects

### ClaimRef

每个重要事实/主张必须有来源追踪：

- `claim_id`
- `text`
- `source_refs`
- `strength`
- `allowed_transformations`

导演可以改变表达、顺序、视觉隐喻与节奏，但不得增加未来源支持的事实、数字、引用、产品 claims 或提高结论强度。

### BeatSpec

Beat 是最小时间导演单位：

- `beat_id`
- `start_sec`
- `end_sec`
- `narrative_function`
- `emotional_function`
- `visual_action`
- `visual_devices`
- `camera_intent`
- `audio_intent`
- `semantic_refs`

V1 要求每个 Shot 至少 3 个 beat，并覆盖完整 shot 时间轴；不强制每个 beat 必须恰好 0–3/3–7/7–10 秒，因为 HEVI 不是只服务 10 秒视频。

### ContinuityContract

每个 Shot 必须声明 incoming/outgoing continuity anchors。锚点是结构化数据，不是仅存在于自然语言中的“上一镜有一束金光”。

锚点可描述：

- pose
- object
- camera motion
- direction
- frame occupancy
- environment state
- audio state

相邻 shot 的 continuity edge 必须有可验证的共同 anchor。

### ShotSpec

Shot 包含：

- renderer-independent intent
- duration
- narrative function
- beats
- composition
- camera intent
- audio intent
- semantic refs
- continuity in/out
- renderer constraints

Shot 不包含 Gemini prompt。具体 prompt 属于 renderer adapter 的派生 artifact。

### DirectorProposal

提案必须绑定：

- `direction_id`
- `revision`
- `source_fingerprint`
- `aspect_ratio`
- `duration_sec`
- `visual_style`
- `narrative_strategy`
- `shots`
- `continuity_edges`

Proposal hash 是 approval binding 的核心。

## NarrativeStrategy

5-stage heartbeat 作为策略之一，而不是 HEVI ontology：

- `MOTIVATIONAL`
- `EDUCATIONAL`
- `SCIENTIFIC`
- `HISTORICAL`
- `PRODUCT`
- `CUSTOM`

Stickman 的 Golden Hook -> Disrupt -> Insider -> Truth -> Elevation 属于 `MOTIVATIONAL` 的一个默认模板。

## Approval invariant

批准必须绑定 proposal hash 与 revision。

```
approve(proposal_hash, revision)
  -> compile(proposal_hash, revision)
```

任何全局导演设置变化必须生成新 proposal hash，并使旧 approval 失效。

V1 的全局变化集合：

- aspect ratio
- duration
- visual style/theme
- narrator/voice
- tone
- narrative strategy
- palette
- global composition policy

不能通过字符串替换绕过重新提案。

## Renderer boundary

ProductionPlan 是唯一 renderer 输入。

禁止：

```
Director -> renderer-specific prompt -> runtime
```

允许：

```
Director -> ProductionPlan -> RendererAdapter -> render
```

Gemini/Omni prompt 是 renderer adapter 输出，不是 canonical state。

## Quality invariants

以下层次必须独立：

```
artifact_exists
!=
render_success
!=
QA_pass
!=
publishable
```

导演契约本身不宣称媒体质量通过；它只保证导演计划结构完整且可被验证。

## V1 acceptance gates

D1 source fingerprint present
D2 all semantic claims traceable
D3 proposal has explicit ratio/duration/style/strategy
D4 proposal has >= 1 shot
D5 every shot has >= 3 beats
D6 beat timeline is contiguous
D7 every shot declares continuity in/out
D8 adjacent continuity edges share an anchor
D9 proposal hash is deterministic
D10 compile rejects missing approval
D11 compile rejects stale proposal hash
D12 compile rejects stale revision
D13 renderer-specific prompt fields are absent from canonical objects
D14 global changes are explicitly detectable
D15 no renderer selection occurs inside Director Contract

## Adoption

V1 intentionally does not delete or replace existing HEVI director implementations. It establishes the canonical contract and adapters can migrate progressively.

Priority migration:

1. Existing `hevi/creative/direction_plan` Beat/Camera/Cue data -> `BeatSpec` compatible adapter
2. Existing `direction_state` revision/approval -> proposal binding
3. Existing `storygraph/ShotIR` -> legacy compatibility adapter
4. Renderer adapters consume `ProductionPlan`
5. Existing QA/evidence remains authoritative for rendered artifacts

## Existing HEVI integration

The existing P10c `BeatPlan` remains the source representation. `hevi.creative.director_adapter` projects it into the canonical contract and requires an external anchor resolver for absolute seconds; it never guesses timing from anchor IDs.

`ShotIR` is a compatibility projection only. It may carry `director_proposal_hash` in node metadata, but it is not an approval or execution authority.

`DirectionState` now has optional `proposal_hash` and `approved_proposal_hash` fields. Legacy snapshots remain valid. For any revision with a non-empty proposal hash:

- APPROVE must bind `proposal_hash` to the stored proposal hash.
- COMPILE must bind the same proposal hash.
- COMPILE additionally requires `approved_proposal_hash == proposal_hash`.

This closes the approval-to-compile gap without invalidating pre-V1 state.
