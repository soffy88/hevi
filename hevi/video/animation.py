"""可寻址动画系统 — 对标 HyperFrames Frame Adapter 模式。

核心:GSAP timeline seek 到任意帧。任何能 seek 到指定帧的运行时都能接入。

用法:
    from hevi.video.animation import GsapTimelineBuilder

    builder = GsapTimelineBuilder()
    builder.from_element(".title", opacity=0, y=-50, duration=1.0)
    builder.to_element(".subtitle", opacity=1, duration=0.5, delay=0.5)

    script = builder.build()  # → GSAP JS 代码

对标: HyperFrames /hyperframes-animation skill
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "GsapTimelineBuilder",
    "AnimationStep",
    "build_gsap_script",
    "AnimationEase",
]


class AnimationEase:
    """GSAP 缓动函数。"""
    LINEAR = "none"
    EASE_IN = "power2.in"
    EASE_OUT = "power2.out"
    EASE_IN_OUT = "power2.inOut"
    ELASTIC = "elastic.out(1, 0.3)"
    BOUNCE = "bounce.out"
    BACK = "back.out(1.7)"


@dataclass
class AnimationStep:
    """动画步骤。"""
    method: str  # "from" / "to" / "fromTo" / "set"
    selector: str
    props: dict[str, Any]
    duration: float = 1.0
    delay: float = 0.0
    ease: str = AnimationEase.EASE_OUT
    stagger: float | None = None


class GsapTimelineBuilder:
    """GSAP Timeline 构建器。

    构建 GSAP JS 代码,可注入到 HyperFrames HTML composition 中。
    """

    def __init__(self, timeline_var: str = "tl"):
        self.timeline_var = timeline_var
        self.steps: list[AnimationStep] = []
        self._paused = True

    def from_element(
        self,
        selector: str,
        *,
        opacity: float | None = None,
        x: float | None = None,
        y: float | None = None,
        scale: float | None = None,
        rotation: float | None = None,
        duration: float = 1.0,
        delay: float = 0.0,
        ease: str = AnimationEase.EASE_OUT,
        stagger: float | None = None,
    ) -> "GsapTimelineBuilder":
        """添加 from() 步骤(从指定状态动画到当前状态)。"""
        props: dict[str, Any] = {}
        if opacity is not None:
            props["opacity"] = opacity
        if x is not None:
            props["x"] = x
        if y is not None:
            props["y"] = y
        if scale is not None:
            props["scale"] = scale
        if rotation is not None:
            props["rotation"] = rotation

        self.steps.append(AnimationStep(
            method="from",
            selector=selector,
            props=props,
            duration=duration,
            delay=delay,
            ease=ease,
            stagger=stagger,
        ))
        return self

    def to_element(
        self,
        selector: str,
        *,
        opacity: float | None = None,
        x: float | None = None,
        y: float | None = None,
        scale: float | None = None,
        rotation: float | None = None,
        duration: float = 1.0,
        delay: float = 0.0,
        ease: str = AnimationEase.EASE_OUT,
    ) -> "GsapTimelineBuilder":
        """添加 to() 步骤(从当前状态动画到指定状态)。"""
        props: dict[str, Any] = {}
        if opacity is not None:
            props["opacity"] = opacity
        if x is not None:
            props["x"] = x
        if y is not None:
            props["y"] = y
        if scale is not None:
            props["scale"] = scale
        if rotation is not None:
            props["rotation"] = rotation

        self.steps.append(AnimationStep(
            method="to",
            selector=selector,
            props=props,
            duration=duration,
            delay=delay,
            ease=ease,
        ))
        return self

    def set_element(
        self,
        selector: str,
        *,
        opacity: float | None = None,
        x: float | None = None,
        y: float | None = None,
    ) -> "GsapTimelineBuilder":
        """添加 set() 步骤(立即设置,无动画)。"""
        props: dict[str, Any] = {}
        if opacity is not None:
            props["opacity"] = opacity
        if x is not None:
            props["x"] = x
        if y is not None:
            props["y"] = y

        self.steps.append(AnimationStep(
            method="set",
            selector=selector,
            props=props,
        ))
        return self

    def build(self) -> str:
        """构建 GSAP JS 代码。"""
        lines = [
            f"const {self.timeline_var} = gsap.timeline({{ paused: {str(self._paused).lower()} }});"
        ]

        for step in self.steps:
            props_json = json.dumps(step.props)

            if step.method == "set":
                lines.append(f'{self.timeline_var}.set("{step.selector}", {props_json});')
            else:
                duration_str = f", {step.duration}" if step.duration != 1.0 else ""
                ease_str = f', ease: "{step.ease}"' if step.ease else ""
                delay_str = f", delay: {step.delay}" if step.delay > 0 else ""
                stagger_str = f", stagger: {step.stagger}" if step.stagger else ""

                time_str = duration_str + ease_str + delay_str + stagger_str
                lines.append(
                    f'{self.timeline_var}.{step.method}("{step.selector}", {props_json}{time_str});'
                )

        # 注册到 window.__timelines(HyperFrames 约定)
        lines.append(f'window.__timelines = window.__timelines || {{}};')
        lines.append(f'window.__timelines["root"] = {self.timeline_var};')

        return "\n".join(lines)


def build_gsap_script(builder: GsapTimelineBuilder) -> str:
    """便捷函数:从 builder 生成完整 GSAP 脚本。"""
    return builder.build()
