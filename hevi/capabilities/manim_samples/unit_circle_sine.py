"""Unit circle -> sine wave, 3Blue1Brown style.

Sample scene for the ``video.manim_render`` capability: a point travels
around the unit circle while its height traces out the sine wave on a
pair of axes to the right.  Black background, faded grid, real LaTeX
formulae (MathTex).  Render with::

    python -m hevi.capabilities.manim_render \
        hevi/capabilities/manim_samples/unit_circle_sine.py \
        UnitCircleSine --quality medium --out out_dir
"""

import numpy as np

from manim import (
    BLUE,
    GREEN,
    GREY_B,
    WHITE,
    YELLOW,
    Axes,
    Circle,
    DashedLine,
    Dot,
    FadeIn,
    FadeOut,
    Line,
    MathTex,
    NumberPlane,
    Scene,
    Text,
    TracedPath,
    ValueTracker,
    Create,
    DOWN,
    LEFT,
    RIGHT,
    UP,
    always_redraw,
)


class UnitCircleSine(Scene):
    def construct(self):
        # --- title ---------------------------------------------------
        title = MathTex(r"y = \sin\theta", color=YELLOW).scale(1.6)
        subtitle = Text(
            "How a circle draws a sine wave", font_size=30, color=GREY_B
        ).next_to(title, DOWN, buff=0.35)
        self.play(FadeIn(title, shift=UP * 0.3), FadeIn(subtitle), run_time=1.4)
        self.wait(0.8)
        self.play(FadeOut(title), FadeOut(subtitle), run_time=0.8)

        # --- stage: grid, circle (left), axes (right) -----------------
        plane = NumberPlane(
            x_range=[-7.11, 7.11, 1],
            y_range=[-4, 4, 1],
            background_line_style={
                "stroke_color": BLUE,
                "stroke_width": 1.5,
                "stroke_opacity": 0.22,
            },
            axis_config={"stroke_opacity": 0.0},
        )
        center = LEFT * 4.3
        radius = 1.7
        circle = Circle(radius=radius, color=BLUE, stroke_width=5).move_to(center)

        axes = Axes(
            x_range=[0, 2 * np.pi, np.pi / 2],
            y_range=[-1.25, 1.25, 0.5],
            x_length=6.2,
            y_length=3.4,
            axis_config={"color": GREY_B, "stroke_width": 3},
            tips=False,
        ).move_to(RIGHT * 2.9)
        x_label = MathTex(r"\theta", color=WHITE).scale(0.8)
        x_label.next_to(axes.x_axis, DOWN, buff=0.18).shift(RIGHT * 2.6)
        y_label = MathTex(r"\sin\theta", color=YELLOW).scale(0.8)
        y_label.next_to(axes.y_axis, LEFT, buff=0.18).shift(UP * 1.35)

        self.play(FadeIn(plane), run_time=1.2)
        self.play(Create(circle), run_time=1.6)
        self.play(Create(axes), FadeIn(x_label), FadeIn(y_label), run_time=1.4)

        # --- moving parts ---------------------------------------------
        theta = ValueTracker(0.0)

        def point_pos():
            t = theta.get_value()
            return center + radius * np.array([np.cos(t), np.sin(t), 0])

        def wave_pos():
            t = theta.get_value()
            return axes.c2p(t % (2 * np.pi), np.sin(t))

        dot = always_redraw(lambda: Dot(point_pos(), color=YELLOW, radius=0.07))
        radius_line = always_redraw(
            lambda: Line(center, point_pos(), color=WHITE, stroke_width=4)
        )
        height_line = always_redraw(
            lambda: Line(
                point_pos(),
                np.array([point_pos()[0], center[1], 0]),
                color=GREEN,
                stroke_width=5,
            )
        )
        guide = always_redraw(
            lambda: DashedLine(
                point_pos(), wave_pos(), color=GREY_B, stroke_width=3, dash_length=0.12
            )
        )
        wave_dot = always_redraw(lambda: Dot(wave_pos(), color=YELLOW, radius=0.06))
        wave = TracedPath(wave_dot.get_center, stroke_color=YELLOW, stroke_width=5)
        theta_label = MathTex(r"\theta", color=WHITE).scale(0.75)
        theta_label.next_to(center, RIGHT, buff=0.55).shift(UP * 0.28)
        sin_label = MathTex(r"\sin\theta", color=GREEN).scale(0.7)
        sin_label.next_to(center, DOWN, buff=0.35).shift(LEFT * 0.4)

        self.play(
            FadeIn(dot), FadeIn(radius_line), FadeIn(height_line),
            FadeIn(theta_label), FadeIn(sin_label), run_time=1.0,
        )
        self.add(guide, wave, wave_dot)

        # two full turns: the wave grows out of the circle
        self.play(theta.animate.set_value(2 * np.pi), run_time=7, rate_func=lambda t: t)
        self.wait(0.5)
        caption = Text(
            "the height of the point becomes the wave",
            font_size=28, color=WHITE,
        ).to_edge(DOWN, buff=0.45)
        self.play(FadeIn(caption), run_time=0.8)
        self.play(theta.animate.set_value(4 * np.pi), run_time=7, rate_func=lambda t: t)
        self.wait(0.6)

        # --- closing formula ------------------------------------------
        formula = MathTex(r"y = \sin\theta", color=YELLOW).scale(1.5)
        formula.to_edge(UP, buff=0.5)
        self.play(FadeIn(formula, shift=DOWN * 0.2), run_time=1.0)
        self.wait(1.6)
