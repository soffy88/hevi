# P1 入口审计 — `hevi/production/p0_pipeline.py`（改代码前）

634 行。逐个定位 `next/sorted/max/min/[0]`，区分**资产选择**与 **lookup/receipt**。

## 1. 分类结果

| 行 | 模式 | 语义 | 判定 |
|---|---|---|---|
| 387–397 | `for keyword, asset_file in nasa_assets.items(): if keyword in ...` + `break` | **决定哪个 asset 被选** | **第二选择 authority — 必须迁移** |
| 424 | `next((a for a in resolved_assets if a.intent_id == ...), None)` | 取该 intent 已绑定的 asset；`if not asset: continue` = **generation admission** | **必须迁移到 ShotResolution** |
| 445 | `next((i for i in visual_intents if i.intent_id == ...))` | intent 查找（非 asset） | 保留 |
| 476 | `next(a.source_uri for a in resolved_assets if a.asset_id == s.resolved_asset_id)` | 按已定 asset_id 做 receipt | 保留（spec §5 允许 lookup/serialization） |
| 477–478 | `next(m.motion_type ...)` / `next(m.motion_params ...)` | motion 查找 | 保留 |
| 282 / 307 / 324 | `next((a for a in artifacts if a.get("logical_role") == ...))` | artifact 按角色查找 | 保留 |
| 467 / 525 | `min(max_proof_seconds, duration_s)` | 时长 clamp | 保留 |
| 511 / 567 | `next((a for a in artifacts if a.get("primary") and ...))` | artifact 取主件 | 保留 |

**结论：资产选择语义只有 387–397 一处；424 是 admission gate。** 其余 10 处均为 lookup/receipt/clamp，按 spec §5 保留。

## 2. 七条路径（spec §3 要求全审，不能只改 happy path）

| 路径 | 现状 | P1 处理 |
|---|---|---|
| 正常 | 387 命中 → 403 append → 424 取到 → 建 ShotPlan | 迁移到 ShotResolution |
| 空候选 | 387 全不命中 → `matched=False` → record ASSET_RELEVANCE False → 424 `continue` | 保留（resolve 后 selected 空 → 不生成） |
| 多候选 | **不存在** —— `break` 使每个 intent 最多 1 个 asset | P1 让 discovery 产出**全部**候选（按文件去重），由 canonical selector 决定 |
| unresolved | 无此概念 | 新：requirement 无合规候选 |
| unbound | 无此概念 | 新：local ref 未绑定 canonical identity |
| human review | 无接线 | 新：尊重既有 `needs_human_review` |
| retry / regeneration | 无 selection 复用（每次重跑全流程） | P1 不新增 retry 路径；只保证 resolution 每次重算 |
| checkpoint / resume | 无 selection 状态持久化 | 同上（p0 无 resume 实现） |

## 3. 最小垂直方案（不做大重构）

```text
387–397  discovery: 产出**候选**（不 break，按 asset file 去重）
        ↓
        每个 intent 组装 ShotPreparation（candidate.requirement_id = canonical p7 id）
        ↓
        resolve()  ← canonical scorer + selector
        ↓
        ShotResolution
        ↓
424     admission: resolution.ready_for_generation → 建 ShotPlan；否则跳过并 record
```

- `resolved_assets` 字段与其 `ResolvedAsset` 类型**保留**（p1_pipeline:705/730 在消费）。
- discovery 的相关性分需要一个**声明适用域**的 scorer（S3 契约），落在 p0 discovery 层，
  `applicable_domains = {"science_nasa"}`。
- 424 的 `next(...)` 消失：asset_id 改从 `ShotResolution.selected` 取。

## 4. 不在 P1 改（spec §11）

provider_policy / scorer 语义 / selector 语义 / `needs_human_review` / RepairPolicy /
Artifact validation / Director authority / VisualIntent / provider qualification / Acquirer 语义。
发现问题 → 记录 finding，不偷改。

## 5. 已知 finding（记录，不在 P1 处理）

- **F1**: `asset_base` 硬编码 `/tmp/hevi-science-v3/assets`（L388），临时目录，不可复现。
- **F2**: 整个 discovery 是黑洞/NASA 专用关键词表，非通用；P1 只加适用域声明，不通用化。
- **F3**: `semantic_relevance=0.95` 硬编码（L409），与实际匹配无关。
- **F4**: `ShotPlan.camera_setup="static"`（L433）硬编码，未用 MotionPlan 的 ken_burns。
- **F5**: 无 retry/resume 实现，故 Invariant E/F 只能以「每次重算 resolution」满足，
  无法验证「retry 复用旧 selected」的负面场景 —— 该能力本身不存在。