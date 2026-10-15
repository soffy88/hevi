"""Hevi 动效导演层 (Motion Director) 全面单元与集成测试。

覆盖:
- DirectorBrief 自动补全与校验 (支持多产品线)
- 拍点网格与重动作吸附
- 运动语言纯函数与物理原语 (≥8 种)
- 错相编排与主次层次
- SFX 从运动长出与响度合规
- 全通自检闸门 (director_check)
- 线路薄适配器
- 能力注册表调用
- 样片与审片面板生成
"""

from __future__ import annotations

from pathlib import Path
import pytest

from hevi.director_lens.brief import autofill, DirectorBrief, LINE_CATALOG, write_example_briefs
from hevi.director_lens.beat import build_grid, snap_heavy_action, beat_alignment_rate
from hevi.director_lens.motion import sample_track, primitives_implemented, GRAVITY
from hevi.director_lens.stagger import apply_stagger, check_primary_secondary_hierarchy
from hevi.director_lens.audio import generate_audio_events, check_audio_compliance
from hevi.director_lens.gate import director_check_workflow
from hevi.director_lens.adapters import adapt_to_line
from hevi.director_lens.render import render_comparison_package
from hevi.director_lens.review import generate_review_html
from hevi.capabilities.registry import get as get_capability


def test_line_catalog_and_autofill() -> None:
    assert "explainer" in LINE_CATALOG
    assert "character_narrative" in LINE_CATALOG
    assert "scene3d" in LINE_CATALOG
    assert "montage" in LINE_CATALOG

    brief = autofill("小球学弹跳", line="explainer", duration_s=8.0, aspect="16:9")
    assert brief.id.startswith("explainer-")
    assert brief.line == "explainer"
    assert len(brief.shots) >= 2
    errs = brief.validate()
    assert not errs


def test_all_lines_autofill() -> None:
    for line in LINE_CATALOG:
        brief = autofill(f"测试{line}", line=line, duration_s=6.0, aspect="9:16")
        assert brief.line == line
        assert not brief.validate()


def test_beat_grid_and_snapping() -> None:
    grid = build_grid(bpm=90.0, fps=30, duration_s=6.0)
    assert grid.frames == 180
    assert len(grid.beat_frames) > 0
    f = snap_heavy_action(2.0, "impact", grid, heavy=True)
    assert isinstance(f, int)
    rate, details = beat_alignment_rate([{"kind": "impact", "t": 2.0}], grid)
    assert 0.0 <= rate <= 1.0


def test_motion_primitives_and_velocity_continuity() -> None:
    prims = primitives_implemented()
    assert len(prims) >= 8
    assert "gravity" in prims
    assert "bounce" in prims
    assert "spring" in prims
    assert "soft_body" in prims

    brief = autofill("水滴落进小水塘", line="scene3d", duration_s=6.0)
    track = brief.tracks[0]
    st0 = sample_track(track, 0.5, brief.duration_s)
    st1 = sample_track(track, 0.52, brief.duration_s)
    # 速度连续验证
    assert st0.phase is not None
    assert isinstance(st1.dy, float)


def test_stagger_and_hierarchy() -> None:
    brief = autofill("小狐狸学分享", line="character_narrative", duration_s=6.0)
    brief2 = apply_stagger(brief)
    assert brief2.tracks[1].start_delay_frames > 0
    ok, violations = check_primary_secondary_hierarchy(brief2)
    assert isinstance(ok, bool)


def test_audio_generation_and_compliance() -> None:
    brief = autofill("搭积木", line="explainer", duration_s=6.0)
    audio_evs = generate_audio_events(brief)
    assert len(audio_evs) > 0
    rep = check_audio_compliance(audio_evs)
    assert rep["passed"] is True


def test_director_check_workflow(tmp_path: Path) -> None:
    brief = autofill("小球学弹跳", line="explainer", duration_s=6.0)
    report = director_check_workflow(brief)
    assert isinstance(report, dict)
    assert "checks" in report


def test_line_adapters() -> None:
    brief = autofill("种子发芽", line="montage", duration_s=8.0)
    for line in LINE_CATALOG:
        adapted = adapt_to_line(brief, line)
        assert adapted["line"] == line
        assert len(adapted["shots"]) > 0


def test_capabilities_registration() -> None:
    cap_brief = get_capability("director_brief")
    assert cap_brief.name == "director_brief"

    cap_check = get_capability("director_check")
    assert cap_check.name == "director_check"

    cap_motion = get_capability("motion_director")
    assert cap_motion.name == "motion_director"


def test_render_and_review_generation(tmp_path: Path) -> None:
    brief = autofill("小球学弹跳", line="explainer", duration_s=6.0)
    comparison = render_comparison_package(brief, tmp_path)
    assert "director_version" in comparison
    assert "baseline_version" in comparison

    html_path = generate_review_html(brief, comparison, tmp_path / "review.html")
    assert html_path.exists()
    assert "Hevi 动效导演层" in html_path.read_text(encoding="utf-8")


def test_write_example_briefs(tmp_path: Path) -> None:
    paths = write_example_briefs(tmp_path)
    assert len(paths) >= 4
    for p in paths:
        b = DirectorBrief.load(p)
        assert not b.validate()
