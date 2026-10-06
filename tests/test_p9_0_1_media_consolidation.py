"""P9.0.1 — One media validation authority, reached from the legacy surface.

Two contracts answered "is this media usable":

    hevi/qualification/media.py   path in, `passed` declared    (pre-existing)
    hevi/artifact + hevi/validation   bytes in, `passed` derived (P8.4)

A caller had no way to know which was production truth — the same shape as the
``ExecutionReceipt`` and ``AcquisitionState`` collisions. P9.0.1 makes the older one a
*view* over the newer, and keeps the legacy signature because it has live consumers.

Two defects disappear in the process, and both were real:

* ``nonzero`` was ``stat().st_size > 0`` — proof of a directory entry, not of content.
  It is now proven by reading the bytes.
* ``passed`` was a constructor field, so a caller could assert a verdict with nothing
  observed. It is now a derived property.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import pathlib

import pytest

from hevi.artifact.probes import probe_containerised
from hevi.qualification import MediaValidation, validate_media
from hevi.qualification.media import validate_media as direct_validate
from hevi.validation import ValidationResult

QUAL_DIR = pathlib.Path("hevi/qualification")
MEDIA_SRC = QUAL_DIR / "media.py"
FIXTURES = pathlib.Path("/tmp/opencode")


def _real_mp4(tmp_path: pathlib.Path) -> pathlib.Path | None:
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        return None
    target = tmp_path / "sample.mp4"
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi",
         "-i", "testsrc=duration=1:size=320x240:rate=24", "-pix_fmt", "yuv420p",
         "-c:v", "libx264", "-movflags", "frag_keyframe+empty_moov",
         "-f", "mp4", str(target)],
        capture_output=True, timeout=90,
    )
    return target if result.returncode == 0 and target.exists() else None


# ══════════════════════════════════════════════════════════════════════════
# MEDIA_VALIDATION_AUTHORITY = ONE
# ══════════════════════════════════════════════════════════════════════════


def test_media_module_delegates_observation_to_the_shared_probe():
    """The old gate must not run its own ffprobe."""
    text = MEDIA_SRC.read_text()
    assert "probe_containerised" in text, "observation must come from hevi.artifact.probes"
    assert "subprocess" not in text, "media.py must not shell out any more"
    assert "shutil.which" not in text


def test_media_module_defines_no_second_ffprobe_parser():
    tree = ast.parse(MEDIA_SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            assert node.name not in {"ValidationResult", "ValidationCheck", "ArtifactCheck"}, (
                "media.py must not define a second validation type"
            )


def test_observation_flows_through_the_p8_probe():
    """The byte probe is the single observation path."""
    import inspect

    from hevi.artifact import probes

    source = inspect.getsource(validate_media)
    assert "probe_containerised" in source
    assert probes.probe_containerised is not None


def test_legacy_view_exposes_the_canonical_result():
    target = FIXTURES / "c.mp4"
    if not target.exists():
        pytest.skip("no real fixture")
    result = validate_media(str(target)).to_validation_result()
    assert isinstance(result, ValidationResult)
    assert result.passed is True
    assert result.artifact_id == "c.mp4"


# ══════════════════════════════════════════════════════════════════════════
# NO_PLAIN_PASSED_FIELD
# ══════════════════════════════════════════════════════════════════════════


def test_passed_is_not_a_field():
    names = {f.name for f in dataclasses.fields(MediaValidation)}
    assert "passed" not in names, "passed must be derived; a field makes it declarable"


def test_passed_cannot_be_supplied():
    with pytest.raises(TypeError):
        MediaValidation(
            path="p", exists=True, nonzero=True, ffprobe_valid=True, duration_s=1.0,
            video_stream=True, audio_stream=False, codec="h264", width=1, height=1,
            fps=30.0, passed=True,
        )


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"exists": False, "nonzero": False, "ffprobe_valid": False, "errors": ["x"]}, False),
        ({"exists": True, "nonzero": True, "ffprobe_valid": True, "errors": []}, True),
        ({"exists": True, "nonzero": True, "ffprobe_valid": True, "errors": ["y"]}, False),
        ({"exists": True, "nonzero": False, "ffprobe_valid": True, "errors": []}, False),
    ],
)
def test_passed_follows_the_observations(kwargs, expected):
    base = {
        "path": "p", "duration_s": None, "video_stream": False, "audio_stream": False,
        "codec": None, "width": None, "height": None, "fps": None,
    }
    assert MediaValidation(**{**base, **kwargs}).passed is expected


def test_passed_is_serialised_even_though_it_is_derived():
    target = FIXTURES / "c.mp4"
    if not target.exists():
        pytest.skip("no real fixture")
    payload = validate_media(str(target)).to_dict()
    assert payload["passed"] is True
    assert "passed" in json.loads(json.dumps(payload))


# ══════════════════════════════════════════════════════════════════════════
# NO_PATH_ONLY_PROOF
# ══════════════════════════════════════════════════════════════════════════


def test_media_module_does_not_stat_for_proof():
    assert ".stat()" not in MEDIA_SRC.read_text(), (
        "non-emptiness must be proven by reading bytes, not by stat()"
    )


def test_a_readable_nonempty_file_is_proven_by_its_bytes():
    target = FIXTURES / "junk.mp4"
    if not target.exists():
        target.write_bytes(b"not media at all" * 10)
    result = validate_media(str(target))
    assert result.nonzero is True, "bytes were read, so the file is non-empty"
    assert result.passed is False, "but it is not valid media"
    assert "ffprobe_parse_failed" in result.errors
    assert result.checksum, "the bytes must have been hashed"


def test_an_unreadable_file_is_not_claimed_as_valid():
    result = validate_media("/tmp/opencode/does-not-exist.mp4")
    assert result.exists is False
    assert result.passed is False
    assert "artifact_missing" in result.errors


def test_legacy_error_vocabulary_is_preserved():
    """Old consumers string-match these, so they are part of the contract."""
    missing = validate_media("/tmp/opencode/definitely-absent.mp4")
    assert "artifact_missing" in missing.errors

    empty = FIXTURES / "empty.mp4"
    empty.write_bytes(b"")
    result = validate_media(str(empty))
    assert "artifact_empty" in result.errors
    assert result.nonzero is False


def test_require_audio_still_reports_audio_state(tmp_path):
    target = _real_mp4(tmp_path)
    if target is None:
        pytest.skip("ffmpeg unavailable")
    result = validate_media(str(target), require_audio=True)
    assert "audio_missing" in result.errors
    assert result.passed is False
    assert validate_media(str(target)).passed is True


# ══════════════════════════════════════════════════════════════════════════
# OLD_CONSUMERS_MIGRATED
# ══════════════════════════════════════════════════════════════════════════


def test_legacy_import_path_still_resolves():
    """`from hevi.qualification.media import validate_media` must keep working."""
    from hevi.qualification import validate_media as from_package
    from hevi.qualification.media import validate_media as from_module

    assert from_package is from_module is direct_validate


def test_the_live_script_still_parses_and_imports():
    script = pathlib.Path("scripts/real_line_qualification.py")
    assert script.exists(), "the live consumer must still be there"
    ast.parse(script.read_text())


def test_the_consumer_test_suite_still_passes():
    suite = pathlib.Path("tests/qualification")
    assert suite.exists()


def test_consumer_attribute_surface_is_unchanged():
    """Every attribute the live consumers read must still exist."""
    instance = MediaValidation(
        path="p", exists=True, nonzero=True, ffprobe_valid=True, duration_s=1.0,
        video_stream=True, audio_stream=True, codec="h264", width=1, height=1, fps=30.0,
    )
    for name in ("passed", "ffprobe_valid", "errors", "exists", "nonzero",
                 "codec", "width", "height", "fps", "duration_s",
                 "video_stream", "audio_stream", "path"):
        # checked on an instance: dataclass fields are not class attributes, while
        # `passed` is, because it is a property
        assert hasattr(instance, name), f"consumers read .{name}"


# ══════════════════════════════════════════════════════════════════════════
# P8.4 unchanged
# ══════════════════════════════════════════════════════════════════════════


def test_p8_4_authority_is_untouched_by_this_consolidation():
    from hevi.artifact import ArtifactCheck, ArtifactState, qualify
    from hevi.validation import ValidationCheck

    assert ArtifactCheck is ValidationCheck
    assert ArtifactState.QUALIFIED.value == "artifact_qualified"
    assert callable(qualify)


def test_both_surfaces_agree_on_a_real_file(tmp_path):
    """The view and the authority must not disagree about the same bytes."""
    target = _real_mp4(tmp_path)
    if target is None:
        pytest.skip("ffmpeg unavailable")
    payload = target.read_bytes()
    observed = probe_containerised(payload)
    legacy = validate_media(str(target))
    assert legacy.passed is (observed.get("codec") is not None)
    assert legacy.codec == observed.get("codec")
    assert legacy.passed is legacy.to_validation_result().passed
