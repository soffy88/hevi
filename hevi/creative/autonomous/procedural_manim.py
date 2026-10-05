"""P2-B1 的两个配方 + Manim backend 适配。

配方各自声明**诚实**的 `substitute_kind`,且**不得**读 requirement 的禁止清单:

| recipe | substitute_kind | 是否标题卡 |
|---|---|---|
| `explanatory_motion_graphics` | `motion_graphics` | 否 —— 有动画元素的示意画面 |
| `generic_stars` | `generic_stars` | 否 —— 但正是 p0 声明要禁的装饰性填充 |

这组划分解释了 B0 为什么必须先做:**示意性画面可以合理满足「解释某个概念」的需求,
装饰性填充不能。** 被禁止的替代物正是把两者区分开的机制。
"""

from __future__ import annotations

from pathlib import Path

from hevi.creative.autonomous.acquire_procedural import (
    ProceduralRecipe,
)

_EXPLANATORY_TEMPLATE = '''from manim import *


class ProceduralVisual(Scene):
    """由 requirement 驱动的示意画面:一个被标注的运动元素。"""

    def construct(self):
        label = Text({label!r}, font_size=28, color=WHITE)
        core = Dot(radius=0.10, color=YELLOW)
        ring = Circle(radius=0.34, color=BLUE, stroke_width=3)
        group = VGroup(core, ring)
        title = Text({title!r}, font_size=22, color=GREY_B).to_edge(UP)
        self.add(title, group, label.next_to(group, DOWN))
        self.play(ring.animate.set_opacity(0.35).scale(1.35), run_time=0.8)
        self.play(group.animate.scale(1.6), run_time=0.9)
        self.wait(0.3)
'''

_GENERIC_STARS_TEMPLATE = '''from manim import *


class ProceduralVisual(Scene):
    """装饰性星空填充 —— 正是 p0 VisualIntent 声明的 forbidden substitute。"""

    def construct(self):
        stars = VGroup(*[
            Dot(radius=0.01 + 0.02 * (i % 3) / 3.0,
                color=random_color() if False else WHITE).shift(
                np.array([random.uniform(-7, 7), random.uniform(-4, 4), 0.0]))
            for i in range(90)
        ])
        self.add(stars)
        self.play(stars.animate.shift(UP * 0.4), run_time=1.2)
        self.wait(0.8)
'''


def _explanatory_source(requirement: object, slug: str) -> str:
    query = requirement.query() or requirement.semantic_role.value  # type: ignore[attr-defined]
    return _EXPLANATORY_TEMPLATE.format(label=query[:40], title=slug[:48])


def _generic_stars_source(requirement: object, slug: str) -> str:
    """通用星空:与 query 无关 —— 这正是它「通用」的地方,也是被禁的原因。"""
    return _GENERIC_STARS_TEMPLATE


EXPLANATORY_MOTION_GRAPHICS = ProceduralRecipe(
    recipe_id="explanatory_motion_graphics",
    substitute_kind="motion_graphics",
    build_source=_explanatory_source,
)

GENERIC_STARS = ProceduralRecipe(
    recipe_id="generic_stars",
    substitute_kind="generic_stars",
    build_source=_generic_stars_source,
)

#: 第一版只这两个配方,且顺序即尝试顺序。
DEFAULT_PROCEDURAL_RECIPES: tuple[ProceduralRecipe, ...] = (
    EXPLANATORY_MOTION_GRAPHICS,
    GENERIC_STARS,
)


class ManimBackend:
    """把配方源码交给 canonical Manim 能力 `manim_generate` 渲染。

    本类**不**自己 spawn manim CLI —— 渲染器归 provider 层。
    窄接口刻意只有 `render`,这样测试可以注入替身而绕过真实渲染成本,
    生产路径则直接打到真实能力。
    """

    backend_id = "manim"

    def __init__(self, *, quality: str = "low") -> None:
        self._quality = quality

    async def render(self, *, source_code: str, output_path: Path, duration_s: float,
                     width: int, height: int, fps: int) -> Path:
        from hevi.providers.manim.provider import manim_generate

        return await manim_generate(
            code=source_code, output_path=output_path, duration_s=duration_s,
            width=width, height=height, fps=fps, quality=self._quality)


__all__ = [
    "DEFAULT_PROCEDURAL_RECIPES",
    "EXPLANATORY_MOTION_GRAPHICS",
    "GENERIC_STARS",
    "ManimBackend",
]