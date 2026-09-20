"""P3: canonical oservi manifest + boundary contract checks.

Validates the generic oservi package publishes complete, signature-consistent
manifests and carries zero HEVI business state.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import oservi
from oservi import PipelineComposerEngine, StepSpec
from oservi.engines._base import list_skeletons


def test_oservi_manifest_present_and_versioned() -> None:
    manifest = oservi.__manifest__
    assert manifest["package"] == "oservi"
    assert manifest["version"] == oservi.__version__
    assert manifest["elements"]


def test_pipeline_composer_is_manifested() -> None:
    names = {e["name"] for e in oservi.__manifest__["elements"]}
    assert "PipelineComposerEngine" in names


def test_pipeline_composer_manifest_signature_matches() -> None:
    element = next(
        e for e in oservi.__manifest__["elements"] if e["name"] == "PipelineComposerEngine"
    )
    declared = element["signature"]
    # Declared signature must name the real method and its parameter set.
    assert declared.startswith("run(")
    params = inspect.signature(PipelineComposerEngine.run).parameters
    for name in ("config", "input_data", "output_dir", "on_step"):
        assert name in params, f"{name} missing from run()"
        assert name in declared, f"{name} missing from manifest signature"


def test_pipeline_composer_registered_as_skeleton() -> None:
    assert "pipeline_composer" in list_skeletons()


def test_oservi_has_no_business_authority_symbols() -> None:
    src = Path(oservi.__file__).parent
    forbidden = (
        "ArtifactManifest",
        "ArtifactCurrency",
        "PresentationReadModel",
        "RepairIncident",
        "ProductionRun",
        "ProviderCallRecord",
    )
    violations = []
    for py in src.rglob("*.py"):
        if py.name == "__init__.py":
            continue
        text = py.read_text(encoding="utf-8", errors="replace")
        for token in forbidden:
            if token in text:
                violations.append(f"{py.name}:{token}")
    assert not violations, f"oservi must not own business authority symbols: {violations}"


def test_pipeline_composer_step_spec_is_generic() -> None:
    fields = set(StepSpec.__dataclass_fields__)
    assert fields == {"step_id", "transaction", "depends_on", "mode", "optional", "priority"}
    # No HEVI/business fields
    for forbidden in ("project_id", "user_id", "artifact", "provider"):
        assert forbidden not in fields
