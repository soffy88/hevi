"""SPEC-003 主线导演流水线的五级契约(Concept → Screenplay → DesignList → ShotList → 生成)。

见 docs/specs/SPEC-003-mainline-director-pipeline.md。这条链跟现有的"一句话 →
EpisodeRequest → 直接产集"(director.py::director_create_episode)并行存在,不替换它——
G1 阶段只新增,不删旧路径(见 spec §7 vs 本次实施的取舍记录)。

四级模型逐级递进,后一级引用前一级已锁定的产物:
  Concept(主题/基调/时长档)
    → Screenplay(白话分场剧本,叙述与对白已区分)
      → DesignList(场景/人物/道具三张清单,锁定后落成真实 Subject 资产)
        → ShotList(切镜头,每镜带台词行[谁说+说什么]+出场资产引用)

DesignList 锁定后每个 character/scene/prop 都有一个真实的 `subject_id`(见
hevi/api/routers/director_pipeline.py 的 design-list/lock 端点)——ShotList 里的
character_ids/scene_id/prop_ids 引用的就是这些 subject_id,不是清单里的临时序号。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ── ① 立意 Concept ───────────────────────────────────────────────────────


class Concept(BaseModel):
    theme: str = ""  # 主题
    tone: str = ""  # 基调(如"悬疑压抑""温情治愈")
    style: str = ""  # 风格倾向(如"电影感""国风水墨")
    target_audience: str = ""  # 目标观众
    duration_archetype: str = "1-5min"  # 时长档,复用主线既有的 short/1-5min/.../45min+
    quality_bar: str = ""  # 品质基准(如"标清快速出片" vs "精品慢工")


# ── ② 剧本 Screenplay(白话、分场、叙述与对白已区分)────────────────────────


class ScreenplayDialogueLine(BaseModel):
    """一句对白。character_name 是剧本阶段的人物名(自由文本,还没有 subject_id——
    到③设计清单锁定后才会有真正的 subject_id,见 ShotListDialogueLine)。"""

    character_name: str
    text: str  # 白话,不是文言/书面语
    # SPEC-004:对谁说(A 对 B 说 → target_name=B)。升到②剧本级,让"谁对谁说"成为场事实的
    # 一部分——③.5 SceneStage.sightlines 从此确定性派生(INC-001 §H 升格),④ShotList 保持一致。
    # 空 = 未指明受话对象(独白/对众)。
    target_name: str = ""


class ScreenplayScene(BaseModel):
    scene_no: int
    time: str = ""  # 时间(如"黄昏""三日后")
    location: str = ""  # 地点
    characters_present: list[str] = Field(default_factory=list)  # 人物名列表
    narration: str = ""  # 该场的叙述文字(非对白部分,白话)
    dialogue: list[ScreenplayDialogueLine] = Field(default_factory=list)
    event_summary: str = ""  # 该场事件概要


class Screenplay(BaseModel):
    scenes: list[ScreenplayScene] = Field(default_factory=list)


# ── ③ 设计清单 DesignList(场景/人物/道具三张待锁定清单)───────────────────


class DesignCharacter(BaseModel):
    name: str  # 对应 Screenplay 里的 character_name,用于关联
    appearance: str = ""  # 外貌
    wardrobe: str = ""  # 衣着
    hairstyle: str = ""  # 发型
    personality: str = ""  # 性格
    is_lead: bool = False  # 是否主角
    voice_hint: str = ""  # 声线倾向(如"低沉沙哑""清亮少年音"),供选声线参考
    # 锁定后回填,见 hevi/api/routers/director_pipeline.py 的 design-list/lock。
    subject_id: str | None = None
    voice_id: str | None = None  # CURATED_VOICES 键或 edge-tts 原生音色 ID


class DesignScene(BaseModel):
    name: str  # 对应 Screenplay 里的 location,用于关联
    environment: str = ""  # 环境描述
    lighting: str = ""  # 光照
    mood: str = ""  # 氛围
    is_primary: bool = False  # 是否主场景(反复出现)
    subject_id: str | None = None  # 锁定后回填


class DesignProp(BaseModel):
    name: str
    appearance: str = ""  # 外观
    subject_id: str | None = None  # 锁定后回填


class DesignList(BaseModel):
    characters: list[DesignCharacter] = Field(default_factory=list)
    scenes: list[DesignScene] = Field(default_factory=list)
    props: list[DesignProp] = Field(default_factory=list)


# ── ④ 分镜头剧本 ShotList(切镜头,台词行带 speaker,占位/走位,资产引用)──────


class ShotListDialogueLine(BaseModel):
    """分镜级台词行——治"只有旁白没对白"的关键字段。character_name 为空 = 旁白
    (走旁白声线);非空则是该角色的台词,按 DesignList 锁定的角色声线配音。"""

    character_name: str = ""  # 空 = 旁白;非空须能在 DesignList.characters 里按 name 找到
    text: str
    # INC-001 §H 对谁说:A 对 B 说话 → target_name=B。直接驱动 eyeline(说话者看向受话者),
    # 是 v3.2 eyeline 维度的数据源,不用另标注。空 = 未指明受话对象(独白/对众)。
    target_name: str = ""


class ShotBlocking(BaseModel):
    """占位/走位——这镜头里这个角色站哪、朝向哪(§2 ④ 的"占位"字段,机位驱动渲染用)。"""

    character_name: str
    position: str = ""  # 如"画面左侧""居中"
    facing: str = ""  # 如"面向镜头""侧对角色B"


class ShotListItem(BaseModel):
    shot_id: str
    scene_no: int  # 引用 Screenplay 的 scene_no
    shot_size: str = ""  # 景别:远/全/中/近/特写
    camera: str = ""  # 机位/摄法
    visual_prompt: str = ""  # 画面内容描述(生成用的视觉 prompt 主体)
    dialogue_lines: list[ShotListDialogueLine] = Field(default_factory=list)
    blocking: list[ShotBlocking] = Field(default_factory=list)
    # INC-001 §B 动作弧:一组有序动作拍点(字符串列表,不做结构化对象)。首帧抓 trigger、
    # (3point)关键帧抓 peak、尾帧抓 aftermath——喂 kf2v 的首尾帧因此构成有起承转合的运动,
    # 而不是一张图微微动一下。为空则退回按 visual_prompt 自然语言切片(现状行为不变)。
    action_beats: list[str] = Field(default_factory=list)
    character_names: list[str] = Field(default_factory=list)  # 本镜出场角色(剧本阶段名字)
    scene_name: str = ""  # 本镜所在场景(对应 DesignScene.name)
    prop_names: list[str] = Field(default_factory=list)
    duration_s: float = 5.0
    # SPEC-004 ③.5 场事实引用(阶段 3)——画面空间/落位/焦点从 SceneStage 确定性投影(桥接层),
    # 不再由本镜自由想象。v1 由 link_shots_to_scene_stage 按对白锚定的 beats 确定性填充
    # (非 LLM);None/空 = 未接场事实(向后兼容旧 work)。见 SPEC-004 §3.1。
    scene_stage_ref: int | None = None  # 引用哪个 SceneStage(= SceneStage.scene_ref = scene_no)
    beat_range: list[str] = Field(default_factory=list)  # 覆盖 SceneStage 的哪些 beat_id
    camera_setup_ref: str = ""  # coverage_plan 里的 setup_id(自带 axis_side/shot_size)
    attention_ref: str = ""  # 服务哪个 attention_beat(= at_beat,带出 focus_target/intensity)


class ShotList(BaseModel):
    shots: list[ShotListItem] = Field(default_factory=list)


# ── ③.5 场面调度 SceneStage(场事实,SPEC-004)──────────────────────────────
# 每场一个,插在 ③设计清单 与 ④分镜 之间。该场所有镜头从同一"场事实"切视角,而不是各自
# 想象空间(§0.3 根因)。v1 = 纯结构化 JSON + 从 zones 确定性派生的俯视示意(不做 3D,不让
# AI 自由画图,§7 单一真相源)。AI 出完整草案、人在 Construction-First 下攻击落位/注意力/机位后锁定。


class SceneZone(BaseModel):
    """空间关键区域(俯视示意用)。如 门口 / 沙发区 / 窗边 / 桌旁。"""

    zone_id: str
    name: str = ""
    rel_position: str = ""  # 相对位置,如"左上""画面中心"(供 layout_sketch 派生)


class SceneLandmark(BaseModel):
    """关键家具/道具落位(引用 DesignProp.name)。"""

    name: str
    zone_id: str = ""


class SceneSpaceMap(BaseModel):
    """空间图。layout_sketch 不存字段——需要时从 zones 确定性派生(§7 单一真相源)。"""

    zones: list[SceneZone] = Field(default_factory=list)
    landmarks: list[SceneLandmark] = Field(default_factory=list)


class SceneBeat(BaseModel):
    """节拍:整场戏的时间轴单元,一切按节拍组织。action_beats(镜头内动作弧)挂在其下。"""

    beat_id: str
    order: int = 0
    trigger: str = ""  # 本拍触发(某句台词/某个动作/某个进场)
    dialogue_ref: str = ""  # 关联④分镜台词行(speaker→target 文本或 line_id)
    duration_hint: float = 0.0


class InitialPosition(BaseModel):
    char_id: str  # 对应 DesignCharacter.name
    zone_id: str = ""
    facing: str = ""  # 朝向,自由文本(如"面向门口""侧对乙")——给人看/给 prompt
    posture: str = ""  # 姿态,如"站立""端坐"
    # SPEC-004 v2:角色朝向的**结构化场景方位角**(0-359°,0=场景"正前/朝镜头 master 侧")。
    # 与 CameraSetup.azimuth_deg 一起,几何算出这镜这角色该用 Subject3D 的哪个视图(front/left/
    # right/back)当 img2img 底图,让朝向真正落到画面(见 scene_stage.resolve_subject_view)。
    # None = 未定 → 退回正面(用 2D 真照,身份最强)。
    facing_deg: int | None = None


class BlockingMove(BaseModel):
    char_id: str
    at_beat: str = ""  # beat_id:谁在第几拍从哪移到哪
    from_zone: str = ""
    to_zone: str = ""
    action: str = ""


class Sightline(BaseModel):
    """视线关系。★直接从对白 speaker→target 派生(INC-001 §H 升格);无对白时刻由 AI 补
    (assumed=True),人审核。"""

    at_beat: str = ""
    char_id: str = ""
    looking_at: str = ""  # char_id / landmark / zone
    assumed: bool = False


class SceneBlocking(BaseModel):
    """人物落位与动线(核心之一)。"""

    initial_positions: list[InitialPosition] = Field(default_factory=list)
    moves: list[BlockingMove] = Field(default_factory=list)
    sightlines: list[Sightline] = Field(default_factory=list)


class AxisShift(BaseModel):
    at_beat: str = ""
    new_axis: list[str] = Field(default_factory=list)  # [char_a, char_b] 或 [char, landmark]
    reason: str = ""


class SceneAxis(BaseModel):
    """轴线(the line,180°规则基准)。人物大幅移动后可合法重建,但必须显式声明 axis_shift。"""

    primary_axis: list[str] = Field(default_factory=list)  # 通常是两主要角色连线
    axis_shifts: list[AxisShift] = Field(default_factory=list)
    side_convention: str = ""  # 约定正方向,如"甲恒在画左,乙恒在画右"


class AttentionBeat(BaseModel):
    """注意力节拍(核心之二,"该看谁"的答案)。"""

    at_beat: str = ""
    focus_target: str = ""  # 此刻观众该看谁/什么(char_id 或 prop_id)
    reason: str = ""  # speaking/reacting/key_action/about_to_speak/reveal/entrance
    transition: str = "cut"  # cut/pan/push/rack_focus/follow
    intensity: str = "primary"  # exclusive(独占虚化他人)/primary(主焦点保留环境)/shared(群像)


class CameraSetup(BaseModel):
    """覆盖机位。对着"已存在的调度事实"架,不是对着想象。"""

    setup_id: str
    position: str = ""  # 相对 space_map 的机位
    axis_side: str = ""  # ★必须声明:在 primary_axis 的哪一侧(如 left/right / A侧/B侧)
    shot_size: str = ""  # 默认景别
    serves_beats: list[str] = Field(default_factory=list)  # beat_id 列表
    subjects: list[str] = Field(default_factory=list)  # 主要拍谁(char_id)
    # SPEC-004 v2:机位在场景里的**结构化方位角**(0-359°,= 从被摄角色看向相机的方向)。
    # 与角色 facing_deg 一起几何算 Subject3D 视图。None = 未定 → 该镜各角色退回正面视图。
    azimuth_deg: int | None = None


class CoveragePlan(BaseModel):
    """机位方案(核心之三)。master=能看清全场地理的宽景;setups=覆盖机位。"""

    master: CameraSetup | None = None
    setups: list[CameraSetup] = Field(default_factory=list)


class SceneStage(BaseModel):
    """场事实。该场所有 ShotListItem 通过 scene_stage_ref/beat_range/camera_setup_ref/
    attention_ref 引用它,画面内容全部从它确定性推导(SPEC-004 §3)。"""

    scene_ref: int  # 引用 Screenplay.scene_no
    space_map: SceneSpaceMap = Field(default_factory=SceneSpaceMap)
    beats: list[SceneBeat] = Field(default_factory=list)
    blocking: SceneBlocking = Field(default_factory=SceneBlocking)
    axis: SceneAxis = Field(default_factory=SceneAxis)
    attention_script: list[AttentionBeat] = Field(default_factory=list)
    coverage_plan: CoveragePlan = Field(default_factory=CoveragePlan)
    assumed: bool = False  # 是否含 AI 假设字段(§2.1),人锁定前应攻击确认


class SceneStageSet(BaseModel):
    """一个 work 的场面调度集合——每场一个 SceneStage(scene_ref = Screenplay.scene_no)。
    作 ③.5 级的 draft/lock 端点 body 与内存存储(director_pipeline._WORKS["scene_stage"])。"""

    stages: list[SceneStage] = Field(default_factory=list)
