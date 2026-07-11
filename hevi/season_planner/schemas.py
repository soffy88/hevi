"""剧集规划器输出契约 SeasonPlan —— 见 SPEC-001 §3.3。

把一部小说的 StoryGraph 切成 N 集,每集分配节拍/角色/场景/情感目标。season 绑定一个
Series(season = series),下游逐集交给现有 Director 生成分镜。

设计沿革:剧集规划器是**新的规划层**(SPEC 冻结决策 3),坐在 Director 之上、消费
StoryGraph、产出 SeasonPlan——仿 tongjian L1 Constitution 的"LLM 切分 + 确定性门"范式,
但粒度从"一章分幕"升到"整部分集"。relationships/arcs 在 B0 阶段 1 未填,故
continuity_constraints 阶段 1 只记角色逐集在场(轻量版),关系状态快照留给阶段 2。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


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


class SeasonPlan(BaseModel):
    season_id: str = ""  # 绑定一个 Series(season = series);未绑定前为空
    story_source: str = ""  # StoryGraph meta.source 引用
    target_episodes: int = 0
    stylepack_ref: str | None = None  # 全季共用锁定(绑定 Series 时落定)
    subject_refs: list[SubjectRef] = Field(default_factory=list)  # 全季角色组
    episodes: list[EpisodePlan] = Field(default_factory=list)
    continuity_constraints: list[ContinuityConstraint] = Field(default_factory=list)
