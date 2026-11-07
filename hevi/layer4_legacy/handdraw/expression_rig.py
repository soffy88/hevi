"""Hand-drawn character expression rig (views x emotions x parts).

A *rig* here is a parametric face: a character is defined once as a model
sheet (body proportions, palette, identity marks, per-view face layouts),
and any expression is then produced by *combining parts* -- an eye style, a
mouth style, a brow style and optional extras -- instead of drawing every
expression as a separate one-off picture.  An emotion is just a named preset
over those parts; callers may override any single part on top of a preset.

Structure borrowed at the *method* level only (model sheet, parts
composition, ``(view, emotion, eyes, mouth)`` call convention).  The demo
character shipped here, ``tuantuan``, is a 100% original design drawn by
this module's own code; no third-party character design, silhouette,
palette or asset is copied or referenced.  See
``docs/rules/expression_rig.md`` for the naming/combination rules and the
originality red line.

Schema choice: the rig spec is plain frozen dataclasses (the handdraw
line's existing convention -- see ``rough_stroke.RoughStrokeResult`` and
``styles.HanddrawStyleConfig``), serialised to a JSON model sheet via
:meth:`CharacterRig.model_sheet`.  The render-request contract is a JSON
Schema dict (:data:`FACE_REQUEST_SCHEMA`), the same mechanism the
capability registry validates with, so the technique module and the
capability layer share one contract.

Rendering: pure PIL, procedural, on top of the clean-room
:mod:`hevi.layer4_legacy.handdraw.rough_stroke` technique (jittered,
bowed, double-drawn lines).  No paid image API, no network, CPU only.
Deterministic: every roughen call is seeded from the caller's ``seed``
plus a fixed part index; the global RNG is never touched, so the same
parameters always produce byte-identical PNGs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from hevi.layer4_legacy.handdraw.rough_stroke import roughen_polyline

# ---------------------------------------------------------------------------
# Catalogues: views, part styles, emotion presets
# ---------------------------------------------------------------------------

#: Views shipped for the demo character (front / three-quarter / profile).
VIEWS: tuple[str, ...] = ("front", "three_quarter", "profile")

#: Eye styles.  ``wink`` is a composite: arc on the character's left eye,
#: dot on the right (a single visible eye in profile becomes the arc).
EYE_STYLES: tuple[str, ...] = (
    "dot",
    "wide",
    "arc_smile",
    "half_lid",
    "droopy",
    "line",
    "star",
    "spiral",
    "angled",
    "wink",
)

#: Mouth styles.
MOUTH_STYLES: tuple[str, ...] = (
    "smile",
    "smile_open",
    "laugh_open",
    "flat",
    "slant_flat",
    "frown",
    "smirk",
    "cat",
    "small_o",
    "big_o",
    "wavy",
    "grit",
    "yawn",
    "tongue_out",
)

#: Brow styles.  ``one_raised`` = character's left brow raised, right neutral.
BROW_STYLES: tuple[str, ...] = (
    "none",
    "neutral",
    "raised",
    "worried",
    "angry",
    "one_raised",
)

#: Optional overlay extras (at most one of each; combinable).
EXTRA_STYLES: tuple[str, ...] = (
    "blush_strong",
    "tear",
    "sweat",
    "sparkles",
    "zzz",
    "anger_mark",
)


@dataclass(frozen=True)
class EmotionPreset:
    """One named emotion = a fixed combination of parts."""

    eyes: str
    mouth: str
    brows: str = "neutral"
    extras: tuple[str, ...] = ()
    gaze: tuple[float, float] = (0.0, 0.0)  # pupil offset for dot-like eyes
    eye_scale: float = 1.0
    cheek_scale: float = 1.0
    tilt: float = 0.0  # whole-face tilt in degrees (rendered last)


#: The emotion set.  Names are lower_snake_case English ids; the Chinese
#: gloss lives in the rule card, not in identifiers.
EMOTIONS: dict[str, EmotionPreset] = {
    "neutral": EmotionPreset(eyes="dot", mouth="flat"),
    "happy": EmotionPreset(eyes="arc_smile", mouth="smile_open"),
    "joy": EmotionPreset(
        eyes="arc_smile", mouth="laugh_open", brows="raised", cheek_scale=1.15
    ),
    "playful": EmotionPreset(eyes="wink", mouth="tongue_out", brows="raised"),
    "proud": EmotionPreset(eyes="half_lid", mouth="smirk"),
    "shy": EmotionPreset(
        eyes="dot",
        mouth="smile",
        extras=("blush_strong",),
        gaze=(-7.0, 3.0),
        cheek_scale=1.3,
    ),
    "surprised": EmotionPreset(eyes="wide", mouth="big_o", brows="raised"),
    "excited": EmotionPreset(
        eyes="star", mouth="smile_open", brows="raised", extras=("sparkles",)
    ),
    "thinking": EmotionPreset(
        eyes="dot", mouth="flat", brows="one_raised", gaze=(7.0, -5.0)
    ),
    "confused": EmotionPreset(
        eyes="dot", mouth="wavy", brows="one_raised", tilt=-5.0
    ),
    "sad": EmotionPreset(
        eyes="droopy", mouth="frown", brows="worried", extras=("tear",)
    ),
    "angry": EmotionPreset(
        eyes="angled", mouth="grit", brows="angry", extras=("anger_mark",)
    ),
    "scared": EmotionPreset(
        eyes="wide",
        mouth="wavy",
        brows="worried",
        extras=("sweat",),
        eye_scale=0.8,
        gaze=(0.0, 2.0),
    ),
    "disgusted": EmotionPreset(
        eyes="half_lid", mouth="slant_flat", gaze=(8.0, 2.0)
    ),
    "sleepy": EmotionPreset(eyes="line", mouth="yawn", extras=("zzz",)),
    "dizzy": EmotionPreset(eyes="spiral", mouth="wavy", tilt=5.0),
}

#: Render-request contract (JSON Schema).  The capability layer reuses the
#: same enum sets for its params schema.
FACE_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "character": {"type": "string", "enum": ["tuantuan"], "default": "tuantuan"},
        "view": {"type": "string", "enum": list(VIEWS), "default": "front"},
        "emotion": {"type": "string", "enum": list(EMOTIONS), "default": "neutral"},
        "eyes": {"type": "string", "enum": list(EYE_STYLES)},
        "mouth": {"type": "string", "enum": list(MOUTH_STYLES)},
        "brows": {"type": "string", "enum": list(BROW_STYLES)},
        "extras": {
            "type": "array",
            "items": {"type": "string", "enum": list(EXTRA_STYLES)},
            "uniqueItems": True,
        },
        "seed": {"type": "integer", "default": 0},
        "size": {"type": "integer", "minimum": 96, "maximum": 1024, "default": 480},
    },
}


# ---------------------------------------------------------------------------
# Character rig spec (the model sheet)
# ---------------------------------------------------------------------------


def _hex_rgba(code: str, alpha: int = 255) -> tuple[int, int, int, int]:
    clean = code.lstrip("#")
    return (int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16), alpha)


@dataclass(frozen=True)
class CharacterRig:
    """A character's model sheet: everything that must NOT change between
    expressions (the "same character, no face swap" contract)."""

    character_id: str
    display_name: str
    description: str
    palette: dict[str, str]
    views: tuple[str, ...]
    proportions: dict[str, float]
    identity_marks: tuple[str, ...]

    def model_sheet(self) -> dict[str, Any]:
        """JSON-serialisable model sheet: spec + full parts catalogue."""
        return {
            "character_id": self.character_id,
            "display_name": self.display_name,
            "description": self.description,
            "palette": dict(self.palette),
            "views": list(self.views),
            "proportions": dict(self.proportions),
            "identity_marks": list(self.identity_marks),
            "eyes_catalogue": list(EYE_STYLES),
            "mouths_catalogue": list(MOUTH_STYLES),
            "brows_catalogue": list(BROW_STYLES),
            "extras_catalogue": list(EXTRA_STYLES),
            "emotions": {
                name: {
                    "eyes": preset.eyes,
                    "mouth": preset.mouth,
                    "brows": preset.brows,
                    "extras": list(preset.extras),
                    "gaze": list(preset.gaze),
                    "eye_scale": preset.eye_scale,
                    "cheek_scale": preset.cheek_scale,
                    "tilt": preset.tilt,
                }
                for name, preset in EMOTIONS.items()
            },
        }


#: The demo character.  100% original design: a butter-yellow round blob
#: ("tuantuan", a little dough ball) whose bottom spreads slightly like a
#: puddle, with one spiral-curl sprout on top of its head, fixed coral
#: cheeks and an ink-brown hand-drawn outline.  No element references any
#: existing IP character.
DEMO_CHARACTER = CharacterRig(
    character_id="tuantuan",
    display_name="团团",
    description=(
        "原创手绘小角色:奶黄色圆团子身体,底部微微摊开像小水洼;"
        "头顶一根螺旋卷呆毛;两颊固定珊瑚色腮红;墨褐色手绘描边。"
    ),
    palette={
        "body": "#FFE3A3",
        "belly": "#FFF3D0",
        "ink": "#2B2622",
        "cheek": "#FF9D8A",
        "mouth_interior": "#74362A",
        "tongue": "#F4907F",
        "accent": "#F2A93B",
        "sweat": "#9AD0E8",
        "anger": "#E4572E",
        "paper_white": "#FFFFFF",
    },
    views=VIEWS,
    proportions={
        "model_space": 480.0,
        "head_rx": 148.0,
        "head_ry": 132.0,
        "eye_dx": 52.0,  # eye centre offset from face centre (front view)
        "eye_y": 238.0,
        "mouth_y": 300.0,
    },
    identity_marks=(
        "butter-yellow round blob body, bottom slightly spread",
        "single spiral-curl sprout on top of the head",
        "coral cheek blush on both cheeks (one on profile)",
        "ink-brown rough double-stroke outline",
    ),
)

CHARACTERS: dict[str, CharacterRig] = {DEMO_CHARACTER.character_id: DEMO_CHARACTER}


def get_character(character_id: str = "tuantuan") -> CharacterRig:
    rig = CHARACTERS.get(character_id)
    if rig is None:
        raise ValueError(
            f"unknown character {character_id!r}; valid: {sorted(CHARACTERS)}"
        )
    return rig


# ---------------------------------------------------------------------------
# Expression resolution: preset + per-part overrides, strict validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedFace:
    """The effective part combination for one render."""

    character: str
    view: str
    emotion: str
    eyes: str
    mouth: str
    brows: str
    extras: tuple[str, ...]
    gaze: tuple[float, float]
    eye_scale: float
    cheek_scale: float
    tilt: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "character": self.character,
            "view": self.view,
            "emotion": self.emotion,
            "eyes": self.eyes,
            "mouth": self.mouth,
            "brows": self.brows,
            "extras": list(self.extras),
            "gaze": list(self.gaze),
            "eye_scale": self.eye_scale,
            "cheek_scale": self.cheek_scale,
            "tilt": self.tilt,
        }


def _check(name: str, value: str, valid: tuple[str, ...]) -> str:
    if value not in valid:
        raise ValueError(f"unknown {name} {value!r}; valid: {list(valid)}")
    return value


def resolve_face(
    *,
    character: str = "tuantuan",
    view: str = "front",
    emotion: str = "neutral",
    eyes: str | None = None,
    mouth: str | None = None,
    brows: str | None = None,
    extras: list[str] | tuple[str, ...] | None = None,
) -> ResolvedFace:
    """Resolve an emotion preset plus optional per-part overrides.

    Raises :class:`ValueError` on any unknown character / view / emotion /
    part name -- never guesses or silently falls back.
    """
    get_character(character)
    _check("view", view, VIEWS)
    if emotion not in EMOTIONS:
        raise ValueError(
            f"unknown emotion {emotion!r}; valid: {sorted(EMOTIONS)}"
        )
    preset = EMOTIONS[emotion]
    eff_eyes = _check("eyes", eyes, EYE_STYLES) if eyes is not None else preset.eyes
    eff_mouth = (
        _check("mouth", mouth, MOUTH_STYLES) if mouth is not None else preset.mouth
    )
    eff_brows = (
        _check("brows", brows, BROW_STYLES) if brows is not None else preset.brows
    )
    if extras is None:
        eff_extras = preset.extras
    else:
        eff_extras = tuple(_check("extra", item, EXTRA_STYLES) for item in extras)
        if len(set(eff_extras)) != len(eff_extras):
            raise ValueError(f"duplicate extras: {list(eff_extras)}")
    return ResolvedFace(
        character=character,
        view=view,
        emotion=emotion,
        eyes=eff_eyes,
        mouth=eff_mouth,
        brows=eff_brows,
        extras=eff_extras,
        gaze=preset.gaze,
        eye_scale=preset.eye_scale,
        cheek_scale=preset.cheek_scale,
        tilt=preset.tilt,
    )


# ---------------------------------------------------------------------------
# Geometry helpers (model space: 480 x 480, y grows downwards)
# ---------------------------------------------------------------------------

Point = tuple[float, float]


def _ellipse_pts(
    cx: float, cy: float, rx: float, ry: float, *, n: int = 48
) -> list[Point]:
    return [
        (cx + rx * math.cos(2 * math.pi * i / n), cy + ry * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]


def _arc_pts(
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    a0_deg: float,
    a1_deg: float,
    *,
    n: int = 18,
) -> list[Point]:
    return [
        (
            cx + rx * math.cos(math.radians(a0_deg + (a1_deg - a0_deg) * i / (n - 1))),
            cy + ry * math.sin(math.radians(a0_deg + (a1_deg - a0_deg) * i / (n - 1))),
        )
        for i in range(n)
    ]


def _bezier_pts(p0: Point, pc: Point, p1: Point, *, n: int = 14) -> list[Point]:
    out: list[Point] = []
    for i in range(n):
        t = i / (n - 1)
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * pc[0] + t**2 * p1[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * pc[1] + t**2 * p1[1]
        out.append((x, y))
    return out


def _body_outline(view: str) -> list[Point]:
    """The character's silhouette per view -- fixed by the model sheet."""
    if view == "profile":
        cx, cy, rx, ry = 228.0, 258.0, 112.0, 130.0
    elif view == "three_quarter":
        cx, cy, rx, ry = 238.0, 258.0, 140.0, 132.0
    else:
        cx, cy, rx, ry = 240.0, 258.0, 148.0, 132.0
    pts: list[Point] = []
    n = 64
    for i in range(n):
        a = 2 * math.pi * i / n
        wobble = 1.0 + 0.018 * math.sin(3 * a + 0.7)
        x = cx + rx * wobble * math.cos(a)
        y = cy + ry * wobble * math.sin(a)
        if view == "profile":
            # Small nose bump on the face side, at face height.
            bump = 11.0 * math.exp(-(((a + 0.18) ** 2) / (2 * 0.13**2)))
            x += bump * math.cos(a)
        if y > 372.0:  # bottom spreads flat, like a little puddle
            y = 372.0 + (y - 372.0) * 0.35
        pts.append((x, y))
    return pts


def _antenna_pts(view: str) -> list[Point]:
    """Stem + spiral curl: the character's fixed identity mark."""
    if view == "profile":
        base, top, centre = (262.0, 134.0), (276.0, 98.0), (289.0, 86.0)
    elif view == "three_quarter":
        base, top, centre = (268.0, 130.0), (270.0, 94.0), (283.0, 82.0)
    else:
        base, top, centre = (240.0, 130.0), (240.0, 96.0), (253.0, 84.0)
    pts: list[Point] = [base, ((base[0] + top[0]) / 2 + 3.0, (base[1] + top[1]) / 2), top]
    steps = 26
    for i in range(steps + 1):
        t = i / steps
        ang = -math.pi / 2 + t * math.radians(320.0)
        r = 13.0 * (1.0 - t) + 3.5 * t
        pts.append((centre[0] + r * math.cos(ang), centre[1] + r * math.sin(ang)))
    return pts


@dataclass(frozen=True)
class _EyeSlot:
    cx: float
    cy: float
    s: float  # scale vs the front-view near eye
    side: float  # -1 = character's left, +1 = character's right


@dataclass(frozen=True)
class _Layout:
    eyes: tuple[_EyeSlot, ...]
    mouth: Point
    mouth_s: float
    brows: tuple[_EyeSlot, ...]
    cheeks: tuple[tuple[float, float, float], ...]  # cx, cy, scale
    belly: tuple[float, float, float, float] | None  # cx, cy, rx, ry
    tear_pt: Point
    sweat_pt: Point
    sparkle_pts: tuple[Point, ...]
    zzz_pt: Point
    anger_pt: Point


_LAYOUTS: dict[str, _Layout] = {
    "front": _Layout(
        eyes=(_EyeSlot(188, 238, 1.0, -1), _EyeSlot(292, 238, 1.0, 1)),
        mouth=(240, 300),
        mouth_s=1.0,
        brows=(_EyeSlot(188, 198, 1.0, -1), _EyeSlot(292, 198, 1.0, 1)),
        cheeks=((148, 286, 1.0), (332, 286, 1.0)),
        belly=(240, 352, 66, 30),
        tear_pt=(172, 268),
        sweat_pt=(356, 188),
        sparkle_pts=((104, 118), (372, 108), (356, 208)),
        zzz_pt=(348, 128),
        anger_pt=(116, 122),
    ),
    "three_quarter": _Layout(
        eyes=(_EyeSlot(216, 238, 0.8, -1), _EyeSlot(306, 238, 1.0, 1)),
        mouth=(262, 300),
        mouth_s=0.95,
        brows=(_EyeSlot(216, 198, 0.8, -1), _EyeSlot(306, 198, 1.0, 1)),
        cheeks=((168, 286, 0.8), (348, 286, 1.0)),
        belly=(244, 352, 60, 30),
        tear_pt=(200, 268),
        sweat_pt=(366, 188),
        sparkle_pts=((112, 118), (378, 108), (362, 208)),
        zzz_pt=(356, 128),
        anger_pt=(124, 122),
    ),
    "profile": _Layout(
        eyes=(_EyeSlot(292, 238, 1.0, 1),),
        mouth=(320, 296),
        mouth_s=0.9,
        brows=(_EyeSlot(292, 198, 1.0, 1),),
        cheeks=((264, 288, 1.0),),
        belly=(212, 352, 46, 28),
        tear_pt=(276, 268),
        sweat_pt=(338, 182),
        sparkle_pts=((128, 112), (352, 120)),
        zzz_pt=(330, 122),
        anger_pt=(140, 118),
    ),
}


# ---------------------------------------------------------------------------
# Painter: supersampled PIL canvas, all strokes via rough_stroke
# ---------------------------------------------------------------------------


class _Painter:
    def __init__(self, *, size: int, seed: int, roughness: float = 1.5) -> None:
        self.ss = 3
        self.size = size
        self.img = Image.new("RGBA", (size * self.ss, size * self.ss), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img, "RGBA")
        self.seed = seed
        self.roughness = roughness
        self._part = 0

    def _next_seed(self) -> int:
        self._part += 1
        return self.seed * 100003 + self._part * 131

    def _scale(self, pts: list[Point]) -> list[Point]:
        k = self.ss * self.size / 480.0
        return [(x * k, y * k) for x, y in pts]

    def _w(self, width: float) -> int:
        return max(1, round(width * self.ss * self.size / 480.0))

    def polyline(
        self,
        pts: list[Point],
        color: tuple[int, int, int, int],
        *,
        width: float = 4.5,
        rough: float | None = None,
        double: bool = True,
    ) -> None:
        res = roughen_polyline(
            pts,
            roughness=self.roughness if rough is None else rough,
            bowing=1.0,
            seed=self._next_seed(),
            double_stroke=double,
        )
        for one_pass in res.passes:
            self.d.line(
                self._scale(list(one_pass)),
                fill=color,
                width=self._w(width),
                joint="curve",
            )

    def filled(
        self,
        pts: list[Point],
        color: tuple[int, int, int, int],
        *,
        outline: tuple[int, int, int, int] | None = None,
        width: float = 4.0,
        rough: float = 0.7,
    ) -> None:
        res = roughen_polyline(
            pts,
            roughness=rough,
            bowing=0.4,
            seed=self._next_seed(),
            double_stroke=False,
            closed=True,
        )
        self.d.polygon(self._scale(list(res.passes[0])), fill=color)
        if outline is not None:
            self.polyline([*pts, pts[0]], outline, width=width, rough=rough)

    def ellipse_fill(
        self,
        cx: float,
        cy: float,
        rx: float,
        ry: float,
        color: tuple[int, int, int, int],
        *,
        outline: tuple[int, int, int, int] | None = None,
        width: float = 4.0,
        rough: float = 0.7,
    ) -> None:
        self.filled(
            _ellipse_pts(cx, cy, rx, ry, n=36),
            color,
            outline=outline,
            width=width,
            rough=rough,
        )

    def finish(self) -> Image.Image:
        return self.img.resize((self.size, self.size), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Part drawing
# ---------------------------------------------------------------------------


def _star_pts(cx: float, cy: float, r_out: float, r_in: float, *, points: int = 5) -> list[Point]:
    out: list[Point] = []
    for i in range(points * 2):
        ang = -math.pi / 2 + i * math.pi / points
        r = r_out if i % 2 == 0 else r_in
        out.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return out


def _sparkle_pts(cx: float, cy: float, r: float) -> list[Point]:
    inner = r * 0.22
    raw = [(0, -r), (inner, -inner), (r, 0), (inner, inner), (0, r), (-inner, inner), (-r, 0), (-inner, -inner)]
    return [(cx + dx, cy + dy) for dx, dy in raw]


def _draw_eye(
    p: _Painter,
    slot: _EyeSlot,
    style: str,
    *,
    ink: tuple[int, int, int, int],
    accent: tuple[int, int, int, int],
    paper: tuple[int, int, int, int],
    gaze: tuple[float, float],
    scale: float,
) -> None:
    cx, cy = slot.cx, slot.cy
    s = slot.s * scale
    gx, gy = gaze[0] * s, gaze[1] * s
    if style == "dot":
        p.ellipse_fill(cx + gx, cy + gy, 10.5 * s, 13.5 * s, ink)
        p.ellipse_fill(cx + gx - 3 * s, cy + gy - 4.5 * s, 2.6 * s, 2.6 * s, paper, rough=0.2)
    elif style == "wide":
        p.ellipse_fill(cx + gx, cy + gy, 14 * s, 18 * s, ink)
        p.ellipse_fill(cx + gx - 4 * s, cy + gy - 6 * s, 3.6 * s, 3.6 * s, paper, rough=0.2)
    elif style == "arc_smile":
        p.polyline(
            _arc_pts(cx, cy + 5 * s, 15 * s, 12 * s, 195, 345), ink, width=5.2 * s + 1.5
        )
    elif style == "half_lid":
        lower = _arc_pts(cx, cy - 1 * s, 13 * s, 12 * s, 0, 180)
        p.filled([*lower, (cx + 13 * s, cy - 1 * s)], ink, rough=0.4)
        p.polyline(
            _arc_pts(cx, cy - 1 * s, 15.5 * s, 8 * s, 185, 355), ink, width=4.6 * s + 1.2
        )
    elif style == "droopy":
        p.ellipse_fill(cx, cy + 3.5 * s, 9 * s, 10.5 * s, ink)
        outer = (cx + slot.side * 15 * s, cy - 0.5 * s)
        inner = (cx - slot.side * 15 * s, cy - 7 * s)
        ctrl = (cx, cy - 11 * s)
        p.polyline(_bezier_pts(outer, ctrl, inner), ink, width=4.6 * s + 1.2)
    elif style == "line":
        pts = [
            (cx - 13 * s + i * (26 * s) / 10, cy + 1.4 * s * math.sin(i * 1.1))
            for i in range(11)
        ]
        p.polyline(pts, ink, width=4.6 * s + 1.2)
    elif style == "star":
        p.filled(_star_pts(cx, cy, 16.5 * s, 7 * s), accent, outline=ink, width=2.6)
    elif style == "spiral":
        pts = []
        for i in range(41):
            t = i / 40
            ang = t * math.pi * 5
            r = 1.5 + 12.5 * t
            pts.append((cx + r * s * math.cos(ang), cy + r * s * math.sin(ang)))
        p.polyline(pts, ink, width=4.2 * s + 1.2, double=False)
    elif style == "angled":
        p.ellipse_fill(cx, cy + 1 * s, 10 * s, 12 * s, ink)
        outer = (cx + slot.side * 14.5 * s, cy - 14 * s)
        inner = (cx - slot.side * 14.5 * s, cy - 5.5 * s)
        p.polyline([outer, inner], ink, width=5.2 * s + 1.5)
    else:  # pragma: no cover - resolve_face validates the style first
        raise ValueError(f"unknown eye style {style!r}")


def _open_mouth(
    p: _Painter,
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    *,
    ink: tuple[int, int, int, int],
    interior: tuple[int, int, int, int],
    tongue: tuple[int, int, int, int],
) -> None:
    shape = [*_arc_pts(cx, cy, rx, ry, 0, 180, n=22), (cx + rx, cy), (cx - rx, cy)]
    p.filled(shape, interior, rough=0.5)
    # Tongue: a small ellipse low inside the mouth; sized so it can never
    # poke outside the half-disc interior.
    p.ellipse_fill(cx, cy + ry * 0.55, rx * 0.5, ry * 0.36, tongue, rough=0.3)
    p.polyline(_arc_pts(cx, cy, rx, ry, 0, 180, n=22), ink, width=4.6)
    p.polyline([(cx - rx, cy), (cx + rx, cy)], ink, width=4.6)


def _draw_mouth(
    p: _Painter,
    cx: float,
    cy: float,
    s: float,
    style: str,
    *,
    ink: tuple[int, int, int, int],
    interior: tuple[int, int, int, int],
    tongue: tuple[int, int, int, int],
    paper: tuple[int, int, int, int],
) -> None:
    if style == "smile":
        p.polyline(_arc_pts(cx, cy - 6 * s, 17 * s, 12 * s, 15, 165), ink, width=5.0)
    elif style == "flat":
        pts = [(cx - 13 * s + i * 2.6 * s, cy + 0.8 * s * math.sin(i * 0.9)) for i in range(11)]
        p.polyline(pts, ink, width=4.6)
    elif style == "slant_flat":
        p.polyline([(cx - 13 * s, cy - 3 * s), (cx + 13 * s, cy + 4 * s)], ink, width=4.6)
    elif style == "frown":
        p.polyline(_arc_pts(cx, cy + 11 * s, 15 * s, 10 * s, 195, 345), ink, width=5.0)
    elif style == "smirk":
        p.polyline(_arc_pts(cx + 3 * s, cy - 5 * s, 16 * s, 11 * s, 15, 140), ink, width=5.0)
        p.polyline(
            [(cx + 17 * s, cy + 2 * s), (cx + 20 * s, cy - 3 * s)], ink, width=5.0
        )
    elif style == "cat":
        p.polyline(_arc_pts(cx - 8.5 * s, cy - 3 * s, 8.5 * s, 7 * s, 10, 170), ink, width=4.4)
        p.polyline(_arc_pts(cx + 8.5 * s, cy - 3 * s, 8.5 * s, 7 * s, 10, 170), ink, width=4.4)
    elif style == "small_o":
        p.ellipse_fill(cx, cy, 7 * s, 9 * s, interior, outline=ink, width=3.6)
    elif style == "big_o":
        p.ellipse_fill(cx, cy, 12 * s, 15.5 * s, interior, outline=ink, width=4.2)
    elif style == "wavy":
        pts = [
            (cx - 14 * s + i * (28 * s) / 16, cy + 3.2 * s * math.sin(i * math.pi / 4))
            for i in range(17)
        ]
        p.polyline(pts, ink, width=4.6)
    elif style == "grit":
        rect = [
            (cx - 16 * s, cy - 8 * s),
            (cx + 16 * s, cy - 8 * s),
            (cx + 16 * s, cy + 8 * s),
            (cx - 16 * s, cy + 8 * s),
        ]
        p.filled(rect, paper, outline=ink, width=4.2, rough=0.5)
        for dx in (-5.3, 0.0, 5.3):
            p.polyline(
                [(cx + dx * s, cy - 8 * s), (cx + dx * s, cy + 8 * s)],
                ink,
                width=3.0,
                double=False,
            )
        p.polyline([(cx - 16 * s, cy), (cx + 16 * s, cy)], ink, width=3.0, double=False)
    elif style == "yawn":
        p.ellipse_fill(cx, cy, 11 * s, 16 * s, interior, outline=ink, width=4.2)
        p.ellipse_fill(cx, cy + 7 * s, 6.5 * s, 5 * s, tongue, rough=0.3)
    elif style == "smile_open":
        _open_mouth(p, cx, cy - 4 * s, 16 * s, 13 * s, ink=ink, interior=interior, tongue=tongue)
    elif style == "laugh_open":
        _open_mouth(p, cx, cy - 4 * s, 21 * s, 18 * s, ink=ink, interior=interior, tongue=tongue)
    elif style == "tongue_out":
        p.polyline(_arc_pts(cx, cy - 6 * s, 15 * s, 10 * s, 20, 160), ink, width=5.0)
        tongue_shape = [
            *_arc_pts(cx, cy + 3 * s, 8.5 * s, 7.5 * s, 0, 180, n=14),
            (cx + 8.5 * s, cy + 3 * s),
            (cx - 8.5 * s, cy + 3 * s),
        ]
        p.filled(tongue_shape, tongue, outline=ink, width=3.6, rough=0.4)
        p.polyline([(cx, cy + 4 * s), (cx, cy + 9 * s)], ink, width=2.6, double=False)
    else:  # pragma: no cover - validated upstream
        raise ValueError(f"unknown mouth style {style!r}")


def _draw_brow(
    p: _Painter,
    slot: _EyeSlot,
    style: str,
    *,
    ink: tuple[int, int, int, int],
) -> None:
    if style == "none":
        return
    cx, cy, s = slot.cx, slot.cy, slot.s
    eff = style
    if style == "one_raised":
        eff = "raised" if slot.side < 0 else "neutral"
    if eff == "neutral":
        p.polyline(_arc_pts(cx, cy + 6 * s, 21 * s, 10 * s, 200, 340), ink, width=4.4)
    elif eff == "raised":
        p.polyline(_arc_pts(cx, cy - 3 * s, 21 * s, 11 * s, 200, 340), ink, width=4.4)
    elif eff == "worried":
        outer = (cx + slot.side * 21 * s, cy + 4 * s)
        inner = (cx - slot.side * 21 * s, cy - 10 * s)
        p.polyline(_bezier_pts(outer, (cx, cy - 5 * s), inner), ink, width=4.6)
    elif eff == "angry":
        outer = (cx + slot.side * 21 * s, cy - 10 * s)
        inner = (cx - slot.side * 21 * s, cy + 4 * s)
        p.polyline(_bezier_pts(outer, (cx, cy - 4 * s), inner), ink, width=5.0)
    else:  # pragma: no cover - validated upstream
        raise ValueError(f"unknown brow style {style!r}")


def _drop_pts(cx: float, cy: float, r: float) -> list[Point]:
    pts: list[Point] = [(cx, cy - r * 1.7)]
    steps = 20
    for i in range(steps + 1):
        a = math.radians(-50 + (280 * i) / steps)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _draw_extras(
    p: _Painter,
    layout: _Layout,
    face: ResolvedFace,
    *,
    palette: dict[str, tuple[int, int, int, int]],
) -> None:
    ink = palette["ink"]
    for extra in face.extras:
        if extra == "blush_strong":
            continue  # handled with the cheeks (identity marks, scaled up)
        if extra == "tear":
            x, y = layout.tear_pt
            p.filled(_drop_pts(x, y, 6.5), palette["sweat"], rough=0.3)
        elif extra == "sweat":
            x, y = layout.sweat_pt
            p.filled(_drop_pts(x, y, 9.0), palette["sweat"], outline=ink, width=3.0, rough=0.3)
        elif extra == "sparkles":
            for i, (x, y) in enumerate(layout.sparkle_pts):
                p.filled(
                    _sparkle_pts(x, y, (15, 11, 9)[i % 3]),
                    palette["accent"],
                    outline=ink,
                    width=2.2,
                    rough=0.3,
                )
        elif extra == "zzz":
            x, y = layout.zzz_pt
            for dx, dy, size in ((0, 0, 10), (17, -21, 14), (40, -46, 19)):
                zx, zy = x + dx, y + dy
                p.polyline(
                    [(zx, zy), (zx + size, zy), (zx, zy + size), (zx + size, zy + size)],
                    ink,
                    width=4.0,
                    double=False,
                )
        elif extra == "anger_mark":
            x, y = layout.anger_pt
            color = palette["anger"]
            p.polyline(
                _bezier_pts((x - 17, y), (x, y + 5), (x + 17, y)), color, width=7.0, double=False
            )
            p.polyline(
                _bezier_pts((x, y - 17), (x + 5, y), (x, y + 17)), color, width=7.0, double=False
            )


# ---------------------------------------------------------------------------
# Rendering entry points
# ---------------------------------------------------------------------------


def _validate_render_args(seed: int, size: int) -> None:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError(f"seed must be an int, got {type(seed).__name__}")
    if isinstance(size, bool) or not isinstance(size, int) or not 96 <= size <= 1024:
        raise ValueError(f"size must be an int within [96, 1024], got {size!r}")


def render_face(
    *,
    character: str = "tuantuan",
    view: str = "front",
    emotion: str = "neutral",
    eyes: str | None = None,
    mouth: str | None = None,
    brows: str | None = None,
    extras: list[str] | tuple[str, ...] | None = None,
    seed: int = 0,
    size: int = 480,
) -> Image.Image:
    """Render one expression as an RGBA image (transparent background).

    Same (character, view, emotion, parts, seed, size) -> byte-identical
    PNG.  Unknown names raise :class:`ValueError`.
    """
    _validate_render_args(seed, size)
    rig = get_character(character)
    face = resolve_face(
        character=character,
        view=view,
        emotion=emotion,
        eyes=eyes,
        mouth=mouth,
        brows=brows,
        extras=extras,
    )
    palette = {name: _hex_rgba(code) for name, code in rig.palette.items()}
    ink = palette["ink"]
    layout = _LAYOUTS[face.view]

    p = _Painter(size=size, seed=seed)
    # Identity layer: antenna (stem base is covered by the body fill),
    # body fill + outline, belly patch, cheeks.  None of this depends on
    # the emotion -- that is what keeps the character from "changing face".
    p.polyline(_antenna_pts(face.view), ink, width=5.0)
    body = _body_outline(face.view)
    p.filled(body, palette["body"], rough=0.9)
    p.polyline([*body, body[0]], ink, width=5.2, rough=0.9)
    if layout.belly is not None:
        bx, by, brx, bry = layout.belly
        p.ellipse_fill(bx, by, brx, bry, palette["belly"], rough=0.5)
    cheek_scale = face.cheek_scale * (1.45 if "blush_strong" in face.extras else 1.0)
    cheek_color = _hex_rgba(rig.palette["cheek"], 165)
    for ccx, ccy, cs in layout.cheeks:
        p.ellipse_fill(ccx, ccy, 17 * cs * cheek_scale, 11 * cs * cheek_scale, cheek_color, rough=0.4)
        if "blush_strong" in face.extras:
            for k in range(3):
                hx = ccx - 9 * cs + k * 9 * cs
                p.polyline(
                    [(hx, ccy - 6 * cs), (hx + 5 * cs, ccy + 6 * cs)],
                    _hex_rgba(rig.palette["cheek"], 230),
                    width=3.0,
                    double=False,
                )
    # Expression layer: brows, eyes, mouth, extras.
    for brow_slot in layout.brows:
        _draw_brow(p, brow_slot, face.brows, ink=ink)
    for idx, eye_slot in enumerate(layout.eyes):
        style = face.eyes
        if style == "wink":
            style = "arc_smile" if idx == 0 else "dot"
        _draw_eye(
            p,
            eye_slot,
            style,
            ink=ink,
            accent=palette["accent"],
            paper=palette["paper_white"],
            gaze=face.gaze,
            scale=face.eye_scale,
        )
    mx, my = layout.mouth
    _draw_mouth(
        p,
        mx,
        my,
        layout.mouth_s,
        face.mouth,
        ink=ink,
        interior=palette["mouth_interior"],
        tongue=palette["tongue"],
        paper=palette["paper_white"],
    )
    _draw_extras(p, layout, face, palette=palette)

    img = p.finish()
    if face.tilt:
        img = img.rotate(
            face.tilt, resample=Image.BICUBIC, center=(size / 2, size / 2)
        )
    return img


def _load_label_font(px: int) -> ImageFont.ImageFont:
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, px)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=px)
    except TypeError:  # very old Pillow: bitmap default font, fixed size
        return ImageFont.load_default()


def build_contact_sheet(
    *,
    character: str = "tuantuan",
    views: list[str] | tuple[str, ...] | None = None,
    emotions: list[str] | tuple[str, ...] | None = None,
    cell: int = 220,
    seed: int = 0,
) -> Image.Image:
    """Grid proof sheet: rows = views, columns = emotions, labelled cells.

    This is the rig's acceptance artefact: one look shows whether the
    expressions are distinguishable and whether the character stays the
    same character across the whole grid.
    """
    get_character(character)
    eff_views = list(views) if views is not None else list(VIEWS)
    eff_emotions = list(emotions) if emotions is not None else list(EMOTIONS)
    if not eff_views or not eff_emotions:
        raise ValueError("contact sheet needs at least one view and one emotion")
    for v in eff_views:
        _check("view", v, VIEWS)
    for e in eff_emotions:
        if e not in EMOTIONS:
            raise ValueError(f"unknown emotion {e!r}; valid: {sorted(EMOTIONS)}")
    if isinstance(cell, bool) or not isinstance(cell, int) or not 96 <= cell <= 512:
        raise ValueError(f"cell must be an int within [96, 512], got {cell!r}")

    label_h = 30
    strip_w = 92
    width = strip_w + len(eff_emotions) * cell
    height = len(eff_views) * (cell + label_h)
    sheet = Image.new("RGBA", (width, height), (255, 252, 244, 255))
    draw = ImageDraw.Draw(sheet)
    font = _load_label_font(17)
    ink = (43, 38, 34, 255)
    for r, view in enumerate(eff_views):
        y0 = r * (cell + label_h)
        draw.text((10, y0 + cell // 2 - 10), view, fill=ink, font=font)
        for c, emotion in enumerate(eff_emotions):
            face_img = render_face(
                character=character, view=view, emotion=emotion, seed=seed, size=cell
            )
            x0 = strip_w + c * cell
            sheet.alpha_composite(face_img, (x0, y0))
            draw.text((x0 + 8, y0 + cell + 6), emotion, fill=ink, font=font)
    return sheet


__all__ = [
    "BROW_STYLES",
    "CHARACTERS",
    "DEMO_CHARACTER",
    "EMOTIONS",
    "EXTRA_STYLES",
    "EYE_STYLES",
    "FACE_REQUEST_SCHEMA",
    "MOUTH_STYLES",
    "VIEWS",
    "CharacterRig",
    "EmotionPreset",
    "ResolvedFace",
    "build_contact_sheet",
    "get_character",
    "render_face",
    "resolve_face",
]
