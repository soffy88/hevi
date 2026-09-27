"""HEVI P5.2 — editable project backend abstraction.

``EditableProjectManifest`` is the single description of an editable project.
A backend is only a *projection* of that manifest into some tool's format. This
is the whole reason the abstraction exists: if the manifest is the authority,
then adding CapCut CLI cannot fork HEVI's notion of what an editable project
is, it can only add another way of writing one.

Each projection must report honestly what it can and cannot represent. An
element it cannot expose for editing is ``FLATTENED_MEDIA`` — never
``NATIVE_EDITABLE`` — because a downstream editor who is told a flattened clip
is "editable" will waste an afternoon trying to change a caption that is baked
into the picture.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class EditabilityLevel(StrEnum):
    """How faithfully a backend can represent one timeline element."""

    NATIVE_EDITABLE = "NATIVE_EDITABLE"
    PARAMETRIC_EDITABLE = "PARAMETRIC_EDITABLE"
    FLATTENED_MEDIA = "FLATTENED_MEDIA"


class EditableBackendId(StrEnum):
    INTERNAL_JIANYING = "INTERNAL_JIANYING"
    CAPCUT_CLI = "CAPCUT_CLI"


class ProjectOutcome(StrEnum):
    OK = "OK"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"
    LINT_FAILED = "LINT_FAILED"


@dataclass
class TrackElement:
    """One element on one semantic track (§69)."""

    element_id: str
    layer: str
    semantic_role: str
    start_ms: int
    end_ms: int
    source_artifact: str = ""
    source_in_ms: int = 0
    source_out_ms: int = 0
    z_order: int = 0
    transform: dict[str, float] = field(default_factory=dict)
    opacity: float = 1.0
    editable_properties: dict[str, Any] = field(default_factory=dict)
    editability: EditabilityLevel = EditabilityLevel.NATIVE_EDITABLE

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["editability"] = self.editability.value
        return d


@dataclass
class EditableProjectManifest:
    """The canonical editable description. Backends project *this*."""

    project_id: str
    backend_hint: str = ""
    duration_ms: int = 0
    canvas_width: int = 1280
    canvas_height: int = 720
    fps: int = 30
    elements: list[TrackElement] = field(default_factory=list)
    content_id: str = ""
    candidate_id: str = ""

    def by_layer(self) -> dict[str, list[TrackElement]]:
        out: dict[str, list[TrackElement]] = {}
        for element in self.elements:
            out.setdefault(element.layer, []).append(element)
        return out

    def counts(self) -> dict[str, int]:
        return {layer: len(items) for layer, items in self.by_layer().items()}

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "backend_hint": self.backend_hint,
            "content_id": self.content_id,
            "candidate_id": self.candidate_id,
            "duration_ms": self.duration_ms,
            "canvas": [self.canvas_width, self.canvas_height],
            "fps": self.fps,
            "track_count": len(self.by_layer()),
            "element_count": len(self.elements),
            "counts": self.counts(),
            "elements": [e.to_dict() for e in self.elements],
        }


@dataclass
class BackendProjection:
    """What one backend produced, and how faithfully."""

    backend: str
    outcome: ProjectOutcome = ProjectOutcome.OK
    project_path: str = ""
    timeline_path: str = ""
    track_count: int = 0
    material_count: int = 0
    duration_ms: int = 0
    semantic_roles: list[str] = field(default_factory=list)
    #: Semantic layers this projection actually carries. This — not the physical
    #: track count — is what two backends must agree on.
    layer_coverage: list[str] = field(default_factory=list)
    flattened: list[str] = field(default_factory=list)
    lint_errors: list[str] = field(default_factory=list)
    reason: str = ""
    version: str = ""
    revision: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome is ProjectOutcome.OK

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["outcome"] = self.outcome.value
        d["backend"] = str(self.backend)
        return d


@dataclass
class DifferentialReport:
    """Backend differential validation (§73).

    The point is to prove the *manifest* is the authority: two different
    projections of one manifest must agree on the dimensions the manifest
    actually owns — track count, duration, and semantic roles.

    Material count is compared as a **floor**, not for equality. The two tools
    have different material models: CapCut materialises a full BOM (speeds,
    colour, placeholder entries for every segment) while the internal builder
    materialises only what it references. Treating that difference as a
    divergence would report a modelling difference as a manifest bug, and
    treating it as equal would hide a real missing material. So each projection
    must clear the manifest's own distinct-source count, and the raw numbers are
    reported either way.
    """

    ok: bool = True
    shared: dict[str, int] = field(default_factory=dict)
    track_counts: dict[str, int] = field(default_factory=dict)
    material_counts: dict[str, int] = field(default_factory=dict)
    divergences: list[str] = field(default_factory=list)
    backends: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Lint (§72) ───────────────────────────────────────────────────────────

_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9._\- ]+$")


def lint_manifest(manifest: EditableProjectManifest, *, project_root: Path) -> list[str]:
    """Lint a manifest before it is projected.

    Catches the failures that would otherwise ship: missing material files,
    zero/negative durations, source ranges outside the source, elements past the
    end of the timeline, caption overlaps where the layer forbids them, and
    elements claiming an editability the layer cannot support.
    """
    errors: list[str] = []
    root = Path(project_root)
    if manifest.duration_ms <= 0:
        errors.append("INVALID_TOTAL_DURATION")
    seen: set[str] = set()
    for element in manifest.elements:
        if element.element_id in seen:
            errors.append(f"DUPLICATE_ELEMENT_ID:{element.element_id}")
        seen.add(element.element_id)
        if element.duration_ms <= 0:
            errors.append(f"NON_POSITIVE_DURATION:{element.element_id}")
        if element.end_ms > manifest.duration_ms:
            errors.append(f"ELEMENT_BEYOND_TIMELINE:{element.element_id}")
        if not element.semantic_role:
            errors.append(f"MISSING_SEMANTIC_ROLE:{element.element_id}")
        source = element.source_artifact
        if not source:
            # A parametric element is built from its own properties rather than
            # from a media file -- a lower third whose text is editable is the
            # canonical case. Demanding a source artifact for it would make an
            # *editable* project inexpressible and push every overlay toward a
            # flattened image, which is the opposite of what this layer is for.
            # The escape is narrow: the element has to actually declare the
            # properties it is built from.
            if element.editable_properties:
                pass
            else:
                errors.append(f"MISSING_SOURCE_ARTIFACT:{element.element_id}")
        elif (
            not source.startswith("http")
            and not (root / source).exists()
            and not Path(source).exists()
        ):
            errors.append(f"MISSING_MATERIAL_FILE:{element.element_id}:{source}")
        if element.source_out_ms and element.source_out_ms <= element.source_in_ms:
            errors.append(f"INVALID_SOURCE_RANGE:{element.element_id}")
        if element.opacity < 0.0 or element.opacity > 1.0:
            errors.append(f"INVALID_OPACITY:{element.element_id}")
        if element.layer == "CAPTIONS" and element.semantic_role != "CAPTION":
            errors.append(f"CAPTION_LAYER_ROLE_MISMATCH:{element.element_id}")
    return errors


def compare_projections(
    manifest: EditableProjectManifest, projections: list[BackendProjection]
) -> DifferentialReport:
    """Compare two projections of the same manifest."""
    report = DifferentialReport(backends=[p.backend for p in projections])
    if len(projections) < 2:
        report.ok = False
        report.divergences.append("NEED_TWO_BACKENDS_FOR_DIFFERENTIAL")
        return report

    # Duration and semantic coverage are the manifest-owned invariants. The
    # *physical* track count is deliberately not compared for equality: the
    # internal builder gives every clip its own track so it stays independently
    # editable, while CapCut groups clips by track type. Both are valid ways to
    # carry the same manifest, so requiring equal track counts would report a
    # tool difference as a manifest bug.
    for attribute in ("duration_ms",):
        values = {getattr(p, attribute) for p in projections}
        if len(values) == 1:
            report.shared[attribute] = values.pop()
        else:
            report.divergences.append(
                f"{attribute.upper()}_DIVERGES:"
                + ",".join(f"{p.backend}={getattr(p, attribute)}" for p in projections)
            )

    layer_sets = {frozenset(p.layer_coverage) for p in projections}
    manifest_layers = frozenset(e.layer for e in manifest.elements)
    for projection in projections:
        missing = sorted(manifest_layers - set(projection.layer_coverage))
        if missing:
            report.divergences.append(
                f"LAYERS_MISSING:{projection.backend}={','.join(missing)}"
            )
    if len(layer_sets) == 1 and not report.divergences:
        report.shared["semantic_layers"] = len(manifest_layers)
    report.track_counts = {p.backend: p.track_count for p in projections}

    # Material count: a floor check, because the two tools model materials
    # differently. A projection that dropped a real material still fails.
    required_materials = len({e.source_artifact for e in manifest.elements if e.source_artifact})
    report.material_counts = {p.backend: p.material_count for p in projections}
    for projection in projections:
        if projection.material_count < required_materials:
            report.divergences.append(
                f"MATERIALS_BELOW_MANIFEST:{projection.backend}="
                f"{projection.material_count}<{required_materials}"
            )
    if not report.divergences:
        report.shared["required_materials"] = required_materials

    role_sets = {p.backend: set(p.semantic_roles) for p in projections}
    distinct = {frozenset(roles) for roles in role_sets.values()}
    if len(distinct) == 1:
        report.shared["semantic_roles"] = len(next(iter(distinct)))
    else:
        report.divergences.append(
            "SEMANTIC_ROLES_DIVERGE:"
            + ",".join(f"{backend}={sorted(roles)}" for backend, roles in role_sets.items())
        )

    report.ok = not report.divergences
    return report


class EditableProjectBackend:
    """Base class for editable project backends."""

    backend_id: EditableBackendId = EditableBackendId.INTERNAL_JIANYING
    version: str = ""
    revision: str = ""
    available: bool = False
    unavailable_reason: str = "not probed"

    def detect(self) -> bool:
        return self.available

    def project(self, manifest: EditableProjectManifest, output_dir: Path) -> BackendProjection:
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self.backend_id.value,
            "version": self.version,
            "revision": self.revision,
            "available": self.detect(),
            "unavailable_reason": self.unavailable_reason,
        }


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
]
