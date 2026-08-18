"""Manim SceneIR 编译器 —— 结构化镜头 → 可渲染的 Manim 源码(纯逻辑,无 IO)。

「代码即画面」的安全入口:LLM / 确稿台只产 SceneIR(配方 + 公式 + 条目),
本模块确定性编译成 ManimCE(默认)或 ManimGL 源码。不在这里 ``exec``。

纪律:
  - 不翻译、不调网、不写盘。
  - 默认 ``Text`` 而不是 ``MathTex``/``Tex``:后者依赖本机 LaTeX,共享宿主机常没有。
  - 主题默认 3b1b 深蓝底 + 黄/白字。
  - 产出的源码必须过 ``hevi.providers.manim.sandbox`` 白名单。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

RECIPES: tuple[str, ...] = (
    "equation",
    "transform",
    "list_reveal",
    "title_card",
    "number_line",
    "axes_plot",
    "comparison",
)
THEMES: tuple[str, ...] = ("3b1b", "light")
ENGINES: tuple[str, ...] = ("ce", "gl")

_DEFAULT_BG = {"3b1b": "#1a1a2e", "light": "#f4f1ea"}
_DEFAULT_FG = {"3b1b": "#ece6dd", "light": "#222222"}
_ACCENT = {"3b1b": "#ffff00", "light": "#b58900"}

_LATEX = re.compile(r"\$([^$]+)\$|\\\[(.+?)\\\]")
_ARROW = re.compile(r"(.+?)(?:→|->|=>|⇒)(.+)", re.DOTALL)
_BULLET = re.compile(r"(?:^|\n)\s*(?:\d+[\.、]|[-•])\s+(.+)")


@dataclass
class ManimSceneIR:
    """结构化 Manim 镜头。to_dict() 可进 cue.visual_config['scene']。"""

    recipe: str = "equation"
    title: str = ""
    tex: str = ""
    tex_to: str = ""
    bullets: list[str] = field(default_factory=list)
    series: list[float] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    left_label: str = ""
    right_label: str = ""
    duration_s: float = 5.0
    theme: str = "3b1b"
    scene_name: str = "HeviScene"
    use_mathtex: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipe": self.recipe,
            "title": self.title,
            "tex": self.tex,
            "tex_to": self.tex_to,
            "bullets": list(self.bullets),
            "series": list(self.series),
            "labels": list(self.labels),
            "left_label": self.left_label,
            "right_label": self.right_label,
            "duration_s": self.duration_s,
            "theme": self.theme,
            "scene_name": self.scene_name,
            "use_mathtex": self.use_mathtex,
        }

    @staticmethod
    def from_dict(data: Any) -> ManimSceneIR:
        if isinstance(data, ManimSceneIR):
            return data
        if not isinstance(data, dict):
            return draft_scene_ir(str(data or ""))
        recipe = str(data.get("recipe") or "equation")
        if recipe not in RECIPES:
            recipe = "equation"
        theme = str(data.get("theme") or "3b1b")
        if theme not in THEMES:
            theme = "3b1b"
        name = _safe_ident(str(data.get("scene_name") or "HeviScene"))
        bullets = [str(item).strip() for item in (data.get("bullets") or []) if str(item).strip()]
        series: list[float] = []
        for item in data.get("series") or []:
            try:
                series.append(float(item))
            except (TypeError, ValueError):
                continue
        labels = [str(item) for item in (data.get("labels") or [])]
        try:
            duration = float(data.get("duration_s") or 5.0)
        except (TypeError, ValueError):
            duration = 5.0
        return ManimSceneIR(
            recipe=recipe,
            title=str(data.get("title") or ""),
            tex=str(data.get("tex") or data.get("formula") or ""),
            tex_to=str(data.get("tex_to") or data.get("formula_to") or ""),
            bullets=bullets[:8],
            series=series[:24],
            labels=labels[:24],
            left_label=str(data.get("left_label") or ""),
            right_label=str(data.get("right_label") or ""),
            duration_s=min(max(duration, 1.0), 60.0),
            theme=theme,
            scene_name=name,
            use_mathtex=bool(data.get("use_mathtex")),
        )


def _safe_ident(name: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]", "", name) or "HeviScene"
    if cleaned[0].isdigit():
        cleaned = f"S{cleaned}"
    return cleaned[:48]


def draft_scene_ir(
    text: str,
    *,
    title: str = "",
    duration_s: float = 5.0,
    theme: str = "3b1b",
) -> ManimSceneIR:
    """旁白/主题 → SceneIR。无 LLM,供装配层在 cue 没带 scene 时补全。"""
    body = (text or "").strip()
    formulas = [a or b for a, b in _LATEX.findall(body)]
    bullets = [match.group(1).strip() for match in _BULLET.finditer(body)]
    first = re.split(r"[。！？!?\n]", body)[0].strip()[:36]
    heading = (title or first).strip()
    duration = min(max(float(duration_s), 1.0), 60.0)
    if len(formulas) >= 2:
        return ManimSceneIR(
            recipe="transform",
            title=heading,
            tex=formulas[0],
            tex_to=formulas[1],
            duration_s=duration,
            theme=theme,
        )
    if len(formulas) == 1:
        return ManimSceneIR(
            recipe="equation",
            title=heading,
            tex=formulas[0],
            duration_s=duration,
            theme=theme,
        )
    arrow = _ARROW.search(body)
    if arrow:
        return ManimSceneIR(
            recipe="transform",
            title=heading,
            tex=arrow.group(1).strip()[:80],
            tex_to=arrow.group(2).strip()[:80],
            duration_s=duration,
            theme=theme,
        )
    if len(bullets) >= 2:
        return ManimSceneIR(
            recipe="list_reveal",
            title=heading,
            bullets=bullets[:6],
            duration_s=duration,
            theme=theme,
        )
    return ManimSceneIR(
        recipe="title_card",
        title=heading or "HEVI",
        tex=body[:80],
        duration_s=duration,
        theme=theme,
    )


def resolve_scene_ir(cue_like: Any, *, duration_s: float | None = None) -> ManimSceneIR:
    """从 cue / visual_config / 旁白抽出 SceneIR。"""
    cfg: dict[str, Any] = {}
    text = ""
    estimate = duration_s
    if hasattr(cue_like, "visual_config"):
        raw_cfg = getattr(cue_like, "visual_config", None) or {}
        cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
        text = str(getattr(cue_like, "text", "") or "")
        if estimate is None:
            estimate = getattr(cue_like, "time_estimate_s", None)
    elif isinstance(cue_like, dict):
        raw_cfg = cue_like.get("visual_config") or {}
        cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
        text = str(cue_like.get("text") or "")
        if estimate is None:
            estimate = cue_like.get("time_estimate_s")
        # provider 直传 to_dict() 时配方在顶层,不在 visual_config 里。
        if not any(cfg.get(key) for key in ("recipe", "tex", "scene", "bullets")) and (
            cue_like.get("recipe") or cue_like.get("tex") or cue_like.get("bullets")
        ):
            cfg = cue_like
    else:
        text = str(cue_like or "")
    scene = cfg.get("scene")
    if isinstance(scene, (dict, ManimSceneIR)):
        ir = ManimSceneIR.from_dict(scene)
    elif any(cfg.get(key) for key in ("recipe", "tex", "formula", "bullets")):
        ir = ManimSceneIR.from_dict(cfg)
    else:
        ir = draft_scene_ir(text, duration_s=float(estimate or 5.0))
    if estimate and not (isinstance(scene, dict) and scene.get("duration_s")):
        ir.duration_s = min(max(float(estimate), 1.0), 60.0)
    return ir


def compile_manim_source(ir: ManimSceneIR | dict[str, Any], *, engine: str = "ce") -> str:
    """SceneIR → Manim 源码字符串。engine=ce|gl。"""
    scene = ir if isinstance(ir, ManimSceneIR) else ManimSceneIR.from_dict(ir)
    backend = engine if engine in ENGINES else "ce"
    header = "from manimlib import *\n\n" if backend == "gl" else "from manim import *\n\n"
    math_cls = "Tex" if backend == "gl" else "MathTex"
    token_cls = math_cls if scene.use_mathtex else "Text"
    bg = _DEFAULT_BG.get(scene.theme, _DEFAULT_BG["3b1b"])
    fg = _DEFAULT_FG.get(scene.theme, _DEFAULT_FG["3b1b"])
    accent = _ACCENT.get(scene.theme, _ACCENT["3b1b"])
    body = _recipe_body(scene, token_cls=token_cls, fg=fg, accent=accent)
    wait_tail = max(scene.duration_s * 0.15, 0.4)
    return (
        f"{header}"
        f"class {scene.scene_name}(Scene):\n"
        f"    def construct(self):\n"
        f"        self.camera.background_color = {bg!r}\n"
        f"{body}"
        f"        self.wait({wait_tail:.2f})\n"
    )


def _recipe_body(scene: ManimSceneIR, *, token_cls: str, fg: str, accent: str) -> str:
    title = scene.title.strip()
    tex = scene.tex.strip() or title or "HEVI"
    tex_to = scene.tex_to.strip()
    write_t = max(min(scene.duration_s * 0.35, 2.4), 0.6)
    hold_t = max(min(scene.duration_s * 0.25, 2.0), 0.4)
    lines: list[str] = []
    if title and scene.recipe != "title_card":
        lines.append(f"        title = Text({title!r}, font_size=36, color={accent!r})")
        lines.append("        title.to_edge(UP)")
        lines.append("        self.play(FadeIn(title), run_time=0.5)")
    if scene.recipe == "transform" and tex_to:
        lines.append(f"        src = {token_cls}({tex!r}, font_size=64, color={fg!r})")
        lines.append(f"        dst = {token_cls}({tex_to!r}, font_size=64, color={accent!r})")
        lines.append(f"        self.play(Write(src), run_time={write_t:.2f})")
        lines.append(f"        self.play(Transform(src, dst), run_time={hold_t:.2f})")
        return "\n".join(lines) + "\n"
    if scene.recipe == "list_reveal":
        items = scene.bullets or [tex]
        lines.append("        group = VGroup()")
        lines.extend(
            f"        group.add(Text({item!r}, font_size=32, color={fg!r}))"
            for item in items[:6]
        )
        lines.append("        group.arrange(DOWN, aligned_edge=LEFT, buff=0.35)")
        lines.append("        group.move_to(ORIGIN)")
        step = write_t / max(len(items), 1)
        lines.append("        for item in group:")
        lines.append(f"            self.play(FadeIn(item, shift=RIGHT * 0.2), run_time={step:.2f})")
        return "\n".join(lines) + "\n"
    if scene.recipe == "comparison":
        left = scene.left_label or tex
        right = scene.right_label or tex_to or title
        lines.append(f"        left = Text({left!r}, font_size=40, color={fg!r})")
        lines.append(f"        right = Text({right!r}, font_size=40, color={accent!r})")
        lines.append("        left.shift(LEFT * 3)")
        lines.append("        right.shift(RIGHT * 3)")
        lines.append(f"        self.play(FadeIn(left), FadeIn(right), run_time={write_t:.2f})")
        return "\n".join(lines) + "\n"
    if scene.recipe == "number_line":
        lines.append(
            "        line = NumberLine("
            "x_range=[-4, 4, 1], length=10, include_numbers=True)"
        )
        lines.append(f"        dot = Dot(color={accent!r}).move_to(line.n2p(0))")
        lines.append("        self.play(Create(line), run_time=0.8)")
        lines.append("        self.play(FadeIn(dot), run_time=0.3)")
        lines.append("        self.play(dot.animate.move_to(line.n2p(2)), run_time=1.0)")
        return "\n".join(lines) + "\n"
    if scene.recipe == "axes_plot":
        series = scene.series or [0.4, 1.1, 0.8, 1.6, 1.2]
        pairs = ", ".join(f"({index}, {value:.4f})" for index, value in enumerate(series))
        lines.append(
            "        axes = Axes(x_range=[0, 6, 1], y_range=[0, 3, 1],"
            " x_length=8, y_length=4)"
        )
        lines.append(
            f"        dots = VGroup(*[Dot(axes.c2p(x, y), color={accent!r})"
            f" for x, y in ({pairs},)])"
        )
        lines.append("        self.play(Create(axes), run_time=0.8)")
        lines.append(f"        self.play(FadeIn(dots), run_time={write_t:.2f})")
        return "\n".join(lines) + "\n"
    # title_card / equation 默认:写出主句
    size = 48 if scene.recipe == "title_card" else 64
    lines.append(f"        main = {token_cls}({tex!r}, font_size={size}, color={fg!r})")
    lines.append(f"        self.play(Write(main), run_time={write_t:.2f})")
    if scene.recipe == "title_card" and title and title != tex:
        lines.append(f"        sub = Text({title!r}, font_size=32, color={accent!r})")
        lines.append("        sub.next_to(main, UP, buff=0.5)")
        lines.append("        self.play(FadeIn(sub), run_time=0.5)")
    return "\n".join(lines) + "\n"
