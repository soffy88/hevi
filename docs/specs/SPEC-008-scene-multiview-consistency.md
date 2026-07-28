# Hevi 场景多视图一致性 · SPEC-008（草案）

> 状态：草案 v0.1（Wiki 裁决 B+C 后起草，待核 → 交 CC 实施）
> 依赖：`SPEC-004`（SceneStage / space_map 结构化坐标）、`INC-004`（ControlNet 最小验证 + VRAM 实测）、`QNLR-AQIN-PROJ-001`（驱动需求）、`QNLR-EP0-CONF-001` §3/§8（早先标"8 方位=需新 SPEC"）、签字工件 `G1a-aqin-L2-finding-20260723`（naive txt2img 证伪）
> 缘起：G1a 试跑证伪——独立 per-azimuth txt2img 生不出"同一座殿的 8 视点"（机位不可由文字控制、无 3D 几何真值、无 ControlNet）。Wiki 裁决走 **B（3D 底模）+ C（ControlNet-depth）** 合流方案。
> 定调：**几何真值来自 3D 底模（B），写实纹理来自 SDXL 受 depth-ControlNet 约束（C）。txt2img 想象空间 → depth 图硬约束空间。** 一次能力投资，服务 A-QIN 全季底版 + 所有需多视点一致的场景。

---

## 0. 问题与目标

**问题**（G1a 实证）：SceneStage 定了 D1 大殿的轴线（王座 N / 殿门 S / 柱阵东西各 4），但生成端拿不到这份几何——txt2img 每个方位各自想象，8 张互不相干且丢地标。

**目标**：给定一个 SceneStage，产出 **N 个方位一致的写实底版**（柱阵/王座/殿门跨视点空间连续），支持 D1/D2 dressing，且深度图可复用于角色合成的几何硬约束。

**非目标**：不做实时渲染引擎；不追求建筑级精确 3D（够导出可信 depth/法线即可）；不在本 SPEC 解决角色身份锁（那是 IP-Adapter/Subject3D 既有线）。

---

## 1. 现状盘点（决定 B/C 各自工作量）

| 组件 | 现状 | 指针 | 对 B/C 的意义 |
|---|---|---|---|
| ControlNet VRAM | **已真机验证**（INC-004，2026-07-19，3080 峰值实测） | `image/sdxl_local_service.py:81-87` | C 的可行性已证；门槛注释在案 |
| ControlNet worker 分支 | **脚手架就绪、未接**：OpenPose 分支接线 TODO 详列（`StableDiffusionXLControlNetPipeline` + 权重 + `controlnet_conditioning_scale`） | `image/_sdxl_worker.py:35-51` | C 是"接已设计好的分支 + 加 depth 变体"，非从零 |
| 控制图产出 | 合成图设计上兼作 ControlNet 控制图；OpenPose 骨架控制图已能产出 | `tongjian/scene_render_avatar.py:628-635, 780-831` | C 的 depth 控制图需**新增**（B 提供），骨架图那套是角色用、可复用管道 |
| SceneStage 几何 | `SceneSpaceMap`（zones + landmarks + rel_position）**结构化但"不做 3D"**，仅派生俯视示意 | `director/pipeline_schemas.py:495-518, 619` | B 的几何种子——把结构化坐标升成粗 3D |
| Subject3D | TripoSR 对**单主体**（角色）出 GLB + 4 视图 | `subjects/subject3d_local.py:49` | B 可试 TripoSR-on-hall，但建筑非其训练域，风险高（见 §5） |

**结论**：C 的地基（VRAM 验证 + worker 接线模式 + 控制图管道）大半已在，增量 = **depth ControlNet 变体 + 场景 depth 控制图来源**；B 的增量 = **SceneStage 结构化坐标 → 粗 3D → 逐方位 depth 渲染**。二者在 depth 图处合流。

---

## 2. 架构：B 供几何、C 渲写实（合流于 depth 图）

```
SceneStage.space_map (王座N/殿门S/柱阵EW×4, 结构化坐标)
        │  [B track]
        ▼
   粗 3D 底模 (parametric blocking 3D / 或导入轻量 3D 资产)
        │  逐方位相机 (azimuth_deg 0/45/.../315)
        ▼
   per-azimuth depth map (+ 可选法线/分割图)   ◄── 几何真值
        │  [C track]  控制图
        ▼
   SDXL + ControlNet-depth (img2img/txt2img, conditioning_scale ~0.6)
   + 写实提示 (photographic anchors) + dressing 提示 (D1素黑/D2玄黑)
        ▼
   写实、方位一致的底版组 (柱阵/王座/殿门跨视点连续)
```

**B · 3D 场景底模**（几何真值源）：
- 输入 = SceneStage `space_map` 结构化坐标（已有：zones/landmarks/rel_position）+ 轴线约定（SPEC-004 `SceneAxis`）。
- 产出 = 一个粗 3D 场景（柱阵按"东西各 4"参数化摆位、王座台 N、殿门 S），可被虚拟相机按 `azimuth_deg` 环绕，导出**逐方位 depth map**。
- 路线优先级（§5 详）：**参数化 blocking 3D（荐）** > 导入轻量 3D 资产 > TripoSR-on-hall（探路，风险高）。

**C · ControlNet-depth 渲染**（写实纹理，受几何约束）：
- 接 `_sdxl_worker.py:35` 已 TODO 的 ControlNet 分支模式，**加 depth 变体**（`diffusers` depth ControlNet-SDXL 权重，与已规划的 openpose 分支并列）。
- 控制图 = B 产的 per-azimuth depth map（非角色骨架图）。
- `conditioning_scale` 起点 ~0.6（几何硬约束）+ img2img init 可选（B 的粗彩渲当 init 软约束，承接 `scene_render_avatar:628` 的"同一底图两用"设计）。
- 与既有 IP-Adapter 共存（角色合成时几何 + 锁脸并行，承接 `:629` 架构正解）。

---

## 3. 建议落点（3O 惯例，本 SPEC 不实现）

| 增量 | 建议落点 | 备注 |
|---|---|---|
| 场景几何 → depth | 新 `hevi/image/scene3d_local.py`（与 `subject3d_local` 平级；参数化 blocking 3D + 相机环绕 + depth 导出） | 独立 venv 与否视 3D 库依赖定 |
| SceneStage → 3D 映射 | `director/scene_stage.py` 加 `space_map → geometry` 派生（承接 SPEC-004 "结构化坐标"未竟项，CONF §4 标"部分"） | 复用 `azimuth_deg` 约定（含 §5.4 光轴/机位换算交底） |
| depth ControlNet 接线 | `_sdxl_worker.py` ControlNet 分支加 depth 变体（沿 `:35-51` 已列 openpose 模式） | 与 openpose 分支共用管道改动 |
| adapter 新 op | `qnlr/gen_adapter.py` 加 `render_scene_view`（T-2 场景变体：depth 控制图 + dressing → 写实底版），横切照旧（cost/trail/vault） | DR-1 约束 1 延续 |
| dressing 变体 | SceneStage `dressing_state`（D1/D2 共几何、异色/仪仗），CONF §3 已标"需新 SPEC"——并入本 SPEC | 一套 3D 几何出 D1/D2 两版渲染 |

---

## 4. 分期与验收门（G-SCENE3D）

**EP0 最小闭环**（tranche 1 解阻塞）：D1 大殿一套几何 → 8 方位 depth → 8 张写实一致底版；G1a 判据（柱阵东西各 4 连续、王座 N/殿门 S 地标跨视点一致、写实风）此时**可过**。
**季度级**：dressing D1/D2 双版、景深档、多场景（未央宫/洛阳宫等 A-HAN 重皮线复用同管线）。

**G-SCENE3D 验收**：取一套 SceneStage，出 8 方位底版，逐相邻方位对（8 对）人工勾验柱序不跳变 + 地标连续（即 G1a 原判据，现有几何真值支撑）；depth 图可复用于该场角色合成的几何约束（抽 1 镜验证）。

---

## 5. 风险与开放问题

1. **TripoSR-on-hall 大概率不行**：TripoSR 训练域是单主体/角色，建筑几何非其所长（Subject3D 对角色侧视图已偏软，建筑更甚）。**故 B 首选参数化 blocking 3D，不押 TripoSR**；TripoSR-on-hall 仅作对照探路。
2. **VRAM（3080 10GB）**：ControlNet + IP-Adapter 共存峰值（INC-004 实测在案）逼近上限；STATUS 🔒 记 IP-Adapter + attention-slicing 已敏感。depth-CN 单独（场景无需锁脸）应更宽裕，但**共存路径需真机复测**（标"需试跑验证"）。
3. **depth 图质量**：参数化粗 3D 的 depth 是否足够引导 SDXL 出可信透视，需实拍标定 `conditioning_scale`。
4. **协同红利**：接 depth-CN 的 worker 改动与已规划的 openpose-CN 分支共用管道——**一次接线，角色姿势控制（Gap 1 阶段2）一并解锁**，值得并做。

---

## 6. 关联与排期交底（诚实提示）

- 本 SPEC 是 **L 级季度能力投资**（B 新建 3D 管道 + C 接 ControlNet）。
- **EP0 8 月底硬发布窗口约 5 周，B+C 全建大概率赶不上**——若 EP0 必须按窗口出，D1 底版仍可能需一个**临时替代**（写实 master `scratchpad/l2/az000_master_realistic.png` 已备 + 少量人工构图角度）**过渡**，B+C 作季度正解并行建、EP5（牧野）前切换（呼应 DR-1 移植窗口节奏）。此为排期事实陈述，非重开 A/B/C 裁决——裁决 B+C 已定，本条只把窗口张力显式随档，供你排期时权衡是否 EP0 走过渡、季度落 B+C。
- **★ 排期裁决（Wiki 2026-07-23，已拍）**：EP0 走过渡路（写实 master + 人工角度），B+C 定为季度正解、目标 EP5（牧野）前切换；SPEC-008 落地窗口**显式绑定 DR-1（EP0-SPEC §11）的 V2 移植窗口为同一缓冲期**——EP1–3 考古期（生成压力谷值）两件 L 级工作共用同一缓冲，是排期结构本应如此。依据：EP0 冷开场实际 =13 镜、六七机位，人工角度扛得住，真正需八方位一致的廷议群像/多场景本在 tranche 2 及以后。
- **★ EP5 切换口径澄清（防季中误读）**：「EP5 前切换」指**宫殿类场景的渲染路径切换**（naive→depth-CN）。EP5 牧野是**开阔战场，走低几何依赖路线**（AMORT-001 §4），本就不吃 B+C——故不得拿 EP5 当 B+C 的验收窗口；B+C 验收锚在其首个宫殿类消费场景（EP11/EP12 未央宫线），非牧野。
- 成本：本 SPEC 起草零成本；实现期真机试跑项（VRAM 共存复测、depth 标定）另计，届时报预算。
