"""DirectorStyle dataclass contracts and validators (3O oprim)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StyleGradeStep:
    """A single ffmpeg filter step from a style's grade.ffmpeg_steps entry."""
    filter: str
    args: str = ""

    @property
    def ffmpeg(self) -> str:
        if not self.args:
            return self.filter
        return f"{self.filter}={self.args}" if self.filter != "lut3d" else f"{self.filter}=file={self.args}"


@dataclass(frozen=True)
class DirectorStyle:
    """One director visual style, loaded from data/*.json and schema-validated."""
    id: str
    display_zh: str
    display_en: str
    source: dict[str, Any]
    lens_aspect: dict[str, Any]
    composition: dict[str, Any]
    lighting: dict[str, Any]
    color: dict[str, Any]
    motion: dict[str, Any]
    rhythm: dict[str, Any]
    signature: list[dict[str, Any]]
    negative: list[str]
    fits: list[str]
    avoid: list[str]
    vertical_9x16: dict[str, Any]
    grade: dict[str, Any]
    reframe_9x16: dict[str, Any] = field(default_factory=dict)
    kind: str = "director"
    anime_safe: dict[str, Any] = field(default_factory=dict)
    character_dna: str = ""
    voice_profile: str = ""
    line_weight: str = ""
    palette_wordlist: list[str] = field(default_factory=list)

    @property
    def grade_steps(self) -> list[StyleGradeStep]:
        steps: list[StyleGradeStep] = []
        for entry in self.grade.get("ffmpeg_steps", []):
            if isinstance(entry, str):
                if "=" in entry:
                    f, a = entry.split("=", 1)
                    steps.append(StyleGradeStep(f.strip(), a.strip()))
                else:
                    steps.append(StyleGradeStep(entry.strip()))
            elif isinstance(entry, dict):
                steps.append(StyleGradeStep(str(entry.get("filter", "")), str(entry.get("args", ""))))
        return steps

    @property
    def required_signatures(self) -> list[dict[str, str]]:
        return [s for s in self.signature if s.get("required")]

    def is_wide_aspect(self) -> bool:
        a = str(self.lens_aspect.get("aspect", "")).lower()
        # 2.35:1, 2.39:1, 1.85:1 and IMAX 1.43:1 are all "wide" vs 9:16
        if "imax" in a or "1.43" in a:
            return True
        try:
            num, den = a.split(":")[:2]
            return float(num) / float(den) > 1.5
        except Exception:
            return False

    def is_stickman(self) -> bool:
        """True when this style is a stickman art style (character DNA based)."""
        return self.kind == "stickman" or bool(self.character_dna)


def from_dict(data: dict[str, Any]) -> DirectorStyle:
    return DirectorStyle(
        id=data["id"],
        display_zh=data["display_zh"],
        display_en=data["display_en"],
        source=data.get("source", {}),
        lens_aspect=data.get("lens_aspect", {}),
        composition=data.get("composition", {}),
        lighting=data.get("lighting", {}),
        color=data.get("color", {}),
        motion=data.get("motion", {}),
        rhythm=data.get("rhythm", {}),
        signature=data.get("signature", []),
        negative=data.get("negative", []),
        fits=data.get("fits", []),
        avoid=data.get("avoid", []),
        vertical_9x16=data.get("vertical_9x16", {}),
        grade=data.get("grade", {}),
        reframe_9x16=data.get("reframe_9x16", {}),
        kind=data.get("kind", "director"),
        anime_safe=data.get("anime_safe", {}),
        character_dna=data.get("character_dna", ""),
        voice_profile=data.get("voice_profile", ""),
        line_weight=data.get("line_weight", ""),
        palette_wordlist=data.get("palette_wordlist", []),
    )


# 10 directors from the original article, used to gate that the article set is fully present.
ARTICLE_DIRECTOR_IDS: tuple[str, ...] = (
    "wong_kar_wai", "zhang_yimou", "hou_hsiao_hsien", "jiang_wen",
    "johnnie_to", "jia_zhangke", "nolan", "wes_anderson", "tarantino", "fincher",
)

# Stickman art styles from the vendored stickman-video-director skill.
STICKMAN_STYLE_IDS: tuple[str, ...] = (
    "stickman_1a_light",
    "stickman_1b_dark",
    "stickman_2a_studio_tech",
    "stickman_2b_cinematic_story",
    "stickman_3_prehistoric",
)


DIRSTYLE_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SCHEMA_PATH = DIRSTYLE_DATA_DIR / "schema.json"


__all__ = [
    "ARTICLE_DIRECTOR_IDS",
    "DIRSTYLE_DATA_DIR",
    "DirectorStyle",
    "STICKMAN_STYLE_IDS",
    "StyleGradeStep",
    "from_dict",
    "SCHEMA_PATH",
]
