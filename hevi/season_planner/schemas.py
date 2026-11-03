"""剧集规划器输出契约 SeasonPlan —— 见 SPEC-001 §3.3。

把一部小说的 StoryGraph 切成 N 集,每集分配节拍/角色/场景/情感目标。season 绑定一个
Series(season = series),下游逐集交给现有 Director 生成分镜。

设计沿革:剧集规划器是**新的规划层**(SPEC 冻结决策 3),坐在 Director 之上、消费
StoryGraph、产出 SeasonPlan——仿 tongjian L1 Constitution 的"LLM 切分 + 确定性门"范式,
但粒度从"一章分幕"升到"整部分集"。relationships/arcs 在 B0 阶段 1 未填,故
continuity_constraints 阶段 1 只记角色逐集在场(轻量版),关系状态快照留给阶段 2。

生产形态(ProductionForm):决定资产锚点通道、提示词词汇和渲染管线选择。
对标 drama-skills 的 production_profile 概念。
同名 disambiguation：本模块的 DirectorBrief 是短剧导演阐述（视觉方向/生产形态/基调）；hevi.director_lens.brief.DirectorBrief 是导演决策 brief（运动轨迹/物理/主光/BPM/禁止项），hevi.creative.director_brief.DirectorBrief 是 S1 哈希契约，三者互不通用。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ProductionForm(str, Enum):
    """生产形态——决定视觉语言、资产锚点和渲染管线。

    对标 drama-skills 的 production_profile:形态决定哪些身份锚点在本项目里
    可被表达——以剪影为识别通道的形态与以面部结构为识别通道的形态需要不同
    的锚点集合。
    """

    LIVE_ACTION = "live_action"
    """真人实拍:电影级摄影,面部结构为主要识别通道。"""

    DYNAMIC_COMIC_2D = "dynamic_comic_2d"
    """2D 动态漫(漫剧):漫画/动画风格,剪影+色彩签名为主要识别通道。"""

    STYLIZED_3D = "stylized_3d"
    """风格化 3D:3D 渲染,几何形体+材质为主要识别通道。"""

    INKWASH = "inkwash"
    """水墨动画:中国传统水墨画风,笔触+留白为主要识别通道。"""

    PAPER_STOP_MOTION = "paper_stop_motion"
    """纸感定格动画:手工剪纸/折纸/纸板纹理+逐帧动画风格。
    对标 Youmind paper-stop-motion-animation-generator。"""


# 每种形态的默认提示词配方(角色参考图生成用)
PRODUCTION_FORM_PROMPTS: dict[str, str] = {
    ProductionForm.LIVE_ACTION.value: (
        "cinematic character portrait, front facing, neutral expression, "
        "photographic realism, detailed skin texture, natural lighting"
    ),
    ProductionForm.DYNAMIC_COMIC_2D.value: (
        "2D anime character sheet, front/side/back views, clean linework, "
        "vibrant colors, manga illustration style, white background"
    ),
    ProductionForm.STYLIZED_3D.value: (
        "3D character model, turntable views, stylized rendering, "
        "smooth surfaces, expressive proportions, neutral background"
    ),
    ProductionForm.INKWASH.value: (
        "Chinese ink wash painting character, traditional brushwork, "
        "minimalist composition, black ink on rice paper, elegant strokes"
    ),
    ProductionForm.PAPER_STOP_MOTION.value: (
        "handcrafted paper cutout character, stop-motion animation style, "
        "visible paper texture, layered cardboard depth, craft aesthetic, "
        "subtle shadow edges, miniature diorama feel"
    ),
}

# 每种形态对应的渲染管线路由
PRODUCTION_FORM_RENDER_ROUTES: dict[str, str] = {
    ProductionForm.LIVE_ACTION.value: "tongjian_bridge",
    ProductionForm.DYNAMIC_COMIC_2D.value: "toon_render",
    ProductionForm.STYLIZED_3D.value: "wan2_3d_pipeline",
    ProductionForm.INKWASH.value: "inkwash_pipeline",
    ProductionForm.PAPER_STOP_MOTION.value: "seedance_2_paper",
}


class EpisodePlan(BaseModel):
    ep_number: int
    title: str = ""
    event_ids: list[str] = Field(default_factory=list)  # 本集覆盖的 StoryGraph 事件(时间线切片)
    beats: list[str] = Field(default_factory=list)  # 节拍序列(来自 event.beat_type)
    characters_present: list[str] = Field(default_factory=list)  # 本集出场角色 char_id(actors 并集)
    locations: list[str] = Field(default_factory=list)  # 本集场景地点名(并集)
    target_emotion_arc: str = ""  # 本集情感目标(开场→高潮→收束)


class SubjectRef(BaseModel):
    """全季角色组的一条 char_id ↔ subject_id 映射。subject_id 建 Subject 后回填。"""

    char_id: str
    subject_id: str | None = None
    name: str = ""


class ContinuityConstraint(BaseModel):
    """跨集约束。阶段 1:仅记角色逐集在场,供角色断裂检查;阶段 2 补关系状态快照。"""

    char_id: str
    present_in_episodes: list[int] = Field(default_factory=list)


# ── 故事开发输出(对标 drama-skills short-drama-develop)─────────────────────


class StoryBrief(BaseModel):
    """创作简报——锁定不可改的事实、主题与结局承诺。

    对标 drama-skills 的 creative-brief.md:区分不可改的事实、可探索的空白、
    形式约束和目标观众回报。
    """

    theme: str = ""
    """核心主题(一句话)。"""

    conflict_engine: str = ""
    """冲突引擎:压力如何出现、主角如何应对、对手如何反制。"""

    character_pressures: dict[str, str] = Field(default_factory=dict)
    """角色压力:char_id/name → 该角色面临的核心压力。"""

    escalation_mechanism: str = ""
    """升级机制:每轮冲突改变什么,而不是怎样重复得更响。"""

    termination_conditions: str = ""
    """终止条件:哪种人物转变或事实揭开会终结这个引擎。"""

    audience_payoff: str = ""
    """观众回报:目标观众反复能获得的情绪、信息或权力回报。"""


class EpisodeMapEntry(BaseModel):
    """分集地图的一条——每集产生局部戏剧结果、相邻集能精确交接。

    对标 drama-skills 的 episode-map.jsonl。
    """

    ep_number: int
    entering_state: str = ""
    """进入状态:本集开始时的世界/人物状态。"""

    goal: str = ""
    """当集追求:主角在本集的具体目标。"""

    resistance: str = ""
    """阻力:对抗来源和反制方式。"""

    causal_escalation: str = ""
    """因果升级:本集相比上集改变了什么。"""

    turning_point: str = ""
    """方向性转折:不可逆的变化。"""

    payoff: str = ""
    """已兑现回报:本集交付给观众的情绪/信息。"""

    outgoing_pressure: str = ""
    """出去的压力:留给下一集继承的事实。"""

    hook: str = ""
    """集尾钩子:吸引继续观看的悬念或问题。"""


class DirectorBrief(BaseModel):
    """导演阐述——视觉方向与生产形态约束。

    对标 drama-skills 的 director-brief.md。由故事开发产出候选,创作者接受后
    提升为 creator_authority。
    """

    visual_direction: str = ""
    """视觉方向:整体美学概述。"""

    production_form: str = "live_action"
    """生产形态(与 ProductionForm 枚举值一致)。"""

    tone: str = ""
    """基调:作品的情感色彩。"""

    pacing: str = ""
    """节奏:叙事速度和密度。"""

    visual_constraints: list[str] = Field(default_factory=list)
    """视觉约束:本形态下的制作边界(如"无夜间外景"、"场景不超过5个")。"""


class SeasonPlan(BaseModel):
    season_id: str = ""  # 绑定一个 Series(season = series);未绑定前为空
    story_source: str = ""  # StoryGraph meta.source 引用
    target_episodes: int = 0
    stylepack_ref: str | None = None  # 全季共用锁定(绑定 Series 时落定)
    subject_refs: list[SubjectRef] = Field(default_factory=list)  # 全季角色组
    episodes: list[EpisodePlan] = Field(default_factory=list)
    continuity_constraints: list[ContinuityConstraint] = Field(default_factory=list)
