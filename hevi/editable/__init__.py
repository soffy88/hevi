"""HEVI P5.2 — editable project backends.

The manifest is the authority; a backend is a projection. Registering the two
backends here does not create a second editable authority — it creates a second
way of *writing* the one the manifest already describes.
"""

from __future__ import annotations

import json
from pathlib import Path

from hevi.editable.base import (
    BackendProjection,
    DifferentialReport,
    EditabilityLevel,
    EditableBackendId,
    EditableProjectBackend,
    EditableProjectManifest,
    ProjectOutcome,
    TrackElement,
    compare_projections,
    lint_manifest,
)
from hevi.editable.capcut_cli import (
    EXPECTED_REVISION,
    EXPECTED_VERSION,
    CapCutCliBackend,
    CapCutSecurityError,
    assert_contained,
    assert_safe_name,
    scrub_device_identifiers,
)
from hevi.editable.jianying import InternalJianyingBackend

_REGISTERED = False


def register_all_backends(force: bool = False) -> list[str]:
    global _REGISTERED
    if _REGISTERED and not force:
        return [backend.backend_id.value for backend in list_backends()]
    for backend in (InternalJianyingBackend(), CapCutCliBackend()):
        register_backend(backend)
    _REGISTERED = True
    return [backend.backend_id.value for backend in list_backends()]


_BACKENDS: dict[EditableBackendId, EditableProjectBackend] = {}


def register_backend(backend: EditableProjectBackend) -> None:
    _BACKENDS[backend.backend_id] = backend


def list_backends() -> list[EditableProjectBackend]:
    return [_BACKENDS[key] for key in sorted(_BACKENDS, key=lambda k: k.value)]


def get_backend(backend_id: EditableBackendId) -> EditableProjectBackend | None:
    return _BACKENDS.get(backend_id)


def project_manifest(
    manifest: EditableProjectManifest, output_dir: Path, backend_id: EditableBackendId
) -> BackendProjection:
    register_all_backends()
    backend = get_backend(backend_id)
    if backend is None:
        return BackendProjection(
            backend=backend_id.value, outcome=ProjectOutcome.UNAVAILABLE,
            reason="BACKEND_NOT_REGISTERED",
        )
    return backend.project(manifest, Path(output_dir))


def structural_round_trip(
    manifest: EditableProjectManifest, projection: BackendProjection
) -> tuple[bool, list[str]]:
    """Read a projection back and re-validate it structurally (§75).

    The projection is reopened, re-parsed and compared against the manifest it
    came from. A backend that produced a file nobody can read back fails here.
    """
    if not projection.timeline_path:
        return False, ["PROJECTION_WITHOUT_TIMELINE"]
    path = Path(projection.timeline_path)
    if not path.is_file():
        return False, [f"TIMELINE_MISSING:{path}"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, [f"TIMELINE_UNREADABLE:{exc}"]

    errors: list[str] = []
    elements = data.get("elements")
    if elements is None:
        # The Jianying projection keys segments under tracks instead.
        tracks = data.get("tracks")
        if not isinstance(tracks, list) or not tracks:
            errors.append("PROJECTION_HAS_NO_ELEMENTS")
        return (not errors), errors

    if not elements:
        # A delivered editable project with zero elements is never valid, even if
        # the manifest it came from was itself empty.
        errors.append("PROJECTION_HAS_NO_ELEMENTS")
        return (not errors), errors
    if len(elements) != len(manifest.elements):
        errors.append(
            f"ELEMENT_COUNT_MISMATCH:manifest={len(manifest.elements)} projection={len(elements)}"
        )
    manifest_roles = sorted({e.semantic_role for e in manifest.elements})
    if sorted({str(e.get("semantic_role", "")) for e in elements}) != manifest_roles:
        errors.append("SEMANTIC_ROLES_MISMATCH")
    projected_duration = int(data.get("duration_ms", manifest.duration_ms))
    if abs(projected_duration - manifest.duration_ms) > 1000:
        errors.append(
            f"DURATION_MISMATCH:manifest={manifest.duration_ms} projection={projected_duration}"
        )
    for element in elements:
        if not element.get("semantic_role"):
            errors.append(f"PROJECTED_ELEMENT_WITHOUT_ROLE:{element.get('element_id')}")
        if not element.get("source_artifact"):
            errors.append(f"PROJECTED_ELEMENT_WITHOUT_SOURCE:{element.get('element_id')}")
    return (not errors), errors


__all__ = [
    "BackendProjection",
    "DifferentialReport",
    "EditabilityLevel",
    "EditableBackendId",
    "EditableProjectBackend",
    "EditableProjectManifest",
    "ProjectOutcome",
    "TrackElement",
    "compare_projections",
    "lint_manifest",
    "CapCutCliBackend",
    "CapCutSecurityError",
    "assert_contained",
    "assert_safe_name",
    "scrub_device_identifiers",
    "EXPECTED_VERSION",
    "EXPECTED_REVISION",
    "InternalJianyingBackend",
    "register_all_backends",
    "register_backend",
    "list_backends",
    "get_backend",
    "project_manifest",
    "structural_round_trip",
]
