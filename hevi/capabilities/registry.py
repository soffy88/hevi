"""Hevi unified capability registry.

Every product line (zero, talkcraft, short-drama, artmotion, explainer,
ShotSpec workbench, …) must expose its generative abilities through this one
registry, addressed by a stable dotted name (``scene3d.planet_orbit``,
``handdraw.narration``, …).  No line is allowed to keep a private entry point:
see ``CAPABILITY_CONTRACT.md`` (user addendum 2026-10-14).

The contract requires these primitives:

* ``register(Capability(...))`` — install a capability.
* ``get(name)`` — resolve a capability by name (raises ``CapabilityError``).
* ``list(kind=..., aspect=...)`` — enumerate registered capabilities.
* ``Capability.render(params, out_dir, *, duration, aspect, seed)`` — produce
  the artefact (mp4/png/wav) deterministically and return a
  ``CapabilityResult``.  A failed render raises ``CapabilityError``; it must
  never return a fake success.

The scene3d line (``hevi/layer4_legacy/scene3d``) is the first consumer that
registers itself here.  ``webkit`` owns the authoritative registry at merge
time; this branch's implementation is the minimal contract surface agreed in
``CAPABILITY_CONTRACT.md`` and is merge-compatible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import CapabilityError
from .result import CapabilityResult

__all__ = [
    "Capability",
    "CapabilityError",
    "CapabilityResult",
    "register",
    "get",
    "list_capabilities",
    "list",
    "resolve",
    "Registry",
]

# Canonical registry: a process-global, ordered dict keyed by capability name.
_REGISTRY: dict[str, "Capability"] = {}


@dataclass
class Capability:
    """A named, product-line-agnostic generative ability.

    A capability renders an artefact (mp4 / png / wav) deterministically for a
    given ``seed`` and reports the result via :class:`CapabilityResult`.
    """

    name: str
    kind: str  # shot | overlay | transition | audio | title | line
    aspects: list[str]  # e.g. ["16:9", "9:16"]
    params_schema: dict[str, Any]
    cpu_cost_hint: float  # approx CPU-seconds per second of output video
    render: Any  # callable(params, out_dir, *, duration, aspect, seed) -> CapabilityResult
    description: str = ""
    line: str = ""  # owning product line (e.g. "scene3d")

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate ``params`` against ``params_schema``; return the params.

        Raises :class:`CapabilityError` on any schema violation.  When the JSON
        schema validator itself cannot be imported we refuse to validate rather
        than waving the params through: silently accepting unvalidated params is
        a fake success, which the capability contract forbids.
        """
        try:
            import jsonschema
        except Exception as exc:  # pragma: no cover - jsonschema is always present in CI.
            raise CapabilityError(
                f"capability {self.name}: cannot validate params, jsonschema "
                f"unavailable: {exc}"
            ) from exc
        try:
            jsonschema.validate(instance=params, schema=self.params_schema)
        except Exception as exc:  # jsonschema.ValidationError subclasses Exception.
            raise CapabilityError(
                f"capability {self.name}: invalid params: {exc}"
            ) from exc
        return params

    def supports_aspect(self, aspect: str) -> bool:
        return aspect in self.aspects


def register(cap: Capability) -> Capability:
    """Install ``cap`` into the global registry (last writer wins per name)."""
    if not cap.name:
        raise CapabilityError("capability name must be non-empty")
    _REGISTRY[cap.name] = cap
    return cap


def contains(name: str) -> bool:
    """Whether a capability is currently registered."""
    return name in _REGISTRY


def get(name: str) -> Capability:
    """Resolve a capability by name; raise :class:`CapabilityError` if absent."""
    cap = _REGISTRY.get(name)
    if cap is None:
        raise CapabilityError(f"unknown capability: {name!r}")
    return cap


def resolve(name: str) -> Capability:
    """Alias of :func:`get` (ShotSpec-style naming)."""
    return get(name)


def list_capabilities(
    kind: str | None = None, aspect: str | None = None
) -> list[Capability]:
    """Enumerate registered capabilities, optionally filtered by kind/aspect."""
    out: list[Capability] = []
    for cap in _REGISTRY.values():
        if kind is not None and cap.kind != kind:
            continue
        if aspect is not None and aspect not in cap.aspects:
            continue
        out.append(cap)
    return out


# Public alias matching the contract's ``list(kind=..., aspect=...)`` signature.
list = list_capabilities  # noqa: A001 - intentionally mirrors the contract API.


def Registry() -> dict[str, Capability]:  # noqa: N802 - DDD-style factory per contract.
    """Return the live registry mapping (read-only intent; do not mutate)."""
    return dict(_REGISTRY)


def _summary() -> list[dict[str, Any]]:
    """Machine-readable inventory for the API capability listing."""
    return [
        {
            "name": c.name,
            "kind": c.kind,
            "aspects": c.aspects,
            "line": c.line,
            "cpu_cost_hint": c.cpu_cost_hint,
            "description": c.description,
        }
        for c in _REGISTRY.values()
    ]


def export_catalogue(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Write ``docs/generated/capability_catalogue.json`` and return it."""
    data = _summary()
    if path is None:
        path = Path(__file__).resolve().parents[2] / "docs" / "generated" / "capability_catalogue.json"
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


# ---------------------------------------------------------------------------
# Kids / anime safety capabilities (merged from feat/kids-manifest)
#
# These expose the 2–6 岁幼儿 safety gates as first-class capabilities so any
# product line (and the ShotSpec workbench) can run them by dotted name.
# ``hevi.quality.kids_gate`` / ``hevi.kids.story_gate`` /
# ``hevi.kids.consistency_manifest`` stay the single authority for the checks.
# ---------------------------------------------------------------------------

from hevi.quality.kids_gate import kids_gate_workflow  # noqa: E402
from hevi.kids.story_gate import kids_story_gate  # noqa: E402
from hevi.kids.consistency_manifest import validate_manifest  # noqa: E402


def _render_kids_gate(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    """Run the kids anime safety + rhythm gate against a real video."""
    video_path = Path(params.get("video_path", ""))
    srt_path = Path(params.get("srt_path")) if params.get("srt_path") else None
    meta_path = Path(params.get("metadata_path")) if params.get("metadata_path") else None

    report = kids_gate_workflow(
        video_path, srt_path=srt_path, metadata_path=meta_path
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "kids_gate_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return CapabilityResult(
        mp4=str(video_path) if video_path.exists() else None,
        duration_s=duration,
        qa=report,
    )


register(
    Capability(
        name="qa.kids_gate",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={"type": "object"},
        cpu_cost_hint=0.1,
        render=_render_kids_gate,
        description="幼儿动漫安全与节奏质检闸门",
        line="anime",
    )
)


_STORY_GATE_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "story": {
            "type": "object",
            "properties": {
                "logline": {"type": "string"},
                "theme": {"type": "string"},
                "spoken_language": {"type": "string"},
                "fixed_characters": {"type": "array", "items": {"type": "string"}},
                "beats": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string"},
                            "text": {"type": "string"},
                            "emotion": {"type": "string"},
                            "transition": {"type": "string"},
                        },
                        "required": ["kind", "text"],
                    },
                },
            },
            "required": ["beats"],
        },
    },
    "required": ["story"],
}


def _render_kids_story_gate(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    """Validate a kids storyboard against the 6-beat / causal / single-theme gate."""
    from pydantic import ValidationError

    story = params.get("story", {})
    try:
        report = kids_story_gate(story)
        qa = report.to_dict()
    except ValidationError as exc:
        qa = {"status": "FAIL", "findings": [], "metrics": {}, "error": str(exc)}
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "kids_story_gate_report.json"
    report_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(duration_s=duration, qa=qa)


register(
    Capability(
        name="kids.story_gate",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema=_STORY_GATE_PARAMS,
        cpu_cost_hint=0.0,
        render=_render_kids_story_gate,
        description="幼儿故事闸门：6 节拍结构 + 因果转场比 + 单主题 + 固定角色一致性",
        line="anime",
    )
)


_MANIFEST_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "manifest": {"type": "object"},
    },
    "required": ["manifest"],
}


def _render_kids_consistency_manifest(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    """Validate a KidsConsistencyManifest payload (schema + ShotSpec binding)."""
    from pydantic import ValidationError

    manifest = params.get("manifest", {})
    try:
        report = validate_manifest(manifest)
        qa = report.to_dict()
    except ValidationError as exc:
        qa = {"status": "FAIL", "findings": [], "errors": [str(exc)], "error": str(exc)}
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "kids_consistency_manifest_report.json"
    report_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(duration_s=duration, qa=qa)


register(
    Capability(
        name="kids.consistency_manifest",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema=_MANIFEST_PARAMS,
        cpu_cost_hint=0.0,
        render=_render_kids_consistency_manifest,
        description="幼儿一致性清单：schema 校验 + 与 ShotSpec 双向绑定",
        line="anime",
    )
)
