"""E2E-F — one manifest, two real editable backends.

The manifest is the single authority. Both backends receive it unchanged and
each produces a real, openable project: the Internal Jianying backend writes a
layered draft through HEVI's own P5.1 machinery, and the CapCut backend drives
the real ``capcut-cli`` binary. Neither is allowed to become a place where the
edit is decided — they are two projections of one decision, and the differential
report is what proves they agree.

The case that matters is the disagreement. A differential that only ever compares
one backend against itself would pass on any implementation, so the test also
projects a manifest with a deliberate structural divergence and requires the
comparison to notice.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from p5_2_real_assets import ffmpeg_bin

from hevi.editable import (
    EditableBackendId,
    EditableProjectManifest,
    ProjectOutcome,
    TrackElement,
    compare_projections,
    get_backend,
    lint_manifest,
    project_manifest,
    register_all_backends,
    structural_round_trip,
)

pytestmark = pytest.mark.slow


def _capcut_available() -> tuple[bool, str]:
    backend = get_backend(EditableBackendId.CAPCUT_CLI)
    if backend is None:
        return False, "capcut backend not registered"
    if not backend.detect():
        return False, backend.unavailable_reason
    return True, f"capcut-cli {backend.installed_version} @ {backend.revision}"


def _real_clips(workdir: Path) -> dict[str, str]:
    """Real video and real audio on disk, for the timeline to reference."""
    import subprocess

    workdir.mkdir(parents=True, exist_ok=True)
    video = workdir / "picture.mp4"
    audio = workdir / "voice.wav"
    subprocess.run(
        [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=navy:s=640x360:r=25:d=4",
         "-f", "lavfi", "-i", "sine=frequency=220:duration=4",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)],
        check=True, capture_output=True,
    )
    subprocess.run(
        [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "sine=frequency=220:duration=4",
         "-c:a", "pcm_s16le", str(audio)],
        check=True, capture_output=True,
    )
    return {"video": str(video), "audio": str(audio)}


def _manifest(clips: dict[str, str]) -> EditableProjectManifest:
    """A real timeline: a background and a voice track, both backed by real files.

    Only media-backed elements, because those are the ones both backends can
    express today. The parametric overlay is exercised separately, because it is
    exactly where the two backends disagree.
    """
    return EditableProjectManifest(
        project_id="p5.2 e2e f", duration_ms=4000, canvas_width=640, canvas_height=360, fps=25,
        content_id="e2e-f-content", candidate_id="e2e-f-candidate",
        elements=[
            TrackElement("bg", "BACKGROUND", "CONTEXTUAL_BROLL", 0, 4000, clips["video"]),
            TrackElement("voice", "VOICE", "NARRATION", 0, 4000, clips["audio"]),
        ],
    )


def _with_parametric_overlay(manifest: EditableProjectManifest) -> EditableProjectManifest:
    """The same cut plus a lower third whose text is editable rather than baked in."""
    from dataclasses import replace

    return replace(
        manifest,
        elements=[
            *manifest.elements,
            TrackElement("lower-third", "OVERLAY", "EVIDENCE", 500, 2500, "",
                         transform={"x": 0.0, "y": 0.78, "scale": 1.0}, opacity=0.92,
                         editable_properties={"text": "measured, not asserted"}),
        ],
    )


def test_e2e_f1_a_manifest_that_lints_produces_two_real_projects(tmp_path: Path) -> None:
    """Both backends, one manifest, two real projects."""
    register_all_backends()
    clips = _real_clips(tmp_path / "clips")
    manifest = _manifest(clips)

    errors = lint_manifest(manifest, project_root=tmp_path)
    assert not errors, errors

    projections = []
    for backend_id in (EditableBackendId.INTERNAL_JIANYING, EditableBackendId.CAPCUT_CLI):
        available, reason = (True, "") if backend_id is EditableBackendId.INTERNAL_JIANYING \
            else _capcut_available()
        if not available:
            pytest.skip(f"{backend_id.value} unavailable: {reason}")
        projection = project_manifest(manifest, tmp_path / backend_id.value.lower(), backend_id)
        assert projection.outcome is ProjectOutcome.OK, (backend_id, projection.reason)
        assert projection.project_path, backend_id
        assert Path(projection.project_path).exists(), projection.project_path
        assert projection.track_count >= 2, projection.track_count
        assert projection.semantic_roles == ["CONTEXTUAL_BROLL", "NARRATION"], (
            projection.semantic_roles
        )
        assert projection.duration_ms == 4000, projection.duration_ms
        # Both backends agree about what is genuinely flattened. A narration
        # track is a real audio clip and stays editable.
        assert "voice" not in projection.flattened, (
            f"{backend_id.value} flattened an editable narration clip: {projection.flattened}"
        )
        assert not projection.lint_errors, projection.lint_errors
        projections.append(projection)

    for projection in projections:
        ok, reasons = structural_round_trip(manifest, projection)
        assert ok, (projection.backend, reasons)


def test_e2e_f2_the_two_backends_agree_on_one_manifest(tmp_path: Path) -> None:
    """The differential is the point: two projections, one decision."""
    register_all_backends()
    available, reason = _capcut_available()
    if not available:
        pytest.skip(f"capcut backend unavailable: {reason}")

    manifest = _manifest(_real_clips(tmp_path / "clips"))
    projections = [
        project_manifest(manifest, tmp_path / "internal", EditableBackendId.INTERNAL_JIANYING),
        project_manifest(manifest, tmp_path / "capcut", EditableBackendId.CAPCUT_CLI),
    ]
    assert all(p.outcome is ProjectOutcome.OK for p in projections)

    report = compare_projections(manifest, projections)
    assert report.ok, report.divergences
    assert {str(b) for b in report.backends} == {"INTERNAL_JIANYING", "CAPCUT_CLI"}, (
        report.backends
    )
    assert report.track_counts, report.track_counts
    # Both backends carried the semantic roles through, not just the file names.
    for projection in projections:
        assert {"CONTEXTUAL_BROLL", "NARRATION"} <= set(projection.semantic_roles), (
            projection.backend, projection.semantic_roles
        )


def test_e2e_f3_a_parametric_overlay_is_reported_as_a_divergence(tmp_path: Path) -> None:
    """A real limitation, measured rather than papered over.

    A lower third whose text is editable has no media file behind it. CapCut
    expresses that natively as a text track; HEVI's own layered Jianying draft
    drops an element with no source path. The two projections therefore disagree,
    and the differential has to say so — a cut in this state is not eligible for
    dual-backend delivery, and pretending otherwise would ship a project that
    silently lost an overlay in one of the two editors.
    """
    register_all_backends()
    available, reason = _capcut_available()
    if not available:
        pytest.skip(f"capcut backend unavailable: {reason}")

    base = _manifest(_real_clips(tmp_path / "clips"))
    manifest = _with_parametric_overlay(base)

    internal = project_manifest(manifest, tmp_path / "internal", EditableBackendId.INTERNAL_JIANYING)
    capcut = project_manifest(manifest, tmp_path / "capcut", EditableBackendId.CAPCUT_CLI)
    assert internal.outcome is ProjectOutcome.OK, internal.reason
    assert capcut.outcome is ProjectOutcome.OK, capcut.reason

    # CapCut keeps the overlay, as editable text.
    assert "lower-third" in capcut.semantic_roles or capcut.track_count >= 3, (
        "capcut dropped the parametric overlay entirely"
    )
    spec = json.loads((capcut.timeline_path and Path(capcut.timeline_path).read_text())
                      or "{}")
    tracks = spec if isinstance(spec, list) else [spec]
    text_tracks = [
        t for d in tracks if isinstance(d, dict)
        for t in d.get("tracks", []) if t.get("type") == "text"
    ]
    assert text_tracks, "the overlay did not become a CapCut text track"
    # The CLI normalises a text track into its own material references, so look
    # for the copy in the draft rather than in a conveniently shaped item field.
    draft = json.loads(Path(capcut.timeline_path).read_text(encoding="utf-8"))
    assert "measured, not asserted" in json.dumps(draft, ensure_ascii=False), (
        "the overlay text is not present anywhere in the CapCut draft"
    )

    # And the differential refuses to call that agreement.
    report = compare_projections(manifest, [internal, capcut])
    assert report.ok is False, (
        "the parametric overlay was silently dropped by one backend and the "
        "differential still passed"
    )
    assert report.divergences, report.divergences


def test_e2e_f3b_a_structural_divergence_is_caught(tmp_path: Path) -> None:
    """A backend that drops a track must not pass a differential."""
    register_all_backends()
    manifest = _manifest(_real_clips(tmp_path / "clips"))

    honest = project_manifest(
        manifest, tmp_path / "internal", EditableBackendId.INTERNAL_JIANYING,
    )
    assert honest.outcome is ProjectOutcome.OK, honest.reason

    from hevi.editable.base import BackendProjection

    lossy = BackendProjection(
        backend="capcut_cli", outcome=ProjectOutcome.OK,
        project_path=honest.project_path, track_count=1, material_count=0,
        duration_ms=honest.duration_ms, semantic_roles=["CONTEXTUAL_BROLL"],
        layer_coverage={}, flattened=False,
    )
    report = compare_projections(manifest, [honest, lossy])
    assert report.ok is False, "a backend that dropped tracks passed the differential"
    assert report.divergences, report.divergences


def test_e2e_f4_the_capcut_project_really_parses_back(tmp_path: Path) -> None:
    """Not just "a file exists" — the project reads back as a real timeline."""
    register_all_backends()
    available, reason = _capcut_available()
    if not available:
        pytest.skip(f"capcut backend unavailable: {reason}")

    manifest = _manifest(_real_clips(tmp_path / "clips"))
    projection = project_manifest(manifest, tmp_path / "capcut", EditableBackendId.CAPCUT_CLI)
    assert projection.outcome is ProjectOutcome.OK, projection.reason
    assert projection.version, "the capcut project recorded no tool version"
    assert projection.revision, "the capcut project recorded no tool revision"

    path = Path(projection.timeline_path or projection.project_path)
    assert path.is_file(), path
    payload = json.loads(path.read_text(encoding="utf-8"))
    # Find the timeline document and confirm it carries tracks and a duration.
    documents = payload if isinstance(payload, list) else [payload]
    timelines = [
        d for d in documents
        if isinstance(d, dict) and ("tracks" in d or "materials" in d)
    ]
    assert timelines, f"no timeline document in {path}"
    document = timelines[0]
    assert document.get("tracks"), document.keys()
    assert document["tracks"], "the timeline has no tracks"


def test_e2e_f5_a_missing_capcut_binary_is_reported_not_faked(tmp_path: Path) -> None:
    """A backend whose tool is absent says so; it does not emit an empty project."""
    register_all_backends()
    manifest = _manifest(_real_clips(tmp_path / "clips"))

    original = os.environ.get("CAPCUT_CLI_BIN")
    os.environ["CAPCUT_CLI_BIN"] = "capcut-cli-that-does-not-exist"
    try:
        from hevi.editable.capcut_cli import CapCutCliBackend

        absent = CapCutCliBackend()
        projection = absent.project(manifest, tmp_path / "missing")
    finally:
        if original is None:
            os.environ.pop("CAPCUT_CLI_BIN", None)
        else:
            os.environ["CAPCUT_CLI_BIN"] = original

    assert projection.outcome is ProjectOutcome.UNAVAILABLE, projection
    assert projection.reason, "an unavailable backend gave no reason"
    assert not projection.project_path
    assert not list((tmp_path / "missing").rglob("*")), "an unavailable backend wrote files"


def test_e2e_f6_a_manifest_that_fails_lint_is_refused_before_any_backend_runs(
    tmp_path: Path,
) -> None:
    """Lint is a precondition, not a warning."""
    register_all_backends()
    manifest = _manifest(_real_clips(tmp_path / "clips"))
    manifest.elements[0].end_ms = 99_000  # past the end of the timeline
    for backend_id in (EditableBackendId.INTERNAL_JIANYING, EditableBackendId.CAPCUT_CLI):
        projection = project_manifest(manifest, tmp_path / backend_id.value.lower(), backend_id)
        assert projection.outcome is ProjectOutcome.LINT_FAILED, projection.outcome
        assert any("BEYOND_TIMELINE" in e for e in projection.lint_errors), projection.lint_errors
        assert not projection.project_path
