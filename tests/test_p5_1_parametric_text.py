"""P5.1 — parametric text overlay in the layered editable draft.

An element whose content *is* its parameters has no media file behind it. P5.1
used to read that as a missing artifact and drop the element, which meant a
lower third whose wording is editable simply could not be delivered.

These tests pin the behaviour that replaced it, and pin the honesty rules that
must survive the change:

* the copy is real and lands in a real material, not a placeholder;
* position, timing and style survive the projection;
* a text layer with no text is refused by name rather than written as empty;
* a material that loses its copy on disk is caught by validation, not shipped;
* a style field the draft cannot express is recorded, not discarded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hevi.ops.p5_1_editable import (
    PARAMETRIC_TEXT_STYLE_FIELDS,
    LayerElement,
    LayerManifest,
    add_parametric_text_material,
    build_layered_draft,
    is_parametric_text_element,
    parametric_text_fields,
    validate_layered_project,
)
from hevi.ops.p5_1_types import EditableLayer

STYLE = {
    "text": "measured, not asserted",
    "font_size_px": 42,
    "color": "#F59E0B",
    "weight": "bold",
    "align": "left",
    "max_lines": 2,
    "x": 0.0,
    "y": 0.78,
    "scale": 1.2,
    "opacity": 0.92,
}


def _manifest(**overrides) -> LayerManifest:
    params = {**STYLE, **overrides.pop("params", {})}
    manifest = LayerManifest(content_id="c1", candidate_id="cap-1", duration_ms=4000)
    manifest.add(
        LayerElement(
            element_id=overrides.pop("element_id", "lower-third"),
            layer=overrides.pop("layer", EditableLayer.OVERLAY),
            semantic_role=overrides.pop("semantic_role", "SEMANTIC_HIGHLIGHT"),
            start_ms=overrides.pop("start_ms", 500),
            end_ms=overrides.pop("end_ms", 2500),
            editable_params=params,
            **overrides,
        )
    )
    return manifest


def _draft(manifest: LayerManifest, tmp_path: Path):
    project = build_layered_draft(manifest, tmp_path / "draft")
    valid, errors = validate_layered_project(project)
    return project, valid, errors


# ── The element is recognised, and only when it really is one ────────────


def test_a_parametric_text_element_is_recognised() -> None:
    assert is_parametric_text_element(_manifest().elements()[0]) is True


def test_an_element_without_text_is_not_parametric() -> None:
    """Absence of a file alone must not make an element parametric.

    Otherwise a genuinely missing asset would be written as an empty text
    material, and the delivery would claim content nobody authored.
    """
    manifest = _manifest()
    element = manifest.elements()[0]
    element.editable_params = {"font_size_px": 42}
    assert is_parametric_text_element(element) is False


def test_whitespace_is_not_text() -> None:
    manifest = _manifest()
    element = manifest.elements()[0]
    element.editable_params = {"text": "   "}
    assert is_parametric_text_element(element) is False


def test_a_media_layer_is_never_parametric() -> None:
    manifest = _manifest()
    element = manifest.elements()[0]
    element.layer = EditableLayer.BACKGROUND
    assert is_parametric_text_element(element) is False


# ── The draft carries real copy ──────────────────────────────────────────


def test_the_draft_contains_a_real_text_material(tmp_path: Path) -> None:
    project, valid, errors = _draft(_manifest(), tmp_path)
    assert valid, errors
    assert project.refused_elements == []

    draft = json.loads(Path(project.timeline_json).read_text(encoding="utf-8"))
    parametric = [
        m for m in draft["materials"] if (m.get("metadata") or {}).get("parametric_text")
    ]
    assert len(parametric) == 1, draft["materials"]
    material = parametric[0]
    assert material["type"] == "text"

    # A real file with the real copy in it — not a placeholder, and not a path
    # that points at nothing.
    path = Path(material["path"])
    assert path.is_file(), path
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["content"]["text"] == STYLE["text"]
    assert payload["element_id"] == "lower-third"
    assert payload["kind"] == "PARAMETRIC_TEXT"


def test_the_overlay_lands_on_a_track_with_its_timing(tmp_path: Path) -> None:
    project, valid, errors = _draft(_manifest(), tmp_path)
    assert valid, errors

    draft = json.loads(Path(project.timeline_json).read_text(encoding="utf-8"))
    segments = [s for t in draft["tracks"] for s in t["segments"]]
    assert len(segments) == 1
    segment = segments[0]
    # 500ms in, 2000ms long — microseconds in the draft.
    assert segment["target_timerange"]["start"] == 500_000
    assert segment["target_timerange"]["duration"] == 2_000_000


def test_position_and_opacity_survive_the_projection(tmp_path: Path) -> None:
    """An overlay at the lower third is not the same element as one at the top.

    Writing both at the origin would collapse them while still reporting a
    successful delivery, so the geometry is read back rather than assumed.
    """
    project, valid, errors = _draft(_manifest(), tmp_path)
    assert valid, errors

    draft = json.loads(Path(project.timeline_json).read_text(encoding="utf-8"))
    clip = draft["tracks"][0]["segments"][0]["clip"]
    assert clip["transform"]["y"] == pytest.approx(0.78)
    assert clip["transform"]["x"] == pytest.approx(0.0)
    assert clip["alpha"] == pytest.approx(0.92)
    assert clip["scale"]["x"] == pytest.approx(1.2)
    assert clip["scale"]["y"] == pytest.approx(1.2)


def test_two_overlays_at_different_positions_stay_different(tmp_path: Path) -> None:
    """The strongest form of the same property: placement is not erased."""
    manifest = LayerManifest(content_id="c1", duration_ms=4000)
    for name, y in (("top", 0.1), ("bottom", 0.9)):
        manifest.add(
            LayerElement(
                element_id=name, layer=EditableLayer.OVERLAY,
                semantic_role="SEMANTIC_HIGHLIGHT", start_ms=0, end_ms=1000,
                editable_params={"text": name, "y": y},
            )
        )
    project, valid, errors = _draft(manifest, tmp_path)
    assert valid, errors

    draft = json.loads(Path(project.timeline_json).read_text(encoding="utf-8"))
    ys = sorted(
        s["clip"]["transform"]["y"] for t in draft["tracks"] for s in t["segments"]
    )
    assert ys == pytest.approx([0.1, 0.9]), ys


def test_every_supported_style_field_survives(tmp_path: Path) -> None:
    project, valid, errors = _draft(_manifest(), tmp_path)
    assert valid, errors

    draft = json.loads(Path(project.timeline_json).read_text(encoding="utf-8"))
    material = next(
        m for m in draft["materials"] if (m.get("metadata") or {}).get("parametric_text")
    )
    content = json.loads(Path(material["path"]).read_text(encoding="utf-8"))["content"]
    for field in ("text", "font_size_px", "color", "weight", "align", "max_lines"):
        assert content[field] == STYLE[field], field


# ── Refusals stay explicit ───────────────────────────────────────────────


def test_an_unsupported_style_field_is_recorded_not_dropped(tmp_path: Path) -> None:
    """A shadow is not silently discarded; the material says it was asked for."""
    project, valid, errors = _draft(_manifest(params={"shadow": True}), tmp_path)
    assert valid, errors

    draft = json.loads(Path(project.timeline_json).read_text(encoding="utf-8"))
    material = next(
        m for m in draft["materials"] if (m.get("metadata") or {}).get("parametric_text")
    )
    payload = json.loads(Path(material["path"]).read_text(encoding="utf-8"))
    assert "shadow" in payload["unsupported_fields"]
    assert payload["supported_fields"] == sorted(set(PARAMETRIC_TEXT_STYLE_FIELDS) & set(STYLE))


def test_a_text_layer_with_no_text_is_refused_by_name(tmp_path: Path) -> None:
    """Not written as an empty text material, and not silently absent either."""
    manifest = _manifest()
    element = manifest.elements()[0]
    element.editable_params = {"font_size_px": 42}

    project = build_layered_draft(manifest, tmp_path / "draft")
    assert any(
        "PARAMETRIC_TEXT_REQUIRES_TEXT" in record for record in project.refused_elements
    ), project.refused_elements
    draft = json.loads(Path(project.timeline_json).read_text(encoding="utf-8"))
    assert draft["tracks"] == [], "an empty text material was shipped"


def test_a_missing_media_source_is_still_refused(tmp_path: Path) -> None:
    """The new path must not weaken the existing refusal for real media."""
    manifest = LayerManifest(content_id="c1", duration_ms=4000)
    manifest.add(
        LayerElement(
            element_id="bg", layer=EditableLayer.BACKGROUND,
            semantic_role="CONTEXTUAL_BROLL", start_ms=0, end_ms=1000,
            source_path=str(tmp_path / "nope.mp4"),
        )
    )
    project = build_layered_draft(manifest, tmp_path / "draft")
    assert any("SOURCE_MISSING" in r for r in project.refused_elements), (
        project.refused_elements
    )


# ── Validation catches a material that lost its copy ─────────────────────


def test_validation_catches_an_emptied_material(tmp_path: Path) -> None:
    """The sidecar existing is not proof; the copy inside it has to be there."""
    project, valid, _ = _draft(_manifest(), tmp_path)
    assert valid

    draft = json.loads(Path(project.timeline_json).read_text(encoding="utf-8"))
    material = next(
        m for m in draft["materials"] if (m.get("metadata") or {}).get("parametric_text")
    )
    path = Path(material["path"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["content"]["text"] = ""
    path.write_text(json.dumps(payload), encoding="utf-8")

    valid, errors = validate_layered_project(project)
    assert not valid
    assert any("PARAMETRIC_TEXT_EMPTY" in e for e in errors), errors


def test_validation_catches_text_that_drifted_from_the_manifest(tmp_path: Path) -> None:
    project, valid, _ = _draft(_manifest(), tmp_path)
    assert valid

    draft = json.loads(Path(project.timeline_json).read_text(encoding="utf-8"))
    material = next(
        m for m in draft["materials"] if (m.get("metadata") or {}).get("parametric_text")
    )
    path = Path(material["path"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["content"]["text"] = "something else entirely"
    path.write_text(json.dumps(payload), encoding="utf-8")

    valid, errors = validate_layered_project(project)
    assert not valid
    assert any("PARAMETRIC_TEXT_DRIFT" in e for e in errors), errors


def test_validation_catches_an_unreadable_material(tmp_path: Path) -> None:
    project, valid, _ = _draft(_manifest(), tmp_path)
    assert valid

    draft = json.loads(Path(project.timeline_json).read_text(encoding="utf-8"))
    material = next(
        m for m in draft["materials"] if (m.get("metadata") or {}).get("parametric_text")
    )
    Path(material["path"]).write_text("{ not json", encoding="utf-8")

    valid, errors = validate_layered_project(project)
    assert not valid
    assert any("PARAMETRIC_TEXT_UNREADABLE" in e for e in errors), errors


# ── The field split is honest ────────────────────────────────────────────


def test_field_split_separates_supported_from_unsupported() -> None:
    element = _manifest(params={"shadow": True, "stroke": 2}).elements()[0]
    supported, unsupported = parametric_text_fields(element)
    assert "shadow" in unsupported and "stroke" in unsupported
    assert "shadow" not in supported
    assert "text" in supported and "color" in supported


def test_the_overlay_is_still_structurally_editable(tmp_path: Path) -> None:
    """Editable means a change survives validation, not just that a file exists."""
    from hevi.ops.p5_1_editable import structural_round_trip

    project, valid, errors = _draft(_manifest(), tmp_path)
    assert valid, errors
    result = structural_round_trip(project)
    assert result.ok, result.errors
    assert "structural round trip only" in result.note


def test_the_material_is_registered_not_shadowed(tmp_path: Path) -> None:
    """A builder is passed in, not created, so P5 stays the one draft format."""
    from hevi.ops.p5_editable import JianyingDraftBuilder

    manifest = _manifest()
    element = manifest.elements()[0]
    builder = JianyingDraftBuilder(tmp_path / "probe")
    before = len(builder.tracks)
    material_id = add_parametric_text_material(builder, element)
    assert material_id.startswith("text_param_")
    assert len(builder.materials) == 1
    assert len(builder.tracks) == before
