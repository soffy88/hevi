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
    character_names: list[str] = Field(default_factory=list)  # 本镜出场角色(剧本阶段名字)
    scene_name: str = ""  # 本镜所在场景(对应 DesignScene.name)
    prop_names: list[str] = Field(default_factory=list)
    duration_s: float = 5.0


class ShotList(BaseModel):
    shots: list[ShotListItem] = Field(default_factory=list)
