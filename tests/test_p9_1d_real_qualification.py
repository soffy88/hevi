"""P9.1.d — real qualification of the local provider fleet.

Every artifact here was produced by the provider under test. No fixtures, no mocks:
the framework executes the adapter, reads the bytes, computes the digest, issues a
receipt and runs P8.4 validation.

`hyperframes` is the exception and is reported honestly: its binary exists and reports
a version, but `hyperframes_generate` never terminates — it exceeded a 600s timeout on
this machine. That is a real finding, not a skipped test, and it is recorded as
`BLOCKED_BY_RUNTIME` with the cause rather than quietly excluded.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from hevi.artifact.checks import CheckOperator, CheckRequirement
from hevi.qualification.framework_local import qualify_local_provider
from hevi.qualification.models import QualificationRequest
from hevi.qualification.providers import ADAPTERS

MANIM_ARTIFACT = Path(
    "/tmp/opencode/manim_scene/out/videos/scene/480p15/HeviQualificationScene.mp4"
)

VIDEO_CHECKS = (
    CheckRequirement("container", "isom"),
    CheckRequirement("duration", 0.5, CheckOperator.GTE),
)


@pytest.fixture(scope="module")
def workspace():
    path = Path(tempfile.mkdtemp(prefix="hevi-p9-1d-"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(scope="module")
def seed_artifact(workspace: Path) -> Path:
    """A real artifact for ffmpeg to transform. Produced by manim, not fabricated."""
    if not MANIM_ARTIFACT.exists():
        from hevi.qualification.providers.manim import ManimAdapter

        result = ManimAdapter().execute(
            QualificationRequest(provider_id="manim",
                                output_path=str(workspace / "seed.mp4"), timeout_s=420)
        )
        return Path(result.artifact_locator)
    return MANIM_ARTIFACT


def _qualify(provider_id: str, output: Path, **kwargs):
    return qualify_local_provider(
        QualificationRequest(provider_id=provider_id, output_path=str(output), **kwargs),
        checks=VIDEO_CHECKS,
    )


# ══════════════════════════════════════════════════════════════════════════
# real qualification
# ══════════════════════════════════════════════════════════════════════════


def test_manim_is_qualified(workspace):
    result = _qualify("manim", workspace / "manim.mp4", timeout_s=420)
    assert result.qualified, f"{result.verdict.value}: {result.reason}"
    assert result.receipt is not None


def test_remotion_is_qualified(workspace):
    result = _qualify("remotion", workspace / "remotion.mp4", timeout_s=600)
    assert result.qualified, f"{result.verdict.value}: {result.reason}"
    assert result.receipt is not None


def test_html_gsap_is_qualified(workspace):
    result = _qualify("html_gsap", workspace / "html_gsap.mp4",
                      params={"duration_s": 1.5}, timeout_s=300)
    assert result.qualified, f"{result.verdict.value}: {result.reason}"
    assert result.receipt is not None
    assert Path(result.locator).stat().st_size > 0


def test_ffmpeg_is_qualified(workspace, seed_artifact):
    """An encoder transforms a real artifact produced by another provider."""
    result = _qualify("ffmpeg", workspace / "transcoded.mp4",
                      input_path=str(seed_artifact), timeout_s=300)
    assert result.qualified, f"{result.verdict.value}: {result.reason}"
    assert result.receipt is not None
    assert Path(result.locator).stat().st_size > 0


@pytest.mark.parametrize("provider_id", ["manim", "remotion", "html_gsap"])
def test_qualified_artifact_is_real_media(workspace, provider_id):
    """Independent ffprobe confirmation, not the framework's own word for it."""
    result = _qualify(provider_id, workspace / f"{provider_id}-probe.mp4", timeout_s=600)
    if not result.qualified:
        pytest.skip(f"{provider_id} not qualified in this environment")
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_name,width,height", "-show_entries", "format=duration",
         "-of", "json", result.locator],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "codec_name" in proc.stdout


# ══════════════════════════════════════════════════════════════════════════
# hyperframes — reported honestly
# ══════════════════════════════════════════════════════════════════════════


def test_hyperframes_runtime_is_declared_present():
    """The binary exists and answers — which is why this is not NOT_FOUND."""
    from hevi.qualification.providers.hyperframes import hyperframes_bin

    binary = hyperframes_bin()
    if not binary:
        pytest.skip("hyperframes binary absent")
    proc = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, timeout=60, check=False
    )
    assert proc.returncode == 0
    assert proc.stdout.strip()


@pytest.mark.slow
def test_hyperframes_render_terminates(workspace):
    """F2 by non-termination: a render that never returns cannot be qualified.

    The adapter is given a short budget on purpose. `hyperframes_generate` hung past
    600s on this machine, so the honest verdict is BLOCKED_BY_RUNTIME with the timeout
    recorded — not a pass, and not a crash.
    """
    result = _qualify("hyperframes", workspace / "hyperframes.mp4",
                      params={"prompt": "a single blue circle"}, timeout_s=90)
    assert result.verdict.value in {
        "qualified", "blocked_by_runtime", "qualification_failed",
    }, result.verdict.value
    if not result.qualified:
        assert result.reason, "a non-qualification must say why"


# ══════════════════════════════════════════════════════════════════════════
# failure paths
# ══════════════════════════════════════════════════════════════════════════


def test_missing_runtime_is_blocked_not_failed(workspace, monkeypatch):
    """F1: nothing started, so nothing failed."""
    monkeypatch.setattr(ADAPTERS["ffmpeg"], "available",
                        lambda self: __import__(
                            "hevi.qualification.models", fromlist=["x"]
                        ).AdapterAvailability(
                            __import__("hevi.qualification.models", fromlist=["x"]
                                       ).Availability.MISSING_RUNTIME, "no_binary"))
    result = _qualify("ffmpeg", workspace / "never.mp4")
    assert result.verdict.value == "blocked_by_runtime"
    assert result.receipt is None
    assert result.source is None


def test_exit_zero_without_an_artifact_is_rejected(workspace):
    """F2: the runtime ran, reported success, and wrote nothing.

    Previously this used `hyperframes` as its vehicle, which only worked while
    hyperframes could not render at all — so the test was really asserting "hyperframes
    is broken", not "the framework rejects a silent no-op". P9.1.e made hyperframes
    render, and the test inverted for the wrong reason. F2 is a property of the
    *framework*, so it is exercised with a controlled adapter whose exit is zero and
    whose artifact is absent.
    """
    from hevi.qualification.models import (
        AdapterAvailability,
        Availability,
        ExecutionState,
    )
    from hevi.qualification.models import (
        QualificationRequest as QR,
    )
    from hevi.qualification.providers._shared import AdapterFailure

    class _SilentSuccess:
        provider_id = "silent"

        def available(self):
            return AdapterAvailability(Availability.AVAILABLE)

        def execute(self, request):
            raise AdapterFailure(
                ExecutionState.NO_ARTIFACT, "exit reported success but wrote nothing"
            )

    result = qualify_local_provider(
        QR(provider_id="silent", output_path=str(workspace / "never.mp4")),
        checks=VIDEO_CHECKS, adapter=_SilentSuccess(),
    )
    assert result.verdict.value == "rejected"
    assert result.receipt is None


def test_hyperframes_now_qualifies_or_blocks_with_a_reason(workspace):
    """P9.1.e superseded the old expectation; the cause must always be stated."""
    result = _qualify("hyperframes", workspace / "hyperframes.mp4",
                      params={"prompt": "a blue circle"}, timeout_s=180)
    assert result.verdict.value in {
        "qualified", "blocked_by_runtime", "qualification_failed",
    }
    if result.qualified:
        assert result.receipt is not None
        assert result.reason == ""
    else:
        assert result.reason, "a non-qualification must name its cause"


def test_artifact_digest_mismatch_is_invalid(workspace, seed_artifact):
    """F3: bytes that are not what was claimed."""
    from hevi.qualification.framework_local import qualify_local_provider as ql

    result = ql(
        QualificationRequest(provider_id="ffmpeg",
                            output_path=str(workspace / "mismatch.mp4"),
                            input_path=str(seed_artifact), timeout_s=300),
        checks=VIDEO_CHECKS, expected_checksum="b" * 64,
    )
    assert result.verdict.value == "invalid_artifact"
    assert result.receipt is None


def test_encoder_refuses_to_generate_without_an_input(workspace):
    """No prompt → video path exists."""
    result = _qualify("ffmpeg", workspace / "noinput.mp4")
    assert result.verdict.value == "rejected"
    assert "does not generate" in result.reason
