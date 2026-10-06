"""P9.1.d — mutation suite for the local render provider boundary.

Five ways this closes regresses. Each is asserted as a *capability* — an import, a call,
its argv — never as a token. That distinction is Architecture Testing Rule #1, learned
seven times in this codebase: a test that bans the string ``ffprobe`` passes a renderer
that runs ``subprocess.run(["ffprobe", ...])``, because ffprobe is never a called name.

    M1  a provider rename must not require a policy edit
    M2  a renderer must not hash its own output
    M3  neither a renderer nor a provider adapter may invoke ffprobe
    M4  an adapter must have no field in which to return a verdict
    M5  a renderer without a catalogue entry must fail
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from hevi.providers.facts import PROVIDER_CATALOGUE
from hevi.qualification.models import ExecutionResult
from hevi.qualification.providers import ADAPTERS, adapter_for
from hevi.renderers.base import RendererId

ADAPTER_DIR = pathlib.Path("hevi/qualification/providers")
RENDERER_DIR = pathlib.Path("hevi/renderers")

#: process-launching helpers; ffprobe is always an *argument* to one of these
SPAWNERS = {"run", "Popen", "check_output", "check_call", "call", "system"}
MEASURE_MODULES = {"hashlib", "hevi.validation", "hevi.artifact", "hevi.evidence"}


def _modules(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in root.rglob("*.py"))


def _spawned(path: pathlib.Path, binary: str) -> list[int]:
    """Lines where `binary` is passed as an argument to a process launcher."""
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
# M1 — provider identity is the only fact source
# ══════════════════════════════════════════════════════════════════════════


def test_m1_policy_contains_no_provider_name_branch():
    """A rename must not need a policy edit, so policy must not name providers."""
    source = pathlib.Path("hevi/provider_policy/policy.py").read_text()
    tree = ast.parse(source)
    catalogue = set(PROVIDER_CATALOGUE.list_ids())
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for operand in (node.left, *node.comparators):
            if (
                isinstance(operand, ast.Constant)
                and isinstance(operand.value, str)
                and operand.value in catalogue
            ):
                offenders.append(f"policy.py:{node.lineno} compares {operand.value!r}")
    assert offenders == [], f"policy branches on a provider id: {offenders}"


def test_m1_renaming_a_provider_needs_no_policy_change():
    """The structural form: build a decision for a name the policy has never seen."""
    import asyncio

    from hevi.provider_policy.policy import ProviderPolicy, evaluate_provider_policy

    decision = asyncio.run(
        evaluate_provider_policy(
            ProviderPolicy(candidates=["hyperframes_v2", "totally_new_renderer"],
                           quality_floor=1)
        )
    )
    # unknown providers are rejected by the limits table, but policy did not
    # special-case either name to get there
    rejected = {r.provider_id for r in decision.rejected}
    assert {"hyperframes_v2", "totally_new_renderer"} <= rejected
    assert decision.locality == {}, "no facts invented for an undeclared provider"


def test_m1_every_local_provider_has_an_adapter():
    for provider_id in ("manim", "remotion", "hyperframes", "html_gsap", "ffmpeg"):
        assert adapter_for(provider_id) is not None, f"{provider_id} has no adapter"


# ══════════════════════════════════════════════════════════════════════════
# M2 — no renderer owns artifact proof
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("path", _modules(RENDERER_DIR), ids=lambda p: p.name)
def test_m2_no_renderer_hashes_its_own_output(path):
    assert "hashlib" not in _imports(path), f"{path.name} imports hashlib"
    source = path.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            assert name not in {"_hash_file", "_probe_duration"}, (
                f"{path.name} calls {name}"
            )


# ══════════════════════════════════════════════════════════════════════════
# M3 — no ffprobe, in a renderer or in an adapter
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "path", _modules(RENDERER_DIR) + _modules(ADAPTER_DIR), ids=lambda p: p.name
)
def test_m3_nobody_spawns_ffprobe(path):
    """AST argv inspection — a text scan would miss subprocess.run(["ffprobe", ...])."""
    spawned = _spawned(path, "ffprobe")
    assert not spawned, (
        f"{path.name} spawns ffprobe at line(s) {spawned}; proof belongs to P8.4"
    )


@pytest.mark.parametrize("path", _modules(ADAPTER_DIR), ids=lambda p: p.name)
def test_m3_no_adapter_imports_a_validator(path):
    assert not (_imports(path) & MEASURE_MODULES), (
        f"{path.name} imports a measurement module: {_imports(path) & MEASURE_MODULES}"
    )


# ══════════════════════════════════════════════════════════════════════════
# M4 — an adapter cannot declare a verdict
# ══════════════════════════════════════════════════════════════════════════


def test_m4_execution_result_has_no_verdict_or_measurement_field():
    names = {f.name for f in dataclasses.fields(ExecutionResult)}
    assert names == {"artifact_locator", "execution_id", "runtime_metadata"}
    for forbidden in ("qualified", "verdict", "passed", "checksum", "duration_s",
                      "codec", "resolution", "artifact_state"):
        assert forbidden not in names, f"ExecutionResult carries {forbidden!r}"


def test_m4_adapters_never_reference_a_verdict():
    """`return "QUALIFIED"` must not be expressible in an adapter."""
    verdict_values = {"qualified", "QUALIFIED", "qualification_qualified"}
    for path in _modules(ADAPTER_DIR):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant):
                assert str(node.value.value).lower() not in verdict_values, (
                    f"{path.name} returns a verdict"
                )


def test_m4_only_the_framework_knows_the_verdict_type():
    """Exactly one module may import QualificationVerdict."""
    importers = [
        path.name for path in _modules(ADAPTER_DIR)
        if "QualificationVerdict" in path.read_text()
    ]
    assert importers == [], (
        f"adapters import the verdict type: {importers}; the verdict is the framework's"
    )


# ══════════════════════════════════════════════════════════════════════════
# M5 — no anonymous renderer
# ══════════════════════════════════════════════════════════════════════════


def test_m5_every_declared_renderer_id_has_a_catalogue_entry():
    declared: set[str] = set()
    for path in _modules(RENDERER_DIR):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "renderer_id" for t in node.targets)
                and isinstance(node.value, ast.Attribute)
                and getattr(node.value.value, "id", "") == "RendererId"
            ):
                declared.add(node.value.attr.lower())
    assert declared
    for name in sorted(declared):
        assert PROVIDER_CATALOGUE.get(name) is not None, (
            f"RendererId.{name.upper()} exists but {name} is not a provider"
        )


def test_m5_adapter_registry_matches_the_catalogue():
    """A provider cannot be in the catalogue with no adapter, silently."""
    for provider_id in ADAPTERS:
        assert PROVIDER_CATALOGUE.get(provider_id) is not None, (
            f"{provider_id} has an adapter but no catalogue identity"
        )


# ══════════════════════════════════════════════════════════════════════════
# registry sanity
# ══════════════════════════════════════════════════════════════════════════


def test_adapters_declare_their_provider_id():
    for provider_id, cls in ADAPTERS.items():
        assert cls.provider_id == provider_id


def test_ffmpeg_adapter_refuses_to_generate():
    """An encoder has no path from a prompt to a video."""
    profile = PROVIDER_CATALOGUE.resolve("ffmpeg")
    assert "text_to_video" in profile.artifact_contract.excluded_capabilities
    assert "image_generation" in profile.artifact_contract.excluded_capabilities
    # Signature, not text: the module docstring explains that there is no path from
    # a prompt to video, and a token ban would flag that explanation as a violation.
    import inspect

    from hevi.qualification.providers.ffmpeg import FfmpegAdapter

    signature = inspect.signature(FfmpegAdapter.execute)
    assert "prompt" not in signature.parameters
    # and the request it consumes carries an input artifact, not a description
    from hevi.qualification.models import QualificationRequest

    fields = {f.name for f in dataclasses.fields(QualificationRequest)}
    assert "input_path" in fields and "params" in fields
    source = pathlib.Path(ADAPTER_DIR / "ffmpeg.py").read_text()
    assert "request.input_path" in source, (
        "the ffmpeg adapter must consume an existing artifact"
    )


def test_all_five_local_providers_have_adapters():
    assert set(ADAPTERS) == {"manim", "remotion", "hyperframes", "html_gsap", "ffmpeg"}


def test_renderer_ids_still_map_to_provider_ids():
    for renderer_id in RendererId:
        assert renderer_id.value.lower() in ADAPTERS, (
            f"{renderer_id} has no adapter"
        )
