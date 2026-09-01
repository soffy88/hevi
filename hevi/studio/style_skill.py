"""剪辑风格存档 —— 对照 FireRed-OpenStoryline Editing Skill Archiving。

把一次成功剪辑的轨结构/字幕样式/BGM 规则/配方卡存成 JSON,换素材后套用。
不是 YAML 产线配方:产线是工单,Style Skill 是剪辑审美。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CaptionStyle:
    mode: str = "primary"  # primary | bilingual_ass
    font: str = "Noto Sans CJK SC"
    primary_size: int = 48
    secondary_size: int = 28
    preset: str = "large_white"


@dataclass
class StyleSkill:
    name: str
    tracks: tuple[str, ...] = ("video", "voice", "bgm", "captions")
    caption: CaptionStyle = field(default_factory=CaptionStyle)
    bgm_gain: float = 0.28
    voice_first: bool = True
    remove_fillers: bool = False
    recipe_cards: tuple[str, ...] = ()
    energy: str = "medium"
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tracks"] = list(self.tracks)
        data["recipe_cards"] = list(self.recipe_cards)
        data["notes"] = list(self.notes)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StyleSkill:
        cap = data.get("caption") or {}
        return cls(
            name=str(data.get("name") or "untitled"),
            tracks=tuple(data.get("tracks") or ("video", "voice", "bgm", "captions")),
            caption=CaptionStyle(
                mode=str(cap.get("mode") or "primary"),
                font=str(cap.get("font") or "Noto Sans CJK SC"),
                primary_size=int(cap.get("primary_size") or 48),
                secondary_size=int(cap.get("secondary_size") or 28),
                preset=str(cap.get("preset") or "large_white"),
            ),
            bgm_gain=float(data.get("bgm_gain") or 0.28),
            voice_first=bool(data.get("voice_first", True)),
            remove_fillers=bool(data.get("remove_fillers") or False),
            recipe_cards=tuple(data.get("recipe_cards") or ()),
            energy=str(data.get("energy") or "medium"),
            notes=tuple(data.get("notes") or ()),
        )


def archive_style(
    *,
    name: str,
    timeline: dict[str, Any] | None = None,
    caption_mode: str = "primary",
    bgm_gain: float = 0.28,
    remove_fillers: bool = False,
    recipe_cards: list[str] | None = None,
    energy: str = "medium",
) -> StyleSkill:
    """从时间线快照抽出可复用风格。缺字段用默认,不编造品牌。"""
    tracks: tuple[str, ...] = ("video", "voice", "bgm", "captions")
    if timeline:
        raw = timeline.get("tracks") or timeline.get("layers")
        if isinstance(raw, list) and raw:
            names = tuple(str(t.get("name") or t.get("track") or t) for t in raw)
            if names:
                tracks = names
    return StyleSkill(
        name=name,
        tracks=tracks,
        caption=CaptionStyle(mode=caption_mode),
        bgm_gain=bgm_gain,
        remove_fillers=remove_fillers,
        recipe_cards=tuple(recipe_cards or ()),
        energy=energy,
        notes=("style skill; swap media then apply",),
    )


def save_style(skill: StyleSkill, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(skill.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_style(path: Path) -> StyleSkill:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("style skill must be a JSON object")
    return StyleSkill.from_dict(data)


def apply_style(
    skill: StyleSkill,
    *,
    media_path: str,
    clips: list[dict[str, Any]] | None = None,
    bgm: str = "",
) -> dict[str, Any]:
    """套到新素材上,产出 edit_plan。不渲染。"""
    plan_clips = list(clips or [{"source": media_path, "source_in_s": 0.0, "duration_s": 0.0, "track": "video"}])
    for clip in plan_clips:
        clip.setdefault("source", media_path)
        clip.setdefault("track", "video")
        clip.setdefault("action", "keep")
    return {
        "style": skill.name,
        "tracks": list(skill.tracks),
        "caption": asdict(skill.caption),
        "bgm": bgm,
        "bgm_gain": skill.bgm_gain,
        "voice_first": skill.voice_first,
        "remove_fillers": skill.remove_fillers,
        "recipe_cards": list(skill.recipe_cards),
        "cuts": plan_clips,
        "energy": skill.energy,
    }
