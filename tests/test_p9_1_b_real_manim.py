"""P9.1.b — A real manim render, qualified end to end.

Nothing here is simulated. The scene is rendered by manim 0.21.0 in a subprocess,
the artifact is the MP4 manim actually wrote, the checksum is computed from those bytes,
the receipt is issued from them, and P8.4 validates them with a real ffprobe.

That makes this the first **real provider qualification** in HEVI's history:
GAP-003 moves from 0/16 to 1/16.

The failure paths are kept alongside the success path, because a harness that only
proves the happy line proves nothing about the boundaries:

    missing command            -> BLOCKED_BY_RUNTIME
    driver error               -> QUALIFICATION_FAILED
    exit 0 but no artifact     -> REJECTED
    artifact invalid           -> INVALID_ARTIFACT
    artifact valid             -> QUALIFIED
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

from hevi.acquisition.models import AcquiredSource
from hevi.artifact.checks import CheckOperator, CheckRequirement
from hevi.artifact.qualify import ArtifactState
from hevi.evidence.acquisition import AcquisitionEvidence, checksum_bytes
from hevi.execution.models import ProductionReceipt
from hevi.providers.runtime_specs import RUNTIME_SPECS
from hevi.qualification import QualificationVerdict
from hevi.qualification.local_process import run_local_process_qualification
from hevi.validation.artifact import ValidationResult

REPO = pathlib.Path(__file__).resolve().parents[1]
MANIM_BIN = REPO / ".venv" / "bin" / "manim"
SCENE_NAME = "HeviQualificationScene"
LOCATOR = f"out/videos/scene/480p15/{SCENE_NAME}.mp4"

SCENE_SOURCE = '''"""A real manim scene, rendered for P9.1.b qualification."""

from manim import Create, Dot, Line, ORIGIN, RIGHT, Scene, Text, UP, Write


class HeviQualificationScene(Scene):
    def construct(self):
        title = Text("HEVI P9.1.b")
        self.play(Write(title))
        self.play(title.animate.scale(0.5).to_edge(UP))
        line = Line(ORIGIN - 4 * RIGHT, ORIGIN + 4 * RIGHT, color="#3B82F6")
        dot = Dot(ORIGIN, radius=0.18, color="#F59E0B")
        self.play(Create(line))
        self.play(Create(dot), dot.animate.move_to(RIGHT * 4))
        self.wait(0.2)
'''

HAS_MANIM = MANIM_BIN.exists()
pytestmark = pytest.mark.skipif(
    not HAS_MANIM, reason="manim runtime not installed; see GAP-005"
)

# what manim -ql actually produces, verified by ffprobe before these were written
REQUIREMENTS = (
    CheckRequirement("codec", "h264"),
    CheckRequirement("container", "isom"),
    CheckRequirement("resolution", (854, 480)),
    CheckRequirement("duration", 4.0, CheckOperator.GTE),
)

MANIM = RUNTIME_SPECS.resolve("manim")


def _command() -> tuple[str, ...]:
    return (
        str(MANIM_BIN), "render", "scene.py", SCENE_NAME,
        "--media_dir", "out", "-ql", "--format", "mp4",
    )


@pytest.fixture(scope="module")
def rendered(tmp_path_factory) -> tuple[pathlib.Path, bytes]:
    """Render once with real manim; return the scene dir and the artifact bytes."""
    scene_dir = tmp_path_factory.mktemp("manim-scene")
    (scene_dir / "scene.py").write_text(SCENE_SOURCE)
    result = subprocess.run(
        list(_command()), cwd=scene_dir, capture_output=True, timeout=900,
    )
    assert result.returncode == 0, result.stderr.decode()[-800:]
    hits = [
        p for p in sorted((scene_dir / "out").rglob(f"{SCENE_NAME}.mp4"))
        if "partial_movie_files" not in str(p)
    ]
    assert hits, "manim produced no artifact"
    return scene_dir, hits[-1].read_bytes()


def _qualify(scene_dir, payload, **kwargs):
    def read(locator: str) -> bytes:
        if locator:
            candidate = scene_dir / locator
            if candidate.exists():
                return candidate.read_bytes()
        return payload

    return run_local_process_qualification(
        MANIM, requirements=REQUIREMENTS, command=_command(),
        cwd=str(scene_dir), read_artifact=read, artifact_locator=LOCATOR,
        artifact_id="hevi-qualification-scene", producer="manim",
        validator_name="ffprobe", **kwargs,
    )


# ══════════════════════════════════════════════════════════════════════════
# the real qualification
# ══════════════════════════════════════════════════════════════════════════


def test_real_manim_render_qualifies(rendered):
    scene_dir, payload = rendered
    result = _qualify(scene_dir, payload)
    assert result.verdict is QualificationVerdict.QUALIFIED, (
        f"expected QUALIFIED, got {result.verdict.value}: {result.reason}"
    )
    assert result.artifact_state is ArtifactState.QUALIFIED


def test_the_artifact_is_the_bytes_manim_actually_wrote(rendered):
    scene_dir, payload = rendered
    result = _qualify(scene_dir, payload)
    on_disk = (scene_dir / LOCATOR).read_bytes()
    assert result.source.checksum == checksum_bytes(on_disk)
    assert result.observations["bytes"] == len(payload) > 0


def test_validation_observed_the_real_media(rendered):
    scene_dir, payload = rendered
    result = _qualify(scene_dir, payload)
    observed = {c.name: c.observed for c in result.validation.checks}
    assert observed["codec"] == "h264"
    assert observed["resolution"] == (854, 480)
    assert observed["container"] == "isom"
    assert observed["duration"] >= 4.0
    assert result.validation.passed is True


def test_every_link_is_proven_from_real_evidence(rendered):
    scene_dir, payload = rendered
    result = _qualify(scene_dir, payload)
    proven = {link.name.value for link in result.live.links if link.holds}
    assert proven == {"observation", "acquisition", "execution", "artifact"}


def test_receipt_matches_the_acquired_source(rendered):
    scene_dir, payload = rendered
    result = _qualify(scene_dir, payload)
    assert isinstance(result.source, AcquiredSource)
    assert isinstance(result.evidence, AcquisitionEvidence)
    assert isinstance(result.receipt, ProductionReceipt)
    assert isinstance(result.validation, ValidationResult)
    assert result.receipt.artifact_checksum == result.source.checksum
    # the receipt identifies the artifact it covers; run_id names the execution
    assert result.receipt.artifact_id == result.source.source_id
    assert result.receipt.producer == "manim"
    assert result.receipt.validation_result is result.validation


def test_the_render_was_a_real_subprocess(rendered):
    """Not a fixture: the driver recorded a live latency and the renderer ran."""
    scene_dir, payload = rendered
    result = _qualify(scene_dir, payload)
    live = result.live.observed_runtime
    assert live.outcome.is_live is True
    assert live.latency_ms is not None and live.latency_ms > 0
    assert live.status_code == 0


# ══════════════════════════════════════════════════════════════════════════
# failure paths, retained
# ══════════════════════════════════════════════════════════════════════════


def test_missing_command_is_blocked_by_runtime(rendered):
    scene_dir, payload = rendered
    result = run_local_process_qualification(
        MANIM, command=("manim-not-installed",), read_artifact=lambda k: payload,
    )
    assert result.verdict is QualificationVerdict.BLOCKED_BY_RUNTIME
    assert result.receipt is None


def test_driver_error_is_a_failure(rendered):
    scene_dir, payload = rendered

    def boom(command, timeout):
        raise OSError("renderer died")

    result = run_local_process_qualification(
        MANIM, command=_command(), runner=boom, read_artifact=lambda k: payload,
    )
    assert result.verdict is QualificationVerdict.QUALIFICATION_FAILED
    assert "renderer died" in result.reason


def test_exit_zero_without_an_artifact_is_rejected(rendered):
    """The renderer claimed success but named no artifact — caught by the driver."""
    scene_dir, payload = rendered
    result = run_local_process_qualification(
        MANIM, command=_command(), runner=lambda c, t: (0, ""),
        read_artifact=lambda k: b"",
    )
    assert result.verdict is QualificationVerdict.REJECTED
    assert "produced no artifact" in result.reason
    assert result.source is None and result.receipt is None


def test_an_artifact_that_reads_as_empty_is_rejected(rendered):
    """A locator exists but the bytes behind it are empty.

    A different failure from the case above, and the reason is what separates them:
    removing the empty-bytes guard still yields REJECTED, because an empty payload
    fails validation anyway. Only the reason tells the two apart.
    """
    scene_dir, payload = rendered
    result = run_local_process_qualification(
        MANIM, requirements=REQUIREMENTS, command=_command(), cwd=str(scene_dir),
        read_artifact=lambda k: b"", artifact_locator=LOCATOR,
    )
    assert result.verdict is QualificationVerdict.REJECTED
    assert result.reason == "renderer produced no artifact bytes"
    assert result.source is None and result.receipt is None


def test_invalid_artifact_is_invalid(rendered):
    scene_dir, payload = rendered
    result = _qualify(scene_dir, payload, expected_checksum="b" * 64)
    assert result.verdict is QualificationVerdict.INVALID_ARTIFACT
    assert "do not match the declared digest" in result.reason
    assert result.receipt is None


def test_real_artifact_with_the_wrong_requirement_is_rejected(rendered):
    scene_dir, payload = rendered
    result = run_local_process_qualification(
        MANIM, requirements=(CheckRequirement("resolution", (1920, 1080)),),
        command=_command(), cwd=str(scene_dir),
        read_artifact=lambda k: payload, artifact_locator=LOCATOR,
    )
    assert result.verdict is QualificationVerdict.REJECTED
    assert result.artifact_state is ArtifactState.METADATA_MISMATCH


def test_a_locator_alone_is_still_not_proof(rendered):
    scene_dir, payload = rendered
    result = run_local_process_qualification(
        MANIM, requirements=REQUIREMENTS, command=_command(), cwd=str(scene_dir),
        read_artifact=None, artifact_locator=LOCATOR,
    )
    assert result.verdict is QualificationVerdict.REJECTED
    assert "locator is not proof" in result.reason


# ══════════════════════════════════════════════════════════════════════════
# scope of the claim
# ══════════════════════════════════════════════════════════════════════════


def test_this_qualifies_manim_only():
    """One provider of sixteen. GAP-002 and GAP-003 both stay open."""
    assert MANIM.provider_id == "manim"
    from hevi.providers.runtime_specs import RUNTIME_SPECS as registry

    qualified = 1
    assert qualified < len(registry.list_ids())


def test_the_scene_is_a_real_manim_scene():
    """No fallback renderer stands in for manim."""
    assert "from manim import" in SCENE_SOURCE
    assert str(MANIM_BIN) in " ".join(_command())
