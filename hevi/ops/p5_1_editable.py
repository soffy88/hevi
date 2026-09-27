"""HEVI P5.1 — layered editable delivery.

P5 already delivers an editable Jianying project. P5.1 extends that delivery
with *layer semantics* so an editor opening the project can tell what each
element is for, and so a repair can be applied to the right layer without
guessing.

Canonical tracks (§63), bottom to top:

    BACKGROUND, SPEAKER, EVIDENCE, OVERLAY, CAPTIONS, VOICE, BGM, SFX

Every timeline element declares (§64): its semantic role, the source artifact it
came from, its start/end, its z-order, and the parameters that remain editable.

Honesty rules that are load-bearing:

* An absent track is allowed to be absent. It is never back-filled with an empty
  placeholder material just to make a gate pass (§65) — a fake empty asset is a
  lie about the production, so :func:`validate_layered_project` rejects any
  layer whose material does not resolve to a real file.
* §66's round trip is a **structural** round trip. HEVI writes a draft, changes
  one supported editable property, and re-validates. It does not open the Jianying
  GUI, and the artifact says so in as many words.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hevi.ops.p5_1_types import LAYER_Z_ORDER, EditableLayer
from hevi.ops.p5_editable import (
    JianyingDraftBuilder,
    JianyingMaterial,
    JianyingSegment,
    JianyingTrack,
    validate_jianying_draft,
)

#: Layers a knowledge/emotional delivery is expected to be able to populate.
#: A layer not in this set is optional; a layer in this set is only *required*
#: when the production actually used that kind of content.
SEMANTIC_ROLES: dict[EditableLayer, tuple[str, ...]] = {
    EditableLayer.BACKGROUND: ("CONTEXTUAL_BROLL", "FULL_SCREEN_INFORMATION", "SYMBOLIC"),
    EditableLayer.SPEAKER: ("DIRECT_ADDRESS", "EMOTIONAL_PRESENCE"),
    EditableLayer.EVIDENCE: ("EVIDENCE_DOMINANT", "DEMONSTRATION"),
    EditableLayer.OVERLAY: ("SEMANTIC_HIGHLIGHT", "DIAGRAM", "CALLOUT"),
    EditableLayer.CAPTIONS: ("CAPTION",),
    EditableLayer.VOICE: ("NARRATION",),
    EditableLayer.BGM: ("MUSIC_BED",),
    EditableLayer.SFX: ("SFX",),
}

#: Jianying track type per layer. Kept in the existing vocabulary the P5 builder
#: already emits, so the draft stays loadable by the existing runtime.
LAYER_TRACK_TYPE: dict[EditableLayer, str] = {
    EditableLayer.BACKGROUND: "video",
    EditableLayer.SPEAKER: "video",
    EditableLayer.EVIDENCE: "video",
    EditableLayer.OVERLAY: "sticker",
    EditableLayer.CAPTIONS: "text",
    EditableLayer.VOICE: "audio",
    EditableLayer.BGM: "audio",
    EditableLayer.SFX: "audio",
}


@dataclass
class LayerElement:
    """One element on one semantic layer."""

    element_id: str
    layer: EditableLayer
    semantic_role: str
    start_ms: int
    end_ms: int
    source_artifact: str = ""
    source_path: str = ""
    content_hash: str = ""
    z_order: int = 0
    editable_params: dict[str, Any] = field(default_factory=dict)
    beat_id: str = ""
    shot_id: str = ""

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["layer"] = self.layer.value
        return d


@dataclass
class LayerManifest:
    """The layered timeline of a delivered project."""

    content_id: str = ""
    candidate_id: str = ""
    duration_ms: int = 0
    layers: dict[str, list[LayerElement]] = field(default_factory=dict)
    element_index: dict[str, str] = field(default_factory=dict)  # element_id -> material_id

    def add(self, element: LayerElement) -> LayerElement:
        element.z_order = LAYER_Z_ORDER[element.layer]
        self.layers.setdefault(element.layer.value, []).append(element)
        self.element_index[element.element_id] = element.source_artifact
        return element

    def elements(self) -> list[LayerElement]:
        return [
            element
            for layer in sorted(self.layers, key=lambda name: LAYER_Z_ORDER[EditableLayer(name)])
            for element in self.layers[layer]
        ]

    def populated_layers(self) -> list[EditableLayer]:
        return [
            EditableLayer(name)
            for name, elements in self.layers.items()
            if elements
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_id": self.content_id,
            "candidate_id": self.candidate_id,
            "duration_ms": self.duration_ms,
            "layers": {
                name: [element.to_dict() for element in elements]
                for name, elements in self.layers.items()
            },
            "populated_layers": [layer.value for layer in self.populated_layers()],
        }


@dataclass
class LayeredEditableProject:
    """P5's editable manifest extended with layer semantics."""

    project_path: str = ""
    timeline_json: str = ""
    duration_s: float = 0.0
    manifest: LayerManifest | None = None
    round_trip: str = "NOT_RUN"
    validation_errors: list[str] = field(default_factory=list)
    refused_elements: list[str] = field(default_factory=list)
    validated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_path": self.project_path,
            "timeline_json": self.timeline_json,
            "duration_s": self.duration_s,
            "validated": self.validated,
            "validation_errors": self.validation_errors,
            "round_trip": self.round_trip,
            "refused_elements": self.refused_elements,
            "manifest": self.manifest.to_dict() if self.manifest else None,
        }


# ── Draft construction ──────────────────────────────────────────────────


#: Source suffixes the CAPTIONS layer accepts. Captions are text, so an audio or
#: video file on the caption layer is a caller error and is refused rather than
#: silently relabelled.
CAPTION_SUFFIXES = (".srt", ".vtt", ".ass", ".ssa", ".txt", ".json")


def add_caption_material(
    builder: JianyingDraftBuilder, source: Path, *, style: dict[str, Any] | None = None
) -> str:
    """Register a real text material for a caption track.

    P5's builder ships no text-material path, so P5.1 adds one *into the same*
    draft structure rather than creating a second project format. The caption
    source is copied into the draft's materials directory, which is what makes
    the reference resolvable instead of dangling.
    """
    material_id = f"text_{source.stem}_{len(builder.materials)}"
    dest = builder.materials_dir / f"{material_id}{source.suffix}"
    shutil.copy2(source, dest)
    builder.materials.append(
        JianyingMaterial(
            material_id=material_id,
            type="text",
            path=str(dest),
            duration=0,
            metadata={
                "caption_source": source.name,
                "safe_area_pct": float((style or {}).get("safe_area_pct", 0.9)),
                "font_size_px": int((style or {}).get("font_size_px", 48)),
                "max_lines": int((style or {}).get("max_lines", 2)),
                "must_not_occlude_subject": True,
            },
        )
    )
    return material_id


def _segment_for(element: LayerElement, material_id: str) -> JianyingSegment:
    duration_us = int(element.duration_ms * 1000)
    return JianyingSegment(
        segment_id=f"seg_{element.element_id}",
        material_id=material_id,
        target_timerange={"start": int(element.start_ms * 1000), "duration": duration_us},
        source_timerange={"start": 0, "duration": duration_us},
        clip={
            "alpha": 1.0,
            "rotation": 0.0,
            "scale": {"x": 1.0, "y": 1.0},
            "transform": {"x": 0.0, "y": 0.0},
        },
        extra_material_refs=[],
        visible=True,
        volume=float(element.editable_params.get("volume", 1.0)),
        speed=1.0,
    )


def build_layered_draft(
    manifest: LayerManifest,
    output_dir: Path,
    *,
    canvas_width: int = 1280,
    canvas_height: int = 720,
    fps: int = 30,
) -> LayeredEditableProject:
    """Build a Jianying draft from a semantic layer manifest.

    Only layers that actually have content produce a track. Nothing is padded
    with an empty material to satisfy a checklist.
    """
    builder = JianyingDraftBuilder(Path(output_dir))
    element_to_material: dict[str, str] = {}
    refused: list[str] = []

    for element in list(manifest.elements()):
        source = Path(element.source_path) if element.source_path else None
        if source is None or not source.is_file():
            # No real backing file: drop the element so the layer is simply absent
            # rather than shipping a placeholder, and record the refusal so the
            # omission stays visible instead of being quietly swallowed.
            refused.append(f"{element.element_id}:SOURCE_MISSING:{element.source_path}")
            manifest.element_index.pop(element.element_id, None)
            _drop(manifest, element)
            continue
        suffix = source.suffix.lower()
        if element.layer is EditableLayer.CAPTIONS:
            if suffix not in CAPTION_SUFFIXES:
                # Refuse to relabel an audio/video file as captions.
                refused.append(f"{element.element_id}:CAPTIONS_REQUIRES_TEXT_SOURCE:{suffix}")
                manifest.element_index.pop(element.element_id, None)
                _drop(manifest, element)
                continue
            material_id = add_caption_material(
                builder, source, style=element.editable_params
            )
        elif suffix in (".mp4", ".mov", ".mkv", ".webm"):
            material_id = builder.add_video_material(source, element.content_hash)
        elif suffix in (".wav", ".mp3", ".m4a", ".aac", ".flac"):
            material_id = builder.add_audio_material(source, element.content_hash)
        elif suffix in (".png", ".jpg", ".jpeg", ".webp"):
            material_id = builder.add_image_material(source, element.content_hash)
        else:
            continue
        element_to_material[element.element_id] = material_id

    for element in manifest.elements():
        resolved_material = element_to_material.get(element.element_id)
        if not resolved_material:
            continue
        material_id = resolved_material
        track_type = LAYER_TRACK_TYPE[element.layer]
        track = JianyingTrack(
            track_id=f"track_{element.layer.value.lower()}_{len(builder.tracks)}",
            track_type=track_type,
            segments=[_segment_for(element, material_id)],
            attribute=0,
            flag=0,
        )
        builder.tracks.append(track)
        manifest.element_index[element.element_id] = material_id

    # ``JianyingDraftBuilder.save`` returns the draft *directory*; the timeline
    # JSON lives inside it under the canonical P5 filename.
    draft_dir = Path(builder.save(canvas_width=canvas_width, canvas_height=canvas_height, fps=fps))
    timeline = draft_dir / "draft_content.json"
    duration_s = max(
        (element.end_ms for element in manifest.elements()), default=0
    ) / 1000.0

    return LayeredEditableProject(
        project_path=str(draft_dir),
        timeline_json=str(timeline),
        duration_s=duration_s,
        manifest=manifest,
        refused_elements=sorted(refused),
    )


def _drop(manifest: LayerManifest, element: LayerElement) -> None:
    """Remove an element from its layer, deleting the layer when it empties."""
    elements = manifest.layers.get(element.layer.value)
    if not elements:
        return
    remaining = [item for item in elements if item.element_id != element.element_id]
    if remaining:
        manifest.layers[element.layer.value] = remaining
    else:
        manifest.layers.pop(element.layer.value, None)


# ── Validation (§64, §65, A19) ───────────────────────────────────────────


def validate_layered_project(project: LayeredEditableProject) -> tuple[bool, list[str]]:
    """Validate a layered editable project.

    Checks the underlying draft, then the layer semantics: every element must
    name a semantic role its layer actually permits, sit inside the timeline,
    and resolve to a real material. A layer that is empty is fine; a layer whose
    element points at nothing is not.
    """
    errors: list[str] = []
    if not project.project_path or not Path(project.project_path).exists():
        return False, [f"PROJECT_PATH_MISSING:{project.project_path}"]

    valid, draft_errors = validate_jianying_draft(Path(project.project_path))
    if not valid:
        return False, draft_errors

    manifest = project.manifest
    if manifest is None:
        return False, ["LAYER_MANIFEST_MISSING"]

    draft = json.loads(Path(project.timeline_json).read_text(encoding="utf-8"))
    # The builder copies each source into the draft's materials/ directory under a
    # new material_id, so resolution is by material_id, not by original path.
    draft_materials = {
        str(m.get("material_id", "")): m for m in draft.get("materials", []) if m.get("material_id")
    }
    draft_paths = {
        str(m.get("path", "")) for m in draft.get("materials", []) if m.get("path")
    }

    for element in manifest.elements():
        allowed = SEMANTIC_ROLES.get(element.layer, ())
        if allowed and element.semantic_role not in allowed:
            errors.append(
                f"LAYER_SEMANTICS_INVALID:{element.element_id}:"
                f"{element.semantic_role}_NOT_ALLOWED_ON_{element.layer.value}"
            )
        if element.duration_ms <= 0:
            errors.append(f"ELEMENT_ZERO_DURATION:{element.element_id}")
        if manifest.duration_ms and element.end_ms > manifest.duration_ms:
            errors.append(f"ELEMENT_BEYOND_TIMELINE:{element.element_id}")
        material_id = manifest.element_index.get(element.element_id, "")
        if not material_id:
            errors.append(f"BROKEN_REFERENCE:{element.element_id}:no_material")
            continue
        material = draft_materials.get(material_id)
        if material is None:
            errors.append(f"BROKEN_REFERENCE:{element.element_id}:material_{material_id}_absent")
            continue
        material_path = str(material.get("path", ""))
        if not material_path or material_path not in draft_paths or not Path(material_path).exists():
            errors.append(f"BROKEN_REFERENCE:{element.element_id}:{material_path}")
        if element.source_path and not Path(element.source_path).exists():
            errors.append(f"SOURCE_ARTIFACT_MISSING:{element.element_id}:{element.source_path}")

    errors.extend(
        f"EMPTY_TRACK_SHIPPED:{track.get('track_id')}"
        for track in draft.get("tracks", [])
        if not track.get("segments")
    )

    project.validation_errors = errors
    project.validated = not errors
    return (not errors), errors


# ── Structural round trip (§66) ──────────────────────────────────────────

#: Editable properties a downstream editor is expected to be able to change.
SUPPORTED_EDITABLE_PROPERTIES = (
    "caption.safe_area_pct",
    "caption.font_size_px",
    "element.volume",
    "element.speed",
    "element.transform.scale",
    "track.order",
)


@dataclass
class RoundTripResult:
    """Result of a structural round trip through the editable project."""

    ok: bool = False
    kind: str = "STRUCTURAL_ROUND_TRIP"
    mutation: str = ""
    revalidated: bool = False
    errors: list[str] = field(default_factory=list)
    note: str = (
        "structural round trip only: the draft JSON was edited and re-validated. "
        "No GUI round trip is claimed."
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def structural_round_trip(
    project: LayeredEditableProject,
    *,
    mutation: str = "caption.safe_area_pct",
) -> RoundTripResult:
    """Edit one supported editable property, then re-validate the project.

    This proves the delivered project is genuinely editable and not a frozen
    blob: a downstream change survives validation. It is explicitly a
    *structural* qualification — HEVI does not launch Jianying here and does not
    claim a GUI round trip.
    """
    result = RoundTripResult(mutation=mutation)
    timeline = Path(project.timeline_json)
    if not timeline.is_file():
        result.errors.append(f"TIMELINE_MISSING:{timeline}")
        return result

    try:
        data = json.loads(timeline.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result.errors.append(f"TIMELINE_INVALID_JSON:{exc}")
        return result

    applied = _apply_mutation(data, mutation)
    if not applied:
        result.errors.append(f"MUTATION_UNSUPPORTED:{mutation}")
        return result

    backup = timeline.with_suffix(".preroundtrip.json")
    shutil.copy2(timeline, backup)
    timeline.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    valid, errors = validate_layered_project(project)
    result.revalidated = valid
    if not valid:
        result.errors = errors
        shutil.copy2(backup, timeline)
    else:
        backup.unlink(missing_ok=True)
    result.ok = valid
    return result


def _apply_mutation(data: dict[str, Any], mutation: str) -> bool:
    """Apply one supported editable mutation to the draft JSON."""
    if mutation == "element.volume":
        touched = False
        for track in data.get("tracks", []):
            for segment in track.get("segments", []):
                if "volume" in segment:
                    segment["volume"] = round(min(1.0, float(segment["volume"]) * 0.8), 3)
                    touched = True
        return touched

    if mutation == "element.speed":
        touched = False
        for track in data.get("tracks", []):
            for segment in track.get("segments", []):
                if "speed" in segment:
                    segment["speed"] = 0.9
                    touched = True
        return touched

    if mutation == "element.transform.scale":
        touched = False
        for track in data.get("tracks", []):
            for segment in track.get("segments", []):
                clip = segment.get("clip")
                if isinstance(clip, dict) and isinstance(clip.get("scale"), dict):
                    clip["scale"] = {"x": 0.96, "y": 0.96}
                    touched = True
        return touched

    if mutation == "caption.safe_area_pct":
        touched = False
        for material in data.get("materials", []):
            metadata = material.setdefault("metadata", {})
            if material.get("type") == "text":
                metadata["safe_area_pct"] = 0.82
                touched = True
        return touched

    if mutation == "caption.font_size_px":
        touched = False
        for material in data.get("materials", []):
            if material.get("type") == "text":
                material.setdefault("metadata", {})["font_size_px"] = 44
                touched = True
        return touched

    if mutation == "track.order":
        tracks = data.get("tracks")
        if isinstance(tracks, list) and len(tracks) > 1:
            tracks.reverse()
            return True
        return False

    return False


# ── Convenience builder ─────────────────────────────────────────────────


def manifest_from_production(
    *,
    content_id: str,
    candidate_id: str,
    background_path: str = "",
    speaker_path: str = "",
    evidence: list[dict[str, Any]] | None = None,
    overlay: list[dict[str, Any]] | None = None,
    caption_path: str = "",
    voice_path: str = "",
    bgm_path: str = "",
    sfx_paths: list[str] | None = None,
    duration_ms: int = 0,
) -> LayerManifest:
    """Assemble a layer manifest from production artifacts."""
    manifest = LayerManifest(
        content_id=content_id, candidate_id=candidate_id, duration_ms=duration_ms
    )
    if background_path:
        manifest.add(
            LayerElement(
                element_id="bg-main",
                layer=EditableLayer.BACKGROUND,
                semantic_role="CONTEXTUAL_BROLL",
                start_ms=0,
                end_ms=duration_ms,
                source_artifact=background_path,
                source_path=background_path,
            )
        )
    if speaker_path:
        manifest.add(
            LayerElement(
                element_id="speaker-main",
                layer=EditableLayer.SPEAKER,
                semantic_role="DIRECT_ADDRESS",
                start_ms=0,
                end_ms=duration_ms,
                source_artifact=speaker_path,
                source_path=speaker_path,
                editable_params={"volume": 1.0},
            )
        )
    for index, item in enumerate(evidence or []):
        start = int(item.get("start_ms", 0))
        end = int(item.get("end_ms", duration_ms))
        path = str(item.get("path", ""))
        manifest.add(
            LayerElement(
                element_id=f"evidence-{index}",
                layer=EditableLayer.EVIDENCE,
                semantic_role=str(item.get("role", "EVIDENCE_DOMINANT")),
                start_ms=start,
                end_ms=end,
                source_artifact=str(item.get("asset_id", path)),
                source_path=path,
                content_hash=str(item.get("content_hash", "")),
                editable_params={"scale": 1.0},
            )
        )
    for index, item in enumerate(overlay or []):
        start = int(item.get("start_ms", 0))
        end = int(item.get("end_ms", duration_ms))
        path = str(item.get("path", ""))
        manifest.add(
            LayerElement(
                element_id=f"overlay-{index}",
                layer=EditableLayer.OVERLAY,
                semantic_role=str(item.get("role", "SEMANTIC_HIGHLIGHT")),
                start_ms=start,
                end_ms=end,
                source_artifact=str(item.get("asset_id", path)),
                source_path=path,
                editable_params={"scale": 1.0},
            )
        )
    if caption_path:
        manifest.add(
            LayerElement(
                element_id="captions-main",
                layer=EditableLayer.CAPTIONS,
                semantic_role="CAPTION",
                start_ms=0,
                end_ms=duration_ms,
                source_artifact=caption_path,
                source_path=caption_path,
                editable_params={"safe_area_pct": 0.9, "font_size_px": 48},
            )
        )
    if voice_path:
        manifest.add(
            LayerElement(
                element_id="voice-main",
                layer=EditableLayer.VOICE,
                semantic_role="NARRATION",
                start_ms=0,
                end_ms=duration_ms,
                source_artifact=voice_path,
                source_path=voice_path,
                editable_params={"volume": 1.0},
            )
        )
    if bgm_path:
        manifest.add(
            LayerElement(
                element_id="bgm-main",
                layer=EditableLayer.BGM,
                semantic_role="MUSIC_BED",
                start_ms=0,
                end_ms=duration_ms,
                source_artifact=bgm_path,
                source_path=bgm_path,
                editable_params={"volume": 0.18},
            )
        )
    for index, path in enumerate(sfx_paths or []):
        manifest.add(
            LayerElement(
                element_id=f"sfx-{index}",
                layer=EditableLayer.SFX,
                semantic_role="SFX",
                start_ms=0,
                end_ms=min(2000, duration_ms),
                source_artifact=path,
                source_path=path,
                editable_params={"volume": 0.5},
            )
        )
    return manifest


__all__ = [
    "LAYER_TRACK_TYPE",
    "SEMANTIC_ROLES",
    "SUPPORTED_EDITABLE_PROPERTIES",
    "JianyingMaterial",
    "LayerElement",
    "LayerManifest",
    "LayeredEditableProject",
    "RoundTripResult",
    "build_layered_draft",
    "manifest_from_production",
    "structural_round_trip",
    "validate_layered_project",
]
