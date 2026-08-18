"""hevi.explainer 输出契约 —— 见 hevi-remotion/src/types.ts 的镜像定义。

两边字段必须保持同步:这里是 Python(LLM 生成 + 校验)侧,types.ts 是 Remotion(渲染)侧。
用 camelCase 别名是因为最终产物是喂给 TypeScript `import manifest from "./run_manifest.json"`
的原始 JSON,不经过 hevi API 常规的 snake_case↔camelCase 中间层。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

SceneType = Literal["hook", "definition", "cards", "reason", "method", "outro"]
VisualType = Literal[
    "heygen_avatar",
    "broll_news",
    "browser_broll",
    "stock_broll",
    "data_screenshot",
    "remotion_chart",
    "remotion_code",
    "manim_scene",
    "voiceover",
]
AudioStyle = Literal["formal", "conversational"]
LayoutMode = Literal["fullscreen", "broll_pip"]


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class GateResult(BaseModel):
    """各层校验门的统一返回形状(同 hevi.tongjian.schemas.GateResult,独立通道不跨 import)。"""

    passed: bool
    coverage: float = 1.0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class HookItem(_CamelModel):
    emoji: str
    label: str
    cost: str | None = None


class HookProps(_CamelModel):
    title: str
    subtitle: str
    items: list[HookItem] = Field(default_factory=list)


class SplitSide(_CamelModel):
    emoji: str
    title: str
    sub: str = ""


class DefinitionProps(_CamelModel):
    question: str
    formula_head: str
    formula_lines: list[str]
    sink_emojis: list[str] = Field(default_factory=list)
    split_left: SplitSide
    split_right: SplitSide


class Card(_CamelModel):
    emoji: str
    title: str
    desc: str


class CardsProps(_CamelModel):
    header: str
    cards: list[Card]


class Label(_CamelModel):
    title: str
    sub: str = ""


class ReasonProps(_CamelModel):
    question: str
    brain_line: str
    bubble_text: str
    left_label: Label
    right_label: Label


class Point(_CamelModel):
    num: str
    title: str
    sub: str = ""


class MethodProps(_CamelModel):
    header: str
    points: list[Point]


class OutroProps(_CamelModel):
    setup_line1: str
    setup_line2: str
    quote_line1: str
    quote_line2: str
    cta_emojis: list[str] = Field(default_factory=list)
    cta_text: str
    byline: str


_PROPS_BY_SCENE_TYPE: dict[SceneType, type[BaseModel]] = {
    "hook": HookProps,
    "definition": DefinitionProps,
    "cards": CardsProps,
    "reason": ReasonProps,
    "method": MethodProps,
    "outro": OutroProps,
}


class VideoPackaging(_CamelModel):
    """🚨 v9.0: 视频包装配置 —— 强制的独立节点(与 contracts.VideoPackaging 同步)。"""

    main_title: str = Field(
        min_length=2,
        max_length=120,
        description="视频主题大标题，将显示在开场 3 秒封面上",
    )
    subtitle: str = Field(default="", max_length=200, description="副标题或核心信息点")
    theme_image_query: str = Field(
        default="",
        description="用于搜索开场背景图的高精度英文关键词",
    )
    presenter_image_url: str = Field(
        default="",
        description="数字人母体照片 URL（可选）",
    )

    @field_validator("main_title")
    @classmethod
    def main_title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("main_title 不能为空")
        return value


class StoryboardSegment(_CamelModel):
    """E0 产出,未经配音——narration 是待合成的旁白文本。"""

    id: str
    scene_type: SceneType
    narration: str
    keywords: list[str] = Field(default_factory=list)
    props: dict[str, Any]  # 校验后是 _PROPS_BY_SCENE_TYPE[scene_type] 的 model_dump(by_alias=True)
    # v6 visual scaffold metadata.  Remotion can render the six legacy scene
    # types while the assembly layer retains the original cue intent.
    visual_type: str | None = None
    visual_config: dict[str, Any] = Field(default_factory=dict)


class Storyboard(_CamelModel):
    topic: str
    segments: list[StoryboardSegment]


class CaptionCue(_CamelModel):
    text: str
    start: float
    end: float


class ManifestSegment(_CamelModel):
    """E2 配音后产出,并入时间戳——写进 hevi-remotion/src/data/run_manifest.json 的最终形态。"""

    id: str
    scene_type: SceneType
    text: str
    audio_file: str
    duration_sec: float
    start_sec: float
    keywords: list[str]
    props: dict[str, Any]
    captions: list[CaptionCue]
    visual_type: str | None = None
    visual_config: dict[str, Any] = Field(default_factory=dict)
    # 🚨 v9.0: layout mode for PiP transitions + audio style hint
    layout_mode: LayoutMode = "fullscreen"
    audio_style: AudioStyle = "formal"
    visual_search_query: str = Field(default="")


def validate_props(scene_type: SceneType, props: dict[str, Any]) -> dict[str, Any]:
    """按 scene_type 校验 props 形状,返回规整后的 dict(camelCase,供直接写 JSON)。"""
    model = _PROPS_BY_SCENE_TYPE[scene_type]
    return model.model_validate(props).model_dump(by_alias=True, exclude_none=True)
