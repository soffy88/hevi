# QNLR-EP0-CONF-001 · EP0 制作规格 ↔ Hevi 管线差距矩阵

**对照对象**：QNLR-EP0-SPEC-001 Draft v0.1 §2–§8 可执行需求
**管线快照**：`hevi/director/`(V2 director-pipeline)+ `hevi/tongjian/`(确定性讲解线 / avatar 通道),工作树 `feat/spec-001-shortdrama-backend` @ 2026-07-22
**红线**：本轮零真机成本;任何需 cloud 生成的验证项标「需试跑验证」并附成本量级,挂起等批准
**状态**：CC 交付,待 soffy/Wiki 核 → 出 SPEC v0.2

---

## 0. 必须先读:两条生产路分叉(贯穿全矩阵)

管线里有**两条并行编排器**,能力分布不对称,这决定了下面一半格子的读法:

| 路 | 入口 | 生成方式 | 现况 |
|---|---|---|---|
| **V2 director `/produce`**（当前默认，2026-07-21「V1→V2 原地升级」后） | `produce_v2.py:90 run_v2_produce` → `multirole_reference.py:232 generate_multirole_segment` | 云端 **reference-to-video**（happyhorse-1.1，2D canon 参考图 + 场景底板直接喂视频模型，无 init_image、无 composed keyframe） | 主 director 生产路 |
| **tongjian / shortdrama avatar 通道** | `tongjian_render.py:230 render_director_episode` → `scene_render_avatar.py:1218 build_frame_manifest_avatar` | **compose→img2img**（本地 SDXL）+ Subject3D 视图 + happyhorse 生成式口型 | 对 director route 标 deprecated（`director_pipeline.py:19-24`），但仍是**通鉴/短剧/season_planner 频道的活生产依赖**（`tongjian.py:396`、`shortdrama.py`、`tongjian_bridge.py:301`）——"动不得" |

**后果**：SPEC §6 把 compose→img2img / Subject3D / 多人口型当"已验证能力"直接调用——**三项确实存在，但全在 tongjian avatar 通道，当前 V2 主路一个都不走**。EP0 的冷开场/廷议要用这三项，必须先定通道路线：

- **选项 A**：EP0 走 tongjian avatar 通道（三项现成，但该通道对 director route 已 deprecated，等于逆着迁移方向用）。
- **选项 B**：EP0 走 V2，把三项移植进 V2 路（工作量 L，需新 SPEC）。

这是 §6/§5 一切"技术标记"格子的前置决策，**归 Wiki/soffy**，本文不代定。

---

## 1. 差距矩阵（§2–§8）

状态图例：**已就绪** / **部分**（存在但不完整或不在目标路）/ **缺失** / **不在管线内**（图版/剪辑期，本就不该 scope 到 Hevi）

### §2 Screenplay 节拍表

| 需求条目（引节号） | 管线现状（模块/文件指针） | 状态 | 量 | 归属 |
|---|---|---|---|---|
| 9 段节拍 + 段时长 | `pipeline_schemas.py` Screenplay/ScreenplayScene + SceneBeat.duration_hint；V2 段 `SceneScriptSegment.t_start_s/t_end_s`(:741) | 已就绪 | S | CC |
| 每段"形态"混排（AI演绎/图版/真人合成/真人入定格场/文物特写） | 无统一 per-段 modality 字段；tongjian `Segment.type=narration\|drama`(schemas.py:52) 只有二值；混排靠人工装配 | 部分 | M | 需新 SPEC（modality 枚举） |
| 每段"置信主调" | 见 §7（置信标签端到端缺口） | 缺失 | — | 见 §7 |
| §5 段内「周室崩溃地图动画（图版实现）」 | **纠正 SPEC 的图版分类**：地图动画在 tongjian 确定性线**是已就绪资产**（`map_state.py` + `map_anim.py`，G0-D 已过 Wiki 目检），非"不在管线内"。可直接复用 | 已就绪 | S | CC（复用 G0-D） |

### §3 Design List

| 需求条目 | 管线现状 | 状态 | 量 | 归属 |
|---|---|---|---|---|
| 6 具名角色身份表 | `design_list.py` DesignCharacter + Postgres `subjects` 注册表（`subjects/models.py:14-49`），同名跨集复用（`director_pipeline.py:384-399`） | 已就绪 | S | CC |
| 嬴政两态（227 王服 / 221 帝服冕旒） | 单 subject 可挂 `metadata.wardrobe_images`（`subjects.py:250` /wardrobe 上传），但**无"按镜选服制态"的选择器**——两套 dressing 状态目前只能建两个 subject 或人工切参考图 | 部分 | M | CC 实现（态选择器）/ 或人工 |
| 泛型角色（郎中/群臣/甲士） | design_list 支持具名；泛型群像靠 prompt + compose，无专门泛型注册 | 部分 | S | CC |
| 秦俑谱系视觉先验 | 纯 prompt 文本层，无结构化字段 | 已就绪（prompt 级） | S | 人工（写进 design prompt） |
| 道具（§3.2 全表） | DesignProp + subjects `kind=product`（`director_pipeline.py:470`），注册表复用 | 已就绪 | S | CC |
| 环境（大殿） | DesignScene + subjects `kind=scene`（空景板，`director_pipeline.py:402`） | 已就绪 | S | CC |
| Wiki 真人 + 全季固定 wardrobe | **真人摄取口已就绪**：`subjects.py` `/from-photo:120`、`/reference:147`、`/wardrobe:250`、`/voice:229`，真人照片走与 AI 角色同一 `subject_id` 管线，CLIP 身份锚（`subject_service.py:80-131`）。⚠**只有照片+语音口，无真人视频摄取口** | 已就绪（照片/语音） | S | CC |

### §4 SceneStage · 咸阳宫大殿

| 需求条目 | 管线现状 | 状态 | 量 | 归属 |
|---|---|---|---|---|
| 场坐标系（N–S 主轴 / 柱阵 E-W 各4） | SceneStage `space_map`（zones+landmarks，`pipeline_schemas.py:499-518`）为**自由文本 rel_position**，无柱位/罗盘结构；轴线 `SceneAxis.side_convention` 亦自由文本(:580) | 部分 | M | CC（结构化坐标）/ 人工 |
| **两套 dressing D1/D2（一场多态）** | **缺失**：SceneStage 按 `scene_ref` 一场一个（`pipeline_schemas.py:614-632`），无 color/crowd/state/variant/dressing 判别字段。D1/D2 只能建两个独立 SceneStage → 坐标系重复，非"共坐标多态" | 缺失 | M–L | 需新 SPEC（dressing 变体机制） |
| B1–B5 方位字段回填 §5 | **方位约定不是 B1–B5**，是 `CameraSetup.azimuth_deg`(0-359°,4锚点 0/90/180/270，`:602-604`)+ `InitialPosition.facing_deg`(:540)。见**附录 A**（Task C 映射） | 部分 | S | CC（见附录 A） |

### §5 Shot List

| 需求条目 | 管线现状 | 状态 | 量 | 归属 |
|---|---|---|---|---|
| 冷开场 13 + 廷议 8 + W3 shot 结构 | shot schema 齐（V1 `ShotListItem:447-486`；V2 `SceneScriptSegment:728-762`；tongjian `Shot:200-242`） | 已就绪 | S | CC |
| 每镜**时长** | 三套 schema 全带（`duration_s:467` / `t_start_s:741` / `t_start_ms:213`） | 已就绪 | S | CC |
| 每镜**方位** | director 有（azimuth_deg 经 `camera_setup_ref` 挂 SceneStage 层）；tongjian `ShotCamera` 只有 shot_size/movement、**无方位**（schema 自己标注 :259-262） | 部分 | S | CC（见附录 A） |
| 每镜**置信标签**（实录/推演/演绎） | **缺失**：三套 shot schema 均无三值 provenance 字段。邻近：`ScriptLine.dramatized`(二值)、`explainer_contract.VisualFact.evidence_tier` E0-E4(五值,`:87-95`) | 缺失 | S（加字段） | CC → 见 §7 |
| 每镜**技术标记**（lip/compose/3D） | **部分,全隐式**:lip 靠 `ShotFrame.clip_path`;compose 靠 `quality_tier=standard\|key`(tongjian `schemas.py:229`);3D 靠 `facing_deg/azimuth_deg` 几何 + `ref_image_views`。无显式布尔标 | 部分 | S | CC（加显式标）/ Wiki 定路线 |
| **Plan B**（S07 环柱失败→3 静帧快切） | **缺失**:schema 无预授权 fallback 策略字段;只有事后 `ShotFrame.degraded/degrade_reason`(:297) 记录退化已发生。3 静帧快切**不是**已有 shot 类型 | 缺失 | S–M | CC 实现 / 或剪辑期人工 |
| 多人 compose（S01/S02/S13/T01/T03/W） | compose→img2img 存在于 tongjian 通道（`scene_render_avatar._compose_layout_base:719`+`_edit_keyframe:920`）；**V2 主路不走**;且 INC-004 把最难多人"key"镜路由到云端 L4、绕开本地 compose | 部分 | 见 §0 | Wiki 定路线 |
| 口型 T02/T05/T07 | 见 §6 口型行 | 部分 | 见 §6 | Wiki/CC |

### §6 Generation 技术备注

| 需求条目 | 管线现状 | 状态 | 量 | 归属 |
|---|---|---|---|---|
| compose→img2img（"已验证路径"） | `scene_render_avatar.py:719/920`，本地 SDXL img2img。**仅 tongjian 通道**，V2 `/produce` 与 L4 升级路均绕开 | 部分（不在 V2 路） | 见 §0 | Wiki 定路线 |
| Subject3D 6 角色全建（多方位一致） | 真实可调用阶段：`subject3d_local.generate_subject3d:49`（TripoSR CPU，GLB + front/left/right/back 四视图）→ `subject_service.py:355` 缓存 `metadata.subject3d.views`。callers = deprecated V1 director 路(`director_pipeline.py:875`)+ 活的 shortdrama(`shortdrama.py:348`)。**V2 主路不引用**。⚠只 4 视图非 SPEC §8 的"8 方位";非正面视图 INC-003 实测**会削弱泛型脸身份**;TripoSR 自述"探路"级 | 部分 | 见 §0 + 试跑 | Wiki 定路线 |
| **多人口型落对说话者的脸**（G3 判据） | **部分,非真 per-face lip-sync**:`build_frame_manifest_avatar:1218` 用 `lead=speaker` 偏置(强制 speaker canon 排首、prompt 点名说话者、眼神朝受话者),happyhorse 生成式嘴动——**非 wav2lip/landmark 锁脸**。多人"key"镜路由 L4 **完全无口型**(只 mux 音频)。`gate_avatar_manifest:2120` **不验逐脸口型**(留待 ASR)。**G3"3 镜全部落对说话者的脸"当前无自动判据,只能偏置+人工目检** | 部分 | 见 §0 + 试跑 | Wiki 决策（判据）/ 可能新 SPEC |
| S07 高风险镜 Plan B | 见 §5 Plan B 行 | 缺失 | S–M | CC / 人工 |
| 生成顺序建议 | 编排层参数，非管线能力 | 已就绪 | S | 人工/CC 编排 |

### §7 置信标注 UI（soffy 预判的最大缺口——确认属实）

| 需求条目 | 管线现状 | 状态 | 量 | 归属 |
|---|---|---|---|---|
| **三级标签常驻角标**（打进画面） | **不在生产管线内,但技术已在 sandbox 跑通**。生产 assemble 只烧 SRT 字幕(`hevi/assembly/subtitle_burner.py:17`,固定 4 值样式)。**数据驱动角标合成**（PIL 画 PNG → ffmpeg overlay 时间门控）已在 `sandbox/g1a_assemble.py` 实现:`make_collation_note:207`(右上纸卡，文本取自 `DualAccountFact`)、`make_sub_png:144`(字幕+地名)、`make_year_overlays:175`。**未接进任何生产模块**。缺口 = ①shot schema 加 tier 字段（见 §5）②把 sandbox PNG-overlay 技法接进 `tongjian/assemble.py` / director assemble | 缺失（生产）；部分（sandbox 有原型） | ①S + ②M | **CC 实现**（核心交付） |
| 片头 12s 三色图例 | 纯图版/剪辑期 | 不在管线内 | — | 图版/人工 |

**这条正是 soffy 预判的"最大缺口且不只是元数据"——确认属实**:tier 从 schema 到画面角标全链未通,但 sandbox 已证明技法可行、成本低。是本轮**最值得 CC 落地**的一项(schema 字段 S + overlay 接线 M,零真机成本,可本地验证)。

### §8 A-QIN 资产包（跨集复用）

| 需求条目 | 管线现状 | 状态 | 量 | 归属 |
|---|---|---|---|---|
| CHAR 跨集复用（6 角色 + 3D 锚） | **注册表支撑、跨集**:subjects 表 + 同名/同类/同用户复用(`director_pipeline.py:384-399`)+ 确定性同名同脸种子(:410) | 已就绪 | S | CC |
| ENV 复用（大殿底版） | director 路注册表支撑(subjects `kind=scene`);tongjian `SceneAsset` 只 per-run 复用(`schemas.py:274`) | 部分 | S | CC |
| PROP 复用 | 注册表支撑(subjects `kind=product`),但 SceneStage 内按**名字**引用非 subject_id(`pipeline_schemas.py:507`) | 部分 | S | CC |
| **8 方位 × 2–3 景深底版** | Subject3D 只 4 视图（front/left/right/back），非 8 方位；景深无结构化档 | 部分 | 试跑 | 需试跑验证 / Wiki |
| 季度级正式资产目录（指纹/生命周期） | **vault Manifest pack** 存在(pack_id/semver/lifecycle/provenance，`vault/schemas.py:8-63`)——最接近正式跨集指纹目录,**但不在 director lock 路**(director 用 SubjectService)。⚠SPEC 说的"omodul 指纹"是**误名**:omodul 的 fingerprint 是 per-shot 身份分选片(`verdict/scorecard.py:240`)、非资产注册表 | 部分（另一子系统） | L | 需新 SPEC（打通 vault↔director lock） |
| 图版模板（置信 UI / 地图动画 / 考点卡 / 片头卡） | **地图动画在管线内**（tongjian，G0-D 已过，见 §2 纠正）；置信 UI 样式 / 考点卡 / 片头卡 = 图版/剪辑 | 混合 | — | 地图动画=CC 复用；余=不在管线内 |

---

## 2. 需试跑验证项（挂起，等 Wiki 批准另开一轮）

| 项 | 为何需试跑 | 后端 | 成本量级 |
|---|---|---|---|
| Subject3D 6 角色多方位身份保真 | TripoSR 非正面视图 INC-003 实测削弱泛型脸身份，需实拍确认嬴政/荆轲跨 10+ 镜可用 | 本地 TripoSR + 本地 SDXL img2img | **$0（纯本地）**，仅 CPU ~172s/角色 |
| 8 方位 × 2–3 景深大殿底版 | 4 视图能否插值/补足 8 方位需实拍 | 本地 | **$0（本地）** |
| 口型 T02/T05/T07 落脸准确度 | happyhorse 生成式嘴动 + speaker 偏置的真实命中率，无自动判据、只能实拍目检 | **云端 happyhorse**（真机付费） | **~$0.5–0.7/镜 × 3 ≈ $1.5–2.1**，挂起 |
| 多人 compose S01（人数最多镜）压力 | SPEC 定为管线压力测试首镜 | 视通道：tongjian=本地$0 / V2=云端付费 | 依 §0 路线定，云端路挂起 |

**注**:本地 Subject3D / compose→img2img 试跑其实**零真机成本**(本地 SDXL/TripoSR 免费),可在批准后先跑掉不花钱的一半;只有云端 reference-to-video / happyhorse 口型镜是真机付费,严格挂起。

---

## 3. 缺口→建议落点（不实现，按 3O 惯例标注）

| 缺口 | 建议落点 | 前置决策 |
|---|---|---|
| 置信 tier 端到端（§7） | ①shot schema 加 `provenance_tier: Literal[实录,推演,演绎]`；②新模块 `tier_overlay.py` 复用 `g1a_assemble` PNG-overlay 技法，接进生产 assemble | 无（可直接 CC 实现，$0） |
| 一场多 dressing（§4 D1/D2） | SceneStage 加 `dressing_state` 变体（共 space_map/axis，异 color/crowd/props） | 需新 SPEC |
| V2 移植 compose/Subject3D/口型（§0/§6） | 若选 V2 路：把 `build_frame_manifest_avatar` 三能力接进 `run_v2_produce` | **Wiki 定通道路线** |
| G3 口型自动判据 | 接 ASR/landmark 校验（`gate_avatar_manifest` 已留 TODO） | Wiki 决策（判据严格度） |
| 8 方位底版 | Subject3D 4→8 视图，或云端多视图补全 | 需试跑 + 可能新 SPEC |
| vault↔director lock 打通 | 季度级资产走 Manifest pack 而非 SubjectService | 需新 SPEC（季度级，EP0 不阻塞） |

**EP0 可用 workaround（不等季度级 SPEC）**:D1/D2 建两个 SceneStage；ENV/PROP 用 subjects 注册表按名复用;置信 tier CC 本轮直接落地。**季度级**(dressing 变体机制、vault 打通、8 方位)才需另立 SPEC。

---

## 附录 A · Task C 方位回填（§5 罗盘 → Hevi `azimuth_deg`）

### A.0 关键交底：Hevi 无"B1–B5"，用 `azimuth_deg`

SPEC §4 说的"B1–B5 方位驱动约定"在 Hevi 里**不存在离散槽位**。真正的约定（SPEC-004 v2）：

- `CameraSetup.azimuth_deg`（0-359° 整数，`pipeline_schemas.py:602`）= 机位方位角，锚点 **0=正面/观众席/master · 90=画右 · 180=背后 · 270=画左**。
- `InitialPosition.facing_deg`（同上，`:540`）= 角色朝向，同锚点。
- 二者几何算出该角色该用 Subject3D 哪个视图：`resolve_subject_view` 量化到最近 90° → `{front, right, back, left}`（`scene_stage.py:435`）。
- 字段**挂在 SceneStage 的 CameraSetup 上，不在 shot 本身**；shot 经 `camera_setup_ref` 引用。
- ⚠`azimuth_deg` 只编码 yaw（水平）；**低角/仰拍（pitch）、横移（运动）不可表达**。

### A.1 采用的世界罗盘→场景方位锚（需你确认）

咸阳宫大殿世界系:王座(N)/殿门(S)/柱阵(E-W)。设 **scene-0°（master/正面）= 殿门(S)侧、由 S 望 N（望向王座）**。则:

| 世界罗盘机位 | azimuth_deg |
|---|---|
| 殿门 / S 端（望 N） | **0**（=master） |
| 东柱列 / E 侧 | **90**（画右） |
| 王座 / N 端（望 S，反打） | **180**（背后） |
| 西柱列 / W 侧 | **270**（画左） |

**自洽校验**:SPEC 自己把 S01 明标为 master("S 端向 N,大全"),恰落 azimuth 0 = Hevi master——锚点内部自洽。**此锚待你点头,一句话即可锁。**

### A.2 §5.1 冷开场 S 系映射

| Shot | 原罗盘 | azimuth_deg | 判定 |
|---|---|---|---|
| S01 | S 端向 N，大全 | **0** | 清晰（=master） |
| S02 | E 侧，中近 | **90** | 清晰 |
| S03 | W 侧，近 | **270** | 清晰 |
| S04 | 王座侧 E，中 | **⚠歧义** | "王座侧"(N 象限) 与 "E 侧"(E) 冲突，机位在 NE 角；取整倾向 90（E 主导）或 45，**需你定** |
| S05 | 插入特写（卷末寒光） | **—(None)** | 不适用:道具微距插入，无场景机位（None→front 正确） |
| S06 | N 端低角，中 | **180**（+低角） | yaw=180 清晰；**低角=pitch，azimuth 不编码，丢失，标注** |
| S07 | 柱阵间横移，全 | **⚠不适用** | 横移=运动镜头跨角度,单一静态 yaw 表达不了；且 `camera_movement` 字段目前 lint-only 不进生成（STATUS 2026-07-20）。**此镜=S07 Plan B/P0 风险镜** |
| S08 | S 端殿外反打 | **⚠歧义** | 被摄=郎中(殿下 S 外);机位真在 S→0，但要"看向"S 外郎中则应偏 N→180;"反打"是镜头关系非绝对方位，**需你定** |
| S09 | E 侧，快切 | **90** | 清晰 |
| S10 | N 端，中 | **180** | 清晰（呼喊走画外音、快切均不涉方位） |
| S11 | W 侧，中 | **270** | 清晰 |
| S12 | 柱面特写（中铜柱） | **—(None)** | 不适用:道具特写插入 |
| S13 | 双人对角，中 | **⚠歧义** | "对角"=斜角双人镜，未指定哪个对角/象限，通常 3/4 角(~45 或 135)，**需你定哪侧** |

### A.3 §5.2 廷议 T 系 + W 系映射

**结构提示**:§5.2 的 T 表**无"机位/景别"列**（列=画面/置信/技术），故 T 系除画面文字暗示外**无罗盘可转**——azimuth 应在建 SceneStage 时按 blocking 逐 setup 生成，非从 shot 表回填。

| Shot | 原描述 | azimuth_deg | 判定 |
|---|---|---|---|
| T01 | D2 全景 establish | **0** | 按 establish=master 约定给 0（画面文字暗示，非机位列） |
| T02–T05, T08 | （无机位列） | **—** | T 表无机位；T04"全→中"=景别，T07"低角仰拍"=pitch，均无 yaw；建 SceneStage 时逐 setup 定 |
| W3 | 中轴回望帝座 | **0** | 中轴机位望 N（帝座）=master 方位，清晰 |
| W1 / W2 | 王绾侧 / 李斯侧 | **⚠歧义** | 依赖廷议 blocking:王绾/李斯各站轴线哪侧(E/W)未定;定了→90 或 270。**需先定 blocking** |

**歧义清单汇总（需你裁，不猜）**:S04、S07（运动，结构不可表达）、S08、S13、W1/W2（依赖 blocking）。清晰可直接回填:S01/02/03/06(标 pitch 丢失)/09/10/11、T01、W3；不适用（插入镜，None）:S05、S12。

> **✅ 已裁决（SPEC v0.2 · P1/E1–E5，2026-07-23）**：全部歧义清零——S04=270°、S08=180°(俯)、S13=45°、W1/W2=315°/45°(依 E3 廷议 blocking)；S07 结构化重构为 S07a/b/c(AZ 225°/270°/0°)、S10 拆 S10a/b(270°/225°)。逐镜裁决表见 SPEC v0.2 §5.4。
> **⚠ 约定交底**：SPEC §5.4 的 CAM_AZ 采「光轴指向」世界罗盘(0=北/90=东)，与本附录 A 的「机位方位角」(0=master/90=画右) 对 E/W 侧机位**相差约 180°**（S04：SPEC 光轴 270° ↔ 本附录机位 90°，同一台"东侧机位、光轴朝西"的相机）。落 Hevi `azimuth_deg` 前按 SPEC §5.4 交底换算，勿直接透传；0°/180° 两约定一致。
