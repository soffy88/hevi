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


# ── INC-002 单镜表演密度层:镜头内部时间轴 ──────────────────────────────────
# ShotListItem 此前是"静态镜头描述";performance_track 把它升级成"有内部时间轴的表演单元"。
# 与 action_beats(粗3段 trigger/peak/aftermath,服务选首/关/尾帧)是两级粒度:performance_track
# 是细粒度 N 段,服务"时序提示词"编译。未填 → 行为完全不变(inert,走 action_beats 老路)。
# 第一批只落 eyeline_track/emotional_state/body;facial_performance(第二批)、camera_curve
# (第三批)后续加,现留可选空位。


class EyelineTrack(BaseModel):
    """镜头内视线时序(INC-002 缺口①)——一个 PerformancePhase 内的视线状态。"""

    state: str = "locked"  # locked / breaking / averted / returning / closed
    direction: str = "center"  # center / down / down_left / down_right / up / left / right ...
    target_ref: str = ""  # 看向谁/什么;空 = 无目标/回避
    transition_speed: str = "slow"  # snap / quick / slow / trembling


class EmotionalStateCurve(BaseModel):
    """情绪状态(承接 v3.2 挂载树 emotional_state 维度)——本阶段的主情绪与强度。"""

    primary: str = ""  # 主情绪
    intensity: float = 0.0  # 0.0–1.0
    conflict_with: str = ""  # 内心交战的对立面;空 = 无


class PerformanceBody(BaseModel):
    """身体(即使"无夸张肢体"也要写清楚)。"""

    posture: str = ""
    tension: str = ""  # rigid / taut / trembling / slack / collapsing
    breath: str = ""  # held / shallow_rapid / ragged / deep / none


# ── INC-002 第二批:FacialPerformance(面部表演层,§3)—— 肌肉/生理/肌理三块 ──
# Hevi 从没有过的一层。全部可选、inert:未填 → 编译时降级为 emotional_state 的自然语言。


class MuscleAction(BaseModel):
    """解剖级肌肉动作(FACS 思路)。visible_result 必填(编译进 prompt 的就是它,模型认"眉头
    紧皱"不认"降眉肌");muscle 可选结构化标注(给 verdict 校验和未来 3D/ControlNet 精控用)。"""

    muscle: str = ""  # corrugator/masseter/orbicularis_oculi/levator/frontalis/mentalis/platysma
    action: str = ""  # contract / relax / twitch / tremor
    intensity: float = 0.0  # 0.0–1.0
    visible_result: str = ""  # 可观察结果,如"眉头痛苦紧皱""下颌线咬合紧绷"


class TearDetail(BaseModel):
    side: str = ""  # left / right / both
    path: str = ""  # 沿哪条轨迹
    gravity_compliant: bool = True  # 必须遵循重力与表面张力


class Pupil(BaseModel):
    dilation: float = 0.0  # 0.0–1.0
    movement: str = ""


class FacialPhysiology(BaseModel):
    """生理反应(时序性的)——泪/血管/瞳孔/眨眼/吞咽/唇/潮红。"""

    tear_state: str = "none"  # none / welling / film / brimming / falling / dried
    tear_detail: TearDetail = Field(default_factory=TearDetail)
    eye_vasculature: str = ""  # clear / faint / congested(充血泛红)
    pupil: Pupil = Field(default_factory=Pupil)
    blink: str = ""  # none / normal / rapid / forced_open / closing
    swallow: bool = False  # 是否吞咽(→ 喉结动作)
    swallow_difficulty: str = ""  # 如"艰难"
    lip_state: str = ""  # pressed / parting / trembling / slack
    skin_flush: str = ""  # none / cheeks / neck


class SkinTexture(BaseModel):
    """肌理(通常镜头级常量,但可随情绪变化)。"""

    quality: str = ""  # natural_imperfect(自然微瑕) / clean / weathered
    pores: str = ""  # visible / subtle / none
    blemishes: list[str] = Field(default_factory=list)  # 战损擦痕/灰尘/疤痕(带位置)
    lip_texture: str = ""  # 唇纹真实度/干燥度
    sweat: str = ""  # none / sheen / beads
    preserve_base_tone: bool = False  # "不掩盖原本的面部底色"


class FacialPerformance(BaseModel):
    """面部表演层(INC-002 §3):肌肉/生理/肌理三块。全部可选、inert。"""

    muscle_actions: list[MuscleAction] = Field(default_factory=list)
    physiology: FacialPhysiology = Field(default_factory=FacialPhysiology)
    skin_texture: SkinTexture = Field(default_factory=SkinTexture)


# ── INC-002 第三批:CameraCurve(运镜曲线,§4)—— 运镜是表演的一部分,不是死机位参数 ──


class HandheldCurve(BaseModel):
    """手持感(可随时间演化)——频率与幅度解耦(可频率高但幅度小)。"""

    enabled: bool = False
    frequency_start: float = 0.0  # 0.0–1.0 本阶段起始晃动频率
    frequency_end: float = 0.0  # 0.0–1.0 本阶段结束频率
    amplitude_start: float = 0.0
    amplitude_end: float = 0.0
    easing: str = "linear"  # linear / ease_in / ease_out / accelerate


class FocusCurve(BaseModel):
    """焦点(可锁死,可漂移)。"""

    lock_target: str = ""  # 锁在哪:"女子双眼"
    lock_strictness: str = "soft"  # absolute(100%死锁) / soft / rack(变焦点)
    depth_of_field: str = ""  # f-stop 或 shallow/medium/deep
    rack_to: str = ""  # 若 rack:焦点移向哪(+ 何时);absolute 时不得填(P2)


class CameraMovement(BaseModel):
    """推拉摇移(可选)。"""

    type: str = "static"  # static / push_in / pull_out / pan / tilt / follow
    speed_start: float = 0.0
    speed_end: float = 0.0
    easing: str = "linear"
    distance: str = ""


class CameraBreathing(BaseModel):
    """镜头呼吸感(与 handheld 区分:有机的微起伏)。sync_to=character_breath 是 Hevi 独有高级项。"""

    enabled: bool = False
    sync_to: str = "none"  # none / character_breath(与人物呼吸同步) / emotional_intensity


class CameraCurve(BaseModel):
    """运镜曲线(INC-002 §4)——晃动频率曲线/焦点锁死度/镜头呼吸。全部可选、inert。"""

    base_setup_ref: str = ""  # 引用 SceneStage.coverage_plan 的机位(静态骨架)
    handheld: HandheldCurve = Field(default_factory=HandheldCurve)
    focus: FocusCurve = Field(default_factory=FocusCurve)
    movement: CameraMovement = Field(default_factory=CameraMovement)
    breathing: CameraBreathing = Field(default_factory=CameraBreathing)


# ── INC-002 v0.2 第三批半:PropPerformance(道具表演,§4.5)——道具是第二条叙事线 ──


class PropGrip(BaseModel):
    hand: str = ""
    firmness: str = ""  # rigid / firm / loose / slack


class PropContactState(BaseModel):
    """接触状态机(按道具类型分组的枚举,见 §4.5 / performance_track._PROP_STATE_GRAPH)。"""

    state: str = (
        ""  # 枪械:guard/face/pressure_building/threshold/releasing/lifted/off;弓箭:nocked/…
    )
    transition_from: str = ""  # 上一状态(P7 校验转移合法)
    hold_reason: str = ""  # 停在此状态的动机("将扣未扣"的心理)


class MicroDisplacement(BaseModel):
    """亚毫米/毫米级位移(标尺"抬起不到一毫米")。"""

    axis: str = ""
    distance_mm: float = 0.0
    suspended: bool = False  # 是否悬停在该位移处


class ScreenCoord(BaseModel):
    """画面归一化坐标,0.5/0.5 = 正中。"""

    x: float = 0.5
    y: float = 0.5


class AimOffset(BaseModel):
    """指向偏移轨迹(画面坐标系,不是三维仿真)。start=起始指向,end=结束指向。"""

    start: ScreenCoord = Field(default_factory=ScreenCoord)
    end: ScreenCoord = Field(default_factory=ScreenCoord)
    magnitude_desc: str = ""  # 人可读("下垂约两寸")
    easing: str = "linear"


class PropTremor(BaseModel):
    """道具颤动(与 body.tension 咬合)。"""

    amplitude_mm: float = 0.0
    frequency: str = ""
    source: str = ""  # muscle_fatigue / emotional / recoil


class PropSurfaceResponse(BaseModel):
    material_highlight: str = ""  # 金属反光/张力变化/压痕深浅
    deformation_state: str = ""  # 形变(弓弦压脸的深坑变浅)


class PropFramePresence(BaseModel):
    position_desc: str = ""  # 在画面哪("下方三分之一处")
    moves_out_of_frame: bool = False


class PropPerformance(BaseModel):
    """道具表演(INC-002 §4.5)——状态机 + 亚毫米位移 + 画面偏移轨迹 + 颤动。与 facial_performance
    平级(单人特写里两条并列表演线)。全部可选、inert。prop_type/material 供 P7 状态图与声音/负面
    自动派生用。"""

    prop_ref: str = ""  # 引用 ③设计清单锁定的 prop 资产
    prop_type: str = ""  # firearm / bow / blade / …(决定 contact_state 合法转移图)
    material: str = ""  # metal / wood / …(声音派生用)
    grip: PropGrip = Field(default_factory=PropGrip)
    contact_state: PropContactState = Field(default_factory=PropContactState)
    micro_displacement: MicroDisplacement = Field(default_factory=MicroDisplacement)
    aim_offset: AimOffset = Field(default_factory=AimOffset)
    tremor: PropTremor = Field(default_factory=PropTremor)
    surface_response: PropSurfaceResponse = Field(default_factory=PropSurfaceResponse)
    frame_presence: PropFramePresence = Field(default_factory=PropFramePresence)


# ── INC-002 v0.2 第三批半:LightingResponse(光的响应,§4.7)——光源不变,遮挡随表演变 ──


class LightingOcclusion(BaseModel):
    cause: str = ""  # 什么造成的("头部低垂")
    affected_area: str = ""  # 受影响区域("面部"/"眼窝")
    shadow_delta: str = ""  # deepen / lighten / shift


class LightingKeyRatio(BaseModel):
    lit_side: str = ""  # 受光侧("右半脸+持枪手+枪身金属")
    shadow_side: str = ""  # 阴影侧("左半脸沉入深阴影")
    contrast_level: float = 0.0  # 0-1(硬光/伦勃朗通常 >0.8)


class LightingResponse(BaseModel):
    """光的响应(INC-002 §4.7)——光源仍是场级资产(source_ref 只引用),这里只描述"这一段光怎么落"。
    occlusion 可由 body.posture 变化自动派生(低头 → 面部 deepen)。未填 → 继承场级常量(inert)。"""

    source_ref: str = ""  # 引用 SceneStage.lighting 的光源(不新建)
    occlusion: LightingOcclusion = Field(default_factory=LightingOcclusion)
    key_ratio: LightingKeyRatio = Field(default_factory=LightingKeyRatio)
    specular_targets: list[str] = Field(default_factory=list)  # 高光落点
    pattern: str = ""  # rembrandt / split / rim / top / practical_bare_bulb


class PerformancePhase(BaseModel):
    """表演阶段——镜头内部时间轴的一段(INC-002 §2)。t_start_s/t_end_s 精确到秒的时间窗。"""

    phase_id: str = ""
    order: int = 0
    t_start_s: float = 0.0
    t_end_s: float = 0.0
    label: str = ""  # 人可读:"理智断裂与向下看的退缩"
    trigger: str = ""  # 本阶段由什么触发(内心/外部事件)
    eyeline_track: EyelineTrack = Field(default_factory=EyelineTrack)
    emotional_state: EmotionalStateCurve = Field(default_factory=EmotionalStateCurve)
    body: PerformanceBody = Field(default_factory=PerformanceBody)
    # INC-002 第二批:面部表演层(可选,inert)。未填 → 编译时降级为 emotional_state 自然语言。
    facial_performance: FacialPerformance | None = None
    # INC-002 第三批:运镜曲线(可选,inert)。
    camera_curve: CameraCurve | None = None
    # INC-002 v0.2 第三批半:道具表演(第二条叙事线,可多个)+ 光的响应。可选、inert。
    prop_performance: list[PropPerformance] = Field(default_factory=list)
    lighting_response: LightingResponse | None = None


class PerformanceTrack(BaseModel):
    """镜头内部时间轴(INC-002 §1.1)——N 段 PerformancePhase(不限 3 段)。"""

    total_duration_s: float = 0.0
    phases: list[PerformancePhase] = Field(default_factory=list)


# ── INC-002 第四批:PerformancePreset(表演预设库,§5.2)——情绪弧跨镜头/跨剧集复用 ──


class PerformancePreset(BaseModel):
    """表演预设(类比 StylePack):一次写好的情绪弧,可复用、可拉伸。**phases 的 t_start_s/t_end_s
    是相对比例(0.0–1.0)而非绝对秒**;scale_preset_to_duration 按 total_duration_s 拉伸成
    PerformanceTrack(见 performance_track.py)。这是散文标尺给不了的能力。"""

    preset_id: str = ""
    phases: list[PerformancePhase] = Field(default_factory=list)  # t 为 0–1 比例
    scalable_to_duration: bool = True


# ── INC-002 v0.2 第三批半:audio_track(声音时间轴,§4.6)+ NegativeConstraints(§5.5)──
# audio_track 与 performance_track 平级(声音时间边界不必与表演阶段对齐)。


class AudioSegment(BaseModel):
    """声音段。derived_sounds 后端从 physiology/prop 确定性派生;manual_sounds 人/LLM 补。"""

    t_start_s: float = 0.0
    t_end_s: float = 0.0
    derived_sounds: list[str] = Field(default_factory=list)  # 自动派生(§4.6.1)
    manual_sounds: list[str] = Field(default_factory=list)
    mix_note: str = ""  # 混音意图("极微弱"/"渐显")


class AudioAmbient(BaseModel):
    bed: str = ""  # 环境底噪("远处环境低鸣")
    evolution: str = "constant"  # constant / fade_in / fade_out / swell
    evolution_start_s: float = 0.0
    evolution_end_s: float = 0.0


class AudioTrack(BaseModel):
    """声音时间轴(INC-002 §4.6)——与 performance_track 平级。music/dialogue 空 = 无(标尺明确
    要求无配乐无台词)。segments 的时间边界不必与 performance phase 对齐。未填 → inert。"""

    music: str = ""  # "" = 无配乐
    dialogue: str = ""  # "" = 无台词
    segments: list[AudioSegment] = Field(default_factory=list)
    ambient: AudioAmbient = Field(default_factory=AudioAmbient)


class NegativeConstraints(BaseModel):
    """负面约束(INC-002 §5.5)——derived 由 schema 自动派生(零遗漏),manual 人工补。"""

    derived: list[str] = Field(default_factory=list)
    manual: list[str] = Field(default_factory=list)


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
    # INC-002 镜头内部时间轴(细粒度表演单元)。None/空 → 走 action_beats 老路,行为不变(inert)。
    performance_track: PerformanceTrack | None = None
    # INC-002 v0.2:声音时间轴(与 performance_track 平级)+ 手工负面约束(derived 编译时派生)。inert。
    audio_track: AudioTrack | None = None
    manual_negatives: list[str] = Field(default_factory=list)
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
