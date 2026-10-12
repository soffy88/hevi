"""B0 故事图谱(Story Graph)输出契约 —— 见 SPEC-001 §2.3。

短剧通道的入口数据结构:小说手稿 → StoryGraph,供剧集规划器(Episode Planner)消费。

设计沿革:复用 tongjian L0 `ChapterIR` 已验证的抽取范式(LLM 抽草稿、代码定位下标、
确定性 ID、引语幻觉守卫),但脱去《资治通鉴》史料专属字段——
- `year`(公元纪年) → `time_hint`(自由文本,小说无绝对纪年,如"三年后""翌日")
- 新增 `beat_type`(情节节拍:铺垫/冲突/转折/高潮/收束/过场),供规划器切集分配节拍
- 角色新增 `description`(外貌/性格可视化特征),喂 Subject 建模;`subject_id` 建档后回填

阶段 1(G1)只需 characters/events/quotes/locations 打通身份一致闭环,`relationships` 与
`arcs` 先建结构不填充(阶段 2 关系一致性守护接入时再抽)。source_span 语义同 ChapterIR:
[start, end) 字符下标,由代码定位、不由 LLM 报。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StoryCharacter(BaseModel):
    char_id: str
    name: str  # canonical 姓名(选文中最正式/最常用的称呼)
    aliases: list[str] = Field(default_factory=list)  # 别名/字/称号/代称(网文常见一人多称)
    description: str = ""  # 外貌/性格的可视化特征,喂 Subject 建模用
    role: str = ""  # protagonist/antagonist/supporting/anonymous...
    faction: str | None = None  # 所属势力/门派/家族
    first_appearance: tuple[int, int] | None = None  # 首次出场位置(最早 mention 的 span)
    source_spans: list[tuple[int, int]] = Field(default_factory=list)
    subject_id: str | None = None  # char_id ↔ subject_id 映射,建 Subject 后回填


class StoryRelationship(BaseModel):
    """角色关系边(有向)。阶段 1 不填充,结构先立,供阶段 2 跨集关系一致性守护。"""

    from_char: str  # char_id
    to_char: str  # char_id
    relation_type: str = ""  # 亲属/敌对/爱慕/主从...
    valence: float = 0.0  # 情感极性,随剧情可变
    evolution: list[dict[str, Any]] = Field(
        default_factory=list
    )  # 关系演变轨迹 [{event_id, relation_type, valence}]


class StoryEvent(BaseModel):
    """事件节点 = 时间线的一格。actors/causes/effects 均引用 char_id/event_id。"""

    event_id: str
    summary: str
    actors: list[str] = Field(default_factory=list)  # char_id 列表
    location: str | None = None
    time_hint: str = ""  # 自由文本时间线索(小说无绝对纪年)
    causes: list[str] = Field(default_factory=list)  # event_id 列表
    effects: list[str] = Field(default_factory=list)  # event_id 列表
    beat_type: str = ""  # 铺垫/冲突/转折/高潮/收束/过场
    dramatic_weight: int = 3  # 1-5,戏剧性权重,决定该事件是否必入某一集(规划器用)
    source_span: tuple[int, int] = (0, 0)
    # DRAMAPLAN 章节事件图:该事件来自哪一章(StoryChapter.chapter_id)。
    # 单篇(不分章)抽取时为 "",向后兼容旧 StoryGraph。
    chapter_ref: str = ""
    # 跨章合并后保留的原始逐章 event_id(便于回溯/调试);单章时为空。
    merged_from: list[str] = Field(default_factory=list)
    # 因果边来源标注（R5）：以 "from->to" 为 key 的边级映射，
    # 值为 "extracted" (LLM/手稿真实抽取) 或 "stitched" (跨章边界机械缝合)。
    # 旧字段 causal_source 保留向后兼容，但新增调用请用此边级标注。
    edge_sources: dict[str, str] = Field(default_factory=dict)
    # 兼容字段：事件整体来源（默认 extracted；跨章缝合的**首事件**会标 stitched）。
    causal_source: str = "extracted"


class StoryQuote(BaseModel):
    """原文对白。original 必须能在手稿里逐字定位——短剧台词只准改写自这里(叙事红线)。"""

    quote_id: str
    speaker: str  # char_id
    original: str  # 原文逐字对白(未经改写)
    modern: str = ""  # 改写/口语化参考
    event_id: str | None = None
    emotion: str = ""


class StoryLocation(BaseModel):
    location_id: str
    name: str
    type: str = ""  # 城市/宅邸/学校/战场...
    events: list[str] = Field(default_factory=list)  # event_id 列表


class StoryArc(BaseModel):
    """情感弧线(整部或单角色)。阶段 1 不填充,结构先立,供规划器守护。"""

    arc_id: str
    subject: str = ""  # char_id;空字符串 = 整部弧线
    description: str = ""
    events: list[str] = Field(default_factory=list)  # event_id 列表


class StoryChapter(BaseModel):
    """长篇按章节切分的一章元数据(DRAMAPLAN 章节事件图)。"""

    chapter_id: str  # "CH01"(稳定、按顺序分配)
    index: int  # 1 起
    title: str = ""
    summary: str = ""  # 该章摘要(供 memory store 检索/长上下文压缩)
    char_count: int = 0  # 该章正文字数
    event_ids: list[str] = Field(default_factory=list)  # 归入该章的事件(合并后全局 ID)


class OutlineEpisode(BaseModel):
    """改编大纲的一集:覆盖哪些事件、镜头/时长预算。"""

    ep_number: int
    title: str = ""
    event_ids: list[str] = Field(default_factory=list)
    shot_budget: int = 0
    target_duration_s: float = 0.0
    emotion_arc: str = ""
    summary: str = ""


class AdaptationOutline(BaseModel):
    """按“目标集数 × 每集时长”从全书事件图挑选/压缩出的改编大纲。

    接到 season_planner:可用 `outline_to_story()` 把大纲落回一个裁剪后的 StoryGraph,
    再喂 `season_planner.build_season_plan`。
    """

    story_source: str = ""
    target_episodes: int = 0
    episode_duration_s: float = 0.0
    total_shot_budget: int = 0
    episodes: list[OutlineEpisode] = Field(default_factory=list)
    dropped_event_ids: list[str] = Field(default_factory=list)  # 因预算被压缩掉的事件
    compressed: bool = False  # 是否发生了挑选/压缩(全量保留时为 False)


class StoryMeta(BaseModel):
    source: str  # 小说标题/卷名
    char_count: int = 0
    chapter_refs: list[str] = Field(default_factory=list)  # 覆盖的原文章节标识(分卷增量合并用)


class StoryGraph(BaseModel):
    meta: StoryMeta
    characters: list[StoryCharacter] = Field(default_factory=list)
    relationships: list[StoryRelationship] = Field(default_factory=list)  # 阶段 1 空
    events: list[StoryEvent] = Field(default_factory=list)  # = timeline
    quotes: list[StoryQuote] = Field(default_factory=list)
    locations: list[StoryLocation] = Field(default_factory=list)
    arcs: list[StoryArc] = Field(default_factory=list)  # 阶段 1 空
    # DRAMAPLAN 章节事件图:逐章元数据(旧单篇抽取为空列表,向后兼容)。
    chapters: list[StoryChapter] = Field(default_factory=list)
    # 改编大纲(可选;由 chapters.build_adaptation_outline 生成后回填)。
    adaptation_outline: AdaptationOutline | None = None


class EpisodeShot(BaseModel):
    """分镜镜头：每镜带 event_id、画面描述、台词/旁白、时长（DRAMAPLAN P3）。"""

    shot_id: str
    scene_no: int
    event_id: str
    image_prompt: str
    tts_text: str = ""
    duration_s: float = 5.0
    speaker: str = ""


class EpisodeStoryboard(BaseModel):
    """单集镜头级分镜脚本（由审稿通过的 EpisodeScript 派生）。"""

    ep_number: int
    title: str = ""
    target_duration_s: float = 0.0
    shot_budget: int = 0
    shots: list[EpisodeShot] = Field(default_factory=list)

    def total_shots(self) -> int:
        return len(self.shots)

    def total_duration(self) -> float:
        return sum(s.duration_s for s in self.shots)

    def to_shot_plans(self) -> list[Any]:
        """直接转成上游 oskill._schemas.ShotPlan 列表。"""
        from oskill._schemas import ShotPlan

        return [
            ShotPlan(
                shot_id=s.shot_id,
                image_prompt=s.image_prompt,
                tts_text=s.tts_text,
                duration_s=s.duration_s,
            )
            for s in self.shots
        ]
