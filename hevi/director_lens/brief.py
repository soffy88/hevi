"""DirectorBrief —— 线路无关的制作链 brief 数据模型 + 规则/模板自动补全。

一次制作的全部导演决策都落在这份 JSON 上:观众/核心信息、分镜、主次/景深、
每个元素的独立运动轨迹、物理事件、主光方向、拍点、BGM/SFX 事件、禁止项、验收标准。

同一 schema 描述所有产品线(讲解/科普、手绘线、火柴人、3D 短片、漫剧/短剧、
纪录混剪、口播数字人、品牌/产品片),差异只在 ``line`` 字段与各线的适配器。

自动补全纯 CPU、零付费调用、确定性:同一 (prompt, line, seed) 永远产出同一 brief。
补全后是普通 JSON,可人工改完再渲染。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hevi.director_lens.beat import build_grid as _build_grid, snap_all as _snap_all

# ── 线路目录 ────────────────────────────────────────────────────────────
# 每条线:显示名 + 该线的默认节奏/景深/光/禁止项倾向。
LINE_CATALOG: dict[str, dict[str, Any]] = {
    "explainer": {
        "zh": "讲解/科普",
        "bpm": 96.0,
        "shot_roles": ["起势", "发展", "收束"],
        "layer_bias": "mid",
        "default_light_deg": 135.0,
    },
    "character_narrative": {
        "zh": "角色叙事(漫剧/手绘/火柴人)",
        "bpm": 84.0,
        "shot_roles": ["起势", "发展", "收束"],
        "layer_bias": "fg",
        "default_light_deg": 120.0,
    },
    "scene3d": {
        "zh": "3D 短片 / anatomy 机械说明",
        "bpm": 90.0,
        "shot_roles": ["起势", "发展", "收束"],
        "layer_bias": "mid",
        "default_light_deg": 110.0,
    },
    "montage": {
        "zh": "实拍/素材混剪(纪录)",
        "bpm": 100.0,
        "shot_roles": ["起势", "发展", "收束"],
        "layer_bias": "bg",
        "default_light_deg": 100.0,
    },
}

# 幼儿线统一的硬性禁止项(见 KIDS_ANIME_DIRECTION.md)。任何线只要受众含幼儿即注入。
KIDS_PROHIBITIONS: tuple[str, ...] = (
    "禁止居中大字标题(主信息不放在画面正中)",
    "禁止霓虹渐变(neon_glow / grid_floor)",
    "禁止全体元素同步淡入(必须错相)",
    "禁止整幅画面抖动(camera_shake)",
    "禁止快切与闪切(单镜 ≥2.5 秒,平均 ≥3.5 秒)",
    "禁止暴力/血/武器/恐怖/惊吓音效",
    "禁止商业广告植入与品牌名",
    "禁止亮度闪烁 >3 次/秒,禁止大面积红色闪烁",
)

# 通用(任何线都适用)的导演级禁止项 —— 高级感来自删自由度。
GENERIC_PROHIBITIONS: tuple[str, ...] = (
    "禁止无物理依据的随机 easing(运动必须由速度/冲量推导)",
    "禁止同一时刻多个主事件(同屏只有一个注意力中心)",
    "禁止元素静止时高光/受光面/阴影完全冻结",
    "禁止匀速直线入场(廉价 PPT 感)",
)


def _stable_seed(*parts: Any) -> int:
    """由内容派生稳定整数 seed(不依赖时间/随机源)。"""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ── 子结构 ──────────────────────────────────────────────────────────────


@dataclass
class Reference:
    """一条参考。约束写进禁止项与验收标准(范围扩大 §3:参考优先)。"""

    kind: str  # dirstyle | rule_card | video | image
    ref: str
    constraints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ShotPlan:
    """一个分镜:一个主任务 + 时长。起势→发展→收束。"""

    index: int
    role: str  # 起势 | 发展 | 收束
    main_task: str
    start_s: float
    duration_s: float
    main_subject: str
    heavy_beats: list[int] = field(default_factory=list)  # 落在本镜内的重拍序号

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Subject:
    """主体/次主体/背景元素。"""

    id: str
    name: str
    role: str  # primary | secondary | background
    layer: str  # fg | mid | bg
    shape: str  # circle | box | drop | star | ring | bar
    color: str  # #RRGGBB
    size_px: int
    home_x: float  # 归一化 0..1
    home_y: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Layer:
    """前/中/后景。parallax 决定相机运动时的位移倍率。"""

    id: str
    depth: str  # fg | mid | bg
    parallax: float
    blur_px: float
    shade: float  # 明度系数(后景更暗/更淡, 造景深)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MotionEvent:
    """元素轨迹上的一个物理事件。"""

    t: float
    kind: str  # drop | bounce | impact | settle | float | roll | wave | cohere
    magnitude: float = 1.0
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class ElementTrack:
    """一个元素独立的运动轨迹规格:由运动语言从事件推导,不是随机 easing。"""

    element: str
    motion: str  # 运动语言原语: bounce | fall | float | roll | wave | cohere | press | stretch
    events: list[MotionEvent] = field(default_factory=list)
    start_delay_frames: int = 0
    velocity_continuity: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "element": self.element,
            "motion": self.motion,
            "events": [e.to_dict() for e in self.events],
            "start_delay_frames": self.start_delay_frames,
            "velocity_continuity": self.velocity_continuity,
        }


@dataclass
class KeyLight:
    """主光方向。全场一致(自检门会核对)。"""

    azimuth_deg: float  # 0=右(+x), 90=上(+y, 屏幕坐标 y 向下时表示上方来光)
    elevation_deg: float
    color: str
    intensity: float
    shadow_softness: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AudioEvent:
    """BGM/SFX 事件。SFX 从运动长出:速度峰→whoosh, 冲量→impact, 接触帧→点击/落地。"""

    t: float
    kind: str  # sfx | bgm_duck | bgm
    sfx_id: str | None = None
    gain_db: float = 0.0
    source_motion: str | None = None  # 该 SFX 由哪个运动事件长出
    duck_db: float = 0.0  # bgm_duck 用:让路深度

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── 主模型 ──────────────────────────────────────────────────────────────


@dataclass
class DirectorBrief:
    """线路无关的制作链 brief。"""

    id: str
    line: str
    audience: str
    core_message: str
    prompt: str
    duration_s: float
    aspect: str  # "16:9" | "9:16"
    fps: int
    bpm: float
    seed: int
    shots: list[ShotPlan] = field(default_factory=list)
    subjects: list[Subject] = field(default_factory=list)
    layers: list[Layer] = field(default_factory=list)
    tracks: list[ElementTrack] = field(default_factory=list)
    physics_events: list[dict[str, Any]] = field(default_factory=list)
    key_light: KeyLight | None = None
    references: list[Reference] = field(default_factory=list)
    audio_events: list[AudioEvent] = field(default_factory=list)
    prohibitions: list[str] = field(default_factory=list)
    acceptance: list[str] = field(default_factory=list)
    line_params: dict[str, Any] = field(default_factory=dict)

    # ── 序列化 ──
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "line": self.line,
            "audience": self.audience,
            "core_message": self.core_message,
            "prompt": self.prompt,
            "duration_s": self.duration_s,
            "aspect": self.aspect,
            "fps": self.fps,
            "bpm": self.bpm,
            "seed": self.seed,
            "shots": [s.to_dict() for s in self.shots],
            "subjects": [s.to_dict() for s in self.subjects],
            "layers": [l.to_dict() for l in self.layers],
            "tracks": [t.to_dict() for t in self.tracks],
            "physics_events": list(self.physics_events),
            "key_light": self.key_light.to_dict() if self.key_light else None,
            "references": [r.to_dict() for r in self.references],
            "audio_events": [a.to_dict() for a in self.audio_events],
            "prohibitions": list(self.prohibitions),
            "acceptance": list(self.acceptance),
            "line_params": dict(self.line_params),
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DirectorBrief":
        kl = data.get("key_light")
        return cls(
            id=data["id"],
            line=data["line"],
            audience=data.get("audience", ""),
            core_message=data.get("core_message", ""),
            prompt=data.get("prompt", ""),
            duration_s=float(data["duration_s"]),
            aspect=data.get("aspect", "16:9"),
            fps=int(data.get("fps", 30)),
            bpm=float(data.get("bpm", 90.0)),
            seed=int(data.get("seed", 0)),
            shots=[ShotPlan(**s) for s in data.get("shots", [])],
            subjects=[Subject(**s) for s in data.get("subjects", [])],
            layers=[Layer(**l) for l in data.get("layers", [])],
            tracks=[
                ElementTrack(
                    element=t["element"],
                    motion=t["motion"],
                    events=[MotionEvent(**e) for e in t.get("events", [])],
                    start_delay_frames=int(t.get("start_delay_frames", 0)),
                    velocity_continuity=bool(t.get("velocity_continuity", True)),
                )
                for t in data.get("tracks", [])
            ],
            physics_events=list(data.get("physics_events", [])),
            key_light=KeyLight(**kl) if kl else None,
            references=[Reference(**r) for r in data.get("references", [])],
            audio_events=[AudioEvent(**a) for a in data.get("audio_events", [])],
            prohibitions=list(data.get("prohibitions", [])),
            acceptance=list(data.get("acceptance", [])),
            line_params=dict(data.get("line_params", {})),
        )

    @classmethod
    def load(cls, path: str | Path) -> "DirectorBrief":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json(), encoding="utf-8")
        return p

    # ── 校验 ──
    def validate(self) -> list[str]:
        """返回问题列表(空 = 合法)。非法参数一律拒绝。"""
        errs: list[str] = []
        if self.line not in LINE_CATALOG:
            errs.append(f"unknown line {self.line!r}; known: {sorted(LINE_CATALOG)}")
        if self.aspect not in ("16:9", "9:16", "1:1"):
            errs.append(f"unsupported aspect {self.aspect!r}")
        if self.fps <= 0 or self.fps > 120:
            errs.append(f"fps out of range: {self.fps}")
        if not (2.0 <= self.duration_s <= 600.0):
            errs.append(f"duration_s out of range: {self.duration_s}")
        if not (30.0 <= self.bpm <= 240.0):
            errs.append(f"bpm out of range: {self.bpm}")
        if not self.shots:
            errs.append("no shots planned")
        if self.key_light is None:
            errs.append("key_light missing")
        # 分镜必须无缝覆盖整段时长
        if self.shots:
            expected = 0.0
            for s in sorted(self.shots, key=lambda x: x.index):
                if abs(s.start_s - expected) > 1e-3:
                    errs.append(
                        f"shot {s.index} starts at {s.start_s:.3f}s, expected {expected:.3f}s"
                    )
                expected += s.duration_s
            if abs(expected - self.duration_s) > 0.05:
                errs.append(f"shots cover {expected:.3f}s but duration is {self.duration_s:.3f}s")
        for s in self.shots:
            if s.duration_s <= 0:
                errs.append(f"shot {s.index} has non-positive duration")
        # 每个主元素必须有独立轨迹
        primary_ids = {s.id for s in self.subjects if s.role != "background"}
        tracked = {t.element for t in self.tracks}
        missing = primary_ids - tracked
        if missing:
            errs.append(f"subjects without an element track: {sorted(missing)}")
        # 轨迹事件时间必须在片长内
        for t in self.tracks:
            for e in t.events:
                if e.t < -1e-6 or e.t > self.duration_s + 1e-6:
                    errs.append(
                        f"track {t.element} event at {e.t:.3f}s outside [0, {self.duration_s}]"
                    )
        return errs


# ── 自动补全:规则 + 模板 ───────────────────────────────────────────────
# 主题模板:关键词 → 元素/运动/物理事件。纯规则,零模型调用。

_THEME_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("弹跳", "跳", "bounce", "球"), "bounce"),
    (("水滴", "水塘", "水", "滴", "drop", "water"), "water"),
    (("积木", "搭", "砖", "block", "stack"), "blocks"),
    (("星星", "星", "star", "夜", "宇宙"), "star"),
    (("种子", "发芽", "长", "seed", "sprout", "花"), "seed"),
    (("分享", "轮流", "share", "turn"), "share"),
    (("情绪", "生气", "害怕", "难过", "emotion", "feel"), "emotion"),
]

# 每条主题:主体定义 + 运动原语 + 物理事件序列(相对分镜的比例位置)。
_THEME_TEMPLATES: dict[str, dict[str, Any]] = {
    "bounce": {
        "primary": ("小球", "circle", "#F4A261"),
        "secondary": ("地面", "bar", "#8AB17D"),
        "background": ("天空", "bar", "#E9F5DB"),
        "motion": "bounce",
        "heavy_kinds": ["impact", "impact", "impact"],
        "events": [
            (0.18, "drop", 1.0, {"g": 9.8, "h0": 0.72}),
            (0.34, "impact", 1.0, {"restitution": 0.62}),
            (0.46, "bounce", 0.62, {"restitution": 0.62}),
            (0.56, "impact", 0.62, {"restitution": 0.55}),
            (0.66, "bounce", 0.34, {"restitution": 0.55}),
            (0.78, "settle", 0.34, {"omega": 18.0, "zeta": 0.55}),
        ],
    },
    "water": {
        "primary": ("水滴", "drop", "#48CAE4"),
        "secondary": ("水面", "bar", "#90E0EF"),
        "background": ("水塘", "ring", "#CAF0F8"),
        "motion": "wave",
        "heavy_kinds": ["impact", "impact"],
        "events": [
            (0.22, "drop", 1.0, {"g": 9.8, "h0": 0.8}),
            (0.40, "impact", 1.0, {"restitution": 0.1}),
            (0.44, "wave", 0.9, {"rings": 3, "decay": 0.6}),
            (0.60, "cohere", 0.5, {"count": 8}),
            (0.80, "settle", 0.3, {"omega": 10.0, "zeta": 0.7}),
        ],
    },
    "blocks": {
        "primary": ("积木", "box", "#E76F51"),
        "secondary": ("第二块积木", "box", "#F4A261"),
        "background": ("地板", "bar", "#DDB892"),
        "motion": "fall",
        "heavy_kinds": ["impact", "impact"],
        "events": [
            (0.14, "drop", 1.0, {"g": 9.8, "h0": 0.6}),
            (0.30, "impact", 1.0, {"restitution": 0.15}),
            (0.42, "drop", 0.8, {"g": 9.8, "h0": 0.5}),
            (0.58, "impact", 0.9, {"restitution": 0.2}),
            (0.68, "roll", 0.7, {"mu": 0.35}),
            (0.80, "settle", 0.4, {"omega": 14.0, "zeta": 0.6}),
        ],
    },
    "star": {
        "primary": ("小星星", "star", "#FFD166"),
        "secondary": ("小狐狸", "circle", "#F28482"),
        "background": ("夜空", "bar", "#1D3557"),
        "motion": "float",
        "heavy_kinds": ["cohere", "impact"],
        "events": [
            (0.20, "float", 1.0, {"amp": 0.06, "freq": 0.9}),
            (0.45, "cohere", 0.8, {"count": 12}),
            (0.66, "impact", 0.7, {"restitution": 0.3}),
            (0.82, "settle", 0.4, {"omega": 8.0, "zeta": 0.8}),
        ],
    },
    "seed": {
        "primary": ("种子", "drop", "#8AB17D"),
        "secondary": ("泥土", "bar", "#6B705C"),
        "background": ("阳光", "bar", "#FFE8A3"),
        "motion": "float",
        "heavy_kinds": ["impact", "settle"],
        "events": [
            (0.18, "drop", 1.0, {"g": 9.8, "h0": 0.55}),
            (0.34, "impact", 0.8, {"restitution": 0.1}),
            (0.52, "float", 0.7, {"amp": 0.05, "freq": 0.6}),
            (0.72, "cohere", 0.6, {"count": 6}),
            (0.86, "settle", 0.4, {"omega": 9.0, "zeta": 0.75}),
        ],
    },
    "share": {
        "primary": ("小狐狸", "circle", "#F28482"),
        "secondary": ("小兔子", "circle", "#A8DADC"),
        "background": ("草地", "bar", "#B7E4C7"),
        "motion": "roll",
        "heavy_kinds": ["impact", "settle"],
        "events": [
            (0.20, "roll", 1.0, {"mu": 0.4}),
            (0.42, "impact", 0.7, {"restitution": 0.25}),
            (0.62, "float", 0.6, {"amp": 0.04, "freq": 0.7}),
            (0.82, "settle", 0.4, {"omega": 9.0, "zeta": 0.8}),
        ],
    },
    "emotion": {
        "primary": ("小主角", "circle", "#F4A261"),
        "secondary": ("心情", "ring", "#E76F51"),
        "background": ("房间", "bar", "#FFE5D9"),
        "motion": "press",
        "heavy_kinds": ["impact", "settle"],
        "events": [
            (0.20, "press", 1.0, {"amount": 0.3}),
            (0.44, "impact", 0.8, {"restitution": 0.3}),
            (0.62, "float", 0.7, {"amp": 0.05, "freq": 0.8}),
            (0.84, "settle", 0.4, {"omega": 8.0, "zeta": 0.85}),
        ],
    },
}

_DEFAULT_THEME = "bounce"


def detect_theme(prompt: str) -> str:
    """从一句话需求里判定主题(纯关键词规则)。"""
    low = prompt.lower()
    for kws, theme in _THEME_KEYWORDS:
        if any(k.lower() in low for k in kws):
            return theme
    return _DEFAULT_THEME


def _split_shots(duration_s: float, roles: list[str], bpm: float) -> list[tuple[str, float, float]]:
    """把总时长分成 起势→发展→收束,且每镜尽量落在整数拍上(切镜也上拍)。"""
    beat = 60.0 / bpm
    n = len(roles)
    # 目标权重:起势 0.3 / 发展 0.45 / 收束 0.25(两镜时 0.55/0.45)
    if n == 3:
        weights = [0.30, 0.45, 0.25]
    elif n == 2:
        weights = [0.55, 0.45]
    else:
        weights = [1.0 / n] * n
    out: list[tuple[str, float, float]] = []
    start = 0.0
    for i, (role, w) in enumerate(zip(roles, weights)):
        raw = duration_s * w
        # 吸附到最近拍(最后一镜精确补齐剩余)
        beats = max(1, round(raw / beat))
        dur = beats * beat
        if i == n - 1:
            dur = duration_s - start
        out.append((role, start, dur))
        start += dur
    return out


def _heavy_beats_for(duration_s: float, bpm: float, kinds: list[str]) -> list[float]:
    """在片长内按主题的重动作种类铺开重拍时间点。"""
    beat = 60.0 / bpm
    n_beats = max(1, int(duration_s / beat))
    # 重拍倾向:每 2 拍一个候选,取前 len(kinds) 个,并留出起势/收束的呼吸。
    candidates = [b for b in range(2, n_beats - 1, 2)]
    chosen = candidates[: len(kinds)] or [max(1, n_beats // 2)]
    return [round(b * beat, 4) for b in chosen]


def autofill(
    prompt: str,
    *,
    line: str = "explainer",
    duration_s: float = 8.0,
    aspect: str = "16:9",
    fps: int = 30,
    bpm: float | None = None,
    seed: int | None = None,
    references: list[dict[str, Any]] | None = None,
    audience: str | None = None,
) -> DirectorBrief:
    """从一句话需求生成完整导演层 brief(规则+模板,零付费调用,确定性)。

    Args:
        prompt: 一句话需求,例如 "小球学弹跳"。
        line: 产品线,见 ``LINE_CATALOG``。
        references: 参考列表,每条 ``{"kind": ..., "ref": ..., "constraints": [...]}``。

    Returns:
        校验通过的 ``DirectorBrief``。
    """
    if line not in LINE_CATALOG:
        raise ValueError(f"unknown line {line!r}; known: {sorted(LINE_CATALOG)}")
    if aspect not in ("16:9", "9:16", "1:1"):
        raise ValueError(f"unsupported aspect {aspect!r}")
    if not (2.0 <= duration_s <= 600.0):
        raise ValueError(f"duration_s out of range: {duration_s}")

    cfg = LINE_CATALOG[line]
    theme = detect_theme(prompt)
    tmpl = _THEME_TEMPLATES[theme]
    bpm = float(bpm if bpm is not None else cfg["bpm"])
    if not (30.0 <= bpm <= 240.0):
        raise ValueError(f"bpm out of range: {bpm}")
    seed = int(seed if seed is not None else _stable_seed(prompt, line, duration_s, aspect))

    # 幼儿受众 → 注入幼儿硬性禁止项
    kids = (audience is None and line != "montage") or (
        audience is not None and ("幼儿" in audience or "kids" in audience.lower())
    )
    audience = audience or ("2–6 岁幼儿" if kids else "通用观众")

    # ── 分镜 ──
    shot_rows = _split_shots(duration_s, cfg["shot_roles"], bpm)
    heavy_times = _heavy_beats_for(duration_s, bpm, tmpl["heavy_kinds"])
    heavy_idx = 0
    tasks = _shot_tasks(theme, prompt)
    shots: list[ShotPlan] = []
    for i, (role, start, dur) in enumerate(shot_rows):
        hb: list[int] = []
        while heavy_idx < len(heavy_times) and heavy_times[heavy_idx] < start + dur:
            hb.append(heavy_idx)
            heavy_idx += 1
        shots.append(
            ShotPlan(
                index=i,
                role=role,
                main_task=tasks[i] if i < len(tasks) else f"{role}:推进核心信息",
                start_s=round(start, 4),
                duration_s=round(dur, 4),
                main_subject="primary",
                heavy_beats=hb,
            )
        )

    # ── 主体/次主体/背景 ──
    p_name, p_shape, p_color = tmpl["primary"]
    s_name, s_shape, s_color = tmpl["secondary"]
    b_name, b_shape, b_color = tmpl["background"]
    portrait = aspect == "9:16"
    subjects = [
        Subject(
            "primary",
            p_name,
            "primary",
            "fg" if not portrait else "mid",
            p_shape,
            p_color,
            220 if not portrait else 260,
            0.50,
            0.34 if not portrait else 0.40,
        ),
        Subject(
            "secondary",
            s_name,
            "secondary",
            "mid",
            s_shape,
            s_color,
            300 if not portrait else 320,
            0.50,
            0.74,
        ),
        Subject("background", b_name, "background", "bg", b_shape, b_color, 1600, 0.50, 0.50),
    ]

    # ── 前/中/后景 ──
    layers = [
        Layer("fg", "fg", 1.25, 0.0, 1.00),
        Layer("mid", "mid", 0.65, 0.0, 0.94),
        Layer("bg", "bg", 0.30, 1.6, 0.86),
    ]

    # ── 每个元素独立运动轨迹(事件时间已含错相 delay,并吸附到拍点) ──
    # B: 重动作吸附到重拍网格(预备略早 / 撞击准拍 / 碎屑略晚),
    # 使导演版 brief 天然满足 beat_alignment_rate ≥ 0.70。
    snap_grid = _build_grid(bpm, fps, duration_s)
    tmpl_event_dicts = [
        {"t": round(t_rel * duration_s, 4), "kind": kind, "magnitude": mag}
        for t_rel, kind, mag, _p in tmpl["events"]
    ]
    # snap_all 是按索引保序返回的(重动作吸附到重拍 + 类型微偏移,非重动作保持原时间),
    # 因此用 zip 按下标配对,而不是按 (t, kind) 回查(原值已被吸附覆盖)。
    snapped_times = [e["t"] for e in _snap_all(tmpl_event_dicts, snap_grid)]
    snapped_frames = [int(e.get("snapped_frame", -1)) for e in _snap_all(tmpl_event_dicts, snap_grid)]

    tracks: list[ElementTrack] = []
    primary_events: list[MotionEvent] = []
    for (t_rel, kind, mag, params), snapped_t, snapped_f in zip(
        tmpl["events"], snapped_times, snapped_frames
    ):
        raw_t = round(t_rel * duration_s, 4)
        ep = dict(params)
        if snapped_f >= 0:
            ep["snapped_frame"] = snapped_f
        primary_events.append(MotionEvent(snapped_t, kind, mag, ep))
    tracks.append(ElementTrack("primary", tmpl["motion"], primary_events, start_delay_frames=0))

    # 次主体:延迟若干帧,响应主体的重动作(次级响应)
    delay_frames = max(2, round(fps * 0.10))
    secondary_events: list[MotionEvent] = []
    for (t_rel, kind, mag, params), snapped_t in zip(tmpl["events"], snapped_times):
        if kind in ("impact", "wave", "cohere"):
            secondary_events.append(
                MotionEvent(
                    round(snapped_t + delay_frames / fps, 4), kind, mag * 0.5, dict(params)
                )
            )
    tracks.append(
        ElementTrack(
            "secondary", "spring_response", secondary_events, start_delay_frames=delay_frames
        )
    )
    # 背景:漂浮/视差,恒定微动(避免静止冻结)
    bg_events = [
        MotionEvent(0.0, "float", 0.15, {"amp": 0.012, "freq": 0.35}),
        MotionEvent(round(duration_s, 4), "float", 0.15, {"amp": 0.012, "freq": 0.35}),
    ]
    tracks.append(ElementTrack("background", "float", bg_events, start_delay_frames=0))

    # ── 物理事件 ──
    physics_events: list[dict[str, Any]] = []
    kind_to_phys = {
        "drop": "gravity",
        "impact": "collision",
        "bounce": "bounce",
        "roll": "roll_inertia",
        "settle": "spring",
        "wave": "water_wave",
        "cohere": "particles_cohere",
        "float": "buoyancy",
        "press": "soft_body",
    }
    for e in primary_events:
        physics_events.append(
            {
                "t": e.t,
                "kind": kind_to_phys.get(e.kind, e.kind),
                "target": "primary",
                "params": dict(e.params),
            }
        )

    # ── 主光 ──
    key_light = KeyLight(
        azimuth_deg=float(cfg["default_light_deg"]),
        elevation_deg=38.0,
        color="#FFF3D6",
        intensity=1.0,
        shadow_softness=0.55,
    )

    # ── 参考(范围扩大 §3) ──
    refs: list[Reference] = []
    for r in references or []:
        refs.append(
            Reference(kind=r["kind"], ref=r["ref"], constraints=list(r.get("constraints", [])))
        )

    # ── 音频事件:从运动长出 ──
    audio_events = _audio_from_motion(primary_events, duration_s)

    # ── 禁止项 & 验收标准 ──
    prohibitions = list(GENERIC_PROHIBITIONS)
    if kids:
        prohibitions = list(KIDS_PROHIBITIONS) + prohibitions
    for r in refs:
        for c in r.constraints:
            prohibitions.append(f"参考约束[{r.ref}]: {c}")

    acceptance = _acceptance(kids, line)
    for r in refs:
        acceptance.append(f"参考[{r.ref}]的约束已满足")

    brief = DirectorBrief(
        id=f"{line}-{theme}-{seed:08x}",
        line=line,
        audience=audience,
        core_message=_core_message(theme, prompt),
        prompt=prompt,
        duration_s=float(duration_s),
        aspect=aspect,
        fps=int(fps),
        bpm=bpm,
        seed=seed,
        shots=shots,
        subjects=subjects,
        layers=layers,
        tracks=tracks,
        physics_events=physics_events,
        key_light=key_light,
        references=refs,
        audio_events=audio_events,
        prohibitions=prohibitions,
        acceptance=acceptance,
        line_params={"theme": theme, "portrait": portrait},
    )
    errs = brief.validate()
    if errs:
        raise ValueError("autofill produced an invalid brief: " + "; ".join(errs))
    return brief


def _shot_tasks(theme: str, prompt: str) -> list[str]:
    base = {
        "bounce": [
            "起势:小球被举起,预备",
            "发展:落下—撞击—弹跳—能量衰减",
            "收束:小球停稳,高光轻动",
        ],
        "water": ["起势:水滴成形、悬停", "发展:坠落—入水—涟漪扩散", "收束:水面归静,光斑收束"],
        "blocks": ["起势:第一块积木落下", "发展:第二块搭上—失衡—倒下", "收束:积木落定,灰尘沉降"],
        "star": ["起势:夜空亮起,小星星出现", "发展:星星聚集—被狐狸看见", "收束:星光柔和,狐狸仰望"],
        "seed": ["起势:种子落进泥土", "发展:吸水—发芽—向上生长", "收束:嫩芽展开,迎光"],
        "share": ["起势:小狐狸拿着玩具", "发展:小兔子也想玩—轮流", "收束:两个朋友一起玩"],
        "emotion": ["起势:小主角遇到问题", "发展:情绪升起—被识别—平复", "收束:情绪安放,微笑"],
    }.get(theme, ["起势", "发展", "收束"])
    return base


def _core_message(theme: str, prompt: str) -> str:
    return {
        "bounce": "失败了再试一次,就会弹得更高",
        "water": "一滴水也能荡开整个水塘",
        "blocks": "搭高会倒,倒了再搭",
        "star": "再小的光也能被看见",
        "seed": "耐心等待,种子会发芽",
        "share": "分享让快乐变多",
        "emotion": "说出感受,情绪就会变小",
    }.get(theme, prompt)


def _audio_from_motion(events: list[MotionEvent], duration_s: float) -> list[AudioEvent]:
    """SFX 从运动长出:速度峰→whoosh, 冲量→impact, 接触帧→点击/落地。"""
    out: list[AudioEvent] = []
    # BGM 全程铺底(先声明)
    out.append(AudioEvent(0.0, "bgm", sfx_id="bgm:warm_pad", gain_db=-19.0))
    kind_map = {
        "drop": ("sfx", "whoosh_air_down", -9.0),
        "impact": ("sfx", "impact", -7.0),
        "bounce": ("sfx", "pop", -11.0),
        "roll": ("sfx", "whoosh_air_up", -13.0),
        "wave": ("sfx", "chime", -12.0),
        "cohere": ("sfx", "chime", -13.0),
        "settle": ("sfx", "ding", -14.0),
        "float": ("sfx", "chime", -18.0),
        "press": ("sfx", "impact", -12.0),
    }
    for e in events:
        mapped = kind_map.get(e.kind)
        if not mapped:
            continue
        kind, sfx_id, gain = mapped
        out.append(
            AudioEvent(
                t=round(e.t, 4),
                kind=kind,
                sfx_id=sfx_id,
                gain_db=gain + (e.magnitude - 1.0) * 3.0,
                source_motion=e.kind,
            )
        )
    # BGM ducking:在重音(impact)处给人声/主音让路
    for e in events:
        if e.kind == "impact":
            out.append(AudioEvent(t=round(max(0.0, e.t - 0.12), 4), kind="bgm_duck", duck_db=-7.0))
    out.sort(key=lambda a: (a.t, a.kind))
    return out


def _acceptance(kids: bool, line: str) -> list[str]:
    acc = [
        "重动作与重拍偏差 ≤ 1 帧",
        "同一时刻只有一个主事件(注意力中心唯一)",
        "关键物体静止时高光/受光面/阴影仍有微动(不冻结)",
        "主光方向全场一致(方位角偏差 ≤ 8°)",
        "同一 seed 两次渲染 sha256 一致",
        f"line={line} 适配器产出被该线入口接受",
    ]
    if kids:
        acc += [
            "kids_gate PASS(单镜 ≥2.5s, 响度 -16±1 LUFS, 真峰值 ≤-1.5 dBTP)",
            "无禁止项命中(居中大字/霓虹渐变/全体同步淡入/整幅抖动)",
        ]
    return acc


def write_example_briefs(out_dir: str | Path) -> list[Path]:
    """写出每个产品线一支示例 brief(供适配器/审片 HTML 使用)。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    samples = [
        ("explainer", "小球学弹跳", 8.0, "16:9"),
        ("character_narrative", "小狐狸学分享", 10.0, "9:16"),
        ("scene3d", "水滴落进小水塘", 9.0, "16:9"),
        ("montage", "种子发芽的纪录短片", 12.0, "16:9"),
    ]
    paths: list[Path] = []
    for line, prompt, dur, aspect in samples:
        b = autofill(prompt, line=line, duration_s=dur, aspect=aspect)
        p = out / f"{b.id}.json"
        b.save(p)
        paths.append(p)
    return paths


__all__ = [
    "LINE_CATALOG",
    "KIDS_PROHIBITIONS",
    "GENERIC_PROHIBITIONS",
    "Reference",
    "ShotPlan",
    "Subject",
    "Layer",
    "MotionEvent",
    "ElementTrack",
    "KeyLight",
    "AudioEvent",
    "DirectorBrief",
    "detect_theme",
    "autofill",
    "write_example_briefs",
]
