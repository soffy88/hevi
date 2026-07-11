"""C 系列(电影级分支)输出契约 —— 见 HEVI-SPEC-02 §4-5、HEVI-EXEC-01 M3。

跟 hevi.tongjian.schemas(SPEC-01 L 系列)是并列的两套 schema,不是继承关系——
C2.5/C4/C6 消费 tongjian 的 ChapterIR/Constitution/Script 作为输入,但产出的是
电影级专属的场景/镜头结构(scenes/beats/shots),字段形状不同,没必要也不应该
往 L 系列的 Script/ShotList 上硬套。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BeatDialogue(BaseModel):
    """一句台词。quote_id 非空 = 改写自 chapter_ir.quotes 的真实引语(史实红线管的
    那种);quote_id 为空且 is_performative=True = 电影化演绎补充的台词,不是原文
    引语但显式标了"这是编的"——CG2.5 门对这两种走不同的审核路径,不允许"既没
    quote_id 也没标 is_performative"这种悄悄编台词混过去(见 scene_adapt.py)。
    """

    speaker: str  # character_id
    text: str
    quote_id: str | None = None
    is_performative: bool = False
    emotion: str = ""


class Beat(BaseModel):
    beat_id: str
    action: str = ""  # 动作/表演描述,允许合理虚构,但 CG2.5 审"不得改变史实因果"
    dialogue: BeatDialogue | None = None
    # C4 默认按"有没有 dialogue"推断 on_screen/shot_size(有台词→说话人单独中近景,
    # 没台词→全场角色入镜的建立/氛围 wide 镜头),这两个 hint 字段用来覆盖默认推断——
    # 比如一句没有台词的反应镜头(某角色听完话皱眉),既不是"说话人独白"也不该是
    # "全场入镜的建立镜头",没有 hint 字段就没法表达这种情况。
    on_screen_hint: list[str] | None = None
    shot_size_hint: str | None = None


class Scene(BaseModel):
    scene_id: str
    slug: str = ""
    characters: list[str] = Field(default_factory=list)  # character_id 列表
    space_anchor: str = ""
    beats: list[Beat] = Field(default_factory=list)


class CineShotCamera(BaseModel):
    shot_size: str = "medium"  # wide/full/medium/medium_close/close/extreme_close
    movement: str = "static"


class CineShot(BaseModel):
    shot_id: str
    scene_id: str
    beat_ids: list[str] = Field(default_factory=list)
    pack_ids: list[str] = Field(default_factory=list)  # 该镜头引用的身份包 pack_id
    shot_size: str = "medium"
    camera: CineShotCamera = Field(default_factory=CineShotCamera)
    on_screen: list[str] = Field(default_factory=list)  # character_id 列表
    dialogue_inline: BeatDialogue | None = None
    est_duration_s: float = 6.0
    prompt: str = ""  # 已经过 lint_shot_prompt 校验的最终 shot prompt


class CineShotList(BaseModel):
    shots: list[CineShot] = Field(default_factory=list)


class CG6Result(BaseModel):
    """C6 单个镜头的质量门结果——每一项检查独立记录,不是笼统一个 passed。"""

    identity_distance: float | None = None
    identity_passed: bool | None = None
    dialogue_cer: float | None = None
    dialogue_passed: bool | None = None
    vlm_passed: bool | None = None
    vlm_violations: list[str] = Field(default_factory=list)
    lipsync_note: str = "not implemented"
    passed: bool = False


class ShotResult(BaseModel):
    shot_id: str
    output_path: str = ""
    attempts: int = 0
    degraded: bool = False
    degrade_reason: str = ""
    cg6: CG6Result = Field(default_factory=CG6Result)
