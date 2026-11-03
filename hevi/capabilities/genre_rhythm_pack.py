"""Genre rhythm parameter pack (``story.genre_rhythm_pack``).

Clean-room rewrite of the *method* in ``hevi-vs-ai-manju-skills.md``
section 2 / B1: each genre carries a rhythm window -- a shot-count
range, a dialogue-character range, and a scene-count range per
episode. The windows are registered values only: they come from
the source templates' own numbers, are marked ``verified: False``
(author self-report, never measured by hevi), and a
caller-supplied override always wins and is recorded in the
evidence. Nothing here is a hevi default threshold, and no
template text, example name, or plot point is carried over --
only the numeric windows and the genre names.

This module is a pure data pack plus a range judge. It reads no
media bytes, calls no generator, and touches no budget.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_SOURCE_NOTE = "author-reported template values, unverified"

# (slug, display name, shots_min, shots_max, dialogue_min, dialogue_max).
# Scene counts are the template-common 4-7 scenes per episode for
# every genre; they are part of the same unverified registration.
_GENRES: tuple[tuple[str, str, int, int, int, int], ...] = (
    ("chongsheng", "重生", 32, 44, 300, 500),
    ("chuanyue", "穿越", 28, 40, 300, 500),
    ("dushi", "都市", 38, 54, 300, 500),
    ("gongdou", "宫斗", 24, 34, 350, 550),
    ("jiating", "家庭", 22, 32, 400, 600),
    ("minsu", "民俗", 22, 30, 200, 350),
    ("moshi", "末世", 34, 46, 250, 400),
    ("niandai", "年代", 22, 32, 300, 450),
    ("quanmou", "权谋", 22, 32, 350, 550),
    ("shangzhan", "商战", 26, 36, 350, 550),
    ("tianchong", "甜宠", 28, 42, 300, 450),
    ("wuxia", "武侠", 24, 36, 200, 350),
    ("xiaoyuan", "校园", 22, 30, 220, 380),
    ("xihuan", "西幻", 30, 42, 250, 450),
    ("xingji", "星际", 30, 42, 250, 400),
    ("xitong", "系统", 32, 44, 250, 450),
    ("xuanhuan", "玄幻", 34, 48, 250, 450),
    ("xuanyi", "悬疑", 24, 36, 300, 500),
    ("yule", "娱乐", 34, 46, 300, 500),
    ("zhaidou", "宅斗", 26, 36, 350, 550),
    ("zhongtian", "种田", 24, 34, 300, 450),
)

GENRE_RHYTHM: dict[str, dict[str, Any]] = {
    slug: {
        "genre": slug,
        "name": name,
        "shots_min": shots_min,
        "shots_max": shots_max,
        "dialogue_min": dialogue_min,
        "dialogue_max": dialogue_max,
        "scenes_min": 4,
        "scenes_max": 7,
        "verified": False,
        "source": _SOURCE_NOTE,
    }
    for slug, name, shots_min, shots_max, dialogue_min, dialogue_max in _GENRES
}

_NAME_TO_SLUG = {spec["name"]: slug for slug, spec in GENRE_RHYTHM.items()}

_BOUNDS = (
    "shots_min",
    "shots_max",
    "dialogue_min",
    "dialogue_max",
    "scenes_min",
    "scenes_max",
)


def _resolve_genre(genre: Any) -> str:
    if isinstance(genre, str) and genre.strip() in GENRE_RHYTHM:
        return genre.strip()
    if isinstance(genre, str) and genre.strip() in _NAME_TO_SLUG:
        return _NAME_TO_SLUG[genre.strip()]
    raise CapabilityError(
        "story.genre_rhythm_pack: unknown genre "
        f"{genre!r}; expected one of the 21 registered genre slugs "
        "or display names"
    )


def list_genres() -> list[dict[str, Any]]:
    """Return all 21 registered genre rhythm windows (copies)."""
    return [dict(spec) for spec in GENRE_RHYTHM.values()]


def get_genre_rhythm(genre: Any) -> dict[str, Any]:
    """Return one genre's rhythm window (a copy). Raises for unknown genres."""
    return dict(GENRE_RHYTHM[_resolve_genre(genre)])


def check_episode_rhythm(
    genre: Any,
    shots: int,
    dialogue_chars: int,
    scenes: int,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Judge one episode's counts against its genre window.

    ``overrides`` may replace any bound; every override is
    recorded in the evidence and wins over the registered value.
    Returns a report; never raises for an out-of-window episode
    (only an unknown genre raises).
    """
    slug = _resolve_genre(genre)
    window = dict(GENRE_RHYTHM[slug])
    applied_overrides: dict[str, Any] = {}
    if overrides:
        for key, value in overrides.items():
            if key not in _BOUNDS:
                raise CapabilityError(
                    "story.genre_rhythm_pack: override key "
                    f"{key!r} is not a rhythm bound"
                )
            if not isinstance(value, int) or isinstance(value, bool):
                raise CapabilityError(
                    "story.genre_rhythm_pack: override "
                    f"{key!r} must be an integer"
                )
            window[key] = value
            applied_overrides[key] = value
    issues: list[dict[str, Any]] = []

    def _check(value: int, low: int, high: int, field: str, unit: str) -> None:
        if value < low or value > high:
            issues.append(
                {
                    "code": "rhythm_out_of_window",
                    "detail": (
                        f"story.genre_rhythm_pack: {field} {value} {unit} "
                        f"is outside the {GENRE_RHYTHM[slug]['name']} "
                        f"window [{low}, {high}]"
                    ),
                }
            )

    _check(shots, window["shots_min"], window["shots_max"], "shots", "shots")
    _check(
        dialogue_chars,
        window["dialogue_min"],
        window["dialogue_max"],
        "dialogue_chars",
        "chars",
    )
    _check(scenes, window["scenes_min"], window["scenes_max"], "scenes", "scenes")
    verdict = "pass" if not issues else "fail"
    return {
        "ok": verdict == "pass",
        "verdict": verdict,
        "genre": slug,
        "genre_name": GENRE_RHYTHM[slug]["name"],
        "window": window,
        "overrides": applied_overrides,
        "counts": {
            "shots": shots,
            "dialogue_chars": dialogue_chars,
            "scenes": scenes,
        },
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_episode_rhythm(
        params.get("genre"),
        params.get("shots"),
        params.get("dialogue_chars"),
        params.get("scenes"),
        overrides=params.get("overrides"),
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "genre_rhythm_pack_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "ok": report["ok"],
        },
    )


def register_genre_rhythm_pack_capabilities_once() -> list[str]:
    """Register ``story.genre_rhythm_pack`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="story.genre_rhythm_pack",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "genre": {"type": "string"},
                    "shots": {"type": "integer"},
                    "dialogue_chars": {"type": "integer"},
                    "scenes": {"type": "integer"},
                    "overrides": {"type": "object"},
                },
                "required": ["genre", "shots", "dialogue_chars", "scenes"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Genre rhythm pack: the 21 registered genre windows for "
                "shots, dialogue characters, and scenes per episode, "
                "marked unverified author-reported values; "
                "caller-supplied overrides win and are recorded. Pure "
                "data plus a range judge; no generation, no keys."
            ),
            line="story",
        )
    )
    return ["story.genre_rhythm_pack"]


register_genre_rhythm_pack_capabilities_once()
