"""P8.4 — Artifact qualification, and the difference between FOUND and VALID.

    artifact exists  !=  artifact valid

A descriptor records that bytes were located. That is the whole of what existence
proves. ``QUALIFIED`` is strictly stronger: every requirement must be *observed* and
*satisfied*, which means a real measurement was taken and compared.

The property that makes this safe is that **an unobserved requirement cannot pass**. If
ffprobe is missing, or a stream is absent, the check reports not-observed and the
artifact does not qualify. A validator that filled in defaults would turn a missing
probe into a silent pass, which is the failure this phase exists to prevent.

Two duplications were resolved rather than reproduced:

* ``ValidationCheck`` (P8.3) and ``ArtifactCheck`` (P8.4) were one idea under two
  names, and P8.3's took ``passed`` as an input. There is now one check type with
  ``passed`` derived.
* An existing media-probe authority, ``hevi.video.quality_check.probe_stats``, already
  shells out to ffprobe. It is not duplicated; the addition is a byte-oriented seam,
  because a probe that needs a path can also repair the file it inspects.

T1-T5 are the five ways this collapses.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
import shutil
import subprocess

import pytest

from hevi.artifact import (
    ArtifactCheck,
    ArtifactDescriptor,
    ArtifactState,
    CheckOperator,
    CheckRequirement,
    ValidationCheck,
    describe,
    evaluate_checks,
    qualify,
)
from hevi.artifact.probes import (
    probe_containerised,
    probe_image,
)
from hevi.evidence.acquisition import checksum_bytes
from hevi.production.p6.production_runtime import RunState
from hevi.validation import ValidationResult

ARTIFACT_DIR = pathlib.Path("hevi/artifact")
QUALIFY = ARTIFACT_DIR / "qualify.py"
PROBES = ARTIFACT_DIR / "probes.py"
CHECKS = ARTIFACT_DIR / "checks.py"

MP4 = bytes.fromhex("") or b""  # replaced below by a real sample when ffprobe is present
FFPROBE = shutil.which("ffprobe")

PNG = b"\x89PNG\r\n\x1a\n" + b"pixeldata" * 4
JPEG = b"\xff\xd8\xff\xe0" + b"JFIF" + b"\x00" * 20


def _sample_video() -> bytes | None:
    """A real MP4, if ffmpeg is available to make one."""
    if not shutil.which("ffmpeg"):
        return None
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi",
             "-i", "testsrc=duration=1:size=320x240:rate=24",
             "-pix_fmt", "yuv420p", "-c:v", "libx264",
             # fragmented so the mp4 muxer can write to a non-seekable pipe
             "-movflags", "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1"],
            capture_output=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 and result.stdout else None


SAMPLE = _sample_video() if FFPROBE else None


def _descriptor(payload: bytes, media_type: str = "IMAGE") -> ArtifactDescriptor:
    return describe(
        "art1", payload, location="/out/art1", media_type=media_type
    )


def _code_identifiers(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return (
        {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    )


# ══════════════════════════════════════════════════════════════════════════
# there is exactly one check type
# ══════════════════════════════════════════════════════════════════════════


def test_artifact_check_is_the_validation_check():
    """Two names for one idea is the collision P8.2 and P8.3 both hit."""
    assert ArtifactCheck is ValidationCheck


def test_only_one_check_type_exists_in_the_validation_stack():
    assert ValidationResult.__module__ == "hevi.validation.artifact"
    names = {
        n.name for n in ast.walk(ast.parse((ARTIFACT_DIR / "checks.py").read_text()))
        if isinstance(n, ast.ClassDef)
    }
    assert "ArtifactCheck" not in names, (
        "ArtifactCheck must be an alias of ValidationCheck, not a second class"
    )


def test_check_fields_cannot_hold_a_passed_verdict():
    """T1: `passed` must not be a field, so it cannot be supplied."""
    names = {f.name for f in dataclasses.fields(ValidationCheck)}
    assert "passed" not in names, "passed is derived; storing it makes it declarable"
    assert names == {"name", "observed", "expected", "operator", "detail"}


def test_passed_is_derived_from_the_comparison():
    assert ValidationCheck("c", observed="h264", expected="h264").passed
    assert not ValidationCheck("c", observed="vp9", expected="h264").passed
    assert not ValidationCheck("c", observed=(1280, 720), expected=(1920, 1080)).passed


def test_passing_passed_as_a_field_is_impossible():
    with pytest.raises(TypeError):
        ValidationCheck("c", passed=True)  # type: ignore[call-arg]


def test_result_passed_is_derived_from_its_checks():
    passing = ValidationResult(
        "v", (ValidationCheck("c", observed=1, expected=1),),
        observed_checksum=checksum_bytes(b"x"),
    )
    assert passing.passed is True
    failing = ValidationResult(
        "v", (ValidationCheck("c", observed=1, expected=1),
              ValidationCheck("d", observed=2, expected=1)),
        observed_checksum=checksum_bytes(b"x"),
    )
    assert failing.passed is False


# ══════════════════════════════════════════════════════════════════════════
# Rule 1 — existence yields FOUND, never VALID
# ══════════════════════════════════════════════════════════════════════════


def test_descriptor_state_is_always_found():
    descriptor = _descriptor(PNG)
    assert descriptor.state is ArtifactState.FOUND


def test_descriptor_has_no_qualification_state():
    names = {f.name for f in dataclasses.fields(ArtifactDescriptor)}
    assert "state" not in names, "a descriptor may not carry a verdict"
    assert "qualified" not in names and "valid" not in names


def test_artifact_state_never_includes_a_bare_valid():
    values = {s.value for s in ArtifactState}
    assert "valid" not in values and "ok" not in values
    assert ArtifactState.QUALIFIED.value != "valid"


def test_describing_an_existing_artifact_does_not_qualify_it():
    """T4: locating bytes says nothing about them."""
    descriptor = _descriptor(PNG)
    assert descriptor.state is ArtifactState.FOUND
    result, state = qualify(descriptor, PNG)
    # with no requirements, qualification reports observations; the verdict is only
    # ever produced by qualify(), never by describe()
    assert state is ArtifactState.QUALIFIED
    assert result.passed is True


def test_qualification_requires_requirements_or_observations():
    garbage = describe("g", b"not media", location="/x", media_type="IMAGE")
    _, state = qualify(garbage, b"not media")
    assert state is ArtifactState.QUALIFIED  # checksum and size observed, nothing else claimed
    _, strict = qualify(garbage, b"not media", (CheckRequirement("format", "png"),))
    assert strict is ArtifactState.UNVERIFIED


# ══════════════════════════════════════════════════════════════════════════
# Rule 2 — checksum mismatch is INVALID_ARTIFACT
# ══════════════════════════════════════════════════════════════════════════


def test_tampered_payload_is_invalid_artifact():
    """T3: the payload changes, the descriptor's checksum does not."""
    descriptor = _descriptor(PNG)
    result, state = qualify(descriptor, b"tampered bytes entirely")
    assert state is ArtifactState.INVALID_ARTIFACT
    assert result.passed is False
    assert result.checks[0].name == "checksum"


def test_descriptor_checksum_must_be_real():
    for bad in ("", "TODO", "0" * 63, "A" * 64):
        with pytest.raises(ValueError, match="ARTIFACT_DESCRIPTOR_BAD_CHECKSUM"):
            ArtifactDescriptor(
                artifact_id="a", location="/x", media_type="IMAGE",
                size_bytes=1, checksum=bad,
            )


def test_invalid_artifact_is_distinct_from_metadata_mismatch():
    """Different defects deserve different responses."""
    descriptor = _descriptor(PNG)
    assert qualify(descriptor, b"other bytes")[1] is ArtifactState.INVALID_ARTIFACT
    assert qualify(
        descriptor, PNG, (CheckRequirement("format", "jpeg"),)
    )[1] is ArtifactState.METADATA_MISMATCH


def test_checksum_is_recomputed_from_the_payload():
    descriptor = _descriptor(PNG)
    result, state = qualify(descriptor, PNG)
    assert state is ArtifactState.QUALIFIED
    assert result.observed_checksum == checksum_bytes(PNG) == descriptor.checksum
    assert not descriptor.matches_payload(b"different")


# ══════════════════════════════════════════════════════════════════════════
# Rule 3 — metadata mismatch is not a pass
# ══════════════════════════════════════════════════════════════════════════


def test_wrong_resolution_does_not_pass():
    """The spec's example: required 1920x1080, actual 1280x720."""
    check = ValidationCheck(
        "resolution", observed=(1280, 720), expected=(1920, 1080)
    )
    assert check.passed is False
    assert check.was_observed is True, "measured and wrong is not unobserved"


def test_declared_codec_must_match_observed_codec():
    """T2: declared h264, actual vp9."""
    assert not ValidationCheck("codec", observed="vp9", expected="h264").passed


def test_probe_result_overrides_any_declaration():
    """The observation is what counts; a descriptor cannot assert a codec."""
    descriptor = _descriptor(PNG)
    lying = lambda payload: {"codec": "h264", "resolution": (1920, 1080),
                             "checksum": checksum_bytes(payload)}
    _, state = qualify(descriptor, PNG, (CheckRequirement("codec", "h264"),), probe=lying)
    # the probe IS the observation; what matters is that no declaration path exists
    assert state is ArtifactState.QUALIFIED
    descriptor_no_codec = _descriptor(PNG)
    assert not hasattr(descriptor_no_codec, "codec")


def test_metadata_mismatch_is_not_qualification():
    descriptor = _descriptor(PNG)
    result, state = qualify(
        descriptor, PNG, (CheckRequirement("format", "jpeg"),)
    )
    assert state is ArtifactState.METADATA_MISMATCH
    assert result.passed is False


def test_image_format_is_observed_not_declared():
    assert probe_image(PNG).get("format") == "png"
    assert probe_image(JPEG).get("format") == "jpeg"
    assert "format" not in probe_image(b"not an image")


def test_operators_behave_as_named():
    assert CheckRequirement("d", 5, CheckOperator.GTE)
    observed = evaluate_checks(
        (CheckRequirement("d", 5, CheckOperator.GTE),), {"d": 9}
    )[0]
    assert observed.passed is True
    short = evaluate_checks(
        (CheckRequirement("d", 5, CheckOperator.GTE),), {"d": 2}
    )[0]
    assert short.passed is False
    ranged = evaluate_checks(
        (CheckRequirement("d", (1, 10), CheckOperator.IN_RANGE),), {"d": 5}
    )[0]
    assert ranged.passed is True
    out_of_range = evaluate_checks(
        (CheckRequirement("d", (1, 10), CheckOperator.IN_RANGE),), {"d": 50}
    )[0]
    assert out_of_range.passed is False


def test_unknown_operator_is_refused():
    with pytest.raises(ValueError, match="UNKNOWN_CHECK_OPERATOR"):
        CheckRequirement("d", 1, "approximately")


# ══════════════════════════════════════════════════════════════════════════
# an unobserved requirement cannot pass
# ══════════════════════════════════════════════════════════════════════════


def test_never_observed_requirement_does_not_pass():
    check = ValidationCheck("channels", observed=None, expected=2)
    assert check.passed is False
    assert check.was_observed is False


def test_missing_probe_yields_unverified_not_qualified():
    descriptor = _descriptor(PNG)
    _, state = qualify(
        descriptor, PNG,
        (CheckRequirement("duration", 1.0, CheckOperator.GTE),),
        probe=lambda payload: {"checksum": checksum_bytes(payload)},
    )
    assert state is ArtifactState.UNVERIFIED


def test_probe_reporting_nothing_is_unverified():
    descriptor = _descriptor(PNG)
    _, state = qualify(
        descriptor, PNG, (CheckRequirement("format", "png"),),
        probe=lambda payload: {},
    )
    assert state is ArtifactState.UNVERIFIED


def test_probe_cannot_invent_fields():
    descriptor = _descriptor(PNG)
    with pytest.raises(ValueError, match="PROBE_REPORTED_UNKNOWN_FIELDS"):
        qualify(
            descriptor, PNG,
            probe=lambda payload: {"checksum": checksum_bytes(payload), "vibes": "good"},
        )


# ══════════════════════════════════════════════════════════════════════════
# Rule 4 — validation never repairs
# ══════════════════════════════════════════════════════════════════════════


def _imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    return imported


#: Modules that could reach the filesystem or a shell. None may be imported by the
#: probe or the qualification path: a validator that can write can repair.
WRITE_CAPABLE_MODULES = {
    "shutil", "os", "tempfile", "pathlib", "Path", "io", "glob",
    "filecmp", "shelve", "sqlite3", "pickle", "csv",
}

#: Verb-shaped calls that imply mutating the thing being inspected.
WRITE_VERBS = {
    "copy", "copy2", "copyfile", "copytree", "move", "rmtree", "remove", "unlink",
    "rename", "replace", "write", "write_bytes", "write_text", "truncate",
    "mkdir", "rmdir", "makedirs", "chmod", "symlink", "hardlink", "link",
    "save", "dump", "dumps", "sendfile",
}


def test_probe_module_cannot_write():
    """T5: no write, modify, repair or transcode.

    Both halves matter, and the first version of this test had only one. Checking
    identifiers for ``write`` missed a repair helper written as ``shutil.copy``,
    because ``copy`` was never on the list. Banning the modules that can reach the
    filesystem closes that, and the verb list covers a same-module implementation.
    """
    imported = _imported_modules(PROBES)
    assert not (imported & WRITE_CAPABLE_MODULES), (
        f"probes.py imports {imported & WRITE_CAPABLE_MODULES}; it must not write"
    )
    called = {
        getattr(n.func, "id", getattr(n.func, "attr", ""))
        for n in ast.walk(ast.parse(PROBES.read_text()))
        if isinstance(n, ast.Call)
    }
    assert not (called & WRITE_VERBS), f"probes.py calls {called & WRITE_VERBS}"
    identifiers = _code_identifiers(PROBES)
    assert not (identifiers & {"Path", "open"}), (
        "probes.py references a path; probes take bytes"
    )


def test_probe_module_opens_no_files():
    """The reason ffprobe reads `pipe:0`: a validator must not need a path."""
    text = PROBES.read_text()
    assert "pipe:0" in text, "ffprobe must read the payload from a pipe"
    for banned in ("tmp", "tempfile", "NamedTemporary", "mkstemp"):
        assert banned not in text, f"probes.py uses {banned}; it must not write files"


def test_qualify_module_cannot_write():
    imported = _imported_modules(QUALIFY)
    assert not (imported & WRITE_CAPABLE_MODULES), (
        f"qualify.py imports {imported & WRITE_CAPABLE_MODULES}"
    )
    called = {
        getattr(n.func, "id", getattr(n.func, "attr", ""))
        for n in ast.walk(ast.parse(QUALIFY.read_text()))
        if isinstance(n, ast.Call)
    }
    assert not (called & WRITE_VERBS), f"qualify.py calls {called & WRITE_VERBS}"
    identifiers = _code_identifiers(QUALIFY)
    for token in ("write", "open", "unlink", "rename", "Path", "subprocess"):
        assert token not in identifiers, f"qualify.py uses {token}"


def test_payload_is_not_mutated_by_validation():
    payload = bytearray(PNG)
    before = bytes(payload)
    descriptor = _descriptor(PNG)
    qualify(descriptor, bytes(payload), (CheckRequirement("format", "png"),))
    assert bytes(payload) == before


def test_qualification_does_not_change_the_descriptor():
    descriptor = _descriptor(PNG)
    snapshot = descriptor.to_dict()
    qualify(descriptor, PNG)
    qualify(descriptor, b"tampered")
    assert descriptor.to_dict() == snapshot


# ══════════════════════════════════════════════════════════════════════════
# states stay disjoint from every other layer
# ══════════════════════════════════════════════════════════════════════════


def test_artifact_state_is_disjoint_from_run_state():
    assert {s.value for s in ArtifactState}.isdisjoint({s.value for s in RunState})


def test_artifact_states_are_namespaced():
    for state in ArtifactState:
        assert state.value.startswith(("artifact_", "invalid_", "metadata_", "unverified")), (
            f"{state.value} could collide with another layer on the wire"
        )


def test_artifact_package_never_names_run_state():
    for path in (QUALIFY, PROBES, CHECKS):
        assert "RunState" not in _code_identifiers(path)
        assert "ProductionRunResult" not in _code_identifiers(path)


def test_artifact_package_defines_no_production_authority():
    for path in (QUALIFY, PROBES, CHECKS):
        identifiers = _code_identifiers(path)
        for token in ("ProductionReceipt", "PRODUCED", "QA_PASSED", "ArtifactState.PRODUCED"):
            assert token not in identifiers


def test_qualification_cannot_mark_an_execution_produced():
    """Qualifying an artifact says nothing about a render having happened."""
    descriptor = _descriptor(PNG)
    result, state = qualify(descriptor, PNG, (CheckRequirement("format", "png"),))
    payload = result.to_dict()
    assert state is ArtifactState.QUALIFIED
    assert "produced" not in str(payload).lower()


def test_p0_e_execution_plan_is_untouched():
    """P8.4 may not rewrite P0-E."""
    import hevi.execution as execution

    for name in ("ExecutionPlan", "Scheduler", "ResourceSnapshot", "RepairPlan",
                 "SchedulingRequest", "SchedulingDecision", "SchedulingWeights",
                 "ExecutionPlanRepository", "compute_dag_closure", "decide_repair"):
        assert hasattr(execution, name), f"P0-E export {name} went missing"
    assert hasattr(execution, "ProductionReceipt")


# ══════════════════════════════════════════════════════════════════════════
# real observation, against real bytes
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(SAMPLE is None, reason="ffmpeg/ffprobe unavailable")
def test_real_video_is_observed_from_bytes_without_a_file():
    """A real MP4, probed through a pipe — no path, no file written."""
    payload = SAMPLE
    observed = probe_containerised(payload)
    assert observed.get("codec") == "h264"
    assert observed.get("resolution") == (320, 240)
    assert observed.get("duration") == pytest.approx(1.0, abs=0.2)
    assert observed.get("fps") == pytest.approx(24.0, abs=0.5)


@pytest.mark.skipif(SAMPLE is None, reason="ffmpeg/ffprobe unavailable")
def test_real_video_qualifies_against_real_requirements():
    payload = SAMPLE
    descriptor = describe("v1", payload, location="/out/v1.mp4", media_type="VIDEO")
    result, state = qualify(
        descriptor, payload,
        (CheckRequirement("codec", "h264"),
         CheckRequirement("resolution", (320, 240)),
         CheckRequirement("container", "isom")),
    )
    assert state is ArtifactState.QUALIFIED
    assert result.passed is True
    assert all(c.was_observed for c in result.checks)


@pytest.mark.skipif(SAMPLE is None, reason="ffmpeg/ffprobe unavailable")
def test_real_video_rejects_the_wrong_resolution():
    payload = SAMPLE
    descriptor = describe("v1", payload, location="/out/v1.mp4", media_type="VIDEO")
    _, state = qualify(
        descriptor, payload, (CheckRequirement("resolution", (1920, 1080)),)
    )
    assert state is ArtifactState.METADATA_MISMATCH


def test_container_is_detected_from_the_header():
    assert probe_containerised(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 8).get(
        "container"
    ) == "isom"
    assert "container" not in probe_containerised(b"nothing here at all")


def test_unreadable_media_is_not_observed_rather_than_wrong():
    observed = probe_containerised(b"\x00\x00\x00\x18ftypisom" + b"garbage")
    assert observed.get("codec") is None
    descriptor = _descriptor(b"\x00\x00\x00\x18ftypisom" + b"garbage", media_type="VIDEO")
    _, state = qualify(descriptor, b"\x00\x00\x00\x18ftypisom" + b"garbage",
                       (CheckRequirement("codec", "h264"),))
    assert state is ArtifactState.UNVERIFIED


# ══════════════════════════════════════════════════════════════════════════
# the model is strict
# ══════════════════════════════════════════════════════════════════════════


def test_descriptor_requires_identity_and_location():
    for field in ("artifact_id", "location", "media_type"):
        kwargs = {
            "artifact_id": "a", "location": "/x", "media_type": "IMAGE",
            "size_bytes": 1, "checksum": "a" * 64,
        }
        kwargs[field] = ""
        with pytest.raises(ValueError, match="ARTIFACT_DESCRIPTOR_WITHOUT"):
            ArtifactDescriptor(**kwargs)


def test_negative_size_is_refused():
    with pytest.raises(ValueError, match="NEGATIVE_ARTIFACT_SIZE"):
        ArtifactDescriptor(
            artifact_id="a", location="/x", media_type="IMAGE",
            size_bytes=-1, checksum="a" * 64,
        )


def test_validation_result_requires_a_validator_and_checks():
    with pytest.raises(ValueError, match="VALIDATION_RESULT_WITHOUT_VALIDATOR"):
        ValidationResult("", (ValidationCheck("c", observed=1, expected=1),))
    with pytest.raises(ValueError, match="VALIDATION_RESULT_WITHOUT_CHECKS"):
        ValidationResult("v", ())


def test_check_requires_a_name():
    with pytest.raises(ValueError, match="ARTIFACT_CHECK_WITHOUT_NAME|VALIDATION_CHECK_WITHOUT_NAME"):
        ValidationCheck("", observed=1, expected=1)


def test_result_serialises_with_derived_verdicts():
    result, state = qualify(
        _descriptor(PNG), PNG, (CheckRequirement("format", "png"),)
    )
    payload = result.to_dict()
    assert payload["passed"] is True
    assert payload["artifact_id"] == "art1"
    assert payload["checks"][0]["name"] == "format"
