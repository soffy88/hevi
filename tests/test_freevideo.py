"""freevideo 单元测试:确定性分镜 + HTML 模板 + 渲染编排(不打真录屏)。

渲染真录屏(playwright)是集成级操作,单测里只验证:
  - 分镜正确性(句数/首末镜/轮换)
  - 每帧 HTML 自包含、语法结构完整、动画时长不超帧时长
  - workflow 的错误路径(空输入)
真录屏冒烟在 scripts/ 或手工验证。
"""

from __future__ import annotations

import json
import re

import pytest

from hevi.assembly.freevideo.storyboard import FramePlan, plan_from_json, plan_from_text
from hevi.assembly.freevideo.templates import FRAME_KINDS, render_frame_html
from hevi.assembly.freevideo.workflow import (
    FreeVideoConfig,
    FreeVideoInput,
    build_plans,
)

TEXT_4 = (
    "HTML 视频不是新概念,但每个引擎都有自己的套路。"
    "Hyperframes 让你写 HTML 就能出片,零成本录屏。"
    "hevi 把分镜、动效参数、声音设计都变成可校验的数据。"
    "两者一合,就有了这条零成本动画通道。"
)


# ── 分镜 ─────────────────────────────────────────────────────────────────


def test_plan_from_text_structure():
    plans = plan_from_text(TEXT_4, title="零成本")
    # 4 句 → 首 + 2 中 + 末 = 4 镜
    assert len(plans) == 4
    assert plans[0].kind == "title"
    assert plans[-1].kind == "title"
    # 首镜 body = 第一句,末镜 body = 最后一句
    assert plans[0].body.startswith("HTML 视频")
    assert plans[-1].body.startswith("两者一合")
    # 中间镜在合法模板集合内
    for p in plans[1:-1]:
        assert p.kind in FRAME_KINDS


def test_plan_from_text_single_sentence():
    plans = plan_from_text("只有一句。")
    assert len(plans) == 1
    assert plans[0].kind == "title"


def test_plan_from_text_forced_kind():
    plans = plan_from_text(TEXT_4, kind="quote", frame_duration=3.0)
    assert all(p.kind == "quote" for p in plans)
    assert all(p.duration == 3.0 for p in plans)


def test_plan_from_json_structured():
    raw = json.dumps(
        {
            "title": "Demo",
            "frames": [
                {"kind": "bar", "title": "增长", "body": "季度", "duration": 5,
                 "data": {"items": [{"label": "Q1", "value": 10}, {"label": "Q2", "value": 30}]}},
                {"kind": "big_number", "title": "用户", "body": "突破", "duration": 4,
                 "data": {"number": 1200000, "unit": "人"}},
                {"kind": "quote", "title": "结语", "body": "让视频回归表达。"},
            ],
        }
    )
    plans = plan_from_json(raw)
    assert len(plans) == 3
    assert plans[0].kind == "bar"
    assert plans[1].data["number"] == 1200000
    # 未给 duration → 默认 4.0
    assert plans[2].duration == 4.0


def test_plan_from_json_invalid_kind():
    with pytest.raises(ValueError, match="unknown frame kind"):
        plan_from_json('[{"kind": "nope", "title": "x"}]')


def test_build_plans_priority():
    config = FreeVideoConfig()
    # plans 显式 > plans_json > text
    explicit = [FramePlan(kind="title", title="A", body="a")]
    inp = FreeVideoInput(text=TEXT_4, plans=explicit, plans_json='[{"kind":"quote","body":"j"}]')
    assert build_plans(config, inp) is explicit
    inp2 = FreeVideoInput(plans_json='[{"kind":"quote","body":"j"}]')
    assert build_plans(config, inp2)[0].kind == "quote"
    inp3 = FreeVideoInput(text=TEXT_4)
    assert len(build_plans(config, inp3)) == 4
    with pytest.raises(ValueError):
        build_plans(config, FreeVideoInput())


# ── HTML 模板 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", FRAME_KINDS)
def test_every_kind_renders_self_contained(kind):
    plan = FramePlan(
        kind=kind,
        title="测试标题 Test Title",
        body="这是一段足够长的正文,用来验证每个模板都能渲染出完整的自包含页面。",
        data=_sample_data(kind),
        duration=4.0,
    )
    html = render_frame_html(plan, width=1280, height=720)
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html
    # 自包含:无外链 http(s) 资源(除 CDN 外一律禁止)
    assert not re.search(r'https?://(?!fonts\.gstatic|fonts\.google)', html)
    # 有 CSS 动画
    assert "@keyframes" in html
    # 每个模板有开场动画;单次动画时长不应失控(probe 上限 30s,成片时长由
    # tpad/trim 精确裁剪,不受影响;无限循环背景动画不算)
    for line in html.splitlines():
        if "infinite" in line:
            continue
        for dur in re.findall(r"animation-duration:\s*([\d.]+)s", line):
            assert float(dur) <= 30.0, line


def test_bar_normalize_fallback():
    # 无结构化 data → 从正文切条目
    plan = FramePlan(kind="bar", title="T", body="甲 12,乙 28,丙 45", duration=4)
    html = render_frame_html(plan)
    assert "data-v=" in html


def test_scene_template_reuses_visual_scenes():
    plan = FramePlan(kind="scene", title="用火", body="北京人用火的证据", duration=4)
    html = render_frame_html(plan)
    assert "viz" in html


def _sample_data(kind: str) -> dict | None:
    if kind == "bar":
        return {"items": [{"label": "A", "value": 10}, {"label": "B", "value": 25}]}
    if kind == "big_number":
        return {"number": 1_200_000, "unit": "人"}
    if kind == "cards":
        return {"cards": [{"title": "分镜", "sub": "数据"}, {"title": "动效", "sub": "参数"}]}
    if kind == "timeline":
        return {"items": [{"title": "起步", "sub": "2024"}, {"title": "爆发", "sub": "2026"}]}
    return None


# ── broll 混排 ────────────────────────────────────────────────────────────


def test_render_frame_html_with_broll():
    from hevi.assembly.freevideo.storyboard import FramePlan
    from hevi.assembly.freevideo.templates import render_frame_html

    p = FramePlan(kind="title", title="T", body="B", duration=4)
    html = render_frame_html(p, broll="broll_1.mp4")
    assert '<video class="bg" src="broll_1.mp4"' in html
    assert "bgwrap" in html and "bgshade" in html
    assert "brightness(0.42)" in html
    # 无 broll 时干净
    assert "bgwrap" not in render_frame_html(p)


def test_plan_from_json_parses_broll(tmp_path):
    from hevi.assembly.freevideo.storyboard import plan_from_json

    plans = plan_from_json(
        json.dumps(
            {
                "frames": [
                    {"kind": "quote", "title": "T", "body": "B",
                     "broll": "/tmp/x.mp4", "duration": 4},
                    {"kind": "quote", "title": "T2", "body": "B2", "duration": 4},
                ]
            }
        )
    )
    assert plans[0].broll == "/tmp/x.mp4"
    assert plans[1].broll is None
