"""Material pack -> canvas mapping (``hevi.canvas.material_pack``).

A 5-minute film's material pack, as produced by
``pipeline.stable_film_assembly`` (manifest + delivery note), mapped
onto the infinite canvas so every segment is visible, its prompt is
the node's core data, and a human can edit that prompt and send only
the edited segment back through the gates for regeneration.

Fact source discipline (this module invents no second source of
truth): the pack is normalised from the stable-film manifest's own
fields (``segment_plan`` segments, ``gates``, ``pending_material``,
``delivery_note``, ``status``) plus, when the caller supplies them,
compiled prompts from ``story.prompt_compiler``. A field the
material pack does not carry is recorded in ``missing_fields`` --
never guessed, never filled with a placeholder. In particular a
manifest-only pack has no compiled prompt: the segment node's
``prompt`` is then the shots' narration text verbatim
(``prompt_source == "manifest_narration"``) and the compiled fields
(negative list / easing / fallbacks / reference numbers) are listed
missing until a compiled prompt is supplied.

Method provenance (ideas only, no text or code copied): the
reference-number stability rule and the "adopt writes a new version,
old version retained" rule follow the method described in
``~/workspace/hevi-vs-yingce.md`` section 1.3 / section 4 P0-5
(reference numbers stay stable when a model cannot use a reference;
a canvas edit is written back to the fact source as a new version).
All gates reused here are hevi's own: ``story.prompt_compiler``,
``video.segment_assembly_gate``, ``qa.reference_number_gate``,
``story.asset_registry_v2`` (pending-material check),
``pipeline.spend_brake`` and the canvas ``preflight``.

Mapping rules
-------------
* One ``segment`` canvas node per pack segment, in pack order.
  Node id is the segment id (stable across remaps).
* One ``asset`` canvas node per master asset (one master per
  asset id, single version; a duplicate id with a different
  version is an error, never silently merged).
* Continuation edges (segment -> segment) express "this segment's
  tail frame is the next segment's first frame". The edge is
  ``connected`` only when the previous segment carries a tail-frame
  reference; otherwise it is ``pending`` -- a missing tail frame is
  never claimed to be connected.
* Reference edges (asset -> segment) express "this segment
  references this asset". Reference numbers are stored verbatim and
  are never renumbered by this module, including when a model
  cannot use a reference: the gap is recorded, the numbers stay.
* Remapping is idempotent: the same pack remapped onto its own
  graph neither duplicates nodes nor overwrites a newer human edit.
  A pack revision older than a node's stored revision never
  overwrites it; a human edit (dirty) at the same revision keeps
  its prompt. Only a newer pack revision adopts new fact-source
  values, and then the superseded prompt is appended to the node's
  prompt history.
* A human edit marks the edited segment dirty + pending review and
  marks every downstream segment pending review. Downstream
  prompts and results are untouched: an upstream change only flags
  affected downstream, it never rewrites them.
* Regeneration is single-segment only. It requires the prompt
  compiler gate (segment fields, or the full episode gate when a
  beat-schema episode is supplied) and the segment assembly gate
  to pass, plus preflight and the spend brake for paid segments.
  A refused regeneration returns ``status == "refused"`` with
  blockers; it never runs generation. Free code-frame segments
  (estimated cost 0) skip the spend brake; a paid segment without
  strict ``confirmed is True`` is refused. Adoption writes the
  edited prompt back to the pack as a new version (revision + 1,
  old version retained); an unadopted edit is never written back.

This module is pure except for ``request_regeneration``'s optional
executor argument (supplied by the caller, e.g. the canvas API
route delegating to ``ExecutorService``). It makes no network or
generation calls itself and never calls a video model directly:
real video-model regeneration is a caller decision that needs
Soffy's key and budget approval, and is not run by this module.
"""

from __future__ import annotations

import copy
from typing import Any

__all__ = [
    "MATERIAL_PACK_STATUSES",
    "MaterialPackError",
    "adopt_segment_edit",
    "apply_segment_edit",
    "check_regeneration_gates",
    "graph_segment_order",
    "map_to_graph",
    "normalize_material_pack",
    "request_regeneration",
]


class MaterialPackError(ValueError):
    """The pack, graph or edit cannot be honoured as stated. Never silent."""


MATERIAL_PACK_STATUSES = ("done", "pending-material", "partial")

_SEGMENT_STATUSES = frozenset(MATERIAL_PACK_STATUSES)

# Fields a human may edit on a canvas segment node. Anything else in
# a patch is rejected rather than silently stored.
_EDITABLE_FIELDS = (
    "prompt",
    "negative_prompts",
    "duration_sec",
    "reference_numbers",
    "easing",
    "fallbacks",
    "first_frame_ref",
)

_COMPILED_FIELDS = (
    "negative_prompts",
    "easing",
    "fallbacks",
    "reference_numbers",
    "reference_order",
    "first_frame_ref",
    "tail_frame_ref",
    "asset_version",
)


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_str_list(value: Any, what: str) -> list[str]:
    if not isinstance(value, list):
        raise MaterialPackError(f"material pack: {what} must be a list")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise MaterialPackError(
                f"material pack: every {what} item must be a non-empty string"
            )
        out.append(str(item))
    return out


def _as_int_list(value: Any, what: str) -> list[int]:
    if not isinstance(value, list):
        raise MaterialPackError(f"material pack: {what} must be a list")
    out: list[int] = []
    for item in value:
        if not isinstance(item, int) or isinstance(item, bool) or item < 1:
            raise MaterialPackError(
                f"material pack: every {what} item must be a positive integer"
            )
        if item in out:
            raise MaterialPackError(
                f"material pack: {what} lists number {item} twice; "
                "numbers would be ambiguous"
            )
        out.append(item)
    return out


def _segment_status_from_evidence(
    segment: dict[str, Any],
    *,
    pending_shot_ids: set[str],
    generation_shot_ids: set[str],
) -> tuple[str, bool]:
    """Derive a segment status from manifest evidence lists.

    Returns (status, evidence_present). Explicit segment status wins
    over derivation; see :func:`normalize_material_pack`.
    """
    shot_ids = [str(s) for s in segment.get("shot_ids", [])]
    if not shot_ids:
        return "partial", False
    if any(s in pending_shot_ids for s in shot_ids):
        return "pending-material", True
    if generation_shot_ids:
        if all(s in generation_shot_ids for s in shot_ids):
            return "done", True
        if any(s in generation_shot_ids for s in shot_ids):
            return "partial", True
        return "partial", True
    return "partial", False


def _normalize_shots(raw_segment: dict[str, Any]) -> list[dict[str, Any]]:
    shots: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_segment.get("shots") or []):
        if not isinstance(raw, dict):
            raise MaterialPackError(
                "material pack: every shot must be an object"
            )
        shot_id = raw.get("shot_id") or f"shot-{index + 1}"
        text = raw.get("text") or raw.get("line") or ""
        duration = raw.get("duration_sec")
        shots.append(
            {
                "shot_id": str(shot_id),
                "scene_id": str(raw.get("scene_id") or ""),
                "text": str(text),
                "duration_sec": float(duration) if _is_num(duration) else None,
            }
        )
    return shots


def _normalize_segment(
    raw: dict[str, Any],
    *,
    pending_shot_ids: set[str],
    generation_shot_ids: set[str],
    pack_reference_order: list[str] | None,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise MaterialPackError("material pack: every segment must be an object")
    segment_id = raw.get("segment_id") or raw.get("generation_node") or raw.get("id")
    if not isinstance(segment_id, str) or not segment_id:
        raise MaterialPackError(
            "material pack: every segment needs a non-empty segment_id"
        )
    missing: list[str] = []
    shots = _normalize_shots(raw)
    shot_ids = [s["shot_id"] for s in shots]
    if not shot_ids:
        for sid in raw.get("shot_ids") or []:
            shot_ids.append(str(sid))
    duration = raw.get("duration_sec")
    if _is_num(duration):
        duration_sec: float | None = float(duration)
    elif shots and all(s["duration_sec"] is not None for s in shots):
        duration_sec = round(sum(float(s["duration_sec"]) for s in shots), 3)
    else:
        duration_sec = None
        missing.append("duration_sec")
    narration = raw.get("narration") or raw.get("text") or ""
    if not narration and shots:
        narration = "\n".join(s["text"] for s in shots if s["text"])
    narration = str(narration)

    compiled = raw.get("compiled_prompt")
    if compiled is not None and not isinstance(compiled, dict):
        raise MaterialPackError(
            f"material pack: segment {segment_id!r} compiled_prompt must be an object"
        )
    compiled = compiled or {}
    prompt_source: str
    prompt: str
    if isinstance(compiled.get("prompt"), str) and compiled["prompt"].strip():
        prompt = str(compiled["prompt"])
        prompt_source = "compiled"
    elif isinstance(raw.get("prompt"), str) and raw["prompt"].strip():
        prompt = str(raw["prompt"])
        prompt_source = "supplied"
    elif narration:
        prompt = narration
        prompt_source = "manifest_narration"
    else:
        prompt = ""
        prompt_source = "missing"
        missing.append("prompt")

    def _compiled_field(name: str) -> Any:
        if name in compiled:
            return compiled[name]
        return raw.get(name)

    negative_prompts: list[str] = []
    raw_neg = _compiled_field("negative_prompts")
    if raw_neg is not None:
        negative_prompts = _as_str_list(raw_neg, "negative_prompts")
    else:
        missing.append("negative_prompts")
    easing = _compiled_field("easing")
    if easing is None:
        missing.append("easing")
    elif not isinstance(easing, str) or not easing:
        raise MaterialPackError(
            f"material pack: segment {segment_id!r} easing must be a non-empty string"
        )
    fallbacks: list[dict[str, Any]] = []
    raw_fb = _compiled_field("fallbacks")
    if raw_fb is not None:
        if not isinstance(raw_fb, list):
            raise MaterialPackError(
                f"material pack: segment {segment_id!r} fallbacks must be a list"
            )
        for item in raw_fb:
            if not isinstance(item, dict) or not item.get("trigger") or not item.get(
                "replacement"
            ):
                raise MaterialPackError(
                    f"material pack: segment {segment_id!r} every fallback needs "
                    "trigger and replacement strings"
                )
            fallbacks.append(
                {"trigger": str(item["trigger"]), "replacement": str(item["replacement"])}
            )
    else:
        missing.append("fallbacks")
    reference_numbers: list[int] = []
    raw_refs = _compiled_field("reference_numbers")
    if raw_refs is not None:
        reference_numbers = _as_int_list(raw_refs, "reference_numbers")
    else:
        missing.append("reference_numbers")
    reference_order = _compiled_field("reference_order") or pack_reference_order
    if reference_order is not None:
        if not isinstance(reference_order, list) or not reference_order:
            raise MaterialPackError(
                f"material pack: segment {segment_id!r} reference_order must be "
                "a non-empty list of asset ids"
            )
        reference_order = [str(a) for a in reference_order]
    else:
        missing.append("reference_order")
    first_frame_ref = _compiled_field("first_frame_ref") or _compiled_field(
        "first_frame"
    ) or _compiled_field("first_frame_thumbnail")
    if first_frame_ref is None:
        missing.append("first_frame_ref")
    elif not isinstance(first_frame_ref, str) or not first_frame_ref:
        raise MaterialPackError(
            f"material pack: segment {segment_id!r} first_frame_ref must be "
            "a non-empty string"
        )
    tail_frame_ref = _compiled_field("tail_frame_ref") or _compiled_field("tail_frame")
    if tail_frame_ref is None:
        missing.append("tail_frame_ref")
    elif not isinstance(tail_frame_ref, str) or not tail_frame_ref:
        raise MaterialPackError(
            f"material pack: segment {segment_id!r} tail_frame_ref must be "
            "a non-empty string"
        )
    asset_version = _compiled_field("asset_version")
    if asset_version is None:
        missing.append("asset_version")
    elif not isinstance(asset_version, (str, int)):
        raise MaterialPackError(
            f"material pack: segment {segment_id!r} asset_version must be "
            "a string or integer"
        )
    asset_ids: list[str] = []
    for key in ("asset_ids", "scene_ids"):
        for item in raw.get(key) or []:
            item = str(item)
            if item and item not in asset_ids:
                asset_ids.append(item)
    explicit_status = raw.get("status")
    if explicit_status is not None:
        if explicit_status not in _SEGMENT_STATUSES:
            raise MaterialPackError(
                f"material pack: segment {segment_id!r} status {explicit_status!r} "
                f"is unknown; known: {list(MATERIAL_PACK_STATUSES)}"
            )
        status = str(explicit_status)
    else:
        status, evidence = _segment_status_from_evidence(
            {"shot_ids": shot_ids},
            pending_shot_ids=pending_shot_ids,
            generation_shot_ids=generation_shot_ids,
        )
        if not evidence:
            missing.append("status_evidence")
    revision = raw.get("revision")
    if revision is None:
        revision = 1
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise MaterialPackError(
            f"material pack: segment {segment_id!r} revision must be a positive integer"
        )
    versions = raw.get("versions")
    if versions is not None and not isinstance(versions, list):
        raise MaterialPackError(
            f"material pack: segment {segment_id!r} versions must be a list"
        )
    provider = raw.get("provider") or compiled.get("provider")
    return {
        "segment_id": segment_id,
        "duration_sec": duration_sec,
        "narration": narration,
        "prompt": prompt,
        "prompt_source": prompt_source,
        "negative_prompts": negative_prompts,
        "easing": easing,
        "fallbacks": fallbacks,
        "reference_numbers": reference_numbers,
        "reference_order": reference_order,
        "first_frame_ref": first_frame_ref,
        "tail_frame_ref": tail_frame_ref,
        "asset_version": asset_version,
        "asset_ids": asset_ids,
        "shot_ids": shot_ids,
        "shots": shots,
        "status": status,
        "revision": revision,
        "versions": copy.deepcopy(versions or []),
        "provider": str(provider) if provider else None,
        "compiler_episode": copy.deepcopy(raw.get("compiler_episode"))
        if isinstance(raw.get("compiler_episode"), dict)
        else None,
        "missing_fields": sorted(set(missing)),
        "gate_badges": [],
    }


def _normalize_assets(
    raw_assets: Any,
    segments: list[dict[str, Any]],
    *,
    pending_material: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    assets: dict[str, dict[str, Any]] = {}

    def _add(asset_id: str, *, kind: str | None, version: Any, status: str,
             missing: list[str], name: str | None = None) -> None:
        if asset_id in assets:
            existing = assets[asset_id]
            if version is not None and existing.get("version") is not None \
                    and existing["version"] != version:
                raise MaterialPackError(
                    f"material pack: asset {asset_id!r} has two versions "
                    f"({existing['version']!r} and {version!r}); one asset "
                    "has one master version, never two"
                )
            if version is not None:
                existing["version"] = version
                existing["missing_fields"] = [
                    f for f in existing["missing_fields"] if f != "version"
                ]
            return
        entry_missing = list(missing)
        if version is None and "version" not in entry_missing:
            entry_missing.append("version")
        if kind is None and "kind" not in entry_missing:
            entry_missing.append("kind")
        assets[asset_id] = {
            "asset_id": asset_id,
            "kind": kind or "unknown",
            "name": name or asset_id,
            "version": version,
            "status": status,
            "missing_fields": sorted(set(entry_missing)),
        }

    if raw_assets is not None:
        if not isinstance(raw_assets, list):
            raise MaterialPackError("material pack: assets must be a list")
        for raw in raw_assets:
            if not isinstance(raw, dict) or not raw.get("asset_id"):
                raise MaterialPackError(
                    "material pack: every asset needs a non-empty asset_id"
                )
            status = raw.get("status") or "done"
            if status not in _SEGMENT_STATUSES:
                raise MaterialPackError(
                    f"material pack: asset {raw['asset_id']!r} status "
                    f"{status!r} is unknown"
                )
            _add(
                str(raw["asset_id"]),
                kind=raw.get("kind"),
                version=raw.get("version"),
                status=str(status),
                missing=list(raw.get("missing_fields") or []),
                name=raw.get("name"),
            )
    # Manifest evidence: pending-material assets, then scene ids named
    # by segments. Scene assets carry no version claim: the manifest
    # names the scene, it does not state an asset version.
    for item in pending_material:
        if isinstance(item, dict) and item.get("asset_id"):
            _add(
                str(item["asset_id"]),
                kind=None,
                version=None,
                status="pending-material",
                missing=["kind", "version"],
            )
    for segment in segments:
        for asset_id in segment["asset_ids"]:
            _add(
                asset_id,
                kind="scene",
                version=None,
                status="partial",
                missing=["version"],
            )
    return [assets[key] for key in assets]


def normalize_material_pack(raw: Any) -> dict[str, Any]:
    """Normalise a stable-film manifest or an explicit material pack.

    The manifest is the fact source: its ``segment_plan`` segments,
    ``gates``, ``pending_material`` and ``status`` are carried over
    verbatim in meaning. Missing compiled fields are listed, never
    invented. An explicit pack (``segments`` list, optionally with
    compiled prompts and assets) follows the same normalisation.
    """
    if not isinstance(raw, dict):
        raise MaterialPackError("material pack: input must be a JSON object")
    if isinstance(raw.get("manifest"), dict):
        raw = raw["manifest"]
    elif isinstance(raw.get("material_pack"), dict):
        raw = raw["material_pack"]
    if "segment_plan" in raw:
        source = "stable_film_manifest"
        plan = raw.get("segment_plan") or {}
        raw_segments = plan.get("segments") or []
        gates = raw.get("gates") or []
        pending_material = raw.get("pending_material") or []
        pending_shot_ids = {str(s) for s in raw.get("pending_shot_ids") or []}
        generation_shot_ids = {str(s) for s in raw.get("generation_shot_ids") or []}
        title = raw.get("title") or ""
        pack_status_raw = raw.get("status")
        delivery_note = raw.get("delivery_note") or ""
        raw_assets = raw.get("assets")
        total_duration = raw.get("duration_sec") or raw.get("planned_duration_sec")
    elif "segments" in raw:
        source = "material_pack"
        raw_segments = raw.get("segments") or []
        gates = raw.get("gates") or []
        pending_material = raw.get("pending_material") or []
        pending_shot_ids = {
            str(p.get("shot_id"))
            for p in pending_material
            if isinstance(p, dict) and p.get("shot_id")
        }
        generation_shot_ids = {str(s) for s in raw.get("generation_shot_ids") or []}
        title = raw.get("title") or ""
        pack_status_raw = raw.get("status")
        delivery_note = raw.get("delivery_note") or ""
        raw_assets = raw.get("assets")
        total_duration = raw.get("total_duration_sec") or raw.get("duration_sec")
    else:
        raise MaterialPackError(
            "material pack: input needs either a stable-film manifest "
            "(segment_plan) or a material pack (segments list)"
        )
    if not isinstance(raw_segments, list) or not raw_segments:
        raise MaterialPackError("material pack: no segments found; nothing to map")
    pack_reference_order = raw.get("reference_order")
    if pack_reference_order is not None:
        if not isinstance(pack_reference_order, list) or not pack_reference_order:
            raise MaterialPackError(
                "material pack: reference_order must be a non-empty list"
            )
        pack_reference_order = [str(a) for a in pack_reference_order]
    segments: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_segment in raw_segments:
        segment = _normalize_segment(
            raw_segment,
            pending_shot_ids=pending_shot_ids,
            generation_shot_ids=generation_shot_ids,
            pack_reference_order=pack_reference_order,
        )
        if segment["segment_id"] in seen:
            raise MaterialPackError(
                f"material pack: duplicate segment_id {segment['segment_id']!r}"
            )
        seen.add(segment["segment_id"])
        segments.append(segment)
    # Pending-material evidence links shots to assets: a segment that
    # holds a pending shot references that shot's asset (the manifest
    # names the asset per shot, not per segment).
    for item in pending_material:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "")
        asset_id = item.get("asset_id")
        if not shot_id or not asset_id:
            continue
        for segment in segments:
            if shot_id in segment["shot_ids"] and str(asset_id) not in segment["asset_ids"]:
                segment["asset_ids"].append(str(asset_id))
    if not isinstance(gates, list):
        raise MaterialPackError("material pack: gates must be a list")
    gate_list: list[dict[str, Any]] = []
    for gate in gates:
        if not isinstance(gate, dict) or not gate.get("gate"):
            raise MaterialPackError("material pack: every gate needs a gate name")
        gate_list.append(
            {
                "gate": str(gate["gate"]),
                "verdict": str(gate.get("verdict") or "unknown"),
                "detail": str(gate.get("detail") or ""),
            }
        )
    assets = _normalize_assets(raw_assets, segments, pending_material=pending_material)
    # Gate badges: only fail/pending verdicts are hung on segment
    # nodes. Film-level gates with no segment link stay in the pack
    # gate summary; they are never smeared across every segment.
    pending_by_shot: dict[str, list[dict[str, Any]]] = {}
    for item in pending_material:
        if isinstance(item, dict) and item.get("shot_id"):
            pending_by_shot.setdefault(str(item["shot_id"]), []).append(item)
    segment_gate = next(
        (g for g in gate_list if g["gate"] == "video.segment_assembly_gate"), None
    )
    for segment in segments:
        badges: list[dict[str, Any]] = []
        for shot_id in segment["shot_ids"]:
            for item in pending_by_shot.get(shot_id, []):
                badges.append(
                    {
                        "gate": "story.asset_registry_v2",
                        "verdict": "pending",
                        "detail": (
                            f"pending material for shot {shot_id}: "
                            f"asset {item.get('asset_id')}; "
                            f"{item.get('reason') or ''}".strip()
                        ),
                    }
                )
        if segment_gate is not None and segment_gate["verdict"] != "pass":
            badges.append(dict(segment_gate))
        segment["gate_badges"] = badges
    if isinstance(pack_status_raw, str) and pack_status_raw in _SEGMENT_STATUSES:
        pack_status = pack_status_raw
    elif pending_material:
        pack_status = "pending-material"
    elif any(g["verdict"] == "fail" for g in gate_list):
        pack_status = "partial"
    else:
        pack_status = "done"
    if _is_num(total_duration):
        total_duration_sec: float | None = float(total_duration)
    elif all(s["duration_sec"] is not None for s in segments):
        total_duration_sec = round(sum(float(s["duration_sec"]) for s in segments), 3)
    else:
        total_duration_sec = None
    pack_missing: list[str] = []
    if any("compiled_prompt" in s["missing_fields"] or s["prompt_source"] != "compiled"
           for s in segments):
        # Only claim compiled prompts missing when no segment has one.
        if not any(s["prompt_source"] == "compiled" for s in segments):
            pack_missing.append("compiled_prompts")
    if any(a["version"] is None for a in assets):
        pack_missing.append("asset_versions")
    if any(s["first_frame_ref"] is None for s in segments):
        pack_missing.append("first_frame_refs")
    if any(s["tail_frame_ref"] is None for s in segments):
        pack_missing.append("tail_frame_refs")
    if any(s["reference_order"] is None for s in segments):
        pack_missing.append("reference_order")
    pack_id = raw.get("pack_id") or raw.get("id") or title or "material-pack"
    revision = raw.get("revision")
    if revision is None:
        revision = 1
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise MaterialPackError("material pack: revision must be a positive integer")
    return {
        "pack_id": str(pack_id),
        "title": str(title),
        "source": source,
        "revision": revision,
        "status": pack_status,
        "delivery_note": str(delivery_note),
        "total_duration_sec": total_duration_sec,
        "segments": segments,
        "assets": assets,
        "gates": gate_list,
        "pending_material": copy.deepcopy(pending_material),
        "missing_fields": sorted(set(pack_missing)),
    }


# ── Mapping ───────────────────────────────────────────────────────────────────


def _frontend_status(status: str) -> str:
    return "completed" if status == "done" else "pending"


def _segment_node_config(segment: dict[str, Any], *, pack_revision: int) -> dict[str, Any]:
    config: dict[str, Any] = {
        "prompt": segment["prompt"],
        "duration_s": segment["duration_sec"],
        "duration_sec": segment["duration_sec"],
        "negative_prompts": list(segment["negative_prompts"]),
        "easing": segment["easing"],
        "fallbacks": copy.deepcopy(segment["fallbacks"]),
        "reference_numbers": list(segment["reference_numbers"]),
        "reference_order": list(segment["reference_order"])
        if segment["reference_order"] is not None
        else None,
        "first_frame_ref": segment["first_frame_ref"],
        "tail_frame_ref": segment["tail_frame_ref"],
        "material_pack_segment_id": segment["segment_id"],
        "material_pack_status": segment["status"],
        "material_pack_revision": pack_revision,
        "material_pack_prompt_source": segment["prompt_source"],
        "material_pack_missing_fields": list(segment["missing_fields"]),
        "material_pack_gate_badges": copy.deepcopy(segment["gate_badges"]),
        "material_pack_dirty": False,
        "material_pack_review_pending": False,
        "material_pack_versions": copy.deepcopy(segment["versions"]),
        "material_pack_prompt_history": [],
        "material_pack_asset_version": segment["asset_version"],
        "material_pack_narration": segment["narration"],
        "material_pack_shot_ids": list(segment["shot_ids"]),
        "material_pack_shots": copy.deepcopy(segment["shots"]),
    }
    if segment["provider"]:
        config["provider"] = segment["provider"]
    if segment["compiler_episode"] is not None:
        config["material_pack_compiler_episode"] = copy.deepcopy(
            segment["compiler_episode"]
        )
    return config


def _asset_node_config(asset: dict[str, Any], *, pack_revision: int) -> dict[str, Any]:
    return {
        "asset_id": asset["asset_id"],
        "asset_kind": asset["kind"],
        "asset_version": asset["version"],
        "material_pack_asset_id": asset["asset_id"],
        "material_pack_status": asset["status"],
        "material_pack_revision": pack_revision,
        "material_pack_missing_fields": list(asset["missing_fields"]),
        "material_pack_master": True,
    }


def map_to_graph(
    pack: dict[str, Any],
    existing_graph: dict[str, Any] | None = None,
    *,
    pack_revision: int | None = None,
) -> dict[str, Any]:
    """Map a normalised material pack onto a canvas graph, idempotently.

    ``pack`` must come from :func:`normalize_material_pack` (a raw
    manifest/pack dict is normalised first, so callers may pass
    either). Remapping the same pack onto the graph it produced adds
    no nodes and never overwrites a newer human edit; see the module
    docstring for the revision rules.
    """
    if not isinstance(pack, dict) or "segments" not in pack:
        pack = normalize_material_pack(pack)
    revision = pack_revision if pack_revision is not None else int(pack.get("revision", 1))
    if revision < 1:
        raise MaterialPackError("material pack: pack_revision must be >= 1")
    segments: list[dict[str, Any]] = pack["segments"]
    assets: list[dict[str, Any]] = pack.get("assets") or []

    existing_nodes: dict[str, dict[str, Any]] = {}
    existing_edges: list[dict[str, Any]] = []
    preserved_other = 0
    if existing_graph is not None:
        if not isinstance(existing_graph, dict):
            raise MaterialPackError("material pack: existing_graph must be an object")
        raw_nodes = existing_graph.get("nodes") or existing_graph.get("nodes_json") or []
        raw_edges = existing_graph.get("edges") or existing_graph.get("edges_json") or []
        for node in raw_nodes:
            if isinstance(node, dict) and node.get("node_id"):
                existing_nodes[str(node["node_id"])] = copy.deepcopy(node)
        existing_edges = [copy.deepcopy(e) for e in raw_edges if isinstance(e, dict)]

    added_nodes: list[str] = []
    updated_nodes: list[str] = []
    preserved_dirty: list[str] = []
    stale_skipped: list[str] = []
    nodes: list[dict[str, Any]] = []
    # Segment nodes first, in pack order; positions are only assigned
    # to new nodes -- an existing node's layout is the user's, not
    # this mapping's to move.
    for index, segment in enumerate(segments):
        segment_id = segment["segment_id"]
        existing = existing_nodes.get(segment_id)
        fresh_config = _segment_node_config(segment, pack_revision=revision)
        if existing is None:
            nodes.append(
                {
                    "node_id": segment_id,
                    "node_type": "segment",
                    "label": segment_id,
                    "config": fresh_config,
                    "position": {"x": float(index * 280), "y": 200.0},
                    "status": _frontend_status(segment["status"]),
                }
            )
            added_nodes.append(segment_id)
            continue
        stored_revision = (existing.get("config") or {}).get(
            "material_pack_revision", 0
        )
        if revision < stored_revision:
            nodes.append(existing)
            stale_skipped.append(segment_id)
            continue
        if revision == stored_revision and (existing.get("config") or {}).get(
            "material_pack_dirty"
        ):
            # Same revision, unadopted human edit: keep the working
            # prompt. Only non-prompt facts (status/badges) refresh.
            merged = copy.deepcopy(existing)
            merged_config = merged.setdefault("config", {})
            merged_config["material_pack_status"] = segment["status"]
            merged_config["material_pack_gate_badges"] = copy.deepcopy(
                segment["gate_badges"]
            )
            merged_config["material_pack_missing_fields"] = list(
                segment["missing_fields"]
            )
            merged["status"] = _frontend_status(segment["status"])
            nodes.append(merged)
            preserved_dirty.append(segment_id)
            continue
        # Newer revision (or same revision, clean node): adopt the
        # fact-source values, preserving the human's layout, history
        # and -- when superseding a working copy -- the old prompt.
        merged = copy.deepcopy(existing)
        old_config = merged.get("config") or {}
        history = list(old_config.get("material_pack_prompt_history") or [])
        old_prompt = old_config.get("prompt")
        if old_prompt is not None and old_prompt != fresh_config["prompt"]:
            history.append(
                {
                    "prompt": old_prompt,
                    "revision": old_config.get("material_pack_revision"),
                    "source": "superseded_by_pack_revision",
                    "negative_prompts": list(old_config.get("negative_prompts") or []),
                    "duration_sec": old_config.get("duration_sec"),
                    "reference_numbers": list(
                        old_config.get("reference_numbers") or []
                    ),
                }
            )
        fresh_config["material_pack_prompt_history"] = history
        merged["config"] = fresh_config
        merged["node_type"] = "segment"
        merged["label"] = segment_id
        merged.setdefault("position", {"x": float(index * 280), "y": 200.0})
        merged["status"] = _frontend_status(segment["status"])
        nodes.append(merged)
        updated_nodes.append(segment_id)

    for index, asset in enumerate(assets):
        node_id = f"asset-{asset['asset_id']}"
        existing = existing_nodes.get(node_id)
        fresh_config = _asset_node_config(asset, pack_revision=revision)
        if existing is None:
            nodes.append(
                {
                    "node_id": node_id,
                    "node_type": "asset",
                    "label": str(asset.get("name") or asset["asset_id"]),
                    "config": fresh_config,
                    "position": {"x": float(index * 280), "y": 0.0},
                    "status": _frontend_status(asset["status"]),
                }
            )
            added_nodes.append(node_id)
            continue
        stored_revision = (existing.get("config") or {}).get(
            "material_pack_revision", 0
        )
        if revision < stored_revision:
            nodes.append(existing)
            stale_skipped.append(node_id)
            continue
        merged = copy.deepcopy(existing)
        merged["config"] = fresh_config
        merged["node_type"] = "asset"
        merged.setdefault("position", {"x": float(index * 280), "y": 0.0})
        merged["status"] = _frontend_status(asset["status"])
        nodes.append(merged)
        updated_nodes.append(node_id)

    # Nodes in the existing graph that this pack does not describe
    # are the user's own: kept verbatim, never deleted by a remap.
    mapped_ids = {n["node_id"] for n in nodes}
    for node_id, node in existing_nodes.items():
        if node_id not in mapped_ids:
            nodes.append(node)
            preserved_other += 1

    # Edges: continuation chain + asset references. User edges that
    # are not part of this mapping are kept; mapped edges are added
    # only when absent, so a remap never duplicates an edge.
    edges: list[dict[str, Any]] = list(existing_edges)
    seen_edge_keys: set[tuple[str, str, str]] = set()
    for edge in edges:
        seen_edge_keys.add(
            (
                str(edge.get("from_node_id")),
                str(edge.get("to_node_id")),
                str(edge.get("kind") or ""),
            )
        )
    continuation_connected = 0
    continuation_pending = 0
    added_edges: list[str] = []
    for prev, nxt in zip(segments, segments[1:]):
        prev_id, next_id = prev["segment_id"], nxt["segment_id"]
        key = (prev_id, next_id, "continuation")
        connected = prev.get("tail_frame_ref") is not None
        if connected:
            continuation_connected += 1
        else:
            continuation_pending += 1
        if key in seen_edge_keys:
            continue
        edge_id = f"edge-{prev_id}-{next_id}-continuation"
        edges.append(
            {
                "edge_id": edge_id,
                "from_node_id": prev_id,
                "to_node_id": next_id,
                "from_type": "segment",
                "to_type": "segment",
                "kind": "continuation",
                "status": "connected" if connected else "pending",
                "note": (
                    "tail frame of previous segment is the next segment's "
                    "first frame"
                    if connected
                    else "previous segment has no tail frame; continuation "
                    "is pending, not connected"
                ),
            }
        )
        seen_edge_keys.add(key)
        added_edges.append(edge_id)
    asset_node_id = {a["asset_id"]: f"asset-{a['asset_id']}" for a in assets}
    for segment in segments:
        for asset_id in segment["asset_ids"]:
            if asset_id not in asset_node_id:
                continue
            key = (asset_node_id[asset_id], segment["segment_id"], "reference")
            if key in seen_edge_keys:
                continue
            edge_id = f"edge-{asset_node_id[asset_id]}-{segment['segment_id']}-reference"
            edges.append(
                {
                    "edge_id": edge_id,
                    "from_node_id": asset_node_id[asset_id],
                    "to_node_id": segment["segment_id"],
                    "from_type": "asset",
                    "to_type": "segment",
                    "kind": "reference",
                    "status": "reference",
                    "note": f"segment references asset {asset_id}",
                }
            )
            seen_edge_keys.add(key)
            added_edges.append(edge_id)

    graph = {
        "name": str(pack.get("title") or pack.get("pack_id") or "material-pack"),
        "description": str(pack.get("delivery_note") or ""),
        "nodes": nodes,
        "edges": edges,
    }
    report = {
        "pack_id": pack.get("pack_id"),
        "pack_revision": revision,
        "source": pack.get("source"),
        "status": pack.get("status"),
        "segment_count": len(segments),
        "asset_count": len(assets),
        "edge_count": len(edges),
        "continuation_connected": continuation_connected,
        "continuation_pending": continuation_pending,
        "added_nodes": added_nodes,
        "updated_nodes": updated_nodes,
        "preserved_dirty": preserved_dirty,
        "stale_skipped": stale_skipped,
        "preserved_other_nodes": preserved_other,
        "added_edges": added_edges,
        "missing_fields": list(pack.get("missing_fields") or []),
        "gate_summary": copy.deepcopy(pack.get("gates") or []),
        "segment_ids": [s["segment_id"] for s in segments],
    }
    return {"graph": graph, "report": report}


# ── Human edit loop ───────────────────────────────────────────────────────────


def graph_segment_order(graph: dict[str, Any]) -> list[str]:
    """Segment ids in canvas order: continuation chain, else layout order.

    The continuation chain is authoritative when it is intact; a
    broken or cyclic chain falls back to position order (x, then id)
    so downstream marking still has a deterministic order.
    """
    nodes = graph.get("nodes") or graph.get("nodes_json") or []
    segments = [
        n for n in nodes if isinstance(n, dict) and n.get("node_type") == "segment"
    ]
    if not segments:
        return []
    edges = graph.get("edges") or graph.get("edges_json") or []
    next_of: dict[str, str] = {}
    has_incoming: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict) or edge.get("kind") != "continuation":
            continue
        src, dst = str(edge.get("from_node_id")), str(edge.get("to_node_id"))
        if src in next_of:
            return _position_order(segments)
        next_of[src] = dst
        has_incoming.add(dst)
    ids = {str(n.get("node_id")) for n in segments}
    starts = [str(n.get("node_id")) for n in segments if str(n.get("node_id")) not in has_incoming]
    if len(starts) != 1:
        return _position_order(segments)
    order: list[str] = []
    current: str | None = starts[0]
    seen: set[str] = set()
    while current is not None and current in ids and current not in seen:
        seen.add(current)
        order.append(current)
        current = next_of.get(current)
    if len(order) != len(ids):
        return _position_order(segments)
    return order


def _position_order(segments: list[dict[str, Any]]) -> list[str]:
    def _key(node: dict[str, Any]) -> tuple[float, str]:
        pos = node.get("position") or {}
        try:
            x = float(pos.get("x", 0.0))
        except (TypeError, ValueError):
            x = 0.0
        return (x, str(node.get("node_id")))
    return [str(n.get("node_id")) for n in sorted(segments, key=_key)]


def _find_segment_node(
    graph: dict[str, Any], segment_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    nodes = graph.get("nodes") or graph.get("nodes_json") or []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        config = node.get("config") or {}
        if node.get("node_type") == "segment" and (
            node.get("node_id") == segment_id
            or config.get("material_pack_segment_id") == segment_id
        ):
            return node, config
    raise MaterialPackError(
        f"material pack: no segment node {segment_id!r} in this graph"
    )


def _validate_patch(patch: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(patch, dict) or not patch:
        raise MaterialPackError("material pack: edit patch must be a non-empty object")
    unknown = [k for k in patch if k not in _EDITABLE_FIELDS]
    if unknown:
        raise MaterialPackError(
            f"material pack: cannot edit field(s) {unknown}; editable: "
            f"{list(_EDITABLE_FIELDS)}"
        )
    cleaned: dict[str, Any] = {}
    if "prompt" in patch:
        if not isinstance(patch["prompt"], str) or not patch["prompt"].strip():
            raise MaterialPackError("material pack: prompt must be a non-empty string")
        cleaned["prompt"] = str(patch["prompt"])
    if "negative_prompts" in patch:
        cleaned["negative_prompts"] = _as_str_list(
            patch["negative_prompts"], "negative_prompts"
        )
    if "duration_sec" in patch:
        if not _is_num(patch["duration_sec"]) or float(patch["duration_sec"]) <= 0:
            raise MaterialPackError(
                "material pack: duration_sec must be a positive number"
            )
        cleaned["duration_sec"] = float(patch["duration_sec"])
    if "reference_numbers" in patch:
        # Stored verbatim, in the order given: never renumbered here,
        # even when a number has no entry in the reference order.
        cleaned["reference_numbers"] = _as_int_list(
            patch["reference_numbers"], "reference_numbers"
        )
    if "easing" in patch:
        if patch["easing"] is not None and (
            not isinstance(patch["easing"], str) or not patch["easing"]
        ):
            raise MaterialPackError("material pack: easing must be a non-empty string")
        cleaned["easing"] = patch["easing"]
    if "fallbacks" in patch:
        if not isinstance(patch["fallbacks"], list):
            raise MaterialPackError("material pack: fallbacks must be a list")
        cleaned_fallbacks: list[dict[str, Any]] = []
        for item in patch["fallbacks"]:
            if not isinstance(item, dict) or not item.get("trigger") or not item.get(
                "replacement"
            ):
                raise MaterialPackError(
                    "material pack: every fallback needs trigger and replacement"
                )
            cleaned_fallbacks.append(
                {"trigger": str(item["trigger"]), "replacement": str(item["replacement"])}
            )
        cleaned["fallbacks"] = cleaned_fallbacks
    if "first_frame_ref" in patch:
        if not isinstance(patch["first_frame_ref"], str) or not patch["first_frame_ref"]:
            raise MaterialPackError(
                "material pack: first_frame_ref must be a non-empty string"
            )
        cleaned["first_frame_ref"] = str(patch["first_frame_ref"])
    return cleaned


def apply_segment_edit(
    graph: dict[str, Any],
    segment_id: str,
    patch: dict[str, Any],
    *,
    base_revision: int,
) -> dict[str, Any]:
    """Apply a human prompt edit to one segment node.

    The edited segment is marked dirty + pending review and its
    pre-edit prompt is appended to its history (old version kept).
    Every downstream segment is marked pending review; downstream
    prompts and results are not touched. The fact source (pack) is
    not written: that happens only on :func:`adopt_segment_edit`.
    ``base_revision`` must equal the node's stored revision, or the
    edit is refused as stale.
    """
    cleaned = _validate_patch(patch)
    new_graph = copy.deepcopy(graph)
    node, config = _find_segment_node(new_graph, segment_id)
    stored_revision = config.get("material_pack_revision")
    if stored_revision != base_revision:
        raise MaterialPackError(
            f"material pack: segment {segment_id!r} is at revision "
            f"{stored_revision!r}, not base_revision {base_revision!r}; "
            "refresh the canvas before editing (stale edit refused)"
        )
    history = list(config.get("material_pack_prompt_history") or [])
    history.append(
        {
            "prompt": config.get("prompt"),
            "revision": stored_revision,
            "source": "pre-edit",
            "negative_prompts": list(config.get("negative_prompts") or []),
            "duration_sec": config.get("duration_sec"),
            "reference_numbers": list(config.get("reference_numbers") or []),
        }
    )
    config["material_pack_prompt_history"] = history
    for key, value in cleaned.items():
        config[key] = copy.deepcopy(value)
        if key == "duration_sec":
            config["duration_s"] = value
    config["material_pack_dirty"] = True
    config["material_pack_review_pending"] = True
    config["material_pack_prompt_source"] = "edited"
    # Reference numbers are kept exactly as stored. If a stored
    # number has no entry in the declared reference order, record
    # the gap; never renumber, never drop the number.
    notes: list[str] = list(config.get("material_pack_review_notes") or [])
    order = config.get("reference_order")
    if isinstance(order, list) and order:
        for number in config.get("reference_numbers") or []:
            if number > len(order):
                notes.append(
                    f"reference number {number} has no entry in the "
                    f"declared reference order ({len(order)} entries); "
                    "number kept stable, not renumbered"
                )
    config["material_pack_review_notes"] = notes

    order_ids = graph_segment_order(new_graph)
    downstream: list[str] = []
    if segment_id in order_ids:
        downstream = order_ids[order_ids.index(segment_id) + 1:]
    for node_item in new_graph.get("nodes") or []:
        if not isinstance(node_item, dict):
            continue
        if str(node_item.get("node_id")) in downstream \
                and node_item.get("node_type") == "segment":
            downstream_config = node_item.setdefault("config", {})
            downstream_config["material_pack_review_pending"] = True
            downstream_notes = list(
                downstream_config.get("material_pack_review_notes") or []
            )
            downstream_notes.append(
                f"upstream segment {segment_id} edited; re-review before "
                "regenerating (first frame may have changed)"
            )
            downstream_config["material_pack_review_notes"] = downstream_notes
    report = {
        "segment_id": segment_id,
        "dirty": True,
        "review_pending": True,
        "downstream_marked": downstream,
        "history_len": len(history),
        "base_revision": base_revision,
    }
    return {"graph": new_graph, "report": report}


# ── Gates ─────────────────────────────────────────────────────────────────────


def check_regeneration_gates(
    graph: dict[str, Any],
    segment_id: str,
    *,
    model_max_sec: float = 15.0,
) -> dict[str, Any]:
    """Run the prompt-compiler + segment-assembly gates for one segment.

    Also checks the reference-number gate (when the prompt makes
    numbered reference claims) and the pending-material check. Every
    gate that is not a clean pass blocks regeneration; an unrunnable
    gate (no shot evidence, no reference order for a numbered claim)
    is reported ``unknown`` and blocks too -- it is never treated as
    a pass.
    """
    node, config = _find_segment_node(graph, segment_id)
    gates: list[dict[str, Any]] = []
    blockers: list[str] = []

    def _add(name: str, verdict: str, detail: str) -> None:
        gates.append({"gate": name, "verdict": verdict, "detail": detail})
        if verdict != "pass":
            blockers.append(f"{name}: {detail}")

    # Gate 1: story.prompt_compiler. Full episode gate when the node
    # carries a beat-schema episode; otherwise the segment-field
    # checks (prompt present, easing in the closed list, negative
    # list / fallbacks well-formed).
    from hevi.capabilities.prompt_compiler import EASINGS, compile_episode

    episode = config.get("material_pack_compiler_episode")
    prompt = str(config.get("prompt") or "")
    if isinstance(episode, dict):
        try:
            compile_episode(copy.deepcopy(episode))
        except Exception as exc:  # noqa: BLE001 -- gate failure, named
            _add("story.prompt_compiler", "fail", f"full episode gate failed: {exc}")
        else:
            _add(
                "story.prompt_compiler",
                "pass",
                "full episode gate passed (mode: full_episode)",
            )
    else:
        problems: list[str] = []
        if not prompt.strip():
            problems.append("prompt is empty")
        easing = config.get("easing")
        if easing is not None and easing not in EASINGS:
            problems.append(
                f"easing {easing!r} is outside the closed list: "
                f"{', '.join(EASINGS)}"
            )
        for item in config.get("negative_prompts") or []:
            if not isinstance(item, str) or not item.strip():
                problems.append("negative_prompts contains an empty item")
        for item in config.get("fallbacks") or []:
            if not isinstance(item, dict) or not item.get("trigger") or not item.get(
                "replacement"
            ):
                problems.append("fallbacks contains an item without trigger/replacement")
        if problems:
            _add(
                "story.prompt_compiler",
                "fail",
                "segment-field checks failed: " + "; ".join(problems),
            )
        else:
            _add(
                "story.prompt_compiler",
                "pass",
                "segment-field checks passed (mode: segment_fields; "
                "no beat-schema episode supplied, full episode gate not run)",
            )

    # Gate 2: video.segment_assembly_gate over the segment's shots.
    from hevi.capabilities.segment_assembly import MAX_SEGMENT_SEC, plan_segments

    shots = config.get("material_pack_shots") or []
    duration = config.get("duration_sec")
    if not shots:
        _add(
            "video.segment_assembly_gate",
            "unknown",
            "no shot evidence on the segment node; segment math cannot run",
        )
    else:
        by_scene: dict[str, list[dict[str, Any]]] = {}
        for shot in shots:
            scene = str(shot.get("scene_id") or "main")
            by_scene.setdefault(scene, []).append(shot)
        scenes = [
            {
                "scene_id": scene,
                "shots": [
                    {
                        "shot_id": s["shot_id"],
                        "text": s.get("text", ""),
                        **(
                            {"duration_sec": s["duration_sec"]}
                            if s.get("duration_sec") is not None
                            else {}
                        ),
                    }
                    for s in scene_shots
                ],
            }
            for scene, scene_shots in by_scene.items()
        ]
        try:
            plan = plan_segments(scenes, model_max_sec=model_max_sec)
        except Exception as exc:  # noqa: BLE001 -- gate failure, named
            _add("video.segment_assembly_gate", "fail", str(exc))
        else:
            cap = min(MAX_SEGMENT_SEC, float(model_max_sec))
            shot_total = round(
                sum(float(s["duration_sec"]) for s in plan["shots"]), 3
            )
            if _is_num(duration) and abs(float(duration) - shot_total) > 0.05:
                _add(
                    "video.segment_assembly_gate",
                    "fail",
                    f"segment duration {duration}s does not match the sum "
                    f"of its shot durations {shot_total}s",
                )
            elif _is_num(duration) and float(duration) > cap:
                _add(
                    "video.segment_assembly_gate",
                    "fail",
                    f"segment duration {duration}s is over the segment cap {cap}s",
                )
            else:
                _add(
                    "video.segment_assembly_gate",
                    "pass",
                    f"segment math ok: {shot_total}s over "
                    f"{plan['segment_count']} packed segment(s), cap {cap}s",
                )

    # Gate 3: qa.reference_number_gate, only when the prompt makes
    # numbered claims. Stored reference numbers without a {{ref N}}
    # claim in the prompt are not claims and do not fail this gate.
    from hevi.capabilities.reference_number_gate import check_references

    refs_in_prompt = "{{ref" in prompt
    order = config.get("reference_order")
    if not refs_in_prompt:
        _add(
            "qa.reference_number_gate",
            "pass",
            "prompt makes no numbered reference claims",
        )
    elif not order:
        _add(
            "qa.reference_number_gate",
            "unknown",
            "prompt claims numbered references but no reference order "
            "is declared; claims cannot be checked",
        )
    else:
        report = check_references(prompt, order, mode="multi_param")
        if report["ok"]:
            _add(
                "qa.reference_number_gate",
                "pass",
                f"numbered references resolve: {report['resolved']}",
            )
        else:
            _add(
                "qa.reference_number_gate",
                "fail",
                "; ".join(report["problems"]),
            )

    # Gate 4: pending material (asset registry check, by status).
    status = config.get("material_pack_status")
    if status == "pending-material":
        _add(
            "story.asset_registry_v2",
            "fail",
            "segment is pending material; pending shots never enter generation",
        )
    else:
        _add(
            "story.asset_registry_v2",
            "pass",
            f"no pending material on this segment (status: {status})",
        )
    _ = node
    return {"ok": not blockers, "gates": gates, "blockers": blockers}


# ── Regeneration + adoption ───────────────────────────────────────────────────


async def request_regeneration(
    graph: dict[str, Any],
    segment_id: str,
    *,
    confirmed: Any = None,
    smoke_passed: Any = False,
    budget_usd: float | None = None,
    estimated_unit_cost: Any = None,
    free_route: bool = False,
    executor: Any = None,
) -> dict[str, Any]:
    """Plan (or, with an executor, run) regeneration of ONE segment.

    Order: gates, then preflight, then the spend brake. Any refusal
    returns ``status == "refused"`` with blockers and runs nothing.
    With no executor this returns the ready-to-run plan only -- no
    generation happens in this module. With an executor, only the
    single segment node is handed to it; the whole film is never
    re-run from here.
    """
    _find_segment_node(graph, segment_id)  # raises if unknown
    gate_report = check_regeneration_gates(graph, segment_id)
    if not gate_report["ok"]:
        return {
            "status": "refused",
            "segment_id": segment_id,
            "scope": "single_segment",
            "gates": gate_report["gates"],
            "blockers": list(gate_report["blockers"]),
        }

    node, config = _find_segment_node(graph, segment_id)
    from oprim.hevi_types import CanvasNode

    from hevi.canvas.preflight import run_preflight

    canvas_node = CanvasNode.model_validate(
        {
            "node_id": node.get("node_id"),
            "node_type": "segment",
            "label": node.get("label", ""),
            "config": dict(config),
            "position": dict(node.get("position") or {}),
        }
    )
    preflight = run_preflight([canvas_node], budget_usd=budget_usd)
    preflight_report = {
        "passed": preflight.passed,
        "estimated_cost_usd": preflight.estimated_cost_usd,
        "issues": [{"severity": i.severity, "message": i.message} for i in preflight.issues],
    }
    if not preflight.passed:
        return {
            "status": "refused",
            "segment_id": segment_id,
            "scope": "single_segment",
            "gates": gate_report["gates"],
            "preflight": preflight_report,
            "blockers": [
                i.message for i in preflight.issues if i.severity == "error"
            ],
        }

    spend: dict[str, Any]
    if free_route:
        if preflight.estimated_cost_usd > 0:
            return {
                "status": "refused",
                "segment_id": segment_id,
                "scope": "single_segment",
                "gates": gate_report["gates"],
                "preflight": preflight_report,
                "blockers": [
                    "free_route claimed but preflight estimates a "
                    f"non-zero cost (${preflight.estimated_cost_usd:.2f}); "
                    "a free route must cost $0"
                ],
            }
        spend = {
            "approved": True,
            "mode": "free_route",
            "note": "estimated cost $0: spend brake not applicable to a "
            "free code-frame route",
        }
    else:
        from hevi.capabilities.spend_brake import authorize_spend

        shots = config.get("material_pack_shots") or []
        storyboard = [
            {
                "shot_id": s.get("shot_id"),
                "visual": s.get("text", ""),
                "duration_sec": s.get("duration_sec"),
            }
            for s in shots
        ]
        try:
            approval = authorize_spend(
                storyboard,
                confirmed=confirmed,
                smoke_passed=smoke_passed,
                batch_size=1,
                estimated_unit_cost=estimated_unit_cost,
            )
        except Exception as exc:  # noqa: BLE001 -- refusal, named
            return {
                "status": "refused",
                "segment_id": segment_id,
                "scope": "single_segment",
                "gates": gate_report["gates"],
                "preflight": preflight_report,
                "blockers": [str(exc)],
            }
        spend = dict(approval)
    plan = {
        "status": "ready",
        "segment_id": segment_id,
        "scope": "single_segment",
        "gates": gate_report["gates"],
        "preflight": preflight_report,
        "spend": spend,
        "plan": {
            "segment_id": segment_id,
            "prompt": config.get("prompt"),
            "duration_sec": config.get("duration_sec"),
            "first_frame_ref": config.get("first_frame_ref"),
            "note": "only this segment regenerates; the rest of the "
            "film is not re-run",
        },
    }
    if executor is None:
        return plan
    result = await executor(copy.deepcopy(node))
    return {**plan, "status": "executed", "result": result}


def adopt_segment_edit(
    pack: dict[str, Any], graph: dict[str, Any], segment_id: str
) -> dict[str, Any]:
    """Write an edited segment back to the fact source as a new version.

    Requires the segment to be dirty (an unadopted edit) and the
    regeneration gates to pass. The old pack segment is appended to
    the new segment's ``versions`` (retained, never overwritten) and
    the revision increments by 1. The graph node is updated to the
    new revision and cleared of dirty/review flags for itself;
    downstream segments stay pending review.
    """
    if not isinstance(pack, dict) or "segments" not in pack:
        pack = normalize_material_pack(pack)
    node, config = _find_segment_node(graph, segment_id)
    if not config.get("material_pack_dirty"):
        raise MaterialPackError(
            f"material pack: segment {segment_id!r} has no unadopted edit to adopt"
        )
    gate_report = check_regeneration_gates(graph, segment_id)
    if not gate_report["ok"]:
        raise MaterialPackError(
            "material pack: adoption refused, gates did not pass: "
            + "; ".join(gate_report["blockers"])
        )
    segment_index = next(
        (
            i
            for i, s in enumerate(pack["segments"])
            if s["segment_id"] == segment_id
        ),
        None,
    )
    if segment_index is None:
        raise MaterialPackError(
            f"material pack: segment {segment_id!r} is not in this pack"
        )
    old_segment = copy.deepcopy(pack["segments"][segment_index])
    old_revision = int(old_segment["revision"])
    new_segment = copy.deepcopy(old_segment)
    new_segment["prompt"] = str(config.get("prompt"))
    new_segment["prompt_source"] = "adopted_edit"
    new_segment["negative_prompts"] = list(config.get("negative_prompts") or [])
    new_segment["easing"] = config.get("easing")
    new_segment["fallbacks"] = copy.deepcopy(config.get("fallbacks") or [])
    new_segment["reference_numbers"] = list(config.get("reference_numbers") or [])
    if config.get("duration_sec") is not None:
        new_segment["duration_sec"] = float(config["duration_sec"])
    if config.get("first_frame_ref") is not None:
        new_segment["first_frame_ref"] = config["first_frame_ref"]
    new_segment["revision"] = old_revision + 1
    versions = list(old_segment.get("versions") or [])
    versions.append(
        {k: v for k, v in old_segment.items() if k != "versions"}
    )
    new_segment["versions"] = versions
    new_segment["missing_fields"] = [
        f for f in old_segment.get("missing_fields", []) if f != "prompt"
    ]
    new_pack = copy.deepcopy(pack)
    new_pack["segments"][segment_index] = new_segment
    new_pack["revision"] = int(pack.get("revision", 1)) + 1

    new_graph = copy.deepcopy(graph)
    new_node, new_config = _find_segment_node(new_graph, segment_id)
    new_config["material_pack_revision"] = old_revision + 1
    new_config["material_pack_dirty"] = False
    new_config["material_pack_review_pending"] = False
    new_config["material_pack_prompt_source"] = "adopted_edit"
    new_config["material_pack_versions"] = copy.deepcopy(versions)
    _ = new_node
    order_ids = graph_segment_order(new_graph)
    downstream_still_pending = [
        sid
        for sid in order_ids[order_ids.index(segment_id) + 1:]
        if sid in order_ids
    ]
    # Only report downstream that are actually still flagged.
    downstream_still_pending = []
    for item in new_graph.get("nodes") or []:
        if (
            isinstance(item, dict)
            and item.get("node_type") == "segment"
            and str(item.get("node_id")) in order_ids[order_ids.index(segment_id) + 1:]
            and (item.get("config") or {}).get("material_pack_review_pending")
        ):
            downstream_still_pending.append(str(item.get("node_id")))
    report = {
        "segment_id": segment_id,
        "old_revision": old_revision,
        "new_revision": old_revision + 1,
        "versions_retained": len(versions),
        "downstream_still_pending": downstream_still_pending,
    }
    return {"pack": new_pack, "graph": new_graph, "report": report}
