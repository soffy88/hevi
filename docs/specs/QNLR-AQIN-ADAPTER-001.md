# QNLR-AQIN-ADAPTER-001 · `qnlr_gen_adapter` 接口摸底文档

**性质**：T3 交付。**只定义不实现**——本文冻结 adapter 的对外接口、每类调用对应的真实底层入口、以及成本/溯源/登记三项横切约定，供 A0 薄实现照此落地。
**上游**：QNLR-AQIN-PROJ-001（§0 前置链、§1 帽、§3 熔断）、QNLR-EP0-SPEC-001 v0.2 §11 DR-1。
**红线继承**：DR-1 约束 1（director 侧只见 adapter 接口，严禁直连 tongjian 内部）、约束 2（只包不改）、约束 3（产物按 fingerprint + decision_trail 登记）。
**状态**：Draft v0.1，待核 → A0 实现依据。

---

## 0. 落点与形态

- **建议落点**：新增包 `hevi/qnlr/gen_adapter.py`（与 director、tongjian 平级，双向解耦；最终布局 A0 时按仓库惯例定）。
- **形态**：一组**纯函数式薄封装**，每个 adapter 调用 = ①校验入参 → ②调底层真实入口 → ③记 cost ledger + decision_trail → ④（产物类调用）登记 vault 资产 → 返回带 `AdapterResult` 信封的结果。
- **不做**：不改任何 tongjian/subjects/image 内部；缺口只在 adapter 内加垫片（DR-1 约束 2）。

---

## 1. 三类调用（AQIN-PROJ §0 指定）+ 真实底层入口

状态：**本地/免费** = 无真机付费；**云/付费** = 计入金额帽。

### T-1 · subject 摄取 / 身份锚（本地/免费）
封装链（全本地）：
- `subjects/subject_service.py:31 create_subject(*, kind, name, reference_images=None, metadata=None, tags=None, description="", user_id=None) -> dict` — 建 subject，内部触发 `_compute_identity_embeddings`。
- `subjects/subject_service.py:80 _compute_identity_embeddings(refs) -> (whole_clip_vec|None, face_clip_vec|None)` — 双 CLIP 身份向量（均值 + L2 归一）。
- `subjects/subject_service.py:355 generate_subject3d(subject_id, *, output_root="output/subject3d") -> dict|None` — 写 `metadata.subject3d = {glb_path, views:{front/left/right/back}}`（底层 `subject3d_local.py:49 generate_subject3d(image_path, *, output_dir, mc_resolution=256, views=(front,left,right,back), timeout_s)`，TripoSR CPU 子进程，~172s/具）。

**adapter 对外**：`ingest_subject(*, kind, name, reference_images, want_3d=True, ...) -> SubjectAnchor{subject_id, whole_clip, face_clip, subject3d_views}`。摄取本身 0 付费调用；**参考图从哪来**见 T-3（txt2img 生成或真人照片直传）。

### T-2 · compose 合成（本地/免费）
- `tongjian/scene_render_avatar.py:719 _compose_layout_base(*, present, view_path_by_cid, pos_desc_by_cid, size, out_path, background=None, side_by_cid=None) -> Path|None` — 按 blocking 把 N 具 Subject3D 视图几何合成一张 base PNG（任一视图缺失→None）。**这是"N 参考 + 布局 → 一张合成关键帧"的最小入口**。
- **adapter 对外**：`compose_layout(*, subjects:[SubjectAnchor], layout, size, background=None) -> ComposedBase{base_png_path, present_cids}`。纯几何拼合，无生成调用，免费。

### T-3 · img2img 精修（含 txt2img 底版；本地/免费，云为可选付费）
- 本地 SDXL 单一入口，txt2img 与 img2img 同函数：`image/sdxl_local_service.py:183 sdxl_local_generate(*, prompt, negative_prompt="", width=1024, height=1024, output_path, seed=None, timeout_s=120.0, extra=None, require_gpu=True) -> dict` — 子进程隔离（`_sdxl_worker.py`，非队列）。**`extra["init_image"]` 置位即走 img2img 支路**（`_sdxl_worker.py:24`）；不置位 = txt2img（用于生成角色参考图、D1 底版）。批量 `:241 sdxl_local_generate_batch`。
- 云精修（可选、付费）：`scene_render_avatar.py:920 _edit_keyframe(*, image_path, instruction, output_path, fallback_from, engine="local"|"cloud", ...) -> str`（返回实际用的引擎标签）。
- **adapter 对外**：`refine_image(*, prompt, init_image=None, negative="", size=(1024,1024), seed=None, engine="local") -> GenImage{path, engine, seed}`。`init_image=None` → txt2img；`engine="local"` 免费；`engine="cloud"` 计帽（额度风险见 §4）。

### 1.4 · 相机与朝向双字段接口（2026-07-23 补，任务 2 · 只定义不实现）

**动因**：G1a 证伪的单角相机（`azimuth_deg` 一个标量）在 naive txt2img 下只是没生效；但 **SPEC-008 走 3D 底模 + ControlNet-depth 后，单字段的语义歧义会直接暴露在新管线上**——一个 `azimuth_deg` 说不清"相机在环轨哪个点"「看向何处」「主体朝哪」三件事，depth 渲染要的是明确的相机外参 + 每主体朝向，含糊值会渲出错误透视/背对镜头。故在 A0/SPEC-008 实现前先把接口冻结成双字段。

**C-1 · 相机（二选一等价表示，adapter 内部归一为同一外参）**：
- **形式 A（荐，世界坐标绝对）**：`camera = {position: [x,y,z], look_at: [x,y,z], up?: [0,1,0], fov_deg?: 40}` —— 位置 + 注视点，无歧义，直接喂 3D 底模虚拟相机（SPEC-008 §2 逐方位环绕即在此坐标系取点）。
- **形式 B（等价，场景中心极坐标）**：`camera = {pos: {azimuth_deg, elevation_deg, radius}, heading: {yaw_deg, pitch_deg}}` —— pos = 相机在以场景中心为原点的球面位置，heading = 光轴朝向（**与 pos 解耦**：可站 45° 却横摇看向殿门，正是单字段做不到的）。缺 `heading` 时 adapter 默认 heading 指向场景中心（还原旧 orbit 语义，但显式）。
- 约束：两形式**必须二选一给全**，不接受"只给 azimuth"的旧单字段（实现期对单字段输入报错要求补 look_at/heading，不静默按指向中心处理——不静默降级）。`SceneStage.space_map`（SPEC-008 B 轨）提供世界坐标真值，形式 A 为其原生表示。

**C-2 · `subject_facing` 数组（每主体朝向，替代 `pos_desc_by_cid`/`side_by_cid` 的文字近似）**：
- `subject_facing: [{cid, facing_yaw_deg, facing_pitch_deg?=0, anchor_view?}]` —— 每具在场主体一条，`facing_yaw_deg` = 该主体在场景世界坐标里的朝向（非相对相机），adapter 据此 + C-1 相机外参**算出该主体相对相机的视角**，再选 Subject3D 对应视图（front/left/right/back）并做朝向合成；`anchor_view` 可显式钉某视图覆盖自动选择。
- 与现状衔接：现 `_compose_layout_base` 的 `side_by_cid`（左/右文字）与 `pos_desc_by_cid` 是此接口的退化近似；新接口把"朝向"从文字升为角度，消歧后可喂 depth-ControlNet 的几何约束。
- 缺省：`subject_facing` 未给某 cid → 该主体朝向默认 = 面向相机（`facing = 相机→主体 反向`），显式记入 trail，不静默。

**落点（实现期，非本文）**：`compose_layout` / SPEC-008 `render_scene_view` 的入参由 `pos_desc_by_cid` 扩为 `camera`(C-1) + `subject_facing`(C-2)；旧字段实现期保留为过渡近似或弃用，由 A0/SPEC-008 实现时定。**本节只冻结接口语义，不实现。**

---

## 2. 横切约定（三项，adapter 强制）

### 2.1 成本账（cost ledger）
- 累加器：`cost/tracker.py:13 create_hevi_tracker()` → `HeviCostTracker`（底层 `obase.cost_tracker.CostTracker`）。
- 记账：`internal.record(category, provider, model_or_tier, unit, quantity) -> float`（`tracker.py:58/69`）；总额 `internal.total_usd`；`get_summary() -> {total_usd, entries}`（`tracker.py:79`）。
- 帽内预留：`cost/circuit_breaker.py:40 CostTracker.check_and_reserve(amount_usd, limit)`（改 `spent_usd`）—— adapter **每次付费调用前** `check_and_reserve(est, 金额帽=¥80)`，超帽即抛、暂停（AQIN §3.2）。
- **§3 熔断第 5 条落点**：付费调用**返回后**，adapter 计 `折算单价 = actual_usd / (视频时长s | 图像张数)`，>¥1/s（视频）或 >¥0.1/张（图像）→ 即时告警 + 暂停 + 出路由核对短报。
- 单位换算：金额帽以 ¥ 计，provider 计费多为 USD；adapter 需持一个 **¥/USD 折算率**（A0 时由 Wiki 给定或从 config 读，本文标为待填参数 `CNY_PER_USD`）。
- **★ ledger 落盘（2026-07-23 补，任务 1 已实现）**：内存态 `spent_usd` 不是可查询 ledger——首笔支出只落签核 markdown = 记账不是 ledger（反静默断链）。付费调用（`cost_usd>0`）后 adapter **追加一条结构化记录**到 `docs/ledgers/aqin-cost-ledger.jsonl`（已跟踪、append-only JSONL、可提交可复核；本地免费 op 不写）。落点：`hevi/qnlr/cost_ledger.py`（`append_record`/`read_records`/`total_cny`）；接线在 `GenAdapter.ledger_path`（默认上述路径，None=不落盘供单测）。每条字段契约（缺一即拒落盘）：`ts`(调用方传入,无时钟)、`op`、`provider`、`model_or_tier`、`unit`(per_second|per_image)、`quantity`(时长s|张数)、`unit_price_cny`、`cost_cny`、`cost_usd`、`fingerprint`(vault pack_id|None)、`trail_digest`、`cumulative_cny`、`cap_cny`。G0 首笔 ¥4.725 已回填为第一条。tranche 2 预算的实测单价来源 = 此 ledger，不再取人手写文档。

### 2.2 决策留痕（decision_trail）
- 现状：无独立类型，是 `scene_render_avatar.py:1976` 内联构造、挂 `ShotFrame.debug_context: dict`（`tongjian/schemas.py:301`）的扁平 dict。
- **adapter 约定**：每次调用产出一条 `decision_trail` dict = `{op:T-1|T-2|T-3, inputs_digest, provider, model_or_tier, engine, seed, cost_usd, unit_price, ts_from_caller, fingerprint}`（时间戳由调用方传入，adapter 不自取时钟）。随产物落盘 + 喂 vault provenance。

### 2.3 资产登记（fingerprint + vault）
- 登记机制 = `vault/service.py:46 asset_create(pool, minio_client, *, pack_id, pack_type, name, version, files, file_roles=None, **manifest_extra) -> Manifest`（内容寻址 MinIO + draft 行；`:280 asset_promote` 转正、`:115 resolve`、`:257 lineage`）；Manifest schema `vault/schemas.py:34`（pack_id/pack_type/version/`Provenance`@:20/lifecycle）。
- **注意（纠误）**：`verdict/scorecard.py:232 make_scorecard_consistency_fn` 是**逐镜 QC 选优**（omodul 身份指纹选片），**不是**资产注册表——身份锚/合成帧/clip 的跨集登记走 vault，不走 scorecard（呼应 CONF-001 §8「omodul 指纹是误名」）。
- **adapter 约定**：产物类调用（T-1 锚、T-2 合成帧、T-3 图、后续视频 clip）成功后 `asset_create(pack_type=aqin_char|aqin_base|aqin_frame|aqin_clip, provenance=decision_trail, ...)`，返回 `pack_id` 即 fingerprint（DR-1 约束 3）。A-QIN 资产不绑通道、入 vault 新范式（AQIN §0 纪律）。

### 2.4 ★ 产物持久化纪律（2026-07-23 立，凭证↔实物不得分离）

**事故驱动**：G0 支出只存签核 markdown（成本侧，ledger 已补，§2.1）；**资产侧同病未补即复发**——G1a 签核单记"L1 canon 锚集 7/7 可用（嬴政锁脸、荆轲跨视图保持）"，实盘核查（2026-07-23）**盘上 0 具、DB 0 行、reference 图无**，产物全落 scratchpad 已跨会话清；八方位底版 + 写实 master 同样清空。**验收判据引用了不存在的产物**——这是 STATUS 反静默断链纪律在资产侧的漏洞。

**纪律（硬规，G1 起适用，同 ledger 之于成本）**：
1. **任何计入验收判据的产物**（身份锚、底版、合成帧、clip、master、contact sheet 等，凡被签核单/gate 引用为"可用/通过"依据者）**必须落 durable 路径**（vault，或至少 `output/aqin/<layer>/` 等跨会话存活目录），**严禁只存 scratchpad**。
2. 落盘即**登记 manifest**：`{fingerprint, 类型(pack_type), 生成参数摘要(prompt/seed/尺寸/provider digest), 所属层(L1/L2/…), 源(subject_id/scene), ts}`。vault 基建在则走 `asset_create`；未在则落 manifest 边车 JSON（`output/aqin/<layer>/manifest.jsonl`），vault 起来后回迁。
3. **scratchpad 只允许存明确一次性的中间件**（烟测、废片、探针）；凡"要拿去签"的，不进 scratchpad。
4. **签核纪律联动**：签核单声明"N/N 可用"时，须附产物的 durable 路径或 pack_id 清单；无 durable 凭证的产物**不得计入 gate 通过**（即 G1a 的"7/7"若无凭证，判据视为未达成，非已达成）。

**为何现在做**：L3 压测将产十几条视频（实测单价 + 命中率数据），那批若再丢，压测学费白花、tranche 2 预算失据。此纪律现在做比 L3 后做便宜得多。

---

## 3. `AdapterResult` 信封（统一返回）

```
AdapterResult{
  ok: bool,
  op: "T-1"|"T-2"|"T-3"|"T-V",
  artifact_path: str|None,        # 产物落盘
  pack_id: str|None,              # vault fingerprint（产物类才有）
  cost_usd: float,                # 本次实付（本地=0.0）
  unit_price: float|None,         # 折算单价（触发 §3.5 判定）
  decision_trail: dict,           # 2.2 约定
  reason: str|None,               # 失败/降级原因（非 ok 时必填）
}
```
熔断/超帽/单价越界一律走 `ok=False + reason`，**不静默降级**（承接 STATUS 反静默断链纪律）。

---

## 4. ★ 首要待决项：G0 付费通路（A0 scoping 前必须定）

**问题**：G0 = "1–2 次真机调用验通路，**首笔非零支出**"（AQIN §0）。但 §1 的三类调用（T-1/T-2/T-3 default）**真实实现全本地免费**——走它们烟测是零支出，验不了付费云通路。

**已确认唯一充值路** = happyhorse 视频（ALIBABA_MAAS）：`video/alibaba_maas_service.py:203 alibaba_maas_generate(prompt, output_path, *, model="happyhorse_1_1", resolution="720P", ratio="16:9", duration=5, seed=None, config=None, timeout_s=600.0) -> Path`（ref-locked 变体 `:367 happyhorse_1_1_reference_to_video`；env `ALIBABA_MAAS_API_KEY` + `ALIBABA_MAAS_HOST`）。云图像编辑路（qwen-image-edit）2026-07-15 撞 FreeTierOnly 额度墙，**不可信**。

**三个选项（归 Wiki/soffy 定，本文不代定）**：
- **G0-a（荐）**：A0 v0 除三类外**多包一个视频薄封装 T-V**（仅一层 `alibaba_maas_generate`），G0 firing = 1 次 happyhorse 5s 视频，验付费通路 + 落首份实测单价（正好喂 §3.5 阈值校准）。代价：A0 从"三类"扩到"三类+T-V"，仍 S 级。
- **G0-b**：G0 只烟测本地链（T-1→T-2→T-3），接受"零支出烟测"，把首笔付费推迟到 L3（S01 视频）。代价：付费通路未提前验，L3 才暴露连通性问题，风险后置。
- **G0-c**：G0 走一次云 `_edit_keyframe(engine="cloud")` 图像编辑——**额度墙风险高，不荐**。

**我的判断（待你确认，不擅自实现）**：G0-a。理由：付费通路正是要提前验的最高风险项；happyhorse 是唯一确认可用付费路；单次 5s 视频成本小且直接产出 §3.5 单价校准数据。

**采纳（2026-07-23）**：G0-a；`CNY_PER_USD=6.75`（Wiki 设定）。A0 v0 含 T-V 视频薄封装。happyhorse_1_1_maas $0.14/s → ¥0.945/s < ¥1/s（过 §3.5）；5s ≈ $0.70 ≈ ¥4.73，远在 ¥80 帽内。

---

## 5. A0 v0 实现边界（照本文落地时）

**纳入**：T-1/T-2/T-3 三类薄封装 + §2 三横切（cost/trail/vault）+ §3 信封 + circuit_breaker 接线。若 G0 采 G0-a 则加 T-V。
**暂缓**：多人口型 per-face 校验、8 方位补全、云图像编辑路（额度墙）、provenance_tier 角标（T4，另线）。
**验收（A0 自身，零成本）**：单测覆盖——①三类各自 mock 底层入口、断言 decision_trail/cost 记全；②超帽 `check_and_reserve` 抛且 `ok=False`；③单价越界触发 §3.5 暂停路径；④产物类调用确有登记落 pack_id。

**A0 实现状态（2026-07-23）**：✅ 已落 `hevi/qnlr/gen_adapter.py` + `hevi/qnlr/__init__.py`；单测 `tests/test_qnlr_gen_adapter.py` **13/13 通过、ruff 干净、导入不拉重依赖**。vault 登记做成注入式 `register_fn`（None 则跳过并记日志，供无 vault 基建的烟测；接 live vault `asset_create` 为后续接线）。**G0 之前 A0 全绿——达成。**
