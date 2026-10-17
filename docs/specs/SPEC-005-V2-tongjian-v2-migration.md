# SPEC-005-V2 · 通鉴演绎段迁移至 V2 渲染栈 · 迁移设计

> 状态:设计草案 v0.1(soffy 已拍板架构方向,待评审后开工)。
> 前置:SPEC-005(通鉴管线,讲解段=batch1 已跑通)、SPEC-007(V2 cinematic 管线)、
> 王六郎 V2 打磨到顶(A/B2:14/14 / 画风 std 2.25 写实统一 / 4 defect / $17.2,见 STATUS)。
> 本文只定设计,不含代码。评审通过后先进桥接器,后退役老路。

---

## 0. 架构决策(soffy 拍板)

**不把 tongjian 特化注入 V2 的 ①立意/②剧本**——V2 的 `screenplay.py` 硬性要求"文言→白话 +
自由编造动作对白",是 source-fidelity 的反面;把 quote_id 溯源 + G2 史实门 + CG2.5 重造进 V2 =
浪费且危险(史实红线要重新验证,STATUS 🔒 Never)。

**方案 B(桥接)**:复用 tongjian 现成 L0-L2 前端产**演绎段剧本**(史实机制原样保留),桥接进
V2 渲染栈(produce_v2),拿全 V2 战果(写实统一 / 运镜多样 / L5 三级 / 审核预案 / 持久化)。

```
tongjian L0-L2(现成,零改)              桥接层(新建,本设计主体)        V2(现成 + 小改)
chapter_ir → event_unit → script  ─────►  Script/ShotList/CharacterBible  ─────► WorldBible(加历史directive)
(逐字抽取)  (演绎点切分)  (白话对白       →  SceneScriptSet/DesignList         produce_v2(multirole+装配)
             人确认)      +quote_id溯源                                        L5 三级验收
             + G0/G2/CG2.5/T1 史实门全跑                                       director_works 持久化
```

**口型(soffy 定)**:先不锁唇跑一集,但**列为明确观察项非默认结论**——历史正剧对白密度高,
"人在说话嘴不动"的违和可能比王六郎稀疏对白严重;跑完一集人眼判能不能忍,忍不了再补 avatar
分支(那时也知道值不值得为它牺牲部分 V2 战果)。**不现在预设。**

---

## 1. 桥接映射表(核心新代码)

新模块建议:`hevi/director/tongjian_v2_bridge.py`,函数 `build_v2_inputs_from_tongjian(...)`——
输入 tongjian 侧已过 G2/CG2.5 的 `Script`/`ShotList`/`CharacterBible` + `ChapterIR`(当 material),
输出 V2 侧 `SceneScriptSet` + `DesignList` + `WorldBible` + 演绎段的 material_text。反向参照现成的
`director/tongjian_render.py::build_tongjian_inputs`(V2→tongjian),照它反着写。

### 1.1 Script/ShotList(演绎段)→ SceneScriptSet

一个演绎段 = 若干 drama `ScriptLine` + 对应 `Shot`。V2 侧一个 `SceneScript`(scene_ref)含
若干 `SceneScriptSegment`。逐字段:

| tongjian 源 | → V2 目标 | 转换说明 |
|---|---|---|
| `Shot`(一镜) | `SceneScriptSegment`(一段) | 一镜一段 |
| `Shot.visual_prompt` + `ScriptLine.visual_hint` | `SceneScriptSegment.narrative_text` | 拼成"动作+摄像机一体"的连续描述 |
| `ScriptLine.text`(dialogue 行) | `dialogue[].text`(`SceneScriptDialogueLine`) | 白话台词逐字透传(已过史实门) |
| `ScriptLine.speaker` | `dialogue[].character_name` | |
| `ScriptLine.target` | `dialogue[].target_name` | **两侧都有 target/eyeline 概念,直接对上** |
| `ScriptLine.quote_id` / `dramatized` | `dialogue[].quote_id` / `dramatized`(**新增字段**) | **史实溯源必须保留**——见 §1.3 |
| `Shot.camera.movement` | `SceneScriptSegment.camera_movement` | 词表映射,见 §1.2 |
| `Shot.blocking`(角色:位置,朝向) | `narrative_text` 内联 + 供 V2 `extract_scene_stage_from_script` 抽 `SceneStage.blocking` | V2 从 scene_script 抽 stage,blocking 落文本即可被抽回 |
| `Shot.action_beats` | `SceneScriptSegment.beat_description` | 动作弧拍点 |
| `Shot.t_start_ms`/`t_end_ms` | `t_start_s`/`t_end_s`(÷1000) | 之后 V2 `enforce_dialogue_duration` 会再兜底延长 |
| `Shot.characters` | `SceneScript.characters_present` | character_id → name |
| `Shot.scene_id` | `SceneScript.scene_ref` / `location` | 场号 + 地点串 |
| `Shot.negative_prompt` | (V2 无逐段负面;并入 world_bible/location 负面) | 已知损失点,记录 |
| `ScriptLine.emotion` | 融入 `narrative_text` / `beat_description` | |

### 1.2 运镜词表映射(tongjian ShotCamera.movement → V2 camera_movement)

| tongjian | → V2 camera_movement | 备注 |
|---|---|---|
| `static` | `静态对话` | |
| `slow_push_in` | `定场推`(首现)/ `峰值轻推`(情绪点) | 按是否首镜/情绪峰值二选 |
| `slow_pull_out` | `横移` 或保留拉远 | V2 无拉远类,近似 |
| `pan_left`/`pan_right` | `横移` | |
| `tilt_up`/`tilt_down` | `摇向声源` 或 `横移` | |

映射后仍过 V2 的 `enforce_camera_budget`(全片配比 推近≤¼/静态≤½/≥3-4 种)+ 强运动×身份
互斥规则。**注意**:演绎段镜少(3-4 镜),配比约束几乎不触发,主要靠 tongjian 原始运镜标注。

### 1.3 史实溯源保留(关键,不能丢)

V2 `SceneScriptDialogueLine` 当前无 `quote_id`/`dramatized`。**新增两个可选字段**(纯审计透传,
不进生成 prompt):`quote_id: str | None`、`dramatized: bool = False`。理由:史实门在 tongjian L2
(桥接前)已跑,溯源已验证;但把 quote_id 带进 V2 + 落 director_works,保证"成片每句对白可反查
到 chapter_ir 哪条引语"的审计链不断。**这是唯一必须动 V2 schema 的地方**,cheap、可测(字段落地
三件套:此字段不进生成端,是审计标签,在 schema 注释里显式声明,由接线完整性门管住)。

### 1.4 CharacterBible → DesignList.characters

| tongjian `CharacterBibleEntry` | → V2 `DesignCharacter` | 说明 |
|---|---|---|
| `name` | `name` | |
| `appearance` | `appearance` + `wardrobe`(拆分或合并) | |
| `era_check` | 并入 `appearance` + 喂 canon 生成(§3) | 时代考据信号 |
| `voice_id` | `voice_id` | 直接透传 |
| `ref_image` | **不直接用**,走 V2 canon 重生成(§3) | 见 canon 方案 |

### 1.5 WorldBible = 新生成(不来自 tongjian)

tongjian 无 WorldBible 对应物。**用 V2 `generate_world_bible_draft` 新生成**,输入:
- `material_text` = 该演绎段的 `ChapterIR` 相关原文 + `EventUnit.source_text`(史料底本)
- `design_list` = §1.4 桥接出的
- **`visual_style` 扩展为 `domain="historical"`**(见 §2),注入历史正剧 directive

---

## 2. V2 侧小改(world_bible.py 线程扩展)

现状:V2 只有 `visual_style ∈ {realistic, inkwash}`,只到达 visual volume。历史正剧需要
**服饰/器物/建筑考据**到达角色卷 + 世界卷。改动:

1. `_STYLE_DIRECTIVE` 加第三档 `historical`(directive 内容见 §4)。
2. `generate_world_bible_draft` 的 `visual_style` 泛化为接受 `historical`;把历史 directive **也**
   线程到 `_CHARACTER_ENTRY_PROMPT`(服饰考据)+ `_WORLD_ENTRY_PROMPT`(建筑/器物/年代)——
   现在这两个只收 `concept.tone/style`,要加 directive slot。
3. canon 定妆照生成(`_lock_design_list_assets` 的 `_ART_DIRECTION`)也要收历史 directive,否则
   人物定妆照不考据(见 §3)。
4. 桥接旁路 V2 的 ①concept/②screenplay(tongjian 前端替代),但 `produce`/`director_works`
   路径复用——桥接产出的 SceneScriptSet 直接喂 `run_v2_produce`,work 落 director_works。

**这些是"扩展 visual_style 线程"而非新架构**,风险低。

---

## 3. canon 资产方案(通鉴独有问题:历史人物无真人照)

**结论:V2 现有机制已解决,无需新建取图路径。** `_lock_design_list_assets` 用
`qwen_image_generate`(qwen-image 文生图)从"角色名 + 描述"生成定妆照,seed 由角色名
sha256 派生(同名永远同脸,跨进程稳定)——王六郎的 canon 就是这么来的,**从来不需要真人照**。

通鉴落地:
- 桥接把 `CharacterBible.name/appearance/era_check` → `DesignCharacter.name/appearance/wardrobe`,
  V2 `_lock_design_list_assets` 照常生成 canon。
- **考据准确性靠两条**:①`era_check`(tongjian L5 已做的时代校验)进 appearance;②§2.3 让历史
  directive 到达定妆照 prompt(现在 `_ART_DIRECTION` 是通用美术方向,不考据)。
- 商鞅等具名历史人物:文生图按"战国秦国名相、深衣玄端、冠带"这类描述生成,seed 锁定,全集同脸。
  **不追求"长得像真商鞅"(无真容),追求"考据无误 + 全集一致"**——这与王六郎"同一 canon 全集
  一致"是同一保证,只是描述换成考据式。

**★ canon 先验已跑(2026-07-23,§7 步0,~$0.01)= PASS**:qwen-image 生成商鞅/秦孝公定妆照,
两版均**战国形制无误**(交领右衽 深衣/玄端、archaic 冠、粗麻质朴、黑玄端合秦尚水德),**无明清
穿帮**(无补服/顶戴/辫子),负面词压住奇幻甲/发光眼。产物 `output/tongjian_v2_canon_probe/`。
**两条落地经验(进桥接实现)**:①描述必须含时代形制词(战国深衣/玄端/交领右衽),桥接要把
`CharacterBible.era_check` 映成这类词,不能只给"战国人物";②历史定妆照负面词要加反年代穿帮
(明清官服/补服/顶戴/辫子/现代)——`_PORTRAIT_NEGATIVE` 现无这些,历史档要补。canon 风险从
"未知"降为"绿",不再是阻塞项。

---

## 4. 历史正剧 style_render_directive(soffy 选定:候选 B 史诗厚重)

30-50 字可执行渲染词,进 prompt 末行,替代王六郎的水墨/写实民间调:

> **史诗历史正剧摄影,自然天光与火把/烛火光源,厚重低饱和影调、暗部沉稳,端正稳定构图,写实
> 肤质须发与织物/青铜器质感,大景深纵深环境——全片统一写实电影,禁绘画/插画/现代感/浅景深糖水**

定调理由(soffy)：①火把/烛火光源写死——战国到唐宋大量夜戏/朝堂/军帐,自然光候选在这些场景
无光源可依,模型会自己发挥,写死可控性高;②"禁浅景深糖水"治王六郎那种偏抒情质感,正剧要庄重。

---

## 5. 退役清单与影响面

**退役的是"演绎段渲染路径",不是删模块**——`scene_render_avatar.py` 有 ~14 个 importer(多数
只引 `_resolve_vlm` 辅助,含 produce_v2/multirole_reference 自己),不能整删。

| 退役对象 | 影响面 | 处置 |
|---|---|---|
| `scene_render_avatar.build_frame_manifest_avatar`(happyhorse 数字人渲染) | 演绎段渲染 | 演绎段改走 produce_v2;**讲解段 batch1 仍用它?**——不,讲解段走 sdxl_local diagram,不碰 avatar。安全 |
| `scene_render.py` L6 `cloud_avatar` 分支 | tongjian 演绎渲染路由 | 演绎段不再进 L6,改进桥接→produce_v2 |
| `director/tongjian_render.py::render_director_episode` | director locked→tongjian avatar 桥 | 被新桥接器替代,退役 |
| `season_planner/tongjian_bridge.py::render_episode`(avatar 分支) | 季度批量 | 若季度线也迁 V2 需同步改;**本次范围只单集,季度线暂不动,记依赖** |
| `_resolve_vlm` 等辅助 | 被 produce_v2 等引用 | **保留**,不动 |
| L3 voiceover / L8 assemble | tongjian 装配 | 演绎段装配改用 produce_v2 内建装配(assembler);讲解+演绎跨形态装配(SPEC-005 batch3)是**新问题**——见 §7 |

**最大影响面**:讲解段(tongjian 原生 sdxl_local + diagram)与演绎段(迁 V2 produce_v2)现在是
**两套渲染栈**,最后要装配成一集(SPEC-005 §5 "两条路径一个装配")。跨栈装配的接缝/声线/时长
对齐是本迁移的**新集成点**,不在王六郎验证覆盖内,单列风险。

---

## 6. G-T1-V2 完整验收单(重写 SPEC-005 §5.3)

旧 G-T1 纯定性(8 条 ✓,无数值)。用王六郎三版数据补数值线,soffy 已定两处修正:

| # | 项 | 达标线 | 基准/来源 |
|---|---|---|---|
| 1 | **段数完成率** | 演绎段 ≥95%,目标 100% | 王六郎 A/Bv1 86%→A/B2 100%(②精简负面+③审核预案后可达) |
| 2 | **画风统一** | std ≤3.5(硬护栏)+ **目检写实正剧调性达标**(主判) | 王六郎 6.35(摆)→2.25(写实统一) |
| 3 | **L5 真缺陷** | **0 个史实类 / 0 个身份认错人类 defect(硬门);其他类型(运镜/对白时长)≤1** | soffy 修正:史实/认错人历史正剧不能忍,单列;三级规则已滤强运动 expected |
| 4 | **成本/集** | **≤$8/集** | soffy 修正:$1.2/镜含重掷均价,演绎段镜少单镜崩影响完成率大,留余量($6 偏乐观) |
| 5 | **版权** | T1 clean(全程无译本文字) | SPEC-005 继承,硬门 |
| 6 | **史实无穿帮** | **G2/CG2.5 clean + 无年代错误(马镫/纸/椅)——从 warning 升硬门** | SPEC-005 T3 继承 + 升级(正剧穿帮严重) |
| 7 | **对白溯源** | 每句 dialogue 有 quote_id 或 dramatized 标注(CG2.5)+ 白话不文绉绉 | tongjian 原生 |
| 8 | **声线区分** | narrator 与剧中人声线明显区分(T4 clean) | SPEC-005 继承 |
| 9 | **定妆照考据** | 历史人物定妆照人工过目无年代/形制错误 | 新增(§3 风险) |
| 10 | **能看完不尴尬** | **保留人眼终判**(最终裁判是人眼) | SPEC-005 继承 |
| 11 | **口型观察项** | 记录"对白密集段人在说话嘴不动"违和度,人眼判能否忍(非门,是决策输入) | soffy 定,§0 |

**G-T1-V2 不过,不做第二集**(继承 SPEC-005 line 248 硬停)。

### 6a. G-XSTACK 跨栈接缝门(soffy 定,§7 步3 中间门)

讲解段(sdxl_local diagram/静帧)与演绎段(produce_v2 写实电影)是两套渲染栈,§6 的画风 std 是
演绎段**内部**指标,管不了跨栈。此门专测两栈拼接处:

| 项 | 判据 |
|---|---|
| 分辨率/帧率 | 两栈输出必须归一到同一分辨率(720×1280)+ 同帧率(24fps),装配前统一转码 |
| 画风跳变 | 讲解段(图解/静帧)↔演绎段(写实电影)接缝处,人眼判画风落差是否出戏(讲解段本就图解式、
  演绎段写实,**天生有别不算 fail**;要判的是"落差是否突兀到破坏一集的整体感") |
| 色彩/影调 | 接缝两侧色温/影调不应硬跳(必要时演绎段色调向讲解段基调靠,或加转场缓冲) |
| 声线/时长 | narrator(讲解)↔剧中人(演绎)声线区分(T4);段间时长对齐无黑帧/爆音 |

**不过先解决(转码归一 / 转场缓冲 / 色调对齐 / 讲解段调性微调),别带进 G-T1-V2 全集。**

---

## 7. 实施顺序(soffy 评审:canon 先验、跨栈加门)

0. **★ canon 先验(第一步,零成本,几分钟)——soffy 定,前置到最前**:直接用 qwen-image 文生图
   生成商鞅等战国人物定妆照(几分钱),人眼判服饰形制是否考据(战国深衣/玄端 vs 穿帮成明清官服)。
   **不过就先解决(改 appearance 描述细度 / 历史 directive / 或换取图路径),再往下**——qwen-image
   战国先验准度未知,若生成出明清官服后面全白做,几分钟就能证伪,不放进验收单等人审。
1. **桥接器 + V2 schema 小改**:`tongjian_v2_bridge.py`(§1 映射)+ `SceneScriptDialogueLine`
   加 quote_id/dramatized + `_STYLE_DIRECTIVE` 加 historical + 线程到角色/世界/定妆照 prompt。全单测。
2. **单演绎段真跑**:选 SPEC-005 episode 1「商鞅立木」的一个演绎段(单人为主,B5 已证),
   桥接→produce_v2 出片,对 G-T1-V2 的段数/画风/L5/成本/口型逐条量。
3. **★ 跨栈接缝门(G-XSTACK,soffy 定新增中间门)**:讲解段(sdxl_local)一段 + 演绎段
   (produce_v2)一段**拼在一起**,专看接缝处画风/色彩/分辨率/帧率跳不跳——§6 的 std≤3.5 是演绎段
   **内部**护栏,管不了跨栈;两套栈画风/色彩/分辨率/帧率大概率对不上。**此门不过先解决,别等
   G-T1-V2 全集才发现。** 判据见 §6a。
4. **G-T1-V2 全集验收**:整集 5min,人眼终判 + 口型观察项结论。过则通鉴产线迁移成立。
5. 季度线(season_planner)/短剧线迁移:本次不做,记依赖。

---

## 8. 未决 / 风险清单

- **口型**:§0 观察项,跑完一集定。
- **跨栈装配**(§5/§7.3):王六郎未覆盖,最大新集成风险。
- **定妆照考据**(§3):qwen-image 战国服饰先验准度,真机验一版。
- **史实门升硬门**(§6.6):T3 从 warning 升 reject,可能挡下"事件级合理推测"——需保留
  `dramatized` + speculation_mark 的人确认逃生门,别把创作空间也焊死。
- **negative_prompt 逐段损失**(§1.1):tongjian Shot.negative_prompt 无 V2 逐段对应,并入
  world/location 负面,可能损失镜级精度,记录。
- **季度线依赖**(§5):season_planner 仍用老 avatar 路,迁移单集期间两路并存。
