"""P9.1.d — every local renderer has an identity, and none of them proves its own output.

Two invariants, both from the P9 audit:

* **No anonymous renderer.** A renderer that exists but has no ``ProviderProfile`` can be
  invoked without appearing in a decision record — the P6.5 condition. ``T1`` makes that
  structurally impossible: the test walks ``hevi/renderers/``, collects every declared
  ``renderer_id``, and requires a catalogue entry for each.

* **No second artifact authority.** A renderer that hashes its output or probes its
  duration is a validator touching the bytes it judges. ``T2``/``T3`` assert no module
  under ``hevi/renderers/`` or ``hevi/providers/`` imports ``hashlib`` or calls ffprobe.

These are capability checks — imports and calls — not token bans. A docstring that
*names* ffprobe while explaining that the module does not call it must pass; that
distinction is Architecture Testing Rule #1, and a text scan would get it backwards.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from hevi.providers.facts import (
    PROVIDER_CATALOGUE,
    ArtifactContract,
    ProviderKind,
    RuntimeClass,
)
from hevi.renderers.base import RendererId

RENDERERS = pathlib.Path("hevi/renderers")
PROVIDERS = pathlib.Path("hevi/providers")

#: renderer_id -> provider_id. Required to be identical: a renderer whose identity
#: differs from its provider id is two names for one thing, which is how the
#: AcquisitionState / RunState collision happened.
RENDERER_PROVIDER_IDENTITY = {
    RendererId.REMOTION.value: "remotion",
    RendererId.MANIM.value: "manim",
    RendererId.HTML_GSAP.value: "html_gsap",
    RendererId.FFMPEG.value: "ffmpeg",
}


def _modules(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in root.rglob("*.py"))


def _spawns_ffprobe(path: pathlib.Path) -> list[int]:
    """Lines where ffprobe is actually *invoked*.

    An earlier version of this check asserted ``"ffprobe" not in called`` and was
    decorative: ffprobe is never a called name, it is a string argument to
    ``subprocess.run``. The mutation ``subprocess.run(["ffprobe", ...])`` sailed
    through. So this looks for a call whose argv contains the literal — the capability,
    not the token. (Architecture Testing Rule #1, learned twice.)
    """
    tree = ast.parse(path.read_text())
    spawners = {"run", "Popen", "check_output", "check_call", "call", "system"}
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", getattr(node.func, "attr", "")) not in spawners:
            continue
        for arg in node.args:
            elements = (
                arg.elts if isinstance(arg, (ast.List, ast.Tuple)) else [arg]
            )
            if any(
                isinstance(e, ast.Constant) and e.value == "ffprobe" for e in elements
            ):
                hits.append(node.lineno)
    return hits


def _capabilities(path: pathlib.Path) -> tuple[set[str], set[str]]:
    """(imported module roots, called function names)."""
    tree = ast.parse(path.read_text())
    imports: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            calls.add(getattr(node.func, "id", getattr(node.func, "attr", "")))
    return imports, calls


# ══════════════════════════════════════════════════════════════════════════
# T1 — provider completeness
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("renderer_id,provider_id", sorted(RENDERER_PROVIDER_IDENTITY.items()))
def test_t1_every_renderer_has_a_catalogue_entry(renderer_id, provider_id):
    assert PROVIDER_CATALOGUE.get(provider_id) is not None, (
        f"{renderer_id} exists as a renderer but {provider_id} has no ProviderProfile; "
        "a renderer without identity is invisible to policy"
    )


def test_t1_renderer_id_equals_provider_id():
    """One thing, one name. Divergence is how two vocabularies form."""
    for renderer_id, provider_id in RENDERER_PROVIDER_IDENTITY.items():
        assert renderer_id.lower() == provider_id.lower(), (
            f"{renderer_id} and {provider_id} are the same provider under two names"
        )


def test_t1_a_new_renderer_module_cannot_escape_registration():
    """The structural form of T1: scan, don't enumerate.

    Every module under hevi/renderers/ that declares a `renderer_id = RendererId.X`
    must have a corresponding catalogue entry. Adding a renderer therefore fails until
    it is registered — the mutation the spec asks for.
    """
    declared: set[str] = set()
    for path in _modules(RENDERERS):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "renderer_id" for t in node.targets)
                and isinstance(node.value, ast.Attribute)
                and getattr(node.value.value, "id", "") == "RendererId"
            ):
                declared.add(node.value.attr.lower())
    assert declared, "no renderer_id assignments found; the scan is broken"
    for name in sorted(declared):
        assert PROVIDER_CATALOGUE.get(name) is not None, (
            f"RendererId.{name.upper()} is implemented but {name} is not in the "
            "ProviderCatalogue — NO_ANONYMOUS_RENDERER would be violated"
        )


# ══════════════════════════════════════════════════════════════════════════
# T2 / T3 — artifact authority
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("path", _modules(RENDERERS), ids=lambda p: p.name)
def test_t2_no_renderer_owns_artifact_proof(path):
    imports, calls = _capabilities(path)
    assert "hashlib" not in imports, f"{path.name} imports hashlib"
    assert not (calls & {"_hash_file", "_probe_duration"}), (
        f"{path.name} calls an artifact-proof helper"
    )
    spawned = _spawns_ffprobe(path)
    assert not spawned, (
        f"{path.name} invokes ffprobe at line(s) {spawned}; a renderer must return a "
        "locator, not prove its own artifact"
    )


@pytest.mark.parametrize("path", _modules(PROVIDERS), ids=lambda p: p.as_posix())
def test_t3_no_provider_module_owns_artifact_proof(path):
    """T3: the ffmpeg provider must not probe or hash.

    Enforced across the whole provider package rather than naming one file, so the
    boundary holds for providers added later too.
    """
    imports, calls = _capabilities(path)
    assert "hashlib" not in imports, f"{path.as_posix()} imports hashlib"
    spawned = _spawns_ffprobe(path)
    assert not spawned, f"{path.as_posix()} invokes ffprobe at {spawned}"
    for banned in ("qualify", "validate_media"):
        assert banned not in calls, f"{path.as_posix()} performs validation ({banned})"


def test_t3_ffmpeg_profile_is_an_encoder_not_a_generator():
    """ffmpeg transforms media; it does not synthesise it."""
    profile = PROVIDER_CATALOGUE.resolve("ffmpeg")
    assert profile.kind is ProviderKind.ENCODER
    assert profile.runtime_class is RuntimeClass.CLI
    assert "text_to_video" in profile.artifact_contract.excluded_capabilities
    assert "image_generation" in profile.artifact_contract.excluded_capabilities
    for forbidden in ("text_to_video", "image_generation", "t2v"):
        assert forbidden not in profile.capabilities


# ══════════════════════════════════════════════════════════════════════════
# T4 / T5 — identity of the newly registered providers
# ══════════════════════════════════════════════════════════════════════════


def test_t4_hyperframes_identity():
    profile = PROVIDER_CATALOGUE.get("hyperframes")
    assert profile is not None
    assert profile.locality.value == "LOCAL"
    assert profile.runtime_class is RuntimeClass.LOCAL_PROCESS
    assert isinstance(profile.artifact_contract, ArtifactContract)


def test_t5_html_gsap_identity():
    profile = PROVIDER_CATALOGUE.get("html_gsap")
    assert profile is not None
    assert profile.kind is ProviderKind.RENDERER
    assert profile.runtime_class is RuntimeClass.LOCAL_PROCESS


def test_hypermotion_is_not_registered():
    """NOT_FOUND means not registered. A placeholder would be a capability nothing
    can ever verify, which is the declared-vs-verified gap P8 closed."""
    assert PROVIDER_CATALOGUE.get("hypermotion") is None


def test_every_profile_declares_a_runtime_class_and_artifact_contract():
    for provider_id in PROVIDER_CATALOGUE.list_ids():
        profile = PROVIDER_CATALOGUE.resolve(provider_id)
        assert isinstance(profile.runtime_class, RuntimeClass), provider_id
        assert profile.artifact_contract.media_types, provider_id


def test_artifact_contract_requires_a_media_type():
    with pytest.raises(ValueError, match="ARTIFACT_CONTRACT_WITHOUT_MEDIA_TYPE"):
        ArtifactContract(media_types=())


# ══════════════════════════════════════════════════════════════════════════
# regressions: the qualified providers stay qualified
# ══════════════════════════════════════════════════════════════════════════


def test_manim_and_remotion_stay_registered_and_local():
    for provider_id in ("manim", "remotion"):
        profile = PROVIDER_CATALOGUE.get(provider_id)
        assert profile is not None, f"{provider_id} lost its identity"
        assert profile.locality.value == "LOCAL"
        assert profile.runtime_class is RuntimeClass.LOCAL_PROCESS


def test_policy_carries_the_new_providers_without_code_changes():
    import asyncio

    from hevi.provider_policy.policy import ProviderPolicy, evaluate_provider_policy

    decision = asyncio.run(
        evaluate_provider_policy(
            ProviderPolicy(candidates=["manim", "remotion", "ffmpeg", "html_gsap",
                                       "hyperframes"], quality_floor=1)
        )
    )
    for provider_id in ("manim", "remotion", "ffmpeg", "html_gsap", "hyperframes"):
        assert provider_id in decision.considered
        assert provider_id in decision.locality, (
            f"{provider_id} has no declared locality carried into the decision"
        )
