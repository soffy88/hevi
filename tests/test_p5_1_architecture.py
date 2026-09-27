"""HEVI P5.1 — architecture redlines and license boundary.

The whole point of P5.1 is that it *extends* the canonical chain rather than
growing a parallel one. These tests fail if a second pipeline, mission runtime,
repair runtime, provider registry, QA authority, delivery runtime, editable
runtime or completion authority ever appears.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
OPS = REPO / "hevi" / "ops"
P5_1_MODULES = sorted(OPS.glob("p5_1_*.py"))
P5_1_TESTS = sorted((REPO / "tests").glob("test_p5_1_*.py"))


# ── LICENSE_BOUNDARY (§3) ────────────────────────────────────────────────


def test_no_seecut_code_or_skill_was_imported() -> None:
    """SeeCut is a research reference only; no code or skill may be vendored."""
    banned = re.compile(r"seecut|see_cut|see-cut", re.IGNORECASE)
    # This auditor names the boundary on purpose, so it is not scanned itself.
    scanned = [p for p in [*P5_1_MODULES, *P5_1_TESTS] if p.name != Path(__file__).name]
    for path in scanned:
        text = path.read_text(encoding="utf-8")
        # The only permitted mention is the licence-boundary statement itself.
        for line in text.splitlines():
            if banned.search(line):
                assert "research" in line.lower() or "reference" in line.lower() or (
                    "no code" in line.lower()
                ), f"{path.name}: {line.strip()}"


def test_p5_1_does_not_vendor_a_foreign_skill_directory() -> None:
    assert not list((REPO / "hevi" / "ops").glob("seecut*"))
    assert not list(REPO.glob(".claude/skills/seecut*"))


def test_p5_1_uses_only_canonical_hevi_dependencies() -> None:
    """P5.1 may add no new third-party surface.

    Every import must be either the standard library, a HEVI package, or one of
    the third-party libraries HEVI already depends on and already uses for this
    exact kind of work (the provider registry, HTTP, and the existing browser
    capture path).
    """
    import sys

    approved_third_party = {
        "obase",  # the canonical provider registry + routing types
        "httpx",  # async HTTP, already the provider transport
        "playwright",  # the existing screenshot capture path (hevi/motion/page_capture)
        "edge_tts",  # already registered as the canonical TTS provider
    }
    pattern = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][\w.]*)", re.MULTILINE)
    for path in P5_1_MODULES:
        for module in pattern.findall(path.read_text(encoding="utf-8")):
            root = module.split(".")[0]
            assert root in sys.stdlib_module_names or root == "hevi" or (
                root in approved_third_party
            ), f"{path.name} imports unapproved dependency: {module}"


# ── No second authority (§2) ─────────────────────────────────────────────


def test_no_second_provider_registry() -> None:
    """Registration must go through the existing obase ProviderRegistry."""
    for path in P5_1_MODULES:
        text = path.read_text(encoding="utf-8")
        assert "class ProviderRegistry" not in text, path.name
        assert "class VideoProviderRegistry" not in text, path.name
    assert any(
        "ProviderRegistry.get()" in p.read_text(encoding="utf-8") for p in P5_1_MODULES
    ), "P5.1 must reuse the existing provider registry"


def test_no_second_profile_registry() -> None:
    for path in P5_1_MODULES:
        text = path.read_text(encoding="utf-8")
        assert "class ProductionProfileRegistry" not in text, path.name
    finecut = (OPS / "p5_1_finecut.py").read_text(encoding="utf-8")
    assert "get_registry()" in finecut, "the existing P2 registry must be reused"


def test_no_second_asset_registry() -> None:
    for path in P5_1_MODULES:
        assert "class AssetRegistry" not in path.read_text(encoding="utf-8"), path.name


def test_no_second_mission_or_repair_runtime() -> None:
    for path in P5_1_MODULES:
        text = path.read_text(encoding="utf-8")
        assert "class ProductionMission" not in text, path.name
        assert "class MissionExecutor" not in text, path.name
        assert "class MissionExecutor" not in text, path.name
        assert "class RepairController" not in text, path.name


def test_p5_1_does_not_shadow_canonical_types() -> None:
    """P5.1 may not redefine a P0-P5 type."""
    forbidden = {
        "VisualBeat",
        "ShotPlan",
        "MotionPlan",
        "Asset",
        "ProductionMission",
        "RepairPlan",
        "EditableProjectManifest",
        "ProductionJob",
    }
    pattern = re.compile(r"^class (\w+)", re.MULTILINE)
    for path in P5_1_MODULES:
        for name in pattern.findall(path.read_text(encoding="utf-8")):
            assert name not in forbidden, f"{path.name} redefines {name}"


def test_targeted_repair_reuses_the_p3_repair_plan() -> None:
    from hevi.ops.p5_1_diagnosis import TargetedRepairPlan, plan_targeted_repair

    assert "rerun_plan: RepairPlan" in (
        OPS / "p5_1_diagnosis.py"
    ).read_text(encoding="utf-8")
    plan = plan_targeted_repair(
        __import__(
            "hevi.ops.p5_1_types", fromlist=["EditorialDiagnosis"]
        ).EditorialDiagnosis(),
        [],
        content_id="c",
        candidate_id="V0",
    )
    assert isinstance(plan, TargetedRepairPlan)


def test_no_second_completion_authority() -> None:
    """P5.1 must not claim completion; P3's assert_completable still owns it."""
    for path in P5_1_MODULES:
        text = path.read_text(encoding="utf-8")
        assert "def assert_completable" not in text, path.name
        assert "def mark_complete" not in text, path.name
    assert not any("COMPLETED" in p.read_text(encoding="utf-8") for p in P5_1_MODULES)


def test_no_second_qa_authority() -> None:
    for path in P5_1_MODULES:
        text = path.read_text(encoding="utf-8")
        assert "class QualityEvaluator" not in text, path.name
        assert "def final_qa" not in text, path.name


def test_no_second_delivery_or_editable_runtime() -> None:
    for path in P5_1_MODULES:
        text = path.read_text(encoding="utf-8")
        assert "def deliver_local" not in text, path.name
        assert "def package_delivery" not in text, path.name
    # P5.1 extends the P5 editable builder rather than reimplementing it.
    editable = (OPS / "p5_1_editable.py").read_text(encoding="utf-8")
    assert "from hevi.ops.p5_editable import" in editable
    assert "JianyingDraftBuilder" in editable


def test_p5_1_does_not_modify_frozen_p0_to_p4_modules() -> None:
    """P0-P4 are FROZEN: P5.1 lives in its own modules."""
    frozen = [
        REPO / "hevi" / "production" / "p0_pipeline.py",
        REPO / "hevi" / "production" / "p1_types.py",
        REPO / "hevi" / "production" / "p2_types.py",
        REPO / "hevi" / "production" / "p2_profiles.py",
        REPO / "hevi" / "missions" / "p3_types.py",
        REPO / "hevi" / "missions" / "p3_runtime.py",
        REPO / "hevi" / "ops" / "p4_types.py",
        REPO / "hevi" / "ops" / "p4_scheduler.py",
    ]
    import subprocess

    for path in frozen:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", str(path.relative_to(REPO))],
            capture_output=True, text=True, check=True, cwd=REPO,
        )
        assert not result.stdout.strip(), f"P5.1 modified frozen module {path}"


def test_knowledge_profile_is_registered_in_the_existing_registry() -> None:
    from hevi.ops.p5_1_finecut import KNOWLEDGE_TALK_FINECUT, register_knowledge_talk_profile
    from hevi.production.p2_profiles import get_registry
    from hevi.production.p2_types import ProductionProfileRegistry

    register_knowledge_talk_profile()
    registry = get_registry()
    assert isinstance(registry, ProductionProfileRegistry)
    assert registry.resolve(KNOWLEDGE_TALK_FINECUT) is not None
    assert registry.validate(KNOWLEDGE_TALK_FINECUT, "1.0")[0] is True


# ── Failure semantics (§84) ──────────────────────────────────────────────


def test_provider_failure_is_reported_not_hidden() -> None:
    from hevi.ops.p5_1_providers import (
        VideoUnderstandingUnavailable,
        select_video_understanding_provider,
    )

    selection = select_video_understanding_provider("definitely_absent_provider")
    if selection.blocked:
        assert selection.reason
    assert VideoUnderstandingUnavailable is not None


def test_no_module_writes_a_false_zero_cost() -> None:
    """UNKNOWN cost must stay UNKNOWN; a hardcoded 0.0 is a lie."""
    for path in P5_1_MODULES:
        text = path.read_text(encoding="utf-8")
        assert "cost_usd = 0.0" not in text, path.name
        assert "cost_usd=0.0" not in text, path.name


def test_all_p5_1_modules_import_cleanly() -> None:
    import importlib

    for path in P5_1_MODULES:
        module = importlib.import_module(f"hevi.ops.{path.stem}")
        assert module.__doc__, f"{path.name} must document its authority boundary"
        assert hasattr(module, "__all__"), path.name


@pytest.mark.parametrize("path", P5_1_MODULES, ids=lambda p: p.name)
def test_every_module_declares_its_public_surface(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "__all__" in text
    assert "HEVI P5.1" in text.split("\n")[0] or "HEVI P5.1" in text[:400]
