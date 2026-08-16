# SPEC: Director World / 3GS 虚拟片场(3O 内化 Phase D)

> 状态: **设计 spec(待触发)** · 依赖: Subject3D 消费逻辑接通(分镜层机位/方位角字段)
> 来源: dramaclaw `director_world/`(block_world_builder / scene_360_builder /
> scene_spatial_contract / staging_prop_ai)—— "可框取的虚拟片场,锁空间结构、
> 角色走位与机位,保证同一场景跨镜头一致"。
> 3O 归属(待上游): `omodul.scene_block_workflow` + `oprim` 3D 渲染原语。

## 0. 为什么现在不做(诚实的前置判断)

Hevi 的 Subject3D(3D 视角资产)已跑通**数据管道**(GLB + 正/左/右/背四机位帧,
~172s/角色 CPU),但**消费逻辑未接** —— 分镜层没有机位/方位角字段,镜头不知道
自己该用哪个视角的帧(HEVI-ARCH §5.7.0.2 已如实标注)。3GS 是 dramaclaw 在
**3D 消费已通**的前提下建的;Hevi 前置未通,3GS 就是空中楼阁。

## 1. 目标形态(接齐前置后)

```
Scene3D 资产(世界/场景级,与角色级 Subject3D 平级)
  ├── 空间布局(block):可框取的房间/街道骨架 —— 墙/门/家具占位
  ├── 走位(blocking):角色 A/B 在镜头 k 的站位与朝向
  ├── 机位(camera):镜头 k 的机位/焦距/视角(与 shot schema 的方位角字段一致)
  └── 空间契约(scene_spatial_contract):相邻镜头同空间的几何自洽校验
        —— 正反打不穿帮的根因:两个机位是同一 3D 资产的不同投影
```

**消费模式**(复用 HEVI-ARCH §5.7.0 共存模式 3):3D 渲视角结构帧 + 2D 身份参考
一起喂 i2v;背景质感由 2D 场景参考补足。

## 2. 触发条件(三道门,全部满足才开工)

| 门 | 条件 | 现状 |
|---|---|---|
| G1 | 分镜 shot schema 有机位/方位角字段(shot_preparation 消费 3D 帧) | ✅ 已开(ShotListItem.camera_angle/azimuth_deg + scene_contract) |
| G2 | 3D 生成走外采/provider 化 | ✅ **道具路径已开**:`prop3d/img2threejs` provider(veya img2threejs 方法论:参考图→M.C.M.T 蓝图→程序化 Three.js→逐方位条件帧,Apache 2.0,无 GPU 推理);角色/场景全 3D 仍待 |
| G3 | 硬件/license | ✅ **道具路径已开**:img2threejs Apache 2.0 + 代码重建(无 GPU 推理、无网格文件、无 license 障碍);角色 3D(图生3D 大模型)与场景重建(lingbot-map 类)仍观察项 |

## 3. 3O 内化映射(触发后)

- `oprim.scene_block_build`(L2 原语):布局/走位/机位描述 → 3D 场景骨架(block world)
- `oprim.scene_360_render`(L2 原语):骨架 + 机位 → 该机位视角结构帧(复用 Subject3D 渲染管线)
- `oprim.scene_spatial_contract`(L2 原语):相邻镜头几何自洽校验(确定性,不吃模型)
- `omodul.scene_block_workflow`(L1 编排,三件套签名):`_enabled_pillars={report,cost,decision_trail}`,
  失败不 raise;产出机位条件帧组 + 空间契约报告
- hevi wire:Director 分镜阶段产出机位 → workflow 渲条件帧 → 分层流水线身份/场景层消费

## 4. 验收标准

- 正反打两镜:空间契约通过(同一空间不同投影,无几何穿帮)
- 跨集:同一场景第 1 集与第 N 集渲染帧,场景身份分 ≥ 阈值
- 成本:仅机位条件帧走 3D,海量动作帧仍走 i2v 便宜档(经济性不被破坏)

## 5. 本 spec 之外(暂不建)

- 纯 3D 直渲为主干(否决;仅 VTuber 类 Series 作可选 provider)
- 自建渲染农场(否决;3D 生成外采,资产管理与编排自建)

---

# G2/G3 落地(道具路径,Round 3g)

> 来源: veya/templates/skills/img2threejs —— "参考图 → 程序化 Three.js 代码重建",
> Apache 2.0,无 GPU 推理。开掉 G2/G3 的**道具路径**。

## 已实现

| 件 | 内容 |
|---|---|
| `hevi/director/prop3d.py` | M.C.M.T 蓝图(LLM,带确定性 lint)→ 程序化 Three.js 代码 → 相机方位角数学 → HTML harness → headless 逐方位条件帧;浏览器/LLM 缺失优雅降级 |
| `hevi/assembly/scene_block_workflow.py` | 三件套:参考图 → 条件帧组 + scene_contract 空间契约报告(越轴/机位);消费模式 3 落地说明(3D 视角结构 + 2D 身份参考喂 i2v) |
| `hevi/providers/registry.py` | `prop3d/img2threejs` provider 条目(register_all_providers §6) |

## 门状态更新

- **G1 ✅**(camera_angle/azimuth + scene_contract,早前已开)
- **G2 ✅(道具路径)** / **G3 ✅(道具路径)**:Apache 2.0 + 代码重建,无 license/硬件障碍
- 角色 3D(图生3D 大模型)与场景重建(world model):仍观察项,等商用 provider/硬件路径成熟

## 消费模式

`3D 视角结构帧(scene_block_workflow)+ 2D 身份参考 → i2v`(身份由 2D 保证 0.77-0.84,
视角由 3D 保证)——HEVI-ARCH §5.7.0 共存模式 3 的运行时可接形态。
