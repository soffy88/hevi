"""HEVI P5.2 — internal Jianying editable backend.

This is the *existing* HEVI editable authority (P5's ``JianyingDraftBuilder`` and
P5.1's layer manifest) exposed through the backend interface, so a differential
comparison has a canonical side to compare against. It deliberately reuses the
existing builder rather than emitting a second draft format.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.editable.base import (
    BackendProjection,
    EditabilityLevel,
    EditableBackendId,
    EditableProjectBackend,
    EditableProjectManifest,
    ProjectOutcome,
    TrackElement,
    lint_manifest,
    parametric_text_declaration,
)
from hevi.editable.capcut_cli import classify_editability


class InternalJianyingBackend(EditableProjectBackend):
    """Projects the manifest through the canonical P5/P5.1 Jianying builder."""

    backend_id = EditableBackendId.INTERNAL_JIANYING
    version = "p5.1-layered"
    revision = "hevi.ops.p5_1_editable"

    def __init__(self) -> None:
        self.available = True
        self.unavailable_reason = ""

    def detect(self) -> bool:
        return True

    def project(self, manifest: EditableProjectManifest, output_dir: Path) -> BackendProjection:
        from hevi.ops.p5_1_editable import (
            LayerElement,
            LayerManifest,
            build_layered_draft,
            validate_layered_project,
        )
        from hevi.ops.p5_1_types import EditableLayer

        projection = BackendProjection(
            backend=self.backend_id.value, version=self.version, revision=self.revision
        )
        lint = lint_manifest(manifest, project_root=output_dir)
        if lint:
            projection.outcome = ProjectOutcome.LINT_FAILED
            projection.lint_errors = lint
            projection.reason = "MANIFEST_LINT_FAILED"
            return projection

        layer_manifest = LayerManifest(
            content_id=manifest.content_id,
            candidate_id=manifest.candidate_id,
            duration_ms=manifest.duration_ms,
        )
        for element in manifest.elements:
            try:
                layer = EditableLayer(element.layer)
            except ValueError:
                projection.outcome = ProjectOutcome.FAILED
                projection.reason = f"UNKNOWN_LAYER:{element.layer}"
                return projection
            layer_manifest.add(
                LayerElement(
                    element_id=element.element_id,
                    layer=layer,
                    semantic_role=element.semantic_role,
                    start_ms=element.start_ms,
                    end_ms=element.end_ms,
                    source_artifact=element.source_artifact,
                    source_path=element.source_artifact,
                    z_order=element.z_order,
                    editable_params=dict(element.editable_properties),
                )
            )

        project = build_layered_draft(
            layer_manifest,
            Path(output_dir),
            canvas_width=manifest.canvas_width,
            canvas_height=manifest.canvas_height,
            fps=manifest.fps,
        )
        valid, errors = validate_layered_project(project)
        if not valid:
            projection.outcome = ProjectOutcome.FAILED
            projection.lint_errors = errors
            projection.reason = "JIANYING_VALIDATION_FAILED"
            return projection

        draft = json.loads(Path(project.timeline_json).read_text(encoding="utf-8"))
        projection.project_path = project.project_path
        projection.timeline_path = project.timeline_json
        projection.track_count = len(draft.get("tracks", []))
        projection.material_count = len(draft.get("materials", []))
        projection.duration_ms = round(project.duration_s * 1000)

        # Coverage is read back from the project that was actually written, not
        # from the manifest that went in. Deriving it from the input makes the
        # projection claim layers it silently dropped, and a differential built
        # on that claim cannot see a backend losing an element -- which is the
        # one thing a differential exists to catch.
        refused = list(project.refused_elements or [])
        landed = [e for e in manifest.elements if e.element_id not in _refused_ids(refused)]
        projection.layer_coverage = sorted({e.layer for e in landed})
        projection.semantic_roles = sorted({e.semantic_role for e in landed})
        if refused:
            projection.reason = f"REFUSED_ELEMENTS:{';'.join(refused)}"
        # The same honest classification the CapCut projection uses, so the two
        # backends cannot disagree about what is editable.
        projection.flattened = sorted(
            e.element_id
            for e in landed
            if classify_editability(e) is EditabilityLevel.FLATTENED_MEDIA
        )
        self._record_text_capability(projection, manifest, landed, draft)
        return projection

    def _record_text_capability(
        self,
        projection: BackendProjection,
        manifest: EditableProjectManifest,
        landed: list[TrackElement],
        draft: dict[str, Any],
    ) -> None:
        """Fold P5.1's parametric-text capability into the projection.

        P5.1 states its own capability in ``PARAMETRIC_TEXT_STYLE_FIELDS``; the
        expressed set here is what the draft it actually wrote contains, read
        back from the material sidecar and the segment geometry. Anything the
        manifest asked for that is not in the draft comes back as unsupported, so
        the differential can compare capabilities instead of comparing two
        projections that both lost the same value.
        """
        landed_ids = {e.element_id for e in landed}
        sidecars = {
            Path(str(m.get("path", ""))): (m.get("metadata") or {})
            for m in draft.get("materials", [])
            if (m.get("metadata") or {}).get("parametric_text")
        }
        geometry: dict[str, dict[str, Any]] = {}
        for track in draft.get("tracks", []):
            for segment in track.get("segments", []):
                geometry[str(segment.get("segment_id", ""))] = segment.get("clip", {}) or {}

        expressed: set[str] = set()
        unsupported: set[str] = set()
        undeclared: set[str] = set()
        for element in manifest.elements:
            declaration = parametric_text_declaration(element)
            if declaration is None:
                continue
            asked, unknown = declaration
            undeclared.update(unknown)
            sidecar = next(
                (
                    meta
                    for path, meta in sidecars.items()
                    if meta.get("element_id") == element.element_id and path.is_file()
                ),
                None,
            )
            if element.element_id not in landed_ids or sidecar is None:
                unsupported.update(asked)
                continue
            content = _sidecar_content(element.element_id, sidecars)
            clip = geometry.get(f"seg_{element.element_id}", {})
            claimed = set(sidecar.get("supported_fields") or [])
            for field in asked:
                # A field counts as expressed only when P5.1 claimed it *and* it
                # is demonstrably present where it was supposed to land. Trusting
                # the claim alone would let a backend assert a style it dropped.
                if field in claimed and _expressed_in_geometry(field, content, clip):
                    expressed.add(field)
                else:
                    unsupported.add(field)
        projection.expressed_text_fields = sorted(expressed)
        projection.unsupported_text_fields = sorted(unsupported)
        projection.undeclared_text_fields = sorted(undeclared)
        projection.dropped_elements = sorted(
            e.element_id for e in manifest.elements if e.element_id not in landed_ids
        )


def _sidecar_content(element_id: str, sidecars: dict[Path, dict[str, Any]]) -> dict[str, Any]:
    """Read one element's written content back out of its sidecar."""
    for path, meta in sidecars.items():
        if meta.get("element_id") != element_id or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        content = payload.get("content") if isinstance(payload, dict) else None
        return content if isinstance(content, dict) else {}
    return {}


def _expressed_in_geometry(field: str, content: dict[str, Any], clip: dict[str, Any]) -> bool:
    """Whether a placement or styling field actually reached the draft.

    Position and opacity live on the segment, not in the material, so they have to
    be confirmed against the clip. Checking is deliberate: the point is to report
    a field as expressed only when it is demonstrably there.
    """
    transform = clip.get("transform", {}) or {}
    scale = clip.get("scale", {}) or {}
    if field == "x":
        return field in content and "x" in transform
    if field == "y":
        return field in content and "y" in transform
    if field == "scale":
        return field in content and bool(scale)
    if field == "opacity":
        return field in content and "alpha" in clip
    return field in content


def _refused_ids(refused: list[str]) -> set[str]:
    """Element ids P5.1 declined to place, from its ``id:REASON:detail`` records."""
    return {record.split(":", 1)[0] for record in refused if record}


__all__ = ["InternalJianyingBackend"]
