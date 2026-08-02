"""Consumer-side 3O contract checks required for every HEVI release."""

from __future__ import annotations

from pathlib import Path

import obase
import omodul
import oprim
import oservi
import oskill


def test_all_five_3o_packages_publish_versioned_root_manifests() -> None:
    for package in (obase, oprim, oskill, omodul, oservi):
        manifest = package.__manifest__
        assert manifest["package"] == package.__name__
        assert manifest["version"] == package.__version__
        assert manifest["elements"]


def test_skill_manifest_declares_composition_of_multiple_primitives() -> None:
    manifest = oskill.__manifest__
    for element in manifest["elements"]:
        assert len(element["depends_on"]) >= 2


def test_hevi_does_not_import_private_oprim_or_omodul_symbols() -> None:
    root = Path(__file__).parents[1] / "hevi"
    forbidden = ("from oprim._", "import oprim._", "from omodul._", "import omodul._")
    violations = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if any(token in path.read_text(encoding="utf-8") for token in forbidden)
    ]
    assert not violations, f"private 3O imports must use public exports: {violations}"


def test_task_service_does_not_reverse_import_api_router_adapters() -> None:
    root = Path(__file__).parents[1]
    task_service = (root / "hevi/tasks/task_service.py").read_text(encoding="utf-8")
    registry = (root / "hevi/production/adapters.py").read_text(encoding="utf-8")
    assert "hevi.api.routers" not in task_service
    assert "hevi.api.routers" not in registry
