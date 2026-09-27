"""HEVI P5.2 — architecture audit.

The grammar layer earns the right to add renderers and editable backends only by
*not* becoming a second place where decisions get made. These tests are the
mechanical version of that rule: each one fails if a future change introduces a
competing authority, a bypass of the readiness gate, or a mutation of P5.1.

They are deliberately structural — source and registry inspection rather than
behaviour — because the failure mode being guarded against is exactly the kind
that no functional test would notice.
"""

from __future__ import annotations

import ast
import inspect
import subprocess
from pathlib import Path

import pytest

from hevi import editable, production, providers, renderers
from hevi.production.shot_readiness import ShotReadinessError, ShotState

P52_MODULES = (
    "hevi.production.references",
    "hevi.production.entities",
    "hevi.production.shot_readiness",
    "hevi.production.creative_ledger",
    "hevi.production.presenter",
    "hevi.production.raw_footage",
    "hevi.production.product_video",
    "hevi.renderers.base",
    "hevi.renderers.html_gsap",
    "hevi.renderers.ffmpeg",
    "hevi.renderers.remotion",
    "hevi.editable.base",
    "hevi.editable.jianying",
    "hevi.editable.capcut_cli",
    "hevi.providers.pocket_tts",
)

#: P5.1 owns the review/diagnosis/comparison/revision chain and the promotion
#: decision. P5.2 consumes it. These are the files that must not be edited.
#: The commit P5.2 branched from. Diffing against it is what proves P5.1 is intact.
P52_BASE_SHA = "0048d021991295125bf2d499727b34a4c731a87a"

P51_OWNED = (
    "hevi/ops/p5_1_editable.py",
    "hevi/ops/p5_1_types.py",
)


def _source(module: str) -> str:
    import importlib

    return Path(inspect.getmodule(importlib.import_module(module)).__file__).read_text(
        encoding="utf-8"
    )


def _repo_root() -> Path:
    return Path(subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True, cwd=Path(__file__).parent,
    ).stdout.strip())


# ── No second provider authority ─────────────────────────────────────────


def test_provider_authority_is_the_existing_obase_registry() -> None:
    """Provider selection is obase's. P5.2 must route through it, not around it."""
    from obase.provider_registry import ProviderRegistry

    capabilities = {name for name, _ in inspect.getmembers(
        ProviderRegistry, predicate=inspect.isfunction
    ) if not name.startswith("_")}
    # The categories P5.2 could plausibly have needed a parallel registry for.
    assert {"llm", "vlm", "image_gen", "generic", "capabilities"} <= capabilities


@pytest.mark.parametrize("module", P52_MODULES)
def test_no_module_creates_a_private_provider_registry(module: str) -> None:
    """A second provider *selector* is the failure this layer must not have.

    A class that merely *describes* a provider's capabilities is fine — the
    readiness gate needs to know what a presenter or renderer can do. What is not
    fine is a registry: a module-level collection of providers plus the code that
    picks between them. That is obase's job, and a second copy of it would let
    two different answers to "which backend" reach the same cut.
    """
    tree = ast.parse(_source(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods = {
                child.name for child in node.body if isinstance(child, ast.FunctionDef)
            }
            dispatches = methods & {"select", "resolve", "acquire", "dispatch", "pick"}
            assert not (dispatches and "provider" in node.name.lower()), (
                f"{module}:{node.lineno} {node.name} dispatches between providers"
            )
            assert "ProviderRegistry" not in node.name, (
                f"{module}:{node.lineno} defines {node.name}"
            )
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    assert "POCKET" in target.id or "PROVIDER" not in target.id, (
                        f"{module}:{node.lineno} declares provider state {target.id}"
                    )


def test_pocket_tts_registers_into_the_existing_registry() -> None:
    """Pocket TTS extends the one registry rather than standing up its own."""
    from obase.provider_registry import ProviderRegistry

    source = _source("hevi.providers.pocket_tts")
    tree = ast.parse(source)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert called & {"register_generic", "register_with_capability"}, sorted(called)
    assert "registry" in source
    # It must not instantiate a registry of its own.
    assert "ProviderRegistry(" not in source
    assert ProviderRegistry is not None


def test_pocket_tts_does_not_bypass_the_existing_tts_authority() -> None:
    """Adopting Pocket TTS must not silence the P5 Volcano blocker."""
    from hevi.providers.pocket_tts import probe, tts_gate_report

    report = tts_gate_report(probe())
    assert report["CHINESE_TTS"] == "UNSUPPORTED"
    assert report["SILENT_LANGUAGE_FALLBACK"] == 0
    assert report["LOCAL_CPU_TTS"] == "NOT_ADOPTED"
    assert "zh" not in report["declared_languages"]


# ── Renderer / editable registries are not provider registries ───────────


def test_renderer_registry_is_keyed_by_renderer_not_capability() -> None:
    """Backends are chosen by renderer id, not by capability resolution."""
    renderers.register_all_renderers()
    ids = {backend.renderer_id.value for backend in renderers.list_renderers()}
    assert ids == {"FFMPEG", "HTML_GSAP", "REMOTION"}
    for backend in renderers.list_renderers():
        # A renderer states what it can do so the readiness gate can plan. It must
        # not gain the ability to choose a provider, which is obase's authority.
        assert "provider" not in {n.lower() for n in dir(backend)}, backend.renderer_id
        assert not any(
            name.lower().startswith(("select_provider", "resolve_provider"))
            for name in dir(backend)
        ), backend.renderer_id


def test_editable_registry_is_keyed_by_backend_and_carries_no_promotion() -> None:
    """Editable backends project a manifest. They do not decide what gets shipped."""
    editable.register_all_backends()
    ids = {backend.backend_id.value for backend in editable.list_backends()}
    assert ids == {"INTERNAL_JIANYING", "CAPCUT_CLI"}
    forbidden = ("promote", "approve", "select_candidate", "final", "authority")
    for backend in editable.list_backends():
        for name in dir(backend):
            if name.startswith("_"):
                continue
            assert not any(word in name.lower() for word in forbidden), (
                f"{backend.backend_id} exposes {name}"
            )


def test_renderer_and_editable_registries_live_in_their_own_packages() -> None:
    """Two registries, two packages — and neither is a capability registry."""
    for package in (renderers, editable):
        assert package.__name__ in {"hevi.renderers", "hevi.editable"}
    assert providers.__name__ == "hevi.providers"
    assert production.__name__ == "hevi.production"


# ── Readiness is the only door to generation ─────────────────────────────


def test_readiness_refuses_to_emit_when_the_shot_is_not_ready() -> None:
    """The gate is a hard error, not a warning a caller can ignore."""
    from hevi.production.shot_readiness import (
        GENERATION_ALLOWED_STATES,
        ShotPreparation,
        assert_ready_for_generation,
    )

    assert ShotState.READY in GENERATION_ALLOWED_STATES
    assert ShotState.BLOCKED not in GENERATION_ALLOWED_STATES
    for state in ShotState:
        if state in GENERATION_ALLOWED_STATES:
            continue
        preparation = ShotPreparation(
            shot_id="s1", state=state, blocking_reasons=["no asset"],
        )
        with pytest.raises(ShotReadinessError):
            assert_ready_for_generation(preparation)


@pytest.mark.parametrize(
    "module", ["hevi.renderers.html_gsap", "hevi.renderers.ffmpeg", "hevi.renderers.remotion"]
)
def test_renderers_take_prepared_beats_not_raw_text(module: str) -> None:
    """A renderer is handed structured beats; it does not plan the video itself."""
    tree = ast.parse(_source(module))
    signatures = [
        node.args
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    ]
    assert signatures, module
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in {"render", "__call__"}:
            params = {arg.arg for arg in node.args.args}
            assert not ({"script", "prompt", "brief"} & params), (
                f"{module}:{node.lineno} {node.name} accepts raw creative text {params}"
            )


def test_entity_and_readiness_do_not_emit_media() -> None:
    """Planning modules return data. Only renderer and editable packages write files."""
    for module in ("hevi.production.entities", "hevi.production.shot_readiness",
                   "hevi.production.creative_ledger", "hevi.production.presenter",
                   "hevi.production.product_video"):
        tree = ast.parse(_source(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"mkdir", "write_text", "write_bytes"}, (
                    f"{module}:{node.lineno} writes to disk"
                )


# ── P5.1 is consumed, never rewritten ───────────────────────────────────


@pytest.mark.parametrize("relative", P51_OWNED)
def test_p51_owned_files_are_untouched_by_p52(relative: str) -> None:
    """P5.2 must not edit the files that own review and promotion."""
    result = subprocess.run(
        ["git", "diff", "--name-only", P52_BASE_SHA, "--", *P51_OWNED],
        capture_output=True, text=True, check=True, cwd=_repo_root(),
    )
    assert not result.stdout.strip(), f"P5.2 modified P5.1 files: {result.stdout.strip()}"


@pytest.mark.parametrize("module", P52_MODULES)
def test_p52_does_not_define_a_review_or_promotion_authority(module: str) -> None:
    """No re-implementation of P5.1's decision types."""
    tree = ast.parse(_source(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            assert node.name not in {
                "VideoReview", "EditorialDiagnosis", "PairwiseComparison",
                "RevisionSession", "PromotionDecision", "ReviewOutcome",
            }, f"{module}:{node.lineno} redefines P5.1 authority {node.name}"


@pytest.mark.parametrize(
    "module,names",
    [
        ("hevi.production.product_video", ("EvidenceAsset", "EvidenceSourceType")),
        ("hevi.editable.jianying", ("EditableLayer",)),
    ],
)
def test_p52_reuses_p51_types_by_import_not_copy(module: str, names: tuple[str, ...]) -> None:
    """Sharing the vocabulary is the point; copying it would fork the contract."""
    tree = ast.parse(_source(module))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert set(names) <= imported, f"{module} imports {sorted(imported)}"


# ── Scope discipline ─────────────────────────────────────────────────────


def test_p52_did_not_touch_unrelated_pre_existing_work() -> None:
    """p5_factory / p5_volcano were already dirty before P5.2 started."""
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, check=True, cwd=_repo_root(),
    ).stdout
    for path in ("hevi/ops/p5_factory.py", "hevi/ops/p5_volcano_tts.py"):
        assert path not in dirty, f"unrelated file surfaced: {path}"


def test_no_forbidden_reference_project_code_was_imported() -> None:
    """SeeCut is noncommercial and guizang is AGPL; neither may be imported."""
    for module in P52_MODULES:
        tree = ast.parse(_source(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not any(
                        word in alias.name.lower() for word in ("seecut", "guizang")
                    ), f"{module} imports {alias.name}"
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not any(
                    word in node.module.lower() for word in ("seecut", "guizang")
                ), f"{module} imports from {node.module}"
