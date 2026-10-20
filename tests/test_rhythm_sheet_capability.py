"""Offline tests for the launch-rhythm sheet capability.

Covers ``motion.rhythm_sheet`` (``hevi/capabilities/rhythm_sheet.py``)
and the underlying ``hevi/motion/rhythm_sheet.py`` model/validation/
measurement.  All media is synthesized locally with ffmpeg lavfi
(testsrc picture + sine audio); no network, no paid calls.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import hevi.capabilities.rhythm_sheet as rhythm_cap_mod
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import get, list_capabilities
from hevi.motion.rhythm_sheet import RhythmSheet, measure_rhythm, validate_sheet

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg required",
)


def _good_sheet() -> dict:
    """A compliant 30 s hybrid launch sheet (docs/rules/launch_rhythm.md)."""
    return {
        "title": "示例新品发布片",
        "route": "hybrid",
        "bpm": 120,
        "duration_s": 30,
        "stretches": [
            {"name": "钩子", "start_s": 0, "end_s": 3, "role": "hook",
             "energy": 6, "events_per_bar": 3, "changes": [],
             "music": "第一记音头直接进", "first_event_s": 0.5},
            {"name": "铺垫", "start_s": 3, "end_s": 11, "role": "build",
             "energy": 7, "events_per_bar": 3,
             "changes": ["shot_scale", "density"], "music": "全拍切点"},
            {"name": "爆发", "start_s": 11, "end_s": 16, "role": "peak",
             "energy": 9, "events_per_bar": 6,
             "changes": ["speed", "density", "music_texture", "colour"],
             "music": "半拍加密"},
            {"name": "屏息", "start_s": 16, "end_s": 17.2, "role": "stop",
             "energy": 2, "events_per_bar": 0,
             "changes": ["speed", "music_texture"], "music": "tape stop"},
            {"name": "产品定妆", "start_s": 17.2, "end_s": 24, "role": "peak",
             "energy": 10, "events_per_bar": 4,
             "changes": ["shot_scale", "camera", "colour", "music_texture"],
             "music": "最强音乐点", "hero": True},
            {"name": "落点", "start_s": 24, "end_s": 30, "role": "resolve",
             "energy": 4, "events_per_bar": 1,
             "changes": ["density", "colour"], "music": "织体收薄"},
        ],
    }


def _rules(result: dict) -> set[str]:
    return {v["rule"] for v in result["violations"]}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_capability_registered_and_discoverable() -> None:
    registered = rhythm_cap_mod.register_rhythm_sheet_capabilities()
    assert "motion.rhythm_sheet" in registered
    cap = get("motion.rhythm_sheet")
    assert cap.name == "motion.rhythm_sheet"
    assert cap.kind == "line"
    assert cap.line == "motion_taste"
    assert "9:16" in cap.aspects and "16:9" in cap.aspects
    assert any(c.name == "motion.rhythm_sheet" for c in list_capabilities(kind="line"))
    # Illegal params must be rejected by the schema, not waved through.
    with pytest.raises(CapabilityError):
        cap.validate_params({"sheet": {"title": "x"}, "bogus": 1})
    with pytest.raises(CapabilityError):
        cap.validate_params({})


def test_sheet_dict_roundtrip() -> None:
    sheet = RhythmSheet.from_dict(_good_sheet())
    assert sheet.to_dict()["stretches"][4]["hero"] is True
    assert RhythmSheet.from_dict(sheet.to_dict()).to_dict() == sheet.to_dict()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_good_sheet_passes() -> None:
    result = validate_sheet(_good_sheet())
    assert result["ok"], result
    assert result["violations"] == []


def test_missing_hook_triggers_violation() -> None:
    sheet = copy.deepcopy(_good_sheet())
    sheet["stretches"][0]["role"] = "build"
    result = validate_sheet(sheet)
    assert not result["ok"]
    assert "hook_missing" in _rules(result)


def test_no_burst_triggers_violation() -> None:
    sheet = copy.deepcopy(_good_sheet())
    for s in sheet["stretches"]:
        s["events_per_bar"] = min(s["events_per_bar"], 3)
    result = validate_sheet(sheet)
    assert not result["ok"]
    assert "burst_missing" in _rules(result)


def test_hero_not_max_energy_triggers_violation() -> None:
    sheet = copy.deepcopy(_good_sheet())
    sheet["stretches"][4]["energy"] = 5  # burst stretch stays at 9
    result = validate_sheet(sheet)
    assert not result["ok"]
    assert "hero_not_max_energy" in _rules(result)


def test_dead_stretch_triggers_violation() -> None:
    sheet = copy.deepcopy(_good_sheet())
    sheet["stretches"][1]["events_per_bar"] = 0
    result = validate_sheet(sheet)
    assert not result["ok"]
    assert "dead_stretch" in _rules(result)


def test_coverage_gap_triggers_violation() -> None:
    sheet = copy.deepcopy(_good_sheet())
    sheet["stretches"][1]["start_s"] = 3.5  # 0.5 s hole after the hook
    result = validate_sheet(sheet)
    assert not result["ok"]
    assert "coverage_gap" in _rules(result)


def test_capability_validate_only_writes_report(tmp_path: Path) -> None:
    rhythm_cap_mod.register_rhythm_sheet_capabilities()
    cap = get("motion.rhythm_sheet")
    result = cap.render_safe(
        {"sheet": _good_sheet()}, tmp_path,
        duration=30, aspect="9:16", seed=1,
    )
    assert result.qa["ok"] is True
    assert result.qa["violations"] == []
    report_path = Path(result.qa["report"])
    assert report_path.name == "rhythm_sheet_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["measurement"] is None


# ---------------------------------------------------------------------------
# Measurement (ffmpeg-synthesized clip)
# ---------------------------------------------------------------------------

def _make_clip(path: Path) -> Path:
    """6 s clip: 4 s moving testsrc2 + 2 s static black, sine tone throughout."""
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10:duration=4",
        "-f", "lavfi", "-i", "color=c=black:size=320x240:rate=10:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=6",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return path


def _measure_sheet() -> dict:
    return {
        "title": "measure fixture", "route": "montage", "bpm": 120,
        "duration_s": 6,
        "stretches": [
            {"name": "moving-a", "start_s": 0, "end_s": 2, "role": "hook",
             "energy": 5, "events_per_bar": 3, "changes": []},
            {"name": "moving-b", "start_s": 2, "end_s": 4, "role": "build",
             "energy": 7, "events_per_bar": 3,
             "changes": ["density", "colour"]},
            {"name": "static-tail", "start_s": 4, "end_s": 6, "role": "resolve",
             "energy": 3, "events_per_bar": 1,
             "changes": ["density", "colour"]},
        ],
    }


def test_measure_rhythm_numbers_and_dead_flag(tmp_path: Path) -> None:
    clip = _make_clip(tmp_path / "clip.mp4")
    report = measure_rhythm(clip, _measure_sheet())
    rows = report["stretches"]
    assert [r["name"] for r in rows] == ["moving-a", "moving-b", "static-tail"]
    for row in rows:
        assert isinstance(row["audio_rms_db"], float)
        assert isinstance(row["motion"], float)
        assert isinstance(row["planned_energy_norm"], float)
        assert isinstance(row["audio_energy_norm"], float)
        assert isinstance(row["energy_diff"], float)
    assert "shape_correlation" in report
    # Moving testsrc stretches are alive; the static black tail is dead.
    assert rows[0]["dead_flag"] is False
    assert rows[1]["dead_flag"] is False
    assert rows[2]["dead_flag"] is True
    assert report["dead_stretches"] == ["static-tail"]


def test_measure_rhythm_unreadable_media_raises(tmp_path: Path) -> None:
    with pytest.raises(CapabilityError):
        measure_rhythm(tmp_path / "does-not-exist.mp4", _measure_sheet())


def test_capability_measure_mode_writes_report(tmp_path: Path) -> None:
    clip = _make_clip(tmp_path / "clip.mp4")
    sheet = {
        "title": "measure cap", "route": "hybrid", "bpm": 120, "duration_s": 6,
        "stretches": [
            {"name": "钩子", "start_s": 0, "end_s": 1.5, "role": "hook",
             "energy": 6, "events_per_bar": 3, "changes": [],
             "first_event_s": 0.2},
            {"name": "铺垫", "start_s": 1.5, "end_s": 3, "role": "build",
             "energy": 7, "events_per_bar": 3,
             "changes": ["shot_scale", "density"]},
            {"name": "爆发", "start_s": 3, "end_s": 4, "role": "peak",
             "energy": 9, "events_per_bar": 6,
             "changes": ["speed", "density", "music_texture", "colour"]},
            {"name": "定妆", "start_s": 4, "end_s": 5, "role": "peak",
             "energy": 10, "events_per_bar": 4,
             "changes": ["shot_scale", "camera", "colour", "music_texture"],
             "hero": True},
            {"name": "落点", "start_s": 5, "end_s": 6, "role": "resolve",
             "energy": 4, "events_per_bar": 1,
             "changes": ["density", "colour"]},
        ],
    }
    rhythm_cap_mod.register_rhythm_sheet_capabilities()
    cap = get("motion.rhythm_sheet")
    result = cap.render_safe(
        {"sheet": sheet, "media_path": str(clip)}, tmp_path / "out",
        duration=6, aspect="16:9", seed=1,
    )
    assert result.qa["ok"] is True
    assert result.qa["measured"] is True
    report = json.loads(Path(result.qa["report"]).read_text(encoding="utf-8"))
    assert report["measurement"] is not None
    assert len(report["measurement"]["stretches"]) == 5
    for row in report["measurement"]["stretches"]:
        assert isinstance(row["audio_rms_db"], float)
        assert isinstance(row["motion"], float)
