"""S21：出品形式注册表、质量门与埋点聚合。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hevi.studio import format_events
from hevi.studio.formats import (
    FORMAT_BY_ID,
    gate_open,
    list_formats,
    resolve_format,
)


def test_every_visible_line_is_reachable_from_a_format() -> None:
    seen = {style.line_id for fmt in FORMAT_BY_ID.values() for style in fmt.styles}
    for line in (
        "history_scene", "documentary_montage", "cinematic", "director_pipeline",
        "talking_head", "avatar_spokesperson", "ai_drama", "comic_narration",
        "character_animation", "handdraw", "explainer", "kinetic_promo", "scene3d",
        "shorts_clip", "koubo_cut", "podcast_repurpose", "localization_dub",
        "reference_adapt", "collage_broll",
    ):
        assert line in seen, line


def test_resolve_format_maps_style_to_line() -> None:
    plan = resolve_format(format_id="history_scene", style_id="documentary", line_id=None, slots={"topic": "x"})
    assert plan["line_id"] == "documentary_montage"
    assert plan["format"] == "history_scene"
    assert plan["gated"] is False


def test_resolve_format_keeps_legacy_line_id() -> None:
    plan = resolve_format(format_id=None, style_id=None, line_id="talking_head", slots={"topic": "x"})
    assert plan["line_id"] == "talking_head"
    assert plan["format"] == "digital_human"


def test_auto_guesses_once_by_media_then_history_then_default() -> None:
    media = resolve_format(format_id="auto", style_id=None, line_id=None, slots={"media_path": "/tmp/a.mp4"})
    assert (media["format"], media["line_id"]) == ("material_cut", "shorts_clip")
    history = resolve_format(format_id="auto", style_id=None, line_id=None, slots={"topic": "唐朝的历史"})
    assert (history["format"], history["line_id"]) == ("history_scene", "history_scene")
    plain = resolve_format(format_id="auto", style_id=None, line_id=None, slots={"topic": "为什么天是蓝的"})
    assert (plain["format"], plain["line_id"]) == ("explainer", "explainer")


def test_ai_drama_is_gated_by_default_and_can_be_opened(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hevi.studio.formats as formats_mod

    # Isolate from the on-disk gate file: no file == closed.
    monkeypatch.delenv("HEVI_OPEN_AI_DRAMA", raising=False)
    monkeypatch.setattr(formats_mod, "GATES_PATH", tmp_path / "missing.json")
    open_flag, reason = gate_open("ai_drama")
    assert open_flag is False
    assert reason
    live = resolve_format(format_id="live_drama", style_id=None, line_id=None, slots={"topic": "x"})
    assert live["gated"] is True
    # Passing the blackbox writes open=true to the gate file.
    gate_file = tmp_path / "gates.json"
    gate_file.write_text(json.dumps({"ai_drama": {"open": True, "reason": "blackbox passed"}}), encoding="utf-8")
    monkeypatch.setattr(formats_mod, "GATES_PATH", gate_file)
    assert gate_open("ai_drama") == (True, "blackbox passed")
    # Env override also opens it.
    monkeypatch.setenv("HEVI_OPEN_AI_DRAMA", "1")
    assert gate_open("ai_drama")[0] is True


def test_digital_human_auto_routes_on_face_image() -> None:
    plain = resolve_format(format_id="digital_human", style_id="auto", line_id=None, slots={"topic": "x"})
    assert plain["line_id"] == "talking_head"
    with_face = resolve_format(
        format_id="digital_human", style_id="auto", line_id=None,
        slots={"topic": "x", "image_path": "/tmp/face.png"},
    )
    assert with_face["line_id"] == "avatar_spokesperson"


def test_live_drama_offers_cinematic_and_director_styles() -> None:
    styles = {style.id: style.line_id for style in FORMAT_BY_ID["live_drama"].styles}
    assert styles["live_action"] == "ai_drama"
    assert styles["cinematic"] == "cinematic"
    assert styles["director"] == "director_pipeline"


def test_material_format_only_after_upload() -> None:
    assert "material_cut" not in {f["id"] for f in list_formats()}
    assert "material_cut" in {f["id"] for f in list_formats(has_media=True)}


def test_format_events_metrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("HEVI_FORMAT_EVENTS_PATH", str(path))
    format_events.record_event("format_selected", user_id="u1", format_id="history_scene")
    format_events.record_event("auto_changed", user_id="u1", format_id="explainer", detail={"from": "auto"})
    format_events.record_event("storyboard_edited", user_id="u1", format_id="history_scene", detail={"count": 3})
    format_events.record_event("render_started", user_id="u1", format_id="history_scene")
    format_events.record_event("render_completed", user_id="u1", format_id="history_scene")
    data = format_events.metrics()
    assert data["totals"]["selections"] == 1
    assert data["totals"]["auto_changed"] == 1
    assert data["totals"]["storyboard_edits"] == 3
    assert data["totals"]["completion_rate"] == 1.0
    # one event must not be counted twice (target + source)
    assert sum(row["auto_changed"] for row in data["formats"]) == 1
    rows = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert rows["event"] == "format_selected"


def test_unknown_format_rejected() -> None:
    with pytest.raises(ValueError):
        resolve_format(format_id="nope", style_id=None, line_id=None, slots={})
