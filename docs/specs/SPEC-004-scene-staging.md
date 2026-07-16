# Hevi 场面调度层 · SPEC-004

> 状态:草案 v0.2(v0.1 定调 + CC 实施决策已并入 §9)
> 依赖:`SPEC-003 v0.2`(五级导演链)、`INC-001`(action_beats / target_name / 候选表机制)、`Hevi-完整设计-v3.2`
> 定调:**电影级的最小创作单元是"场(Scene)",不是"镜头(Shot)"。此前所有 spec 都建在 Shot 粒度上——这是叠了六份规格、出片仍"啥也不是"的结构性根因。本 spec 在 ③设计清单 与 ④分镜 之间插入 ③.5 场面调度层,让每场戏先"立起来",所有镜头从同一个"场事实"切视角,而不是各自想象空间。**
> 实证依据:真实电影工艺(Master Scene 方法 / blocking 排练落位 / Iñárritu 式注意力预谋 / 180° 轴线与覆盖规则)。

---

## 0. 根因:为什么六份 spec 之后还是"啥也不是"

### 0.1 症状回放

用户对标的效果:**"人物众多,有场景,该把谁显到前面,镜头就转过来,多自然。"**
我们的产出:人一多就乱、空间前后矛盾、观众不知道该看谁、镜头之间像不相干的抽卡。

### 0.2 三个"没有"

| 真实电影有 | Hevi 没有 | 后果 |
|---|---|---|
| **场面调度(blocking)**:排练时定死每一刻谁在哪、朝向哪、何时移动;机位是对着"已存在的调度事实"架的 | 每个镜头在自己的 prompt 里**重新想象一遍空间** | 人一多,各镜头想象出的空间互相矛盾 → 乱 |
| **注意力引导**:导演预谋"这一刻观众看谁",整场调度为"镜头在此刻落到她"服务(Iñárritu/Birdman 手法) | 没有"该看谁"这个概念,注意力靠观众自己找 | 画面平均铺陈,没有焦点,"不知道在看什么" |
| **同一次表演的多视角覆盖**:正打反打拍的是**同一个时空**的两个视角 | 正打反打是**两次独立生成**,不共享任何事实 | 镜头之间没有"同一场戏"的连贯感 |

### 0.3 一句话病理

**我们把所有火力打在了单镜头质量上,而电影感住在镜头关系里。镜头关系的载体是"场",而我们的架构里没有"场"这个实体——剧本直接跳到分镜,中间缺了"把这场戏立起来"的那一层。**

---

## 1. 方案总览:五级链 → 六级链

```
① 立意 → ② 剧本 → ③ 设计清单 → ③.5 场面调度(本 spec 新增) → ④ 分镜 → ⑤ 生成
                                      │
                                      ▼
                              SceneStage(场事实)
                              该场所有镜头共享引用
                              ④分镜从"发明画面"降级为"从场事实切视角"
```

**核心转变一句话:** 镜头不再各自描述"画面是什么",而是声明"我是 SceneStage 的第几拍、从哪个机位看"——画面内容(谁在前景/谁看着谁/朝向哪边)**全部从场事实推导**,镜头间天然一致,因为它们本来就是同一个场的不同视角。这是 Master Scene 方法的数字版。

**readiness 联动:** ③.5 是 ④ 的硬前置——SceneStage 未锁定,该场的分镜禁止生成(沿用五级锁定状态机,INC-001 §A 的 pending/ready 语义)。

---

## 2. SceneStage 数据结构(场事实)

每场一个,由 AI 生成草案、人在 Construction-First 范式(SPEC-003 §2.0)下攻击修正后锁定。

```
SceneStage
├── scene_ref                     # 引用②剧本的场号
├── design_refs                   # 引用③设计清单锁定的场景/角色/道具资产
│
├── space_map                     # 空间图(v1 起步:2D 俯视示意,不需要 3D)
│   ├── layout_sketch             # 粗略俯视图(★v0.2 修订:从 zones 确定性派生 ASCII/SVG,AI 不自由画)
│   ├── zones[]                   # 关键区域:{zone_id, name, 相对位置}
│   │                             #   如:门口 / 沙发区 / 窗边 / 桌子
│   └── landmarks[]               # 关键家具/道具的落位(引用 prop 资产)
│
├── beats[]                       # ★ 节拍序列:整场戏的时间轴,一切按节拍组织
│   └── Beat
│       ├── beat_id / order
│       ├── trigger               # 本拍由什么触发(某句台词/某个动作/某个进场)
│       ├── dialogue_ref          # 关联④分镜台词行(speaker → target)
│       └── duration_hint
│
├── blocking                      # ★ 人物落位与动线(核心之一)
│   ├── initial_positions[]      # {char_id, zone_id, facing(朝向), posture}
│   ├── moves[]                   # {char_id, at_beat, from_zone, to_zone, 动作描述}
│   │                             #   "谁在第几拍从哪移到哪"
│   └── sightlines[]              # 视线关系:{at_beat, char_id, looking_at}
│                                 #   ★ 直接从对白的 speaker→target 派生(INC-001 §H)
│                                 #   无对白时刻由 AI 按剧情补充,人审核
│
├── axis                          # ★ 轴线(the line,180°规则的基准)
│   ├── primary_axis              # 本场主轴:通常是两个主要角色的连线
│   │                             #   {char_a, char_b} 或 {char, landmark}
│   ├── axis_shifts[]             # 轴线转移点:{at_beat, new_axis, 转移理由}
│   │                             #   (人物大幅移动后轴线可合法重建,但必须显式声明)
│   └── side_convention           # 约定正方向(如:甲恒在画左,乙恒在画右)
│
├── attention_script[]            # ★★ 注意力脚本(核心之二,"该看谁"的答案)
│   └── AttentionBeat
│       ├── at_beat
│       ├── focus_target          # 此刻观众该看谁/什么(char_id 或 prop_id)
│       ├── reason                # 为什么:speaking / reacting / key_action /
│       │                         #   about_to_speak / reveal / entrance
│       ├── transition            # 焦点如何转移过来:cut(切) / pan(摇) /
│       │                         #   push(推) / rack_focus(变焦点) / follow(跟)
│       └── intensity             # 焦点强度:exclusive(独占,虚化他人)/
│                                 #   primary(主焦点但保留环境)/ shared(群像)
│
└── coverage_plan                 # ★ 机位方案(核心之三)
    ├── master                    # master 视角:一个能看清全场地理的宽景机位
    │   └── {position, 覆盖范围, 朝向}
    └── setups[]                  # 覆盖机位
        └── CameraSetup
            ├── setup_id
            ├── position          # 机位(相对 space_map 的位置)
            ├── axis_side         # ★ 必须声明:在 primary_axis 的哪一侧
            ├── shot_size         # 默认景别
            ├── serves_beats[]    # 服务哪些注意力节拍
            └── subjects[]        # 主要拍谁
```

### 2.1 生成与审核流程(AI 导演,人监制)

```
输入:锁定的 ②Screenplay(该场) + ③DesignList(该场资产)
AI 生成:完整 SceneStage 草案(空间图 + 落位 + 节拍 + 轴线 + 注意力脚本 + 机位)
         —— 完整可锁定,不是半成品;假设字段标 assumed:true
人攻击:改落位("乙应该在窗边不是门口")/ 改注意力("第7拍焦点该在丙")/ 改机位
锁定:SceneStage locked → 放行该场 ④分镜
```

---

## 3. ④分镜的改造:从"发明画面"到"从场事实切视角"

### 3.1 ShotListItem 的字段变化

在 SPEC-003 v0.2 + INC-001 的基础上,**新增引用、改数据来源:**

> ★v0.2 措辞修正(据现役代码核实):此前 v0.1 说"删除自由字段"是不准的。核实结论——
> `blocking` 是现役唯一的真字段,且**下游零消费**(死写字段);`eyeline` 由 `target_name` 在
> 渲染时推导;`screen_direction / 前景 / 焦点 / 画面空间描述` 在现役代码里**根本不存在**。
> 所以本节不是"拆现役逻辑",而是"**这些字段的数据来源从(LLM 自由产 / 不存在)改为从
> SceneStage 确定性物化**"。

```
ShotListItem(v0.3,场事实驱动版)
├── scene_stage_ref              # ★ 新增:引用哪个 SceneStage(硬前置)
├── beat_range                   # ★ 新增:覆盖场事实的第几拍到第几拍
├── camera_setup_ref             # ★ 新增:用 coverage_plan 里的哪个机位
│                                #   (机位自带 axis_side / shot_size 默认值)
├── attention_ref                # ★ 新增:服务哪个注意力节拍(自动带出 focus_target)
│
├── dialogue_lines[]             # 保留(speaker + target,INC-001 §H)
├── action_beats                 # 保留(trigger/peak/aftermath,INC-001 §B)
├── vfx / music / sfx            # 保留
│
└── ✂ 改数据来源(不再由镜头 LLM 自由产,全部从 SceneStage 确定性物化):
      blocking        ← SceneStage.blocking 在 beat_range 内的切片(现为死写字段,安全接管)
      eyeline         ← SceneStage.sightlines 在该拍的值(现由 target_name 推导)
      screen_direction← camera_setup.axis_side + SceneStage.side_convention 推导(新增)
      前景/焦点        ← attention_ref.focus_target + intensity(新增)
```

### 3.2 prompt 编译的变化(★v0.2 决策:注入桥接层,不经 LLM)

INC-001 的两层提示词(基础/渲染)保留。**空间与人物部分改为"从场事实确定性编译",禁止模型自由想象**:

> ★v0.2 决策(DP1):空间事实是已锁定的结构化数据,拼 prompt 是确定性字符串工程,**不该经
> LLM 手**——让 LLM"根据场事实写画面"等于给它重新想象的机会,那正是要消灭的东西。
> **切分线:LLM 只判断"哪几拍 + 选哪个机位"(导演判断);"这机位这一拍看到什么"由确定性
> 代码投影(计算)。** 注入点选**桥接层 `hevi/director/tongjian_render.py`**(已经是确定性、
> 无 LLM),不改 `shot_list.py` 的 LLM 切镜 prompt。`_local_kf_prompt` 的 parts 扩成
> **「风格 + 空间(场景+落位+焦点)+ 相貌 + 情绪 + 动作」**,空间项靠前,符合 INC-001 §F.1 口径。

```
基础提示词编译输入(该镜头,确定性投影):
  = SceneStage 在 beat_range 的空间切片(谁在哪/朝向/正在做什么动作)
  + camera_setup(从哪看/什么景别/轴线哪侧)
  + attention(焦点是谁/焦点强度/其他人如何处理:虚化/背景/入画边缘)
  + 已锁资产描述(③设计清单,含 DesignScene.environment/lighting/mood —— 见 §9 断链#3)
  + action_beats 的当前阶段(INC-001 §B)
  + 风格链(项目级 visual_style,INC-001 §F.4)
```

**"该把谁显到前面镜头就转过来"的实现路径:**

```
attention_script: 第7拍 focus_target=丙, reason=about_to_speak, transition=push
→ 分镜层派生:一个从当前焦点缓推向丙的镜头(或切到丙的反应特写)
→ prompt 编译:丙进前景/浅景深虚化他人(intensity=exclusive)
              其余角色按 SceneStage 落位置于中后景
→ 观众的目光被注意力脚本牵着走,不是碰运气
```

---

## 4. 确定性守护(四条 lint,零模型成本)

全部是免费的规则检查,加进④分镜的生成后 lint:

| # | 规则 | 检查内容 | 拦截什么 |
|---|---|---|---|
| L1 | **跳轴检查** | 相邻镜头的 camera_setup.axis_side 不得不同侧,除非该拍存在已声明的 axis_shift | 越轴穿帮(观众瞬间迷失方位) |
| L2 | **反打差异** | 对话反打的相邻两镜,shot_size 差 ≥ 2 档 | 镜像感跳切的怪异感 |
| L3 | **eyeline 一致** | 镜头内角色视线方向,必须与 SceneStage.sightlines 在该拍的 looking_at 方向一致(结合机位侧推导画面左右) | A 明明在跟 B 说话却看向反方向 |
| L4 | **剪辑冗余** | 每个 beat 至少被 2 个 camera_setup 覆盖 | 装配时无剪辑余地,一条废全废 |

---

## 5. 与既有机制的咬合(不推翻,是喂给)

| 既有机制 | 关系 |
|---|---|
| INC-001 §H `target_name` | **升格**:从"对白字段"升为 SceneStage.sightlines 的主要派生源 |
| INC-001 §B `action_beats` | 保留,与 SceneStage.beats 对齐:action_beats 是镜头内动作弧,beats 是场级时间轴,前者挂在后者之下 |
| INC-001 §J 相邻镜头上下文 | **简化**:相邻镜头共享同一 SceneStage 后,"承接上一镜"从 prompt 提示变成结构保证;J 的编译建议保留作软化剂 |
| v3.2 观察态机制 | 保留且更准:实际末帧观察到的人物位置,回写的是 **SceneStage 坐标系里的位置**(而非自由文本),偏差可量化 |
| v3.2 挂载树 eyeline/screen_direction | **数据来源变更**:不再由分镜手填,从 SceneStage 推导;verdict 校验基准也指向 SceneStage |
| 五级 readiness(INC-001 §A) | 插入一级:SceneStage 未 locked → 该场所有 shot 保持 pending(★v0.2:走 `_STAGES` 状态机,`locked_through < scene_stage` 即拒,零成本) |
| Construction-First(SPEC-003 §2.0) | ③.5 的审核完全走此范式:AI 出完整场调度草案,人攻击落位/注意力/机位 |

---

## 6. 渐进实施(三段,先证明再铺开)

### v1 — 场事实存在即胜利(两周级)

- SceneStage = 结构化 JSON + 一张粗略俯视示意图(★v0.2:从 zones 确定性派生,AI 不自由画)
- **不需要 3D 引擎、不需要 previz 渲染**
- ④分镜接 scene_stage_ref / beat_range / camera_setup_ref / attention_ref 四个引用字段
- prompt 编译改为从场事实推导空间与人物部分(桥接层,确定性)
- 四条 lint(L1–L4)上线
- **验收门 G-S1(垂直切片):一场 3 人对话戏,1 个 SceneStage + 6 个镜头全部从它派生。**
  - 对照组:同一场戏走现有管线(★v0.2:基线 = 修完断链#3 后的版本,见 §9)
  - 达标线:实验组 6 镜头间无空间矛盾(人物相对位置/朝向一致)、无跳轴、
    eyeline 与对白 target 一致、注意力焦点可辨识
  - ★v0.2 客观化:"注意力焦点可辨识"用 Tier1 VLM 抽帧断言 focus_target 角色在画面里
    占主体/在前景/未被虚化,不靠肉眼
  - **G-S1 不过,不做 v2** —— 先证明"场事实"确实消灭空间矛盾,再铺开

### v2 — 注意力驱动派生

- 从 attention_script 反推镜头序列(半自动分镜:AI 按注意力节拍提议机位切换,人审)
- transition 类型(cut/pan/push/rack_focus/follow)编译进运镜 prompt
- 观察态机制接入 SceneStage 坐标系(末帧位置回写,偏差量化)

### v3 — 3D 预演(远期,依赖 Subject3D 场景资产成熟)

- SceneStage.space_map 从 2D 示意升级为真 3D 场景(scene 类 Subject3D)
- 机位从"示意位置"升级为可渲染的相机参数 → 身份帧/场景帧按真实机位投影
- 此时 lingbot-world 观察哨(v3.1 附录)才真正触发评估

---

## 7. 明确不做

- **不做 3D previz 起步**:v1 就是 JSON + 俯视示意图。3D 是 v3 的事,先让"场事实"这个概念存在。
- **不给单镜头保留"自由空间描述"后门**:凡引用了 SceneStage 的镜头,空间/人物/视线一律推导,不许 prompt 里另写一套(否则场事实形同虚设)。
- **俯视图单一真相源**(★v0.2):layout_sketch 从 zones 确定性派生,AI 不自由画图——空间事实只能有一个真相源,否则又多一层"想象"。
- **不追求全自动调度**:blocking 和注意力脚本是导演判断,AI 出草案、人必须攻击确认——这恰是"AI 导演、人监制"里人最该把守的一级。
- **v1 人审 UI 不做图形化拖拽台**(★v0.2 DP2):v1 = 卡片 + 就地编辑 + 俯视图预览,复用 ShortdramaCreatePanel 向导模式;图形化拖拽调度台留 v2/v3。
- **不承诺解决单镜头画质**:Scene 层解决的是空间与注意力的一致(自然感的七成),单镜画质/动作物理仍受生成模型与 Conservation Law 约束(那三成走 INC-001 的 B/C)。

---

## 8. 一页速览

```
病根:电影级的最小创作单元是"场",不是"镜头"。
      此前六份 spec 全建在 Shot 粒度上 —— 地基粒度错了。

真实工艺:先把戏"立起来"(blocking)→ 机位对着已存在的调度事实架(coverage)
          → 该看谁是预谋的(注意力),不是碰运气的

方案:③设计清单 与 ④分镜 之间插入 ③.5 场面调度层
      SceneStage(场事实)= 空间图 + 落位动线 + 节拍 + 轴线 + 注意力脚本 + 机位方案
      每场一个,该场所有镜头共享引用

核心转变:④分镜从"发明画面"降级为"从场事实切视角"
          镜头声明:我是第几拍 + 从哪个机位看 → 画面内容全部确定性投影
          镜头间天然一致,因为本来就是同一个场的不同视角

"该把谁显到前面镜头就转过来" = attention_script 驱动:
      第N拍 focus=丙(即将开口)→ push 推向丙 → 丙进前景虚化他人
      观众目光被注意力脚本牵着走

四条免费 lint:跳轴 / 反打差异 / eyeline一致 / 剪辑冗余
渐进:v1 JSON+俯视图(两周)→ v2 注意力驱动派生 → v3 真3D预演
验收:一场3人戏垂直切片,6镜头同源一个场事实,无空间矛盾才铺开

口诀:先立场,再架机;镜头是场的视角,不是独立的画。
```

---

## 9. CC 实施决策(v0.2,soffy 2026-07-16 拍板)

基于对现役 director 管线的只读测绘(见测绘结论散见 §3.1/§3.2/§5),定下以下实施决策:

**DP1 — prompt 空间编译注入点 = 桥接层 `tongjian_render.py`。**
LLM 只判断"哪几拍 + 选哪个机位"(导演判断);"这机位这一拍看到什么"由确定性代码投影。
`_local_kf_prompt` 的 parts 扩成「风格 + 空间(场景+落位+焦点)+ 相貌 + 情绪 + 动作」,空间项靠前。

**DP2 — v1 人审 UI = 卡片 + 就地编辑 + 俯视图预览。**
走 Construction-First(AI 出完整草案,人攻击),复用 `ShortdramaCreatePanel` 向导模式。不做图形化拖拽调度台(留 v2/v3)。

**§7 修订采纳** — 俯视图从 zones 确定性派生,不让 AI 自由画图。

### 实施阶段(以 STATUS.md 为准做跨会话追踪)

- **阶段 0** — 本 spec 落库 + STATUS 记 In Progress。
- **★阶段 0.5(先做,单独跑对照,半天)— 修断链#3。**
  现役核实发现:`DesignScene.environment/lighting/mood` 在 draft 里被填,但从桥接层
  `tongjian_render.py` → L6 `scene_render_avatar.py` **全程没有任何一处 prompt 消费它**——
  场景空间描述整条断链。修法:`render_director_episode` 从 `design_list.scenes` 建
  `scene_desc_by_id`(name→"环境,光照,氛围")经 `config.params` 传入 →
  `build_frame_manifest_avatar` 按 `shot.scene_id` 取切片 → `_local_kf_prompt` 加 `scene_space`
  参数(parts 空间靠前)。全部向后兼容(tongjian 管线不设该 param 即无变化)。
  **为什么独立成阶段**:(a) 一次只改一个变量(INC-001 纪律);(b) 它是 SceneStage 的链路
  前置——链不通,场事实同样喂不进;(c) G-S1 的对照基线**必须**是"修完断链后的版本",
  否则测的是"断链修复 + 场事实"的混合增益,测不出 SceneStage 的净增益。
- **阶段 1** — SceneStage schema(pipeline_schemas.py)+ AI 草案生成(hevi/director/scene_stage.py,
  镜像 design_list.py draft 模式,qwen_cloud + 确定性兜底);sightlines 从 speaker→target 派生。
- **阶段 2** — 状态机接一级:`_STAGES` 插 `"scene_stage"` + draft/lock 端点(镜像 design-list 后台模式)。
- **阶段 3** — ShotListItem 接 4 引用字段 + 桥接层确定性投影(DP1)。**v1 实施取舍(2026-07-16)**:
  用**确定性链接**(`link_shots_to_scene_stage`)而非重写已部署的 shot_list LLM prompt——SceneStage
  的 beats 是对白锚定的(trigger=对白文本),镜头覆盖哪几拍可由"匹配镜头对白行→beats"精确派生
  (比 LLM 选更准、无幻觉),camera_setup 按 serves_beats/subjects 重叠择优。DP1 原设想"LLM 判断
  哪几拍+机位"改为确定性派生,作 v1 简化(降风险、不碰已部署生成逻辑),LLM-choice 留 v2。
  投影 `project_shot_space` = 落位/朝向 + 焦点(带 intensity 虚化处理)+ 画面正方向,经
  `shot_space_by_id` 逐镜穿进渲染层,与断链#3 的 scene_desc 一起拼进关键帧 prompt 空间项。
- **阶段 4** — 四条 lint(hevi/director/scene_stage_lint.py)。
- **阶段 5** — G-S1 验收脚本(scripts/gs1_scene_stage_run.py,镜像 g1_shortdrama_run.py)+ VLM 客观化断言。

---

*SPEC-004 v0.2。CC 从 阶段 0.5(断链#3)开始,一次一个变量。*
