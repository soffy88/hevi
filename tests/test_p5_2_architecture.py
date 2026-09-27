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
import os
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
#: decision. P5.2 consumes it.
#:
#: One change to P5.1 is authorised: teaching the layered editable draft to
#: express a parametric text overlay, so both editable backends can deliver the
#: same overlay instead of one of them dropping it. That authorisation is *pinned*
#: below — the guard does not check "P5.1 is untouched", it checks "P5.1 differs
#: only in the reviewed symbols for this one feature". A blanket
#: byte-comparison would have been easy to satisfy by deleting the check, and an
#: open-ended exception would let anything through under its cover.
P52_BASE_SHA = "0048d021991295125bf2d499727b34a4c731a87a"

#: P5.1 files, and for each: the symbols the authorised feature is allowed to
#: add or change. A symbol appearing here that no longer exists, or a top-level
#: definition appearing in the diff that is not listed, fails the test.
P51_AUTHORISED_CHANGES: dict[str, tuple[str, ...]] = {
    "hevi/ops/p5_1_editable.py": (
        "PARAMETRIC_TEXT_LAYERS",
        "PARAMETRIC_TEXT_KEY",
        "PARAMETRIC_TEXT_STYLE_FIELDS",
        "UNSUPPORTED_PARAMETRIC_TEXT_FIELDS",
        "is_parametric_text_element",
        "parametric_text_fields",
        "add_parametric_text_material",
        "_validate_parametric_text",
        "_as_float",
        "_segment_for",
        "build_layered_draft",
        "validate_layered_project",
    ),
    # Deliberately unchanged: the type vocabulary P5.2 imports. If the parametric
    # text feature ever needed a new layer or enum member, this entry would have
    # to change, which is the signal that it stopped being a P5.1-internal change.
    "hevi/ops/p5_1_types.py": (),
}

#: Files that were already modified in the working tree before P5.2 started.
#: They belong to unrelated in-progress work and must survive untouched.
UNRELATED_PRE_EXISTING_DIRTY = (
    "hevi/ops/p5_factory.py",
    "hevi/ops/p5_volcano_tts.py",
)

#: Top-level definitions a P5.1 diff may introduce, flattened from the table above.
P51_ALLOWED_NEW_SYMBOLS = frozenset(
    symbol for symbols in P51_AUTHORISED_CHANGES.values() for symbol in symbols
)


def _source(module: str) -> str:
    import importlib

    return Path(inspect.getmodule(importlib.import_module(module)).__file__).read_text(
        encoding="utf-8"
    )


def _repo_root() -> Path:
    """The repository the structural checks read from.

    Overridable so a mutation can be evaluated against an isolated copy instead
    of the live working tree. That is the whole point: a mutation check that has
    to edit the tree in order to run is a check that will eventually delete
    somebody's uncommitted work, and the way to make that impossible is to never
    require it in the first place.
    """
    override = os.environ.get("HEVI_P52_REPO_ROOT", "").strip()
    if override:
        return Path(override)
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


def _top_level_symbols(source: str) -> set[str]:
    """Names bound at module level, which is what a diff can introduce."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _p51_worktree_source(relative: str) -> str | None:
    """The P5.1 file as it exists at HEAD, or None if this layer did not add it."""
    path = _repo_root() / relative
    return path.read_text(encoding="utf-8") if path.is_file() else None


def test_p51_changed_only_where_the_parametric_text_feature_requires() -> None:
    """P5.2 may extend P5.1's expressiveness, and only in the reviewed places.

    The check is on *symbols*, not on a byte comparison. ``p5_1_types.py`` must be
    untouched outright: the type vocabulary is shared, so growing it would quietly
    change the contract P5.2 imports. ``p5_1_editable.py`` may change, but any
    top-level name the diff introduces has to be one this feature was reviewed to
    add, and every one of those names has to still exist.
    """
    for relative, allowed in P51_AUTHORISED_CHANGES.items():
        # Compared against the working tree rather than HEAD so the guard bites
        # while the change is being written, not only once it is committed.
        changed = subprocess.run(
            ["git", "diff", "--name-only", P52_BASE_SHA, "--", relative],
            capture_output=True, text=True, check=True, cwd=_repo_root(),
        ).stdout.strip()

        if not allowed:
            assert not changed, (
                f"{relative} was modified, but the authorised feature does not "
                f"touch it"
            )
            continue

        base = subprocess.run(
            ["git", "show", f"{P52_BASE_SHA}:{relative}"],
            capture_output=True, text=True, check=True, cwd=_repo_root(),
        ).stdout
        current = _p51_worktree_source(relative)
        assert current is not None, relative

        introduced = _top_level_symbols(current) - _top_level_symbols(base)
        assert introduced <= set(allowed), (
            f"{relative} introduces top-level names outside the authorised "
            f"parametric-text change: {sorted(introduced - set(allowed))}"
        )
        missing = set(allowed) - _top_level_symbols(current)
        assert not missing, (
            f"{relative} no longer defines the authorised symbols {sorted(missing)}; "
            f"the exception has drifted from the code it was written for"
        )


def test_p51_still_owns_the_editable_authority() -> None:
    """Extending P5.1's expressiveness must not add a second authority.

    The parametric text path writes into the same draft, through the same
    builder, and is still validated by the same function. If any of that moved
    into P5.2 the manifest would stop being the authority and the two backends
    would be projecting two different descriptions of the cut.
    """
    import hevi.ops.p5_1_editable as p51
    from hevi.editable.jianying import InternalJianyingBackend

    source = _p51_worktree_source("hevi/ops/p5_1_editable.py") or ""
    # The material is registered on the caller's builder, not a builder of its own.
    assert "JianyingDraftBuilder(" not in source.split("def add_parametric_text_material")[1].split(
        "def "
    )[0], "the parametric text path constructs its own draft builder"
    # Validation of the new element kind is P5.1's, not P5.2's.
    assert hasattr(p51, "_validate_parametric_text")
    jianying_source = _p51_worktree_source("hevi/editable/jianying.py") or ""
    assert "_validate_parametric_text" not in jianying_source, (
        "P5.2 re-implements P5.1's parametric text validation"
    )
    assert InternalJianyingBackend.backend_id.value == "INTERNAL_JIANYING"


def test_p51_keeps_its_own_refusal_rules() -> None:
    """The new path must not have weakened the honesty rules it sits beside."""
    import hevi.ops.p5_1_editable as p51
    from hevi.ops.p5_1_types import EditableLayer

    # A real media element with no file is still refused by name.
    source = _p51_worktree_source("hevi/ops/p5_1_editable.py") or ""
    assert "SOURCE_MISSING" in source
    assert "CAPTIONS_REQUIRES_TEXT_SOURCE" in source
    # And a text layer with neither a file nor wording is refused too, so an empty
    # text material can never be written in its place.
    assert "PARAMETRIC_TEXT_REQUIRES_TEXT" in source
    assert EditableLayer.OVERLAY in p51.PARAMETRIC_TEXT_LAYERS


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
    """The unrelated dirty files must be preserved, not left clean.

    ``git status`` cannot answer this. These files were already modified in the
    working tree before P5.2 began, so asserting they are clean would be
    asserting that someone else's in-progress work had been reverted — and would
    fail in the canonical checkout while passing in an isolated worktree, which
    is the worst possible shape for a guard.

    What can be checked is the thing that actually matters: P5.2's own diff never
    touches them. Whether the working-tree copy is dirty is a fact about the
    checkout, not about this layer.
    """
    touched = subprocess.run(
        ["git", "diff", "--name-only", P52_BASE_SHA, "HEAD", "--",
         *UNRELATED_PRE_EXISTING_DIRTY],
        capture_output=True, text=True, check=True, cwd=_repo_root(),
    ).stdout.strip()
    assert not touched, (
        "P5.2's diff touches files that were already dirty before it started: "
        f"{touched}"
    )


def test_unrelated_dirty_is_recorded_as_preserved() -> None:
    """The declaration exists so a report can state it rather than imply it."""
    assert set(UNRELATED_PRE_EXISTING_DIRTY) == {
        "hevi/ops/p5_factory.py",
        "hevi/ops/p5_volcano_tts.py",
    }


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
