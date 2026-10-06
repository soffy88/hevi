"""P9.1.a — LOCAL_PROCESS qualification semantics.

The harness is complete; the manim runtime is absent. Those are different problems and
this file keeps them apart, which is the point of ``BLOCKED_BY_RUNTIME``:

    NOT_RUN               nothing was attempted
    BLOCKED_BY_RUNTIME    we know exactly what is missing
    QUALIFICATION_FAILED  attempted, and the attempt broke
    REJECTED              the runtime ran and declined to produce an artifact
    INVALID_ARTIFACT      bytes arrived but are not what they claim to be
    QUALIFIED             all four links proven, from real bytes

The layering under test is the one P8.4 demanded:

    renderer  ->  artifact bytes  ->  receipt  ->  validator

A renderer returns **bytes**. It never returns a ``ValidationResult`` — otherwise the
provider would own artifact truth again.

The success path uses a real subprocess writing a real MP4, so the loop is proven end to
end with something that actually exists on disk. The renderer is ``ffmpeg``, not manim,
and that substitution is deliberate: this file claims **LOCAL_PROCESS semantics**, not
``manim`` qualification. manim stays ``BLOCKED_BY_RUNTIME`` until it is installed.
"""

from __future__ import annotations

import ast
import json
import pathlib
import shutil
import subprocess

import pytest

from hevi.acquisition.models import AcquiredSource
from hevi.artifact.checks import CheckRequirement
from hevi.artifact.qualify import ArtifactState
from hevi.evidence.acquisition import AcquisitionEvidence
from hevi.execution.models import ProductionReceipt
from hevi.providers.facts import PROVIDER_CATALOGUE
from hevi.providers.runtime_specs import RUNTIME_SPECS, HealthCheckKind
from hevi.qualification import QualificationVerdict
from hevi.qualification.local_process import (
    run_local_process_qualification,
)
from hevi.runtime.live.credentials import StaticCredentialProvider
from hevi.runtime.live.drivers import DriverRegistry, LocalLiveDriver
from hevi.runtime.live.status import LiveOutcome, LiveRuntimeStatus
from hevi.validation.artifact import ValidationResult

MANIM = RUNTIME_SPECS.resolve("manim")
LOCAL = pathlib.Path("hevi/qualification/local_process.py")
REQUIREMENTS = (
    CheckRequirement("codec", "h264"),
    CheckRequirement("resolution", (320, 240)),
)

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def _render_to(tmp_path: pathlib.Path):
    """A REAL subprocess producing a REAL mp4. Not a stand-in for a provider pass."""
    out = tmp_path / "render.mp4"

    def _run(command: tuple[str, ...], timeout: float) -> tuple[int, str]:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi",
             "-i", "testsrc=duration=1:size=320x240:rate=24", "-pix_fmt", "yuv420p",
             "-c:v", "libx264", "-movflags", "frag_keyframe+empty_moov",
             "-f", "mp4", str(out)],
            capture_output=True, timeout=timeout,
        )
        return result.returncode, (str(out) if out.exists() else "")

    return _run, out


# ══════════════════════════════════════════════════════════════════════════
# MANIM_DECLARED_PROVIDER
# ══════════════════════════════════════════════════════════════════════════


def test_manim_is_a_declared_provider():
    profile = PROVIDER_CATALOGUE.get("manim")
    assert profile is not None
    assert profile.locality.value == "LOCAL"


def test_manim_declares_local_process_and_needs_no_credential():
    spec = RUNTIME_SPECS.resolve("manim")
    assert spec.health_check is HealthCheckKind.LOCAL_PROCESS
    assert spec.auth_requirements == (), "a local runtime needs no credential"


# ══════════════════════════════════════════════════════════════════════════
# the required matrix
# ══════════════════════════════════════════════════════════════════════════


def test_matrix_executable_absent_is_blocked_by_runtime():
    result = run_local_process_qualification(
        MANIM, command=("manim-render-does-not-exist",), read_artifact=None
    )
    assert result.verdict is QualificationVerdict.BLOCKED_BY_RUNTIME
    assert "not found on PATH" in result.reason
    assert result.qualified is False


def test_matrix_driver_exception_is_a_failure():
    def boom(command, timeout):
        raise OSError("renderer crashed")

    result = run_local_process_qualification(
        MANIM, command=("manim",), runner=boom, read_artifact=lambda k: b"x"
    )
    assert result.verdict is QualificationVerdict.QUALIFICATION_FAILED
    assert "crashed" in result.reason


def test_matrix_exit_zero_without_an_artifact_is_rejected():
    result = run_local_process_qualification(
        MANIM, command=("manim",), runner=lambda c, t: (0, ""),
        read_artifact=lambda k: b"",
    )
    assert result.verdict is QualificationVerdict.REJECTED


def test_matrix_invalid_artifact_is_invalid_artifact():
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg unavailable")
    tmp = pathlib.Path("/tmp/opencode")
    run, out = _render_to(tmp)
    result = run_local_process_qualification(
        MANIM, requirements=REQUIREMENTS, command=("manim",), runner=run,
        read_artifact=lambda k: out.read_bytes(), expected_checksum="b" * 64,
    )
    assert result.verdict is QualificationVerdict.INVALID_ARTIFACT
    assert "do not match the declared digest" in result.reason


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg unavailable")
def test_matrix_valid_artifact_is_qualified(tmp_path):
    run, out = _render_to(tmp_path)
    result = run_local_process_qualification(
        MANIM, requirements=REQUIREMENTS, command=("manim",), runner=run,
        read_artifact=lambda k: out.read_bytes(),
    )
    assert result.verdict is QualificationVerdict.QUALIFIED
    assert result.qualified is True


# ══════════════════════════════════════════════════════════════════════════
# the qualified path carries real evidence at every link
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg unavailable")
def test_qualified_run_carries_source_evidence_receipt_and_validation(tmp_path):
    run, out = _render_to(tmp_path)
    result = run_local_process_qualification(
        MANIM, requirements=REQUIREMENTS, command=("manim",), runner=run,
        read_artifact=lambda k: out.read_bytes(),
    )
    assert isinstance(result.source, AcquiredSource)
    assert isinstance(result.evidence, AcquisitionEvidence)
    assert isinstance(result.receipt, ProductionReceipt)
    assert isinstance(result.validation, ValidationResult)
    assert result.artifact_state is ArtifactState.QUALIFIED


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg unavailable")
def test_checksum_is_computed_from_the_real_bytes(tmp_path):
    from hevi.evidence.acquisition import checksum_bytes

    run, out = _render_to(tmp_path)
    result = run_local_process_qualification(
        MANIM, requirements=REQUIREMENTS, command=("manim",), runner=run,
        read_artifact=lambda k: out.read_bytes(),
    )
    payload = out.read_bytes()
    assert result.source.checksum == checksum_bytes(payload)
    assert result.receipt.artifact_checksum == result.source.checksum
    assert result.observations["bytes"] == len(payload)


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg unavailable")
def test_all_four_links_are_proven_only_when_qualified(tmp_path):
    run, out = _render_to(tmp_path)
    result = run_local_process_qualification(
        MANIM, requirements=REQUIREMENTS, command=("manim",), runner=run,
        read_artifact=lambda k: out.read_bytes(),
    )
    proven = [link.name.value for link in result.live.links if link.holds]
    assert set(proven) == {"observation", "acquisition", "execution", "artifact"}


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg unavailable")
def test_unmet_requirement_rejects_a_real_artifact(tmp_path):
    """Real bytes, wrong requirement — must not qualify."""
    run, out = _render_to(tmp_path)
    result = run_local_process_qualification(
        MANIM, requirements=(CheckRequirement("resolution", (1920, 1080)),),
        command=("manim",), runner=run, read_artifact=lambda k: out.read_bytes(),
    )
    assert result.verdict is QualificationVerdict.REJECTED
    assert result.artifact_state is ArtifactState.METADATA_MISMATCH
    assert result.source is not None, "the bytes were still acquired and evidenced"


# ══════════════════════════════════════════════════════════════════════════
# QUALIFIED_REQUIRES_EVIDENCE
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg unavailable")
def test_no_reader_means_no_qualification(tmp_path):
    """A locator is not proof: without bytes there is nothing to validate."""
    run, _ = _render_to(tmp_path)
    result = run_local_process_qualification(
        MANIM, requirements=REQUIREMENTS, command=("manim",), runner=run,
        read_artifact=None,
    )
    assert result.verdict is QualificationVerdict.REJECTED
    assert "locator is not proof" in result.reason
    assert result.receipt is None


def test_blocked_run_carries_no_downstream_evidence():
    result = run_local_process_qualification(
        MANIM, command=("manim-render-does-not-exist",), read_artifact=lambda k: b"x"
    )
    assert result.verdict is QualificationVerdict.BLOCKED_BY_RUNTIME
    assert result.source is None and result.evidence is None
    assert result.receipt is None and result.validation is None


# ══════════════════════════════════════════════════════════════════════════
# BLOCKED_BY_RUNTIME is not NOT_RUN
# ══════════════════════════════════════════════════════════════════════════


def test_blocked_by_runtime_is_a_distinct_verdict():
    assert QualificationVerdict.BLOCKED_BY_RUNTIME is not QualificationVerdict.NOT_RUN
    assert QualificationVerdict.BLOCKED_BY_RUNTIME.value == "blocked_by_runtime"


def test_no_command_configured_is_not_run_not_blocked():
    """No command at all is "we did not try"; a missing binary is "it is not there"."""
    registry = DriverRegistry(
        drivers={
            HealthCheckKind.LOCAL_PROCESS: LocalLiveDriver(
                credentials=StaticCredentialProvider({})
            )
        }
    )
    result = run_local_process_qualification(MANIM, registry=registry)
    assert result.verdict is QualificationVerdict.NOT_RUN


def test_runtime_unavailable_is_its_own_live_outcome():
    assert LiveOutcome.RUNTIME_UNAVAILABLE is not LiveOutcome.NOT_ATTEMPTED
    status = LiveRuntimeStatus(
        "manim", LiveOutcome.RUNTIME_UNAVAILABLE, reason="not installed"
    )
    assert status.was_attempted is False
    assert status.is_live_usable is False


# ══════════════════════════════════════════════════════════════════════════
# layering: renderer -> bytes -> validator
# ══════════════════════════════════════════════════════════════════════════


def test_renderer_never_returns_a_validation_result():
    """Otherwise the provider would own artifact truth."""
    tree = ast.parse(LOCAL.read_text())
    source = LOCAL.read_text()
    assert "ValidationResult(" not in source, "do not construct validation here"
    # the only construction is via qualify(), which belongs to P8.4
    assert "qualify(" in source and "issue_receipt(" in source
    assert not any(
        isinstance(node, ast.ClassDef) and node.name.endswith("Provider")
        for node in ast.walk(tree)
    ), "no provider object that could own artifact truth"


def test_local_process_module_does_not_invoke_a_renderer_or_prober():
    """Capability check, not a token ban.

    ``validator_name="ffprobe"`` only *labels* the validation step; a text ban would
    flag that while missing a real invocation. This is the sixth instance of the
    wrong-test pattern, so it checks imports and calls instead of strings.
    """
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(ast.parse(LOCAL.read_text())):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            called.add(getattr(node.func, "id", getattr(node.func, "attr", "")))
    for banned in ("subprocess", "manim", "ffprobe", "tempfile", "shutil"):
        assert banned not in imported, f"local_process imports {banned}"
    for banned in ("run", "Popen", "check_output"):
        assert banned not in called, f"local_process calls {banned}()"
    # the probe lives in P8.4, not here
    assert "probe_containerised" not in imported


def test_local_process_does_not_touch_the_catalogue():
    before = PROVIDER_CATALOGUE.to_dict()
    run_local_process_qualification(
        MANIM, command=("manim-render-does-not-exist",), read_artifact=None
    )
    assert PROVIDER_CATALOGUE.to_dict() == before


def test_serialised_result_carries_no_credential():
    result = run_local_process_qualification(
        MANIM, command=("manim-render-does-not-exist",), read_artifact=None
    )
    assert "sk-" not in json.dumps(result.to_dict())


# ══════════════════════════════════════════════════════════════════════════
# honest reporting: manim is not qualified here
# ══════════════════════════════════════════════════════════════════════════


def test_manim_is_not_qualified_in_this_environment():
    """The harness works; the runtime is absent. Those are different statements."""
    if shutil.which("manim"):
        pytest.skip("manim is installed; this assertion is about the absent case")
    result = run_local_process_qualification(
        MANIM, command=("manim",), read_artifact=lambda k: b""
    )
    assert result.verdict is QualificationVerdict.BLOCKED_BY_RUNTIME
    assert result.qualified is False
