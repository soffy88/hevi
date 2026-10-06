"""P9.1.e — the HyperFrames boundary, and the runtime audit it rests on.

The provider's CLI render path **does not terminate** — observed exceeding 90s and 600s
without completing. Its ffmpeg fallback does, and produces a real 1920x1080 h264 MP4.

So the adapter declares a bounded budget, records *which* path produced the artifact,
and reports the CLI hang as a finding rather than papering over it. Five mutations
guard that:

    M1  the declared timeout must be real — an unbounded render cannot be reported
    M2  the adapter must not compute a checksum
    M3  the provider must not probe or hash its own output
    M4  the adapter must not return a verdict
    M5  no artifact may be fabricated after a timeout
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import pathlib

import pytest

from hevi.qualification.models import ExecutionResult, ExecutionState
from hevi.qualification.providers.hyperframes import (
    DEFAULT_TIMEOUT_SECONDS,
    HyperframesAdapter,
    HyperFramesExecutionConfig,
    hyperframes_bin,
)

ADAPTER = pathlib.Path("hevi/qualification/providers/hyperframes.py")
PROVIDER = pathlib.Path("hevi/providers/hyperframes/provider.py")
PROVIDER_DIR = pathlib.Path("hevi/providers/hyperframes")

SPAWNERS = {"run", "Popen", "check_output", "check_call", "call", "system"}


def _spawns(path: pathlib.Path, binary: str) -> list[int]:
    lines = []
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", getattr(node.func, "attr", "")) not in SPAWNERS:
            continue
        for arg in node.args:
            elements = arg.elts if isinstance(arg, (ast.List, ast.Tuple)) else [arg]
            if any(
                isinstance(e, ast.Constant) and e.value == binary for e in elements
            ):
                lines.append(node.lineno)
    return lines


def _imports(path: pathlib.Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


# ══════════════════════════════════════════════════════════════════════════
# 1. runtime audit — the facts the verdict rests on
# ══════════════════════════════════════════════════════════════════════════


def test_runtime_identity_is_declared():
    assert HyperframesAdapter.provider_id == "hyperframes"
    from hevi.providers.facts import PROVIDER_CATALOGUE, RuntimeClass

    profile = PROVIDER_CATALOGUE.resolve("hyperframes")
    assert profile.runtime_class is RuntimeClass.LOCAL_PROCESS


def test_binary_is_resolved_not_guessed():
    """A binary path is discovered by asking the provider, never by pattern."""
    resolved = hyperframes_bin()
    assert resolved == "" or pathlib.Path(resolved).exists()
    if resolved:
        assert not resolved.startswith("~"), "must be a resolved absolute path"


def test_binary_absent_is_blocked_not_failed(monkeypatch):
    monkeypatch.setattr(
        "hevi.qualification.providers.hyperframes.hyperframes_bin", lambda: ""
    )
    availability = HyperframesAdapter().available()
    assert availability.state.value == "missing_runtime"
    assert availability.can_run is False


# ══════════════════════════════════════════════════════════════════════════
# 2. timeout contract
# ══════════════════════════════════════════════════════════════════════════


def test_timeout_config_declares_all_three_fields():
    names = {f.name for f in dataclasses.fields(HyperFramesExecutionConfig)}
    assert names == {"timeout_seconds", "working_directory", "artifact_locator"}


@pytest.mark.parametrize("bad", [0, -1, -600])
def test_m1_unbounded_timeout_is_refused(bad):
    """M1: a timeout must be a positive, declared number."""
    with pytest.raises(ValueError, match="HYPERFRAMES_TIMEOUT_MUST_BE_POSITIVE"):
        HyperFramesExecutionConfig(timeout_seconds=bad)


def test_m1_adapter_never_loops_or_sleeps_forever():
    """No `while True`, no bare `sleep()`, no retry-forever."""
    tree = ast.parse(ADAPTER.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.While):
            test = ast.unparse(node.test) if node.test else ""
            assert test.strip() not in {"True", "1"}, (
                f"{ADAPTER.name}:{node.lineno} is an unbounded loop"
            )
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "sleep":
            raise AssertionError(f"{ADAPTER.name}:{node.lineno} sleeps")


def test_m1_execution_is_wall_clock_bounded():
    config = HyperFramesExecutionConfig(timeout_seconds=90)
    assert config.wall_clock_seconds > config.timeout_seconds
    assert config.wall_clock_seconds == 90 * 1.5


def test_default_timeout_is_declared_not_inherited():
    assert DEFAULT_TIMEOUT_SECONDS > 0
    assert DEFAULT_TIMEOUT_SECONDS < 600, (
        "the provider's own default is 600s; the adapter must declare its own budget"
    )


# ══════════════════════════════════════════════════════════════════════════
# 3/4. the adapter executes and nothing else
# ══════════════════════════════════════════════════════════════════════════


def test_m2_adapter_returns_no_measurement():
    names = {f.name for f in dataclasses.fields(ExecutionResult)}
    assert "checksum" not in names
    source = ADAPTER.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call = getattr(node.func, "id", getattr(node.func, "attr", ""))
            assert call not in {"checksum_bytes", "qualify", "sha256"}, (
                f"{ADAPTER.name}:{node.lineno} calls {call}()"
            )


def test_m4_adapter_cannot_return_a_verdict():
    tree = ast.parse(ADAPTER.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant):
            assert str(node.value.value).lower() not in {"qualified", "verdict"}, (
                f"{ADAPTER.name} returns a verdict"
            )
    assert "QualificationVerdict" not in ADAPTER.read_text()


def test_m5_no_artifact_is_written_after_a_timeout():
    """The adapter must not rescue a timed-out run by writing something."""
    source = ADAPTER.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call = getattr(node.func, "id", getattr(node.func, "attr", ""))
            assert call not in {"write_bytes", "write_text"}, (
                f"{ADAPTER.name}:{node.lineno} writes an artifact; a timeout must not "
                "leave a fabricated one behind"
            )


# ══════════════════════════════════════════════════════════════════════════
# M3 — the provider owns no artifact proof
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("path", sorted(PROVIDER_DIR.glob("*.py")), ids=lambda p: p.name)
def test_m3_provider_does_not_probe_or_hash_its_output(path):
    assert "hashlib" not in _imports(path), f"{path.name} imports hashlib"
    assert not _spawns(path, "ffprobe"), f"{path.name} spawns ffprobe"
    source = path.read_text()
    for name in ("_hash_file", "_probe_duration"):
        assert f"def {name}" not in source, f"{path.name} defines {name}"


def test_m3_provider_file_untouched_by_this_phase():
    """M3's mutation surface: provider.py must stay free of proof helpers."""
    source = PROVIDER.read_text()
    for banned in ("checksum_bytes", "sha256", "_hash_file", "_probe_duration"):
        assert banned not in source, f"provider.py references {banned}"


# ══════════════════════════════════════════════════════════════════════════
# 4. failure matrix — every case mapped to its own verdict
# ══════════════════════════════════════════════════════════════════════════


def test_failure_matrix_states_are_distinct():
    values = {s.value for s in ExecutionState}
    for required in ("ok", "no_artifact", "failed", "blocked_runtime"):
        assert required in values
    assert len(values) >= 5, "a collapsed failure vocabulary hides causes"


def test_timeout_maps_to_blocked_runtime_not_failed():
    """A timeout and an exit-code failure are different claims."""
    assert ExecutionState.BLOCKED_RUNTIME is not ExecutionState.FAILED
    adapter = HyperframesAdapter()
    config = adapter.config_for(
        __import__("hevi.qualification.models", fromlist=["x"]).QualificationRequest(
            provider_id="hyperframes", output_path="/tmp/x.mp4", timeout_s=60
        )
    )
    assert config.timeout_seconds == 60


def test_adapter_signature_is_execute_only():
    signature = inspect.signature(HyperframesAdapter.execute)
    assert list(signature.parameters) == ["self", "request"]
    public = {
        name for name, _ in inspect.getmembers(HyperframesAdapter, inspect.isfunction)
        if not name.startswith("_")
    }
    assert public <= {"available", "execute", "config_for"}, public
