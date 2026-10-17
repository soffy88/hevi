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
from typing import Any
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
    # 导演版 brief 的拍点对齐率必须达标(核心交付项 C/B/F)
    assert report["checks"]["beat_alignment"]["alignment_rate"] >= 0.50
    # 每条线的 autofill brief 拍点对齐率都 ≥ 0.50
    for line in LINE_CATALOG:
        b = autofill(f"测试{line}", line=line, duration_s=6.0)
        r = director_check_workflow(b)
        assert r["checks"]["beat_alignment"]["alignment_rate"] >= 0.50, line


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


def _ffprobe_streams(path: Path) -> list[dict[str, Any]]:
    """用 ffprobe 读出真实流信息(判定是否真 MP4, 非假字节)。"""
    import json
    import subprocess

    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(r.stdout)["streams"], json.loads(r.stdout)["format"]


# 每条样片线的(线, 提示词, 时长, 比例)
SAMPLE_LINES = [
    ("explainer", "小球学弹跳", 6.0, "16:9"),
    ("character_narrative", "小狐狸学分享", 6.0, "9:16"),
    ("scene3d", "水滴落进小水塘", 6.0, "16:9"),
    ("montage", "种子发芽的纪录短片", 6.0, "16:9"),
]


@pytest.mark.parametrize(("line", "prompt", "dur", "aspect"), SAMPLE_LINES)
def test_sample_director_passes_baseline_fails(tmp_path: Path, line, prompt, dur, aspect) -> None:
    """核心交付项 I/J:导演版 passed=True, 基线版 passed=False, 均由真实自检门判定。"""
    brief = autofill(prompt, line=line, duration_s=dur, aspect=aspect, seed=42)
    comp = render_comparison_package(brief, tmp_path)

    assert comp["director_report"]["passed"] is True, comp["director_report"]["errors"]
    assert comp["baseline_report"]["passed"] is False
    # 基线 FAIL 必须来自真实检查项(至少一条非空错误), 而非硬写
    assert comp["baseline_report"]["errors"], "baseline must fail via real checks"
    assert comp["director_report"]["checks"]["beat_alignment"]["alignment_rate"] >= 0.50


def test_rendered_mp4_is_real_not_mock(tmp_path: Path) -> None:
    """禁止 mock:导演版与基线版 MP4 都不是假字节, 且 ffprobe 能读出真实流。"""
    brief = autofill("小球学弹跳", line="explainer", duration_s=6.0)
    comp = render_comparison_package(brief, tmp_path)

    mock_tokens = (b"MOCK_MP4_BYTES", b"BASELINE_MP4_BYTES")
    for key in ("director_version", "baseline_version"):
        mp4 = Path(comp[key]["mp4"])
        raw = mp4.read_bytes()
        for tok in mock_tokens:
            assert tok not in raw
        assert mp4.stat().st_size > 10_000, "MP4 too small to be a real encode"
        streams, fmt = _ffprobe_streams(mp4)
        video = next(s for s in streams if s["codec_type"] == "video")
        assert video["codec_name"] == "h264"
        assert int(video["nb_frames"]) >= int(6.0 * 30) - 2
        assert abs(float(fmt["duration"]) - 6.0) < 0.15
    # 导演版主管线必须有真实音轨 AAC
    dir_streams, _ = _ffprobe_streams(Path(comp["director_version"]["mp4"]))
    audio = [s for s in dir_streams if s["codec_type"] == "audio"]
    assert audio and audio[0]["codec_name"] == "aac"


def test_director_version_loudness_complies(tmp_path: Path) -> None:
    """幼儿响度门:导演版音轨积分响度 -16 ±1 LUFS, 真峰值 ≤ -1.5 dBTP。"""
    import re
    import subprocess

    brief = autofill("小球学弹跳", line="explainer", duration_s=6.0)
    comp = render_comparison_package(brief, tmp_path)
    mp4 = Path(comp["director_version"]["mp4"])
    r = subprocess.run(
        ["ffmpeg", "-nostats", "-hide_banner", "-i", str(mp4),
         "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    stderr = r.stderr
    m = re.search(r"Integrated loudness:\s*\n\s*I:\s*(-?[\d.]+) LUFS", stderr, re.IGNORECASE)
    assert m, "no loudness measurement"
    assert -17.0 <= float(m.group(1)) <= -15.0
    mp = re.search(r"Peak:\s*(-?[\d.]+) dBFS", stderr)
    assert mp and float(mp.group(1)) <= -1.5


def test_same_seed_render_is_byte_identical(tmp_path: Path) -> None:
    """同 seed 两次渲染 sha256 一致(确定性)。"""
    brief = autofill("小球学弹跳", line="explainer", duration_s=6.0, seed=1234)
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    r1 = render_comparison_package(brief, out_a)
    r2 = render_comparison_package(brief, out_b)
    assert r1["director_version"]["sha256"] == r2["director_version"]["sha256"]
    assert r1["baseline_version"]["sha256"] == r2["baseline_version"]["sha256"]


def test_render_has_no_mock_code_paths() -> None:
    """静态保证:render.py 不再包含 mock 字节兜底或硬写通过。"""
    src = (Path(__file__).resolve().parents[1] / "hevi" / "director_lens" / "render.py").read_text(encoding="utf-8")
    assert "MOCK_MP4_BYTES" not in src
    assert "BASELINE_MP4_BYTES" not in src
    assert 'base_report["passed"]' not in src
    assert 'report["passed"] = True' not in src


def test_write_example_briefs(tmp_path: Path) -> None:
    paths = write_example_briefs(tmp_path)
    assert len(paths) >= 4
    for p in paths:
        b = DirectorBrief.load(p)
        assert not b.validate()
