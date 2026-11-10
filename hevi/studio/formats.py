"""出品形式（format）—— 用户可见的创作入口。

S21：首页不再让用户面对 19 条内部产线，而是先选“出品形式”。每个形式锁定
一条或多条产线，并可选子风格；旧 API 的 ``line_id`` 继续兼容。

设计原则：
* 形式是产品概念，line 是实现细节，**内部 line id 不出现在用户界面**。
* ``auto`` 只做一次确定性路由（素材类型 → 形式），不猜第二次。
* ai_drama 相关形式受质量门控制；门没开时普通用户看到“即将开放”，
  管理员仍可进入（不报错）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.studio.recipes import get_recipe, line_availability

GATES_PATH = Path(__file__).resolve().parent / "data" / "format_gates.json"

# 素材类形式在用户上传文件后才出现。
MATERIAL_FORMAT_ID = "material_cut"
MATERIAL_SLOT_KEYS = ("media_path", "source_path", "video_path", "audio_path")


@dataclass(frozen=True)
class SubStyle:
    """形式下的一个可选子风格。"""

    id: str
    label: str
    line_id: str
    hint: str = ""
    slots: dict[str, Any] = field(default_factory=dict)
    # 该子风格是否依赖 ai_drama 质量门。
    gated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "hint": self.hint,
            "line_id": self.line_id,
            "gated": self.gated,
        }


@dataclass(frozen=True)
class Format:
    id: str
    label: str
    summary: str
    example: str
    styles: tuple[SubStyle, ...]
    default_style: str
    sample_video: str | None = None
    # 只有上传素材后才出现。
    needs_media: bool = False
    # 卡片整体是否依赖质量门（无可用子风格时显示即将开放）。
    gated: bool = False

    @property
    def default(self) -> SubStyle:
        for style in self.styles:
            if style.id == self.default_style:
                return style
        return self.styles[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "summary": self.summary,
            "example": self.example,
            "sample_video": self.sample_video,
            "needs_media": self.needs_media,
            "gated": self.gated,
            "default_style": self.default_style,
            "styles": [style.to_dict() for style in self.styles],
        }


FORMATS: tuple[Format, ...] = (
    Format(
        id="history_scene",
        label="历史现场",
        summary="史料或主题 → 带出处的讲述、演绎与时间线。",
        example="「安史之乱前夜，长安城的一夜」",
        sample_video="/showcase/s21/history_scene.mp4",
        default_style="standard",
        styles=(
            SubStyle("standard", "标准", "history_scene", "讲解 + 演绎混排"),
            SubStyle(
                "documentary", "纪录片质感", "documentary_montage",
                "真实素材 + 解说，适合纪实题材", {"render_style": "documentary"},
            ),
            SubStyle(
                "cinematic", "电影质感", "cinematic",
                "电影感镜头与调色，节奏更慢", {"render_style": "cinematic"},
            ),
            SubStyle(
                "director", "分镜精修", "director_pipeline",
                "逐镜分镜与导演控制，制作更重", {"render_style": "cinematic"},
            ),
            SubStyle(
                "cutaway_3d", "3D 剖面建造", "scene3d",
                "一个物件经 5–7 轮失败→改进变成完整剖面，真实资产优先",
                {"render_style": "scene3d", "s23_style": "cutaway_3d"},
            ),
            SubStyle(
                "world_3d", "3D 时代场景", "scene3d",
                "按年代考据搭出可走进去的世界，环境声先铺",
                {"render_style": "scene3d", "s23_style": "world_3d"},
            ),
            SubStyle(
                "editorial_2d", "2D 编辑部", "explainer",
                "地图路线 + 真实比例时间轴 + 纸张/半色调/撕纸",
                {"render_style": "motion_graphics", "s23_style": "editorial_2d"},
            ),
        ),
    ),
    Format(
        id="digital_human",
        label="数字人口播",
        summary="一段文案 → 数字人或口播人头出镜讲解。",
        example="「用 60 秒讲清楚复利为什么反直觉」",
        sample_video="/showcase/s21/digital_human.mp4",
        default_style="auto",
        styles=(
            SubStyle("auto", "按素材自动", "talking_head", "没有形象图时用口播人头"),
            SubStyle(
                "avatar", "有形象图", "avatar_spokesperson",
                "上传一张形象图，锁定人物身份",
            ),
            SubStyle(
                "host", "口播人头", "talking_head",
                "无需形象图，配音 + 字幕 + 头像",
            ),
        ),
    ),
    Format(
        id="live_drama",
        label="真人短剧",
        summary="一句话梗概 → 剧本、分镜、写实画面与成片。",
        example="「深夜便利店，店员发现常客的小票停在五年前」",
        sample_video="/showcase/s21/live_drama.mp4",
        default_style="live_action",
        gated=True,
        styles=(
            SubStyle(
                "live_action", "写实短剧", "ai_drama",
                "剧集圣经 + 分镜表自检 + 先图后视频",
                {"style": "live_action"}, gated=True,
            ),
            SubStyle(
                "cinematic", "电影质感", "cinematic",
                "电影感镜头与调色，节奏更慢", {"render_style": "cinematic"},
            ),
            SubStyle(
                "director", "分镜精修", "director_pipeline",
                "逐镜分镜与导演控制，制作更重", {"render_style": "cinematic"},
            ),
        ),
    ),
    Format(
        id="comic_drama",
        label="漫剧",
        summary="动漫风短剧，或轻量的静态漫画解说。",
        example="「社畜的猫在凌晨三点开口说话了」",
        sample_video="/showcase/s21/comic_drama.mp4",
        default_style="anime",
        styles=(
            SubStyle(
                "anime", "动漫短剧", "ai_drama",
                "动漫风格角色与分镜，先图后视频",
                {"style": "anime"}, gated=True,
            ),
            SubStyle(
                "light", "漫画解说（轻量）", "comic_narration",
                "静态漫画 + 旁白，制作更快",
            ),
        ),
    ),
    Format(
        id="animation",
        label="动画",
        summary="角色动画、手绘或 2D 解说动画。",
        example="「一个小机器人第一次学会走路」",
        sample_video="/showcase/s21/animation.mp4",
        default_style="character",
        styles=(
            SubStyle("character", "角色动画", "character_animation", "角色动作与镜头"),
            SubStyle("handdraw", "手绘动画", "handdraw", "白板 / 手绘逐笔出现"),
            SubStyle(
                "explainer_2d", "2D 解说动画", "explainer",
                "图形与文字动效讲解", {"render_style": "motion_graphics"},
            ),
        ),
    ),
    Format(
        id="explainer",
        label="知识讲解",
        summary="把一个问题讲明白：动效标题或 3D 演示。",
        example="「为什么飞机能飞起来」",
        sample_video="/showcase/s21/explainer.mp4",
        default_style="standard",
        styles=(
            SubStyle("standard", "标准讲解", "explainer", "观点 + 证据 + 动效"),
            SubStyle(
                "warm_gold", "暖黑金图解", "warm_gold",
                "近黑暖棕底 + 象牙白 + 香槟金细线；一句话讲清一个反直觉道理",
                {"render_style": "warm_gold", "s26_style": "warm_gold"},
            ),
            SubStyle("kinetic", "动效标题", "kinetic_promo", "强节奏的文字与图形"),
            SubStyle(
                "scene3d", "3D 演示", "scene3d",
                "产品拆解、地图路线、场景复原", {"render_style": "scene3d"},
            ),
            SubStyle(
                "editorial_2d", "2D 编辑部", "explainer",
                "地图路线 + 真实比例时间轴 + 档案拼贴",
                {"render_style": "motion_graphics", "s23_style": "editorial_2d"},
            ),
        ),
    ),
    Format(
        id=MATERIAL_FORMAT_ID,
        label="素材剪辑",
        summary="上传素材后出现：拆条、切片、译制、改编或拼贴 B-roll。",
        example="「把这段 40 分钟访谈剪成 3 条短视频」",
        sample_video="/showcase/s21/material_cut.mp4",
        default_style="shorts",
        needs_media=True,
        styles=(
            SubStyle(
                "shorts", "拆条切片", "shorts_clip",
                "长视频 → 多条短视频（钩子/卡点/字幕安全区/平台导出）",
                {"s23_shorts_spec": True},
            ),
            SubStyle("koubo", "口播精剪", "koubo_cut", "去停顿、加字幕"),
            SubStyle("podcast", "播客切片", "podcast_repurpose", "音频 / 播客 → 视频"),
            SubStyle("dub", "译制配音", "localization_dub", "翻译 + 配音 + 双语字幕"),
            SubStyle(
                "reference", "参考片改编", "reference_adapt",
                "看片（帧表/切点/声谱/转写）→ 翻拍配方 → 按结构重做",
                {"s23_watch_recipe": True},
            ),
            SubStyle("collage", "拼贴 B-roll", "collage_broll", "半调纸拼贴空镜"),
        ),
    ),
)

FORMAT_BY_ID = {fmt.id: fmt for fmt in FORMATS}
LINE_TO_FORMAT: dict[str, tuple[str, str]] = {}
for _fmt in FORMATS:
    for _style in _fmt.styles:
        LINE_TO_FORMAT.setdefault(_style.line_id, (_fmt.id, _style.id))


def _read_gates() -> dict[str, Any]:
    if not GATES_PATH.is_file():
        return {}
    try:
        return json.loads(GATES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def gate_open(line_id: str = "ai_drama") -> tuple[bool, str]:
    """质量门：只有黑盒平均分 >= 4 才对外开放。默认关闭。"""
    env = os.environ.get("HEVI_OPEN_AI_DRAMA", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True, "env override"
    gate = _read_gates().get(line_id) or {}
    if gate.get("open") is True:
        return True, str(gate.get("reason") or "quality gate passed")
    return False, str(gate.get("reason") or "尚未通过 3 主题黑盒（平均分需 ≥ 4）")


def _style_available(style: SubStyle, *, admin: bool) -> bool:
    # ai_drama 是唯一“门开后对外”的内部线；其余内部线仅管理员可用。
    if not admin and line_availability(style.line_id) == "internal" and style.line_id != "ai_drama":
        return False
    if style.gated and not admin:
        return gate_open(style.line_id)[0]
    return True


def format_availability(fmt: Format, *, admin: bool = False) -> tuple[bool, list[str]]:
    available_styles = [s.id for s in fmt.styles if _style_available(s, admin=admin)]
    return bool(available_styles), available_styles


def list_formats(*, admin: bool = False, has_media: bool = False) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for fmt in FORMATS:
        if fmt.needs_media and not has_media:
            continue
        available, style_ids = format_availability(fmt, admin=admin)
        payload = fmt.to_dict()
        payload["available"] = available
        payload["available_styles"] = style_ids
        if not available:
            payload["gated_reason"] = (
                gate_open("ai_drama")[1] if fmt.gated else "该形式尚未开放"
            )
        items.append(payload)
    return items


def get_format(format_id: str) -> Format | None:
    return FORMAT_BY_ID.get(format_id)


def format_for_line(line_id: str) -> tuple[str, str]:
    return LINE_TO_FORMAT.get(line_id, ("", ""))


def _guess_auto(slots: dict[str, Any]) -> tuple[str, str]:
    """Deterministic one-shot routing for 自动. No second guess."""
    if any(slots.get(key) for key in MATERIAL_SLOT_KEYS):
        return MATERIAL_FORMAT_ID, "shorts"
    topic = str(slots.get("topic") or slots.get("source_text") or "")
    if any(word in topic for word in ("历史", "朝代", "战争", "古代", "史料", "人物")):
        return "history_scene", "standard"
    if slots.get("image_path") or slots.get("avatar_image") or slots.get("presenter_id"):
        return "digital_human", "avatar"
    return "explainer", "standard"


def resolve_format(
    *,
    format_id: str | None,
    style_id: str | None,
    line_id: str | None,
    slots: dict[str, Any],
) -> dict[str, Any]:
    """把用户选择（format/style 或旧 line_id）解析成一次执行计划。

    返回 ``{"format", "style", "line_id", "slots", "gated", "reason"}``。
    旧 ``line_id`` 优先兼容：只要传了 line_id 就按它跑。
    """
    merged = dict(slots)
    if line_id:
        fmt_id, fmt_style = format_for_line(line_id)
        return {
            "format": fmt_id or "legacy",
            "style": fmt_style or "legacy",
            "line_id": line_id,
            "slots": merged,
            "gated": False,
            "reason": "",
        }

    chosen_format = format_id or "auto"
    if chosen_format == "auto":
        fmt_id, style_key = _guess_auto(merged)
        chosen_format = fmt_id
        merged.setdefault("format_auto_guess", f"{fmt_id}:{style_key}")
    else:
        style_key = style_id or ""

    fmt = get_format(chosen_format)
    if fmt is None:
        raise ValueError(f"unknown format: {chosen_format}")
    style: SubStyle | None = None
    if style_key:
        style = next((s for s in fmt.styles if s.id == style_key), None)
    if style is None:
        style = fmt.default
    line_id = style.line_id
    # 数字人口播的“自动”按有没有形象图路由，只路由一次。
    if fmt.id == "digital_human" and style.id == "auto":
        has_face = any(
            merged.get(key) for key in ("image_path", "avatar_image", "presenter_id")
        )
        line_id = "avatar_spokesperson" if has_face else "talking_head"
    merged.update(style.slots)
    return {
        "format": fmt.id,
        "style": style.id,
        "line_id": line_id,
        "slots": merged,
        "gated": bool(style.gated),
        "reason": "",
    }


def recipe_product(line_id: str) -> str:
    rec = get_recipe(line_id)
    return rec.product if rec else line_id
