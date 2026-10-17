"""proposal.json 的 schema 版本与校验。

不引外部 jsonschema 依赖, 用显式校验函数, 便于在测试里精确断言失败原因。
"""

from __future__ import annotations

from typing import Any

from hevi.layer4_legacy.stickdir import SCHEMA_VERSION, whitelist

#: 顶层必填键
REQUIRED_TOP = (
    "schema_version",
    "aspect",
    "duration",
    "style",
    "narration",
    "storyboard",
    "voice",
    "palette",
)

#: 每拍必填键
REQUIRED_BEAT = ("index", "t0", "t1", "action", "prop", "metaphor", "camera", "staging", "sfx")

#: 每段必填键
REQUIRED_SEGMENT = (
    "index",
    "start",
    "end",
    "stage",
    "beats",
    "transition",
    "bgm",
    "continuity_in",
    "continuity_out",
)


class SchemaError(ValueError):
    """proposal 结构或取值不合规。"""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise SchemaError(msg)


def validate(proposal: dict[str, Any]) -> None:
    """校验整份 proposal;不通过抛 :class:`SchemaError`。"""
    _require(isinstance(proposal, dict), "proposal must be an object")
    for key in REQUIRED_TOP:
        _require(key in proposal, f"missing top-level key {key!r}")

    _require(
        proposal["schema_version"] == SCHEMA_VERSION,
        f"schema_version must be {SCHEMA_VERSION!r}",
    )
    aspect = proposal["aspect"]
    _require(aspect in whitelist.ASPECT, f"aspect {aspect!r} not in {whitelist.ASPECT}")
    style = proposal["style"]
    _require(style in whitelist.STYLE, f"style {style!r} not in {whitelist.STYLE}")
    duration = proposal["duration"]
    _require(
        isinstance(duration, int) and duration in whitelist.DURATIONS,
        f"duration {duration!r} not in {whitelist.DURATIONS}",
    )

    # narration
    nar = proposal["narration"]
    _require(isinstance(nar, dict), "narration must be an object")
    _require("full_text" in nar and "stages" in nar, "narration needs full_text + stages")
    _require(
        isinstance(nar["stages"], list) and nar["stages"], "narration.stages must be non-empty"
    )

    # storyboard
    sb = proposal["storyboard"]
    _require(isinstance(sb, dict), "storyboard must be an object")
    segs = sb.get("segments")
    _require(isinstance(segs, list) and segs, "storyboard.segments must be non-empty")
    _require(
        len(segs) == duration // 10,
        f"storyboard has {len(segs)} segments, expected {duration // 10}",
    )
    staging_allowed = set(whitelist.staging_for(aspect))
    prev_out = None
    for seg in segs:
        for key in REQUIRED_SEGMENT:
            _require(key in seg, f"segment missing {key!r}")
        _require(
            seg["transition"] in whitelist.TRANSITION,
            f"transition {seg['transition']!r} not in whitelist",
        )
        _require(seg["bgm"] in whitelist.BGM, f"bgm {seg['bgm']!r} not in whitelist")
        _require(
            len(seg["beats"]) == len(whitelist.BEATS),
            f"segment {seg['index']} must have {len(whitelist.BEATS)} beats",
        )
        for beat in seg["beats"]:
            for key in REQUIRED_BEAT:
                _require(key in beat, f"beat missing {key!r}")
            for field in ("action", "prop", "metaphor", "camera"):
                _require(
                    whitelist.is_valid(field, beat[field]),
                    f"beat {field}={beat[field]!r} not in whitelist",
                )
            _require(beat["sfx"] in whitelist.SFX, f"sfx {beat['sfx']!r} not in whitelist")
            _require(
                beat["staging"] in staging_allowed,
                f"staging {beat['staging']!r} not allowed for {aspect}",
            )
        if prev_out is not None:
            _require(
                seg["continuity_in"] == prev_out,
                f"segment {seg['index']} continuity_in {seg['continuity_in']!r} != {prev_out!r}",
            )
        prev_out = seg["continuity_out"]

    # palette: Style 1 强调色 <= 3
    pal = proposal["palette"]
    _require(isinstance(pal, dict), "palette must be an object")
    accents = pal.get("accents", [])
    _require(isinstance(accents, list), "palette.accents must be a list")
    if style in ("1A", "1B"):
        _require(
            len(accents) <= 3, f"Style {style} allows at most 3 accent colors, got {len(accents)}"
        )
    for a in accents:
        _require(a in whitelist.ACCENT, f"accent {a!r} not in whitelist")

    # voice
    voice = proposal["voice"]
    _require(isinstance(voice, dict) and voice.get("profile"), "voice.profile required")


__all__ = ["REQUIRED_BEAT", "REQUIRED_SEGMENT", "REQUIRED_TOP", "SchemaError", "validate"]
