"""HEVI P5.1 — layered delivery, layer semantics, structural round trip.

Covers §61-§66: the eight canonical layers, per-element semantics, honest
refusals and the structural (not GUI) round trip.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hevi.ops.p5_1_editable import (
    CAPTION_SUFFIXES,
    LAYER_TRACK_TYPE,
    SEMANTIC_ROLES,
    SUPPORTED_EDITABLE_PROPERTIES,
    build_layered_draft,
    manifest_from_production,
    structural_round_trip,
    validate_layered_project,
)
from hevi.ops.p5_1_types import LAYER_Z_ORDER, EditableLayer


def _make_video(path: Path, seconds: float = 2.0) -> Path:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"color=c=teal:s=320x180:d={seconds}",
         "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
         "-map", "0:v:0", "-map", "1:a:0", "-shortest",
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(path)],
        check=True, capture_output=True,
    )
    return path


def _make_audio(path: Path, seconds: float = 2.0) -> Path:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:a", "aac", str(path)],
        check=True, capture_output=True,
    )
    return path


def _make_srt(path: Path) -> Path:
    path.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nfirst line\n\n"
        "2\n00:00:02,000 --> 00:00:04,000\nsecond line\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def artifacts(tmp_path: Path) -> dict[str, Path]:
    return {
        "video": _make_video(tmp_path / "bg.mp4"),
        "speaker": _make_video(tmp_path / "speaker.mp4"),
        "audio": _make_audio(tmp_path / "voice.m4a"),
        "srt": _make_srt(tmp_path / "captions.srt"),
    }


def _full_manifest(artifacts: dict[str, Path]):
    return manifest_from_production(
        content_id="c1",
        candidate_id="V1",
        background_path=str(artifacts["video"]),
        speaker_path=str(artifacts["speaker"]),
        evidence=[
            {
                "path": str(artifacts["video"]),
                "start_ms": 0,
                "end_ms": 2000,
                "asset_id": "e1",
                "role": "EVIDENCE_DOMINANT",
            }
        ],
        overlay=[{"path": str(artifacts["video"]), "start_ms": 0, "end_ms": 1000,
                  "asset_id": "o1"}],
        caption_path=str(artifacts["srt"]),
        voice_path=str(artifacts["audio"]),
        bgm_path=str(artifacts["audio"]),
        sfx_paths=[str(artifacts["audio"])],
        duration_ms=4000,
    )


# ── test_layer_semantics ─────────────────────────────────────────────────


def test_canonical_layers_are_the_eight_required_ones() -> None:
    assert {layer.value for layer in EditableLayer} == {
        "BACKGROUND", "SPEAKER", "EVIDENCE", "OVERLAY", "CAPTIONS", "VOICE", "BGM", "SFX"
    }


def test_layer_z_order_is_total_and_ordered() -> None:
    values = [LAYER_Z_ORDER[layer] for layer in EditableLayer]
    assert len(set(values)) == len(values)
    assert LAYER_Z_ORDER[EditableLayer.BACKGROUND] < LAYER_Z_ORDER[EditableLayer.SPEAKER]
    assert LAYER_Z_ORDER[EditableLayer.SPEAKER] < LAYER_Z_ORDER[EditableLayer.CAPTIONS]
    assert LAYER_Z_ORDER[EditableLayer.VOICE] < LAYER_Z_ORDER[EditableLayer.EVIDENCE]


def test_every_layer_has_a_track_type_and_role_vocabulary() -> None:
    for layer in EditableLayer:
        assert LAYER_TRACK_TYPE[layer]
        assert SEMANTIC_ROLES[layer]


def test_every_element_declares_its_semantics() -> None:
    manifest = _full_manifest(
        {"video": _make_video(Path("/tmp/p51_sem_v.mp4")), "speaker": _make_video(Path("/tmp/p51_sem_s.mp4")),
         "audio": _make_audio(Path("/tmp/p51_sem_a.m4a")), "srt": _make_srt(Path("/tmp/p51_sem.srt"))}
    )
    for element in manifest.elements():
        payload = element.to_dict()
        for field in (
            "element_id", "layer", "semantic_role", "start_ms", "end_ms",
            "source_artifact", "z_order", "editable_params",
        ):
            assert field in payload, field
        assert element.z_order == LAYER_Z_ORDER[element.layer]
        assert element.duration_ms > 0


def test_layer_semantics_rejects_a_role_the_layer_cannot_carry(tmp_path: Path) -> None:
    artifacts = {"video": _make_video(tmp_path / "bg.mp4"), "speaker": _make_video(tmp_path / "sp.mp4"),
                 "audio": _make_audio(tmp_path / "v.m4a"), "srt": _make_srt(tmp_path / "c.srt")}
    manifest = _full_manifest(artifacts)
    manifest.layers["BACKGROUND"][0].semantic_role = "DIRECT_ADDRESS"
    project = build_layered_draft(manifest, tmp_path / "proj")
    ok, errors = validate_layered_project(project)
    assert ok is False
    assert any("LAYER_SEMANTICS_INVALID" in e for e in errors)


def test_element_beyond_the_timeline_is_rejected(tmp_path: Path) -> None:
    artifacts = {"video": _make_video(tmp_path / "bg.mp4"), "speaker": _make_video(tmp_path / "sp.mp4"),
                 "audio": _make_audio(tmp_path / "v.m4a"), "srt": _make_srt(tmp_path / "c.srt")}
    manifest = _full_manifest(artifacts)
    manifest.duration_ms = 1000
    project = build_layered_draft(manifest, tmp_path / "proj")
    ok, errors = validate_layered_project(project)
    assert ok is False
    assert any("ELEMENT_BEYOND_TIMELINE" in e for e in errors)


def test_caption_layer_requires_a_text_source(tmp_path: Path) -> None:
    """An audio file must never be relabelled as captions to pass a gate."""
    manifest = manifest_from_production(
        content_id="c1",
        candidate_id="V1",
        caption_path=str(_make_audio(tmp_path / "notcaptions.m4a")),
        duration_ms=2000,
    )
    project = build_layered_draft(manifest, tmp_path / "proj")
    assert manifest.populated_layers() == []
    assert project.refused_elements
    assert "CAPTIONS_REQUIRES_TEXT_SOURCE" in project.refused_elements[0]
    assert ".srt" in CAPTION_SUFFIXES


def test_missing_source_is_refused_not_faked(tmp_path: Path) -> None:
    manifest = manifest_from_production(
        content_id="c1", candidate_id="V1", background_path="/definitely/missing.mp4", duration_ms=2000
    )
    project = build_layered_draft(manifest, tmp_path / "proj")
    assert manifest.populated_layers() == []
    assert "SOURCE_MISSING" in project.refused_elements[0]
    # An absent layer is allowed; the refusal just has to stay visible.
    assert validate_layered_project(project) == (True, [])


def test_broken_reference_blocks_delivery(tmp_path: Path) -> None:
    """A19: a broken reference must be a delivery block, not a warning."""
    artifacts = {"video": _make_video(tmp_path / "bg.mp4"), "speaker": _make_video(tmp_path / "sp.mp4"),
                 "audio": _make_audio(tmp_path / "v.m4a"), "srt": _make_srt(tmp_path / "c.srt")}
    manifest = _full_manifest(artifacts)
    project = build_layered_draft(manifest, tmp_path / "proj")
    assert validate_layered_project(project)[0] is True

    draft = json.loads(Path(project.timeline_json).read_text(encoding="utf-8"))
    draft["materials"] = []
    Path(project.timeline_json).write_text(json.dumps(draft), encoding="utf-8")
    ok, errors = validate_layered_project(project)
    assert ok is False
    assert any("BROKEN_REFERENCE" in e for e in errors)


def test_no_empty_tracks_are_shipped(tmp_path: Path) -> None:
    artifacts = {"video": _make_video(tmp_path / "bg.mp4"), "speaker": _make_video(tmp_path / "sp.mp4"),
                 "audio": _make_audio(tmp_path / "v.m4a"), "srt": _make_srt(tmp_path / "c.srt")}
    project = build_layered_draft(_full_manifest(artifacts), tmp_path / "proj")
    draft = json.loads(Path(project.timeline_json).read_text(encoding="utf-8"))
    for track in draft["tracks"]:
        assert track["segments"], "a track must never ship empty"


# ── test_editable_round_trip ─────────────────────────────────────────────


def test_layered_project_validates_end_to_end(tmp_path: Path, artifacts: dict[str, Path]) -> None:
    project = build_layered_draft(_full_manifest(artifacts), tmp_path / "proj")
    ok, errors = validate_layered_project(project)
    assert ok is True, errors
    assert project.validated is True
    assert project.duration_s == pytest.approx(4.0)
    assert {layer.value for layer in project.manifest.populated_layers()} == {
        "BACKGROUND", "SPEAKER", "EVIDENCE", "OVERLAY", "CAPTIONS", "VOICE", "BGM", "SFX"
    }


@pytest.mark.parametrize("mutation", SUPPORTED_EDITABLE_PROPERTIES)
def test_editable_round_trip_survives_one_supported_edit(
    tmp_path: Path, artifacts: dict[str, Path], mutation: str
) -> None:
    project = build_layered_draft(_full_manifest(artifacts), tmp_path / f"proj_{mutation}")
    result = structural_round_trip(project, mutation=mutation)
    assert result.ok is True, result.errors
    assert result.revalidated is True
    assert result.kind == "STRUCTURAL_ROUND_TRIP"


def test_round_trip_is_labelled_structural_not_gui(tmp_path: Path, artifacts: dict[str, Path]) -> None:
    """§66: a GUI round trip must never be claimed."""
    project = build_layered_draft(_full_manifest(artifacts), tmp_path / "proj")
    result = structural_round_trip(project)
    assert result.kind == "STRUCTURAL_ROUND_TRIP"
    assert "No GUI round trip is claimed" in result.note
    assert "gui" not in result.kind.lower()


def test_round_trip_rejects_an_unsupported_mutation(
    tmp_path: Path, artifacts: dict[str, Path]
) -> None:
    project = build_layered_draft(_full_manifest(artifacts), tmp_path / "proj")
    result = structural_round_trip(project, mutation="delete.everything")
    assert result.ok is False
    assert "MUTATION_UNSUPPORTED" in result.errors[0]


def test_round_trip_actually_changes_the_draft(
    tmp_path: Path, artifacts: dict[str, Path]
) -> None:
    """A round trip that changes nothing would prove nothing."""
    project = build_layered_draft(_full_manifest(artifacts), tmp_path / "proj")
    before = json.loads(Path(project.timeline_json).read_text(encoding="utf-8"))
    result = structural_round_trip(project, mutation="element.volume")
    after = json.loads(Path(project.timeline_json).read_text(encoding="utf-8"))
    assert result.ok is True
    assert before != after


def test_round_trip_restores_the_draft_when_validation_fails(
    tmp_path: Path, artifacts: dict[str, Path]
) -> None:
    project = build_layered_draft(_full_manifest(artifacts), tmp_path / "proj")
    timeline = Path(project.timeline_json)
    original = timeline.read_text(encoding="utf-8")
    project.manifest.duration_ms = 1  # make the existing elements invalid
    result = structural_round_trip(project, mutation="element.volume")
    assert result.ok is False
    assert timeline.read_text(encoding="utf-8") == original
