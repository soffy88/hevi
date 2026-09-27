"""Cross-backend equivalence for a parametric text overlay.

One ``EditableProjectManifest``, two editors. The property under test is that both
of them can say the same thing about the same overlay — and that where they
cannot, the delivery says so out loud.

The negative cases matter as much as the positive one. A differential that only
ever sees two agreeing backends proves nothing, so this file removes each
backend's ability to express a field in turn and requires the differential to
notice. A guard that cannot fail is not a guard.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

import hevi.editable.capcut_cli as capcut_module
import hevi.ops.p5_1_editable as p51_editable
from hevi.editable import (
    EditableBackendId,
    EditableProjectManifest,
    TrackElement,
    compare_projections,
    get_backend,
    lint_manifest,
    project_manifest,
    register_all_backends,
    structural_round_trip,
)
from hevi.editable.base import PARAMETRIC_TEXT_FIELDS, parametric_text_declaration

BACKENDS = (EditableBackendId.INTERNAL_JIANYING, EditableBackendId.CAPCUT_CLI)

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


@pytest.fixture(scope="module", autouse=True)
def _backends() -> list[str]:
    return register_all_backends(force=True)


def _capcut_or_skip() -> None:
    backend = get_backend(EditableBackendId.CAPCUT_CLI)
    if backend is None or not backend.detect():
        pytest.skip(f"capcut-cli unavailable: {backend and backend.unavailable_reason}")


@pytest.fixture
def media(tmp_path: Path) -> dict[str, str]:
    """Real media on disk, so the overlay is delivered alongside a real cut."""
    video = tmp_path / "picture.mp4"
    audio = tmp_path / "voice.wav"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=navy:s=640x360:r=25:d=4",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "sine=frequency=220:duration=4",
         "-c:a", "pcm_s16le", str(audio)],
        check=True, capture_output=True,
    )
    return {"video": str(video), "audio": str(audio)}


def _manifest(media: dict[str, str], **overlay: object) -> EditableProjectManifest:
    properties = {**STYLE, **overlay.pop("properties", {})}
    return EditableProjectManifest(
        project_id="p5.2 parametric overlay", duration_ms=4000,
        canvas_width=640, canvas_height=360, fps=25,
        content_id="eq-content", candidate_id="eq-candidate",
        elements=[
            TrackElement("bg", "BACKGROUND", "CONTEXTUAL_BROLL", 0, 4000, media["video"]),
            TrackElement("voice", "VOICE", "NARRATION", 0, 4000, media["audio"]),
            TrackElement(
                "lower-third", "OVERLAY", "SEMANTIC_HIGHLIGHT", 500, 2500, "",
                transform={"x": 0.0, "y": 0.78}, opacity=0.92,
                editable_properties=properties, **overlay,  # type: ignore[arg-type]
            ),
        ],
    )


def _project(manifest: EditableProjectManifest, tmp_path: Path, name: str):
    return [
        project_manifest(manifest, tmp_path / f"{name}-{b.value.lower()}", b)
        for b in BACKENDS
    ]


def _draft(projection) -> dict:
    return json.loads(Path(projection.timeline_path).read_text(encoding="utf-8"))


# ── Both backends carry the overlay ──────────────────────────────────────


def test_both_backends_deliver_the_overlay(media: dict[str, str], tmp_path: Path) -> None:
    _capcut_or_skip()
    manifest = _manifest(media)
    assert not lint_manifest(manifest, project_root=tmp_path)

    for projection in _project(manifest, tmp_path, "ok"):
        assert projection.outcome.value == "OK", (projection.backend, projection.reason)
        assert projection.dropped_elements == [], projection.backend
        assert "lower-third" not in projection.flattened, projection.backend
        assert "measured, not asserted" in json.dumps(
            _draft(projection), ensure_ascii=False
        ), projection.backend


def test_no_backend_flattens_or_drops_the_overlay(media: dict[str, str], tmp_path: Path) -> None:
    _capcut_or_skip()
    projections = _project(_manifest(media), tmp_path, "flat")
    for projection in projections:
        assert "lower-third" not in projection.flattened
        assert projection.dropped_elements == []


def test_both_backends_survive_a_structural_round_trip(
    media: dict[str, str], tmp_path: Path
) -> None:
    _capcut_or_skip()
    manifest = _manifest(media)
    for projection in _project(manifest, tmp_path, "rt"):
        ok, reasons = structural_round_trip(manifest, projection)
        assert ok, (projection.backend, reasons)


# ── Fidelity, read back out of the real projects ─────────────────────────


def test_text_content_is_preserved_in_both_backends(
    media: dict[str, str], tmp_path: Path
) -> None:
    _capcut_or_skip()
    for projection in _project(_manifest(media), tmp_path, "text"):
        assert STYLE["text"] in json.dumps(_draft(projection), ensure_ascii=False)


def test_start_and_end_are_preserved_in_both_backends(
    media: dict[str, str], tmp_path: Path
) -> None:
    _capcut_or_skip()
    for projection in _project(_manifest(media), tmp_path, "timing"):
        draft = _draft(projection)
        spans = [
            segment["target_timerange"]
            for track in draft["tracks"] for segment in track["segments"]
        ]
        assert {"start": 500_000, "duration": 2_000_000} in spans, projection.backend


def test_position_is_preserved_and_identical_across_backends(
    media: dict[str, str], tmp_path: Path
) -> None:
    """Same placement in both editors, read from the drafts rather than the input."""
    _capcut_or_skip()
    geometry = {}
    for projection in _project(_manifest(media), tmp_path, "pos"):
        draft = _draft(projection)
        clips = [
            segment["clip"]
            for track in draft["tracks"] for segment in track["segments"]
        ]
        overlay = next(
            clip for clip in clips
            if pytest.approx(clip["transform"]["y"]) == pytest.approx(0.78)
        )
        geometry[projection.backend] = (overlay["transform"], overlay["alpha"])
    assert set(geometry) == {b.value for b in BACKENDS}
    values = list(geometry.values())
    assert values[0] == values[1], geometry
    assert values[0][0]["y"] == pytest.approx(0.78)


def test_supported_style_fields_are_preserved_in_both_backends(
    media: dict[str, str], tmp_path: Path
) -> None:
    _capcut_or_skip()
    for projection in _project(_manifest(media), tmp_path, "style"):
        assert set(STYLE) <= set(projection.expressed_text_fields), projection.backend
        assert projection.unsupported_text_fields == [], projection.backend


# ── The differential ─────────────────────────────────────────────────────


def test_the_two_backends_agree_on_one_manifest(
    media: dict[str, str], tmp_path: Path
) -> None:
    _capcut_or_skip()
    manifest = _manifest(media)
    report = compare_projections(manifest, _project(manifest, tmp_path, "diff"))
    assert report.ok, report.divergences
    assert report.divergences == []


def test_a_deliberately_lossy_projection_is_rejected(
    media: dict[str, str], tmp_path: Path
) -> None:
    """The differential must still catch a backend that simply drops a track."""
    from hevi.editable.base import BackendProjection, ProjectOutcome

    manifest = _manifest(media)
    honest = project_manifest(
        manifest, tmp_path / "honest", EditableBackendId.INTERNAL_JIANYING
    )
    lossy = BackendProjection(
        backend="CAPCUT_CLI", outcome=ProjectOutcome.OK,
        project_path=honest.project_path, track_count=1, material_count=0,
        duration_ms=honest.duration_ms, semantic_roles=["CONTEXTUAL_BROLL"],
        layer_coverage={}, flattened=False, dropped_elements=["voice", "lower-third"],
    )
    report = compare_projections(manifest, [honest, lossy])
    assert report.ok is False
    assert any("ELEMENTS_DROPPED" in d for d in report.divergences), report.divergences


# ── Capability divergence is stated, not swallowed ───────────────────────


@pytest.mark.parametrize("lost_by", ["CAPCUT_CLI", "INTERNAL_JIANYING"])
@pytest.mark.parametrize("field", ["color", "align", "font_size_px"])
def test_a_style_field_one_backend_cannot_express_is_reported(
    media: dict[str, str], tmp_path: Path, lost_by: str, field: str
) -> None:
    """Unequal capability is legitimate; concealing it is not.

    Each backend's field map is emptied of one field in turn. The differential has
    to name the field, name who can still do it, and name who cannot — and the
    value must not simply vanish from the draft.
    """
    _capcut_or_skip()
    manifest = _manifest(media)
    saved_capcut = dict(capcut_module.CAPCUT_TEXT_FIELD_MAP)
    saved_internal = dict(p51_editable.PARAMETRIC_TEXT_STYLE_FIELDS)
    if lost_by == "CAPCUT_CLI":
        capcut_module.CAPCUT_TEXT_FIELD_MAP.pop(field, None)
    else:
        p51_editable.PARAMETRIC_TEXT_STYLE_FIELDS.pop(field, None)
    try:
        projections = _project(manifest, tmp_path, f"lose-{field}-{lost_by}")
    finally:
        capcut_module.CAPCUT_TEXT_FIELD_MAP.clear()
        capcut_module.CAPCUT_TEXT_FIELD_MAP.update(saved_capcut)
        p51_editable.PARAMETRIC_TEXT_STYLE_FIELDS.clear()
        p51_editable.PARAMETRIC_TEXT_STYLE_FIELDS.update(saved_internal)

    report = compare_projections(manifest, projections)
    assert report.ok is False, "a backend silently lost a style field"

    assert any(
        d.startswith(f"TEXT_FIELDS_NOT_EXPRESSED:{lost_by}=") and field in d
        for d in report.divergences
    ), report.divergences

    survivor = next(p for p in projections if p.backend != lost_by)
    loser = next(p for p in projections if p.backend == lost_by)
    assert field in survivor.expressed_text_fields
    assert field not in loser.expressed_text_fields
    assert field in loser.unsupported_text_fields, (
        "the backend that cannot express a field must say so, not drop it quietly"
    )
    # The field is still named in the report as a divergence, with both sides.
    assert any(
        d.startswith(f"CAPABILITY_DIVERGENCE:{field}:") and lost_by in d
        for d in report.divergences
    ), report.divergences


def test_a_field_outside_the_vocabulary_is_reported_as_undeclared(
    media: dict[str, str], tmp_path: Path
) -> None:
    """An unknown key is a spec mismatch, and is reported by both backends."""
    _capcut_or_skip()
    manifest = _manifest(media, properties={"shadow": True})
    projections = _project(manifest, tmp_path, "undeclared")
    for projection in projections:
        assert "shadow" in projection.undeclared_text_fields, projection.backend
    report = compare_projections(manifest, projections)
    assert report.ok is False
    assert any("UNDECLARED_TEXT_FIELDS" in d for d in report.divergences), report.divergences


# ── The manifest stays the authority ─────────────────────────────────────


def test_the_manifest_is_the_only_description_of_the_overlay(
    media: dict[str, str], tmp_path: Path
) -> None:
    """Neither backend invented a field the manifest did not ask for."""
    _capcut_or_skip()
    manifest = _manifest(media)
    projections = _project(manifest, tmp_path, "authority")
    for projection in projections:
        asked = {
            field
            for element in manifest.elements
            if (declaration := parametric_text_declaration(element)) is not None
            for field in declaration[0]
        }
        assert set(projection.expressed_text_fields) <= asked
        assert set(projection.expressed_text_fields) <= set(PARAMETRIC_TEXT_FIELDS)
        assert not projection.undeclared_text_fields


def test_a_text_overlay_with_no_text_never_reaches_a_backend(
    media: dict[str, str], tmp_path: Path
) -> None:
    """A media element whose file is absent is a lint error, not a text overlay.

    The manifest is the authority, so the earliest gate is the right place to
    refuse this: had it been written as an empty text material, both backends
    would have dutifully shipped a blank overlay and agreed with each other.
    """
    manifest = EditableProjectManifest(
        project_id="no text", duration_ms=4000,
        elements=[
            TrackElement("bg", "BACKGROUND", "CONTEXTUAL_BROLL", 0, 4000, media["video"]),
            TrackElement("ghost", "OVERLAY", "SEMANTIC_HIGHLIGHT", 0, 1000, ""),
        ],
    )
    assert parametric_text_declaration(manifest.elements[1]) is None

    errors = lint_manifest(manifest, project_root=tmp_path)
    assert any("MISSING_SOURCE_ARTIFACT:ghost" in e for e in errors), errors

    for backend_id in BACKENDS:
        projection = project_manifest(manifest, tmp_path / f"ghost-{backend_id.value}", backend_id)
        assert projection.outcome.value == "LINT_FAILED", projection.backend
        assert projection.project_path == ""
        assert projection.dropped_elements == [], projection.backend


@pytest.fixture(autouse=True)
def _restore_capability_maps() -> Iterator[None]:
    """Guarantee a mutation in one test cannot leak into the next."""
    saved_capcut = dict(capcut_module.CAPCUT_TEXT_FIELD_MAP)
    saved_internal = dict(p51_editable.PARAMETRIC_TEXT_STYLE_FIELDS)
    yield
    capcut_module.CAPCUT_TEXT_FIELD_MAP.clear()
    capcut_module.CAPCUT_TEXT_FIELD_MAP.update(saved_capcut)
    p51_editable.PARAMETRIC_TEXT_STYLE_FIELDS.clear()
    p51_editable.PARAMETRIC_TEXT_STYLE_FIELDS.update(saved_internal)
