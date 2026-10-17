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
from hevi.quality.kids_gate import kids_gate_workflow, kids_gate_extended
from hevi.kids import manifest_adapter
from hevi.kids import review_sheet as review_sheet_mod
from hevi.kids import render_local
from hevi.kids import annotation_revision
from hevi.director_lens.brief import autofill, DirectorBrief
from hevi.director_lens.gate import director_check_workflow
from hevi.director_lens.render import render_comparison_package
from hevi.director_lens.review import generate_review_html

__all__ = [
    "Capability",
    "CapabilityError",
    "CapabilityResult",
    "register",
    "get",
    "list_capabilities",
    "list",
    "names",
    "resolve",
    "Registry",
    "list_caps",
    "describe",
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
        except jsonschema.ValidationError as exc:
            # ``CapabilityError`` subclasses ``RuntimeError``; it is deliberately
            # *not* a ``ValueError`` so callers cannot swallow it by accident.
            # The message repeats jsonschema's own wording so parameter names
            # (e.g. "format") and rejections ("unsupported") stay greppable.
            raise CapabilityError(
                f"capability {self.name}: invalid params: {exc.message}"
            ) from exc
        except Exception as exc:  # jsonschema.SchemaError and friends.
            raise CapabilityError(
                f"capability {self.name}: invalid params: {exc}"
            ) from exc
        return params

    def supports_aspect(self, aspect: str) -> bool:
        return aspect in self.aspects

    def render_safe(
        self,
        params: dict[str, Any],
        out_dir: str | Path,
        *,
        duration: float = 5.0,
        aspect: str = "16:9",
        seed: int = 42,
    ) -> "CapabilityResult":
        """Contract-v1 entry point: validate params, then render."""
        return render_safe(
            self, params, out_dir, duration=duration, aspect=aspect, seed=seed
        )


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
# ``list_caps`` is the name the CAPABILITY_CONTRACT v1 registry uses; keep both so
# the huobao line (and its tests) can import either spelling.
list_caps = list_capabilities


def names() -> list[str]:
    """Return all registered capability names in stable sorted order."""
    return sorted(_REGISTRY.keys())


def Registry() -> dict[str, Capability]:  # noqa: N802 - DDD-style factory per contract.
    """Return the live registry mapping (read-only intent; do not mutate)."""
    return dict(_REGISTRY)


def describe() -> list[dict[str, Any]]:
    """Contract-v1 description of every registered capability (JSON-ready)."""
    return [
        {
            "name": c.name,
            "kind": c.kind,
            "aspects": c.aspects,
            "cpu_cost_hint": c.cpu_cost_hint,
            "params_schema": c.params_schema,
            "description": c.description,
        }
        for c in _REGISTRY.values()
    ]


def render_safe(
    cap: "Capability",
    params: dict[str, Any],
    out_dir: str | Path,
    *,
    duration: float = 5.0,
    aspect: str = "16:9",
    seed: int = 42,
) -> "CapabilityResult":
    """Validate ``params`` then render ``cap``; never returns a fake success.

    Contract-v1 callers (the huobao preview endpoint) expect validation to run
    before the renderer, and expect a non-``CapabilityResult`` return to be an
    error rather than a silently-accepted value.
    """
    cap.validate_params(params)
    result = cap.render(
        params, Path(out_dir), duration=duration, aspect=aspect, seed=seed
    )
    if not isinstance(result, CapabilityResult):
        raise CapabilityError(
            f"capability {cap.name}: render must return CapabilityResult, "
            f"got {type(result).__name__}"
        )
    return result


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
# agent.ops_bridge (merged from feat/agent-ops)
#
# Exposes the Agent canvas operation bridge (read + CAS/idempotent write +
# paid-propose gate) as a first-class capability.  ``hevi.operations`` remains
# the single authority for the operations and the CAS/idempotency rules.
# ---------------------------------------------------------------------------

import hashlib  # noqa: E402
import subprocess  # noqa: E402

from hevi.operations.bridge import (  # noqa: E402
    OperationBridge,
    OperationError,
    SqliteOperationsStore,
)
from hevi.operations.registry import list_operations as _list_operations  # noqa: E402
from hevi.renderers.ffmpeg import resolve_ffmpeg_bin  # noqa: E402


class _OperationCapabilityResult(CapabilityResult):
    """Capability result that also carries the operation inventory."""

    def __init__(self, **kwargs: Any) -> None:
        operations = kwargs.pop("operations", [])
        super().__init__(**kwargs)
        self.operations = operations


def _render_ops_bridge(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    ops = [d.to_dict() for d in _list_operations()]
    report_file = out_path / "ops_bridge_inventory.json"
    report_file.write_text(json.dumps(ops, ensure_ascii=False, indent=2), encoding="utf-8")

    op_receipt: dict[str, Any] = {}
    op_name = params.get("operation")
    if op_name:
        import asyncio

        db_path = params.get("db_path", "data/agent_ops.db")
        bridge = SqliteOperationsStore(db_path)
        br = OperationBridge(bridge, read_only=(params.get("mode") == "read-only"))
        try:
            op_params = params.get("params", {})
            op_id = params.get("opId")
            if params.get("expectedRevision") is not None:
                op_params.setdefault("expectedRevision", params["expectedRevision"])
            op_receipt = asyncio.run(br.execute(op_name, op_params, op_id=op_id))
        except OperationError as exc:
            op_receipt = {"operation": op_name, "error": exc.code, "detail": exc.detail}
        except Exception as exc:
            op_receipt = {"operation": op_name, "error": "execution_failed", "detail": str(exc)}
        (out_path / "ops_receipt.json").write_text(
            json.dumps(op_receipt, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    mp4_file: Path | None = None
    sha256_val = ""
    dur = float(duration) if duration > 0 else 2.0

    # 2 秒预览产物（lavfi 纯 CPU 合成：无云 API / 零网络）
    res = "320x568" if aspect == "9:16" else "568x320"
    mp4_path = out_path / "ops_bridge_preview.mp4"
    ffmpeg_bin = resolve_ffmpeg_bin()
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=indigo:s={res}:d={dur}:rate=24",
        "-f",
        "lavfi",
        "-i",
        f"sine=f=440:r=48000:d={dur}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(mp4_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    sha256_val = hashlib.sha256(mp4_path.read_bytes()).hexdigest()
    mp4_file = mp4_path

    result = _OperationCapabilityResult(
        mp4=str(mp4_file),
        duration_s=dur,
        sha256=sha256_val,
        operations=ops,
        qa={
            "count": len(ops),
            "names": [o["name"] for o in ops],
            "report_file": str(report_file),
            "op_receipt": op_receipt,
        },
    )
    return result


register(
    Capability(
        name="agent.ops_bridge",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "properties": {
                "operation": {"type": "string"},
                "opId": {"type": "string"},
                "expectedRevision": {"type": "integer"},
                "mode": {"type": "string", "enum": ["read-only", "write"]},
                "db_path": {"type": "string"},
                "params": {"type": "object"},
                "format": {"type": "string", "enum": ["summary", "preview"]},
            },
            "additionalProperties": False,
        },
        cpu_cost_hint=0.05,
        render=_render_ops_bridge,
        description="Agent 画布操作桥：只读 + 写(CAS/幂等) + 付费 propose 闸",
        line="agent",
    )
)


# ---------------------------------------------------------------------------
# Kids / anime safety capabilities (merged from feat/kids-manifest,
# feat/review-sheet and feat/agent-ops).
#
# These expose the 2–6 岁幼儿 safety gates as first-class capabilities so any
# product line (and the ShotSpec workbench) can run them by dotted name.
# ``hevi.quality.kids_gate`` / ``hevi.kids.story_gate`` /
# ``hevi.kids.consistency_manifest`` stay the single authority for the checks.
# ---------------------------------------------------------------------------

from hevi.kids.consistency_manifest import validate_manifest  # noqa: E402
from hevi.kids.story_gate import kids_story_gate  # noqa: E402
from hevi.quality.kids_gate import kids_gate_workflow  # noqa: E402


def _render_kids_gate(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    """Run the kids anime safety + rhythm gate against a real video."""
    video_path = Path(params.get("video_path", ""))
    srt_path = Path(params.get("srt_path")) if params.get("srt_path") else None
    meta_path = Path(params.get("metadata_path")) if params.get("metadata_path") else None

    report = kids_gate_workflow(video_path, srt_path=srt_path, metadata_path=meta_path)
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


def _render_kids_gate_extended(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    video_path = Path(params.get("video_path", ""))
    srt_path = Path(params.get("srt_path")) if params.get("srt_path") else None
    meta_path = Path(params.get("metadata_path")) if params.get("metadata_path") else None
    manifest_path = params.get("manifest_path")
    manifest = manifest_adapter.load_manifest(manifest_path) if manifest_path else None
    report = kids_gate_extended(video_path, srt_path=srt_path, metadata_path=meta_path, manifest=manifest)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "kids_gate_extended_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        mp4=str(video_path) if video_path.exists() else None,
        duration_s=duration,
        qa=report,
    )


register(
    Capability(
        name="qa.kids_gate.extended",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={"type": "object"},
        cpu_cost_hint=0.2,
        render=_render_kids_gate_extended,
        description="幼儿动漫安全与节奏质检闸门 + §3.6 续作 QC（连续性/调色/转场/口语语言）",
        line="anime",
    )
)


def _render_review_sheet(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    manifest_path = params.get("manifest_path")
    if not manifest_path:
        raise RuntimeError("review_sheet 需要 manifest_path")
    manifest = manifest_adapter.load_manifest(manifest_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = review_sheet_mod.render_both_aspects(manifest, out_dir, base_name=params.get("base_name", "review_sheet"))
    shas = {a: review_sheet_mod.review_sheet_sha256(p) for a, p in paths.items()}
    return CapabilityResult(
        png=str(paths.get(aspect, next(iter(paths.values())))),
        duration_s=duration,
        qa={"paths": {a: str(p) for a, p in paths.items()}, "sha256": shas},
    )


register(
    Capability(
        name="kids.review_sheet",
        kind="overlay",
        aspects=["16:9", "9:16"],
        params_schema={"type": "object", "required": ["manifest_path"]},
        cpu_cost_hint=0.5,
        render=_render_review_sheet,
        description="分镜审稿表网格 PNG 渲染（每格镜号/时长/台词/机位/景别/缩略图）",
        line="anime",
    )
)


def _render_local_episode(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    manifest_path = params.get("manifest_path")
    if not manifest_path:
        raise RuntimeError("render_local 需要 manifest_path")
    manifest = manifest_adapter.load_manifest(manifest_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    w, h = (720, 1280) if aspect == "9:16" else (1280, 720)
    out = out_dir / "local_episode.mp4"
    info = render_local.render_episode(manifest, out, seed=seed, width=w, height=h)
    return CapabilityResult(
        mp4=str(out), duration_s=info["total_duration"], sha256=info["sha256"], qa=info,
    )


register(
    Capability(
        name="kids.render_local",
        kind="shot",
        aspects=["16:9", "9:16"],
        params_schema={"type": "object", "required": ["manifest_path"]},
        cpu_cost_hint=2.0,
        render=_render_local_episode,
        description="本地 CPU 渲染试点片（真实 ffmpeg，无付费 API，确定性可复现）",
        line="anime",
    )
)


def _render_annotation_patch(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    """从标注请求构建确定性 ShotSpecPatch（注册点，便于产线按名调用）。"""
    manifest_path = params.get("manifest_path")
    ann = params.get("annotation") or {}
    if not manifest_path:
        raise RuntimeError("annotation_revision 需要 manifest_path")
    manifest = manifest_adapter.load_manifest(manifest_path)
    shot_index = int(ann.get("shot_index", 0))
    marks = [
        annotation_revision.AnnotationMark(
            kind=m["kind"], nx=float(m["nx"]), ny=float(m["ny"]),
            nw=float(m.get("nw", 0.0)), nh=float(m.get("nh", 0.0)),
            direction=m.get("direction"), note=m.get("note"),
        )
        for m in ann.get("marks", [])
    ]
    inp = annotation_revision.AnnotationInput(
        shot_index=shot_index,
        from_revision=int(ann.get("from_revision", 0)),
        marks=marks,
        source_time_ms=[float(t) for t in ann.get("source_time_ms", [])],
        authoritative_source=ann.get("authoritative_source"),
    )
    patch = annotation_revision.build_patch(manifest, inp)
    out_dir.mkdir(parents=True, exist_ok=True)
    patch_path = out_dir / f"patch_S{shot_index}.json"
    patch_path.write_text(json.dumps(patch.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        png=None, duration_s=duration, sha256=patch.sha256(),
        qa={"patch": patch.to_dict(), "path": str(patch_path)},
    )


register(
    Capability(
        name="kids.annotation_revision",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={"type": "object", "required": ["manifest_path"]},
        cpu_cost_hint=0.1,
        render=_render_annotation_patch,
        description="帧标注 → 确定性 ShotSpecPatch（§3.5 映射）",
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

# Anatomy explainer capability (merged from feat/anatomy-explainer).  Importing
# the module registers ``anatomy.explainer`` via this same registry.
import hevi.capabilities.anatomy_explainer  # noqa: E402,F401


# ── Director Lens Capabilities ──

def _render_director_brief(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    prompt = params.get("prompt", "小球学弹跳")
    line = params.get("line", "explainer")
    brief = autofill(prompt, line=line, duration_s=duration, aspect=aspect, seed=seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{brief.id}.json"
    brief.save(p)
    return CapabilityResult(
        mp4=None,
        duration_s=duration,
        qa={"brief_id": brief.id, "path": str(p), "status": "success"}
    )


register(Capability(
    name="director_brief",
    kind="shot",
    aspects=["16:9", "9:16", "1:1"],
    params_schema={"type": "object"},
    cpu_cost_hint=0.05,
    render=_render_director_brief,
    description="线路无关的 DirectorBrief 生成与自动补全",
    line="director"
))


def _render_director_check(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    brief_path = params.get("brief_path")
    if brief_path and Path(brief_path).exists():
        brief = DirectorBrief.load(brief_path)
    else:
        brief = autofill(params.get("prompt", "小球学弹跳"), line=params.get("line", "explainer"), duration_s=duration, aspect=aspect, seed=seed)
    report = director_check_workflow(brief, video_path=params.get("video_path"))
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "director_check_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=duration,
        qa=report
    )


register(Capability(
    name="director_check",
    kind="line",
    aspects=["16:9", "9:16", "1:1"],
    params_schema={"type": "object"},
    cpu_cost_hint=0.1,
    render=_render_director_check,
    description="全线通用的出片前自检闸门 (PPT同步/静止冻结/拍点对齐/声画对齐等)",
    line="director"
))


def _render_motion_director(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    prompt = params.get("prompt", "小球学弹跳")
    line = params.get("line", "explainer")
    brief = autofill(prompt, line=line, duration_s=duration, aspect=aspect, seed=seed)
    comparison = render_comparison_package(brief, out_dir)
    html_path = generate_review_html(brief, comparison, out_dir / f"{brief.id}_review.html")
    return CapabilityResult(
        mp4=comparison["director_version"]["mp4"],
        duration_s=duration,
        sha256=comparison["director_version"]["sha256"],
        qa={"comparison": comparison, "review_html": str(html_path)}
    )


register(Capability(
    name="motion_director",
    kind="shot",
    aspects=["16:9", "9:16", "1:1"],
    params_schema={"type": "object"},
    cpu_cost_hint=0.5,
    render=_render_motion_director,
    description="动效导演层完整渲染 pipeline (导演版 vs 基线版 + 逐帧审片 HTML)",
    line="director"
))


# ── StoryPlan capabilities (merged from feat/story-plan, GOLIVE-1016 B) ──
# The branch shipped its own private Capability/_REGISTRY inside
# hevi/storyplan/capabilities.py, so these three never reached the unified
# registry and were therefore invisible to GET /api/capabilities and to
# ShotSpec.  Re-declare them here against the canonical Capability type so all
# lines resolve them through get()/resolve() like every other capability.
# The private module registry is left untouched (its own tests still pass).
def _render_story_plan(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.storyplan.autofill import autofill_story_plan

    topic = str(params.get("topic", "小水滴去哪儿了"))
    plan = autofill_story_plan(topic, aspect=aspect)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "story_plan.json").write_text(
        plan.model_dump_json(indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=float(plan.duration_sec),
        qa={"status": "succeeded"},
    )


def _render_story_check(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.storyplan.autofill import autofill_story_plan
    from hevi.storyplan.check import run_story_check
    from hevi.storyplan.model import StoryPlan

    plan_data = params.get("plan")
    if isinstance(plan_data, dict):
        plan = StoryPlan(**plan_data)
    else:
        plan = autofill_story_plan("小水滴去哪儿了", aspect=aspect)
    report = run_story_check(plan)
    return CapabilityResult(
        duration_s=float(plan.duration_sec),
        qa={"passed": bool(report.passed)},
    )


def _render_take_select(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.storyplan.take_select import TakeCandidate, select_best_take

    raw = params.get(
        "candidates",
        [{"take_id": "t1", "video_path": "dummy.mp4", "duration_sec": 5.0}],
    )
    for c in raw:
        if not isinstance(c, dict) or "take_id" not in c or "video_path" not in c:
            raise CapabilityError(
                "take_select: each candidate must be a dict with take_id and video_path"
            )
    cands = [TakeCandidate(**c) for c in raw]
    criteria = str(params.get("acceptance_criteria", "验收点通过"))
    best, all_res = select_best_take(cands, criteria)
    return CapabilityResult(
        duration_s=duration,
        qa={"selected": best.take_id},
    )


def _render_storyplan_critique(
    params: dict[str, Any], out_dir: Path, *, duration: float = 0.0, aspect: str = "16:9", seed: int = 0
) -> CapabilityResult:
    from hevi.storyplan.critique import render_storyplan_critique

    return render_storyplan_critique(params, out_dir, duration=duration, aspect=aspect, seed=seed)


def _render_storyboard_preview_sheet(
    params: dict[str, Any], out_dir: Path, *, duration: float = 0.0, aspect: str = "16:9", seed: int = 0
) -> CapabilityResult:
    from hevi.storyplan.preview_sheet import render_preview_sheet_capability

    return render_preview_sheet_capability(params, out_dir, duration=duration, aspect=aspect, seed=seed)


def _render_transitions_storybook(
    params: dict[str, Any], out_dir: Path, *, duration: float = 1.0, aspect: str = "16:9", seed: int = 0
) -> CapabilityResult:
    from hevi.motion_fx.transitions.storybook import render_transitions_storybook_capability

    return render_transitions_storybook_capability(params, out_dir, duration=duration, aspect=aspect, seed=seed)


def _render_storybook_voice_align(
    params: dict[str, Any], out_dir: Path, *, duration: float = 0.0, aspect: str = "16:9", seed: int = 0
) -> CapabilityResult:
    from hevi.audio.storybook_voice import render_storybook_voice_align_capability

    return render_storybook_voice_align_capability(params, out_dir, duration=duration, aspect=aspect, seed=seed)


_STORYPLAN_ASPECTS = ["16:9", "9:16", "1:1"]

register(Capability(
    name="story_plan",
    kind="shot",
    aspects=_STORYPLAN_ASPECTS,
    params_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {"topic": {"type": "string"}},
    },
    cpu_cost_hint=0.1,
    render=_render_story_plan,
    description="一句话自动补全叙事/分镜/时间线三层结构 StoryPlan",
    line="storyplan",
))

register(Capability(
    name="story_check",
    kind="shot",
    aspects=_STORYPLAN_ASPECTS,
    params_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {"plan": {"type": "object"}},
    },
    cpu_cost_hint=0.1,
    render=_render_story_check,
    description="StoryPlan 结构自检门 (钩子、声画对齐、冗余、六项必填、闭环、幼儿安全)",
    line="storyplan",
))

register(Capability(
    name="take_select",
    kind="shot",
    aspects=_STORYPLAN_ASPECTS,
    params_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "candidates": {"type": "array"},
            "acceptance_criteria": {"type": "string"},
        },
    },
    cpu_cost_hint=0.1,
    render=_render_take_select,
    description="选段器 take_select：多候选 take 按帧评分与子区间选中",
    line="storyplan",
))

register(Capability(
    name="storyplan.critique",
    kind="shot",
    aspects=_STORYPLAN_ASPECTS,
    params_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "plan": {"type": "object"},
            "topic": {"type": "string"},
            "auto_revise": {"type": "boolean"},
        },
    },
    cpu_cost_hint=0.2,
    render=_render_storyplan_critique,
    description="剧本自审轮：挑剔观众+动画导演双重视角批判与自动修订",
    line="storyplan",
))

register(Capability(
    name="storyboard.preview_sheet",
    kind="shot",
    aspects=["16:9", "9:16"],
    params_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "shots": {"type": "array"},
            "shot_groups": {"type": "array"},
            "plan": {"type": "object"},
            "topic": {"type": "string"},
            "aspect": {"type": "string"},
        },
    },
    cpu_cost_hint=0.3,
    render=_render_storyboard_preview_sheet,
    description="分镜预览图：按镜头组生成漫画格分镜表（景别远中特、画面描述、台词，铅笔线淡彩风格）",
    line="storyplan",
))

register(Capability(
    name="transitions.storybook",
    kind="transition",
    aspects=["16:9", "9:16", "1:1"],
    params_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "transition_type": {
                "type": "string",
                "enum": ["page_flip", "wet_brush", "torn_paper", "pencil_sketch", "watercolor_bloom"],
            },
            "clip_a": {"type": "string"},
            "clip_b": {"type": "string"},
            "duration": {"type": "number"},
            "fps": {"type": "number"},
            "params": {"type": "object"},
        },
    },
    cpu_cost_hint=2.0,
    render=_render_transitions_storybook,
    description="绘本转场：翻页、湿笔刷晕开、纸页撕裂、铅笔线自绘、水彩晕染",
    line="handdraw",
))

register(Capability(
    name="storybook.voice_align",
    kind="audio",
    aspects=["16:9", "9:16", "1:1"],
    params_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "script": {"type": "array"},
            "bgm_style": {"type": "string"},
            "quiet_break_s": {"type": "number"},
            "pre_pad_s": {"type": "number"},
            "post_pad_s": {"type": "number"},
        },
    },
    cpu_cost_hint=2.0,
    render=_render_storybook_voice_align,
    description="绘本配音对齐：按本地TTS实际时长重排镜头，双语字幕逐句对齐(<150ms)，旁白角色多音色语气，BGM避让留白",
    line="audio",
))
