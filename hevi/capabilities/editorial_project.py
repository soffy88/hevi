"""Editorial project model: Asset-first, pinned clips, takes, revision.

Clean-room rewrite of the data-model discipline described in
section 2 / section 8 (items A1-A4) of the hevi-vs-BeatDesign
review (``~/workspace/hevi-vs-beatdesign.md``). No code, text or
configuration from that repository is copied here; the whole
station is not installed, no provider adapter is built, no
provider key system is reproduced, and no third-party brand name
is used as a hevi product name. See BEATDESIGN_ATTRIBUTION.md.

The model answers one question: when a project has been edited
twenty times, which version is the final one, and can a later
generation silently replace it? Four rules, in own wording:

A1. Asset-first. One generation produces one Asset. Canvas
    nodes, timeline clips and generation references only point
    at Assets; they do not own a position. Removing a view
    reference never deletes the Asset it pointed at.
A2. A Clip is pinned to one concrete Asset. Changing a
    generation's pinned output never moves an already-cut
    clip. Replacing a clip's Asset needs an explicit
    confirmation; without it the replacement is refused and
    the clip is untouched.
A3. Takes. One clip slot can hold alternative Takes. Activating
    a Take never moves the clip and never loses the Original:
    the Original can always be restored. A Take shorter than
    the clip slot cannot be activated, because it would leave
    a frozen tail frame in an export.
A4. Lineage and edges are stored separately. Generation
    lineage (which Asset was derived from which) is not the
    canvas edge list (which nodes look connected). Changing
    an edge never changes lineage, and deriving an Asset
    never creates an edge.

Revision / CAS / idempotency (the write path): every mutation
goes through :func:`apply_command` with an expected revision
and an idempotency key. A stale expected revision is a
conflict: nothing is applied. Replaying an idempotency key
returns the stored receipt without re-executing. Whole-document
replacement is refused outright: writes are incremental
operations only. Receipts are a short-lived idempotency store,
not a permanent audit log.

Deliberate non-overlap, so nothing here is a second copy of an
existing rule:

* ``canvas.material_pack`` owns the material-pack-to-canvas mapping, adopt
  writes a new version, and regeneration gates. This module
  never maps a pack and never regenerates.
* ``canvas_workflow`` owns DAG validation and the single retry
  ceiling. This module never validates a DAG: edges here are
  visual organisation only, and cycles in them are not this
  module's business.
* Nothing here renders, exports, or talks to a provider. The
  MCP operation layer, the browser canvas/timeline UI and the
  browser export discipline (review items B1-B3) are NOT built
  here; see the attribution file for the residual list.

Failure contract: malformed inputs (not an object, missing ids,
bad times, unknown operation) raise :class:`CapabilityError`.
Write-path refusals that are a matter of state (revision
conflict, unconfirmed replacement, too-short Take,
whole-document replacement) are reported in the result, never
raised, so a caller can list them. Projects are plain dicts;
no function mutates a project handed to it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

TAKE_SOURCES = frozenset({"original", "derived", "imported"})

# Operation names that mean "replace the whole document". They are
# refused by the write path, never executed.
_WHOLE_REPLACE_OPS = frozenset(
    {"replace_document", "replace_project", "set_state", "set_project"}
)

__all__ = [
    "TAKE_SOURCES",
    "create_project",
    "register_asset",
    "add_view_reference",
    "remove_view_reference",
    "set_pinned_output",
    "add_clip",
    "replace_clip_asset",
    "add_take",
    "activate_take",
    "restore_original",
    "effective_asset_id",
    "add_edge",
    "remove_edge",
    "apply_command",
]


def _fail(message: str) -> None:
    raise CapabilityError(message)


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def create_project(project_id: Any) -> dict[str, Any]:
    """Return an empty editorial project document."""
    if not isinstance(project_id, str) or not project_id:
        _fail("project_id must be a non-empty string")
    return {
        "project_id": project_id,
        "revision": 0,
        "assets": {},
        "views": [],
        "pinned_outputs": {},
        "clips": {},
        "edges": [],
        "lineage": [],
        "receipts": {},
        "history": [],
    }


def _project(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(
        value.get("assets"), dict
    ):
        _fail("project must be an editorial project document")
    return value


def _copy(project: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(project)


def _asset(project: dict[str, Any], asset_id: Any, *, what: str = "asset") -> dict[str, Any]:
    if not isinstance(asset_id, str) or not asset_id:
        _fail(f"{what} id must be a non-empty string")
    asset = project["assets"].get(asset_id)
    if asset is None:
        _fail(f"unknown {what}: {asset_id!r}")
    return asset


def _clip(project: dict[str, Any], clip_id: Any) -> dict[str, Any]:
    if not isinstance(clip_id, str) or not clip_id:
        _fail("clip id must be a non-empty string")
    clip = project["clips"].get(clip_id)
    if clip is None:
        _fail(f"unknown clip: {clip_id!r}")
    return clip


# ------------------------------------------------------------------ A1 assets

def register_asset(
    project: Any,
    asset_id: Any,
    kind: Any,
    *,
    generation_id: Any = None,
    derived_from: Any = None,
) -> dict[str, Any]:
    """Register one Asset. A derived Asset records lineage, not an edge."""
    project = _copy(_project(project))
    if not isinstance(asset_id, str) or not asset_id:
        _fail("asset_id must be a non-empty string")
    if asset_id in project["assets"]:
        _fail(f"asset already registered: {asset_id!r}")
    if not isinstance(kind, str) or not kind:
        _fail("asset kind must be a non-empty string")
    if generation_id is not None and (
        not isinstance(generation_id, str) or not generation_id
    ):
        _fail("generation_id must be a non-empty string or None")
    if derived_from is not None:
        _asset(project, derived_from, what="parent asset")
        project["lineage"].append(
            {
                "child_asset_id": asset_id,
                "parent_asset_id": derived_from,
                "generation_id": generation_id,
            }
        )
    project["assets"][asset_id] = {
        "asset_id": asset_id,
        "kind": kind,
        "generation_id": generation_id,
        "derived_from": derived_from,
        "status": "ready",
    }
    return project


def add_view_reference(
    project: Any, view_id: Any, kind: Any, asset_id: Any
) -> dict[str, Any]:
    """Point one view (canvas node, timeline slot, reference) at an Asset."""
    project = _copy(_project(project))
    if not isinstance(view_id, str) or not view_id:
        _fail("view_id must be a non-empty string")
    if not isinstance(kind, str) or not kind:
        _fail("view kind must be a non-empty string")
    _asset(project, asset_id)
    if any(view["view_id"] == view_id for view in project["views"]):
        _fail(f"view already exists: {view_id!r}")
    project["views"].append(
        {"view_id": view_id, "kind": kind, "asset_id": asset_id}
    )
    return project


def remove_view_reference(project: Any, view_id: Any) -> dict[str, Any]:
    """Remove a view reference. The Asset it pointed at is NOT deleted."""
    project = _copy(_project(project))
    if not isinstance(view_id, str) or not view_id:
        _fail("view_id must be a non-empty string")
    views = [v for v in project["views"] if v["view_id"] != view_id]
    if len(views) == len(project["views"]):
        _fail(f"unknown view: {view_id!r}")
    project["views"] = views
    return project


def set_pinned_output(
    project: Any, generation_id: Any, asset_id: Any
) -> dict[str, Any]:
    """Change a generation's pinned output. No clip is touched."""
    project = _copy(_project(project))
    if not isinstance(generation_id, str) or not generation_id:
        _fail("generation_id must be a non-empty string")
    _asset(project, asset_id)
    project["pinned_outputs"][generation_id] = asset_id
    return project


# ------------------------------------------------------------------ A2 clips

def add_clip(
    project: Any,
    clip_id: Any,
    asset_id: Any,
    *,
    start_sec: Any,
    in_sec: Any,
    out_sec: Any,
    duration_sec: Any,
) -> dict[str, Any]:
    """Add a Clip pinned to one concrete Asset.

    The clip slot is exactly its in/out span: ``duration_sec``
    must equal ``out_sec - in_sec``. A clip never follows a
    later pinned output; it names its Asset here, once.
    """
    project = _copy(_project(project))
    if not isinstance(clip_id, str) or not clip_id:
        _fail("clip_id must be a non-empty string")
    if clip_id in project["clips"]:
        _fail(f"clip already exists: {clip_id!r}")
    _asset(project, asset_id)
    for name, value in (
        ("start_sec", start_sec),
        ("in_sec", in_sec),
        ("out_sec", out_sec),
        ("duration_sec", duration_sec),
    ):
        if not _is_num(value):
            _fail(f"clip {name} must be a number, got {value!r}")
    if float(start_sec) < 0 or float(in_sec) < 0:
        _fail("clip start_sec and in_sec must not be negative")
    if float(out_sec) <= float(in_sec):
        _fail("clip out_sec must be after in_sec")
    if abs(float(duration_sec) - (float(out_sec) - float(in_sec))) > 1e-9:
        _fail(
            "clip duration_sec must equal out_sec - in_sec "
            f"({duration_sec!r} vs {float(out_sec) - float(in_sec)!r})"
        )
    if float(duration_sec) <= 0:
        _fail("clip duration_sec must be positive")
    project["clips"][clip_id] = {
        "clip_id": clip_id,
        "asset_id": asset_id,
        "original_asset_id": asset_id,
        "start_sec": float(start_sec),
        "in_sec": float(in_sec),
        "out_sec": float(out_sec),
        "duration_sec": float(duration_sec),
        "takes": [],
        "active_take_id": None,
        "replaced_from": [],
    }
    return project


def replace_clip_asset(
    project: Any,
    clip_id: Any,
    new_asset_id: Any,
    *,
    confirmed: bool = False,
) -> dict[str, Any]:
    """Replace a clip's pinned Asset, only with explicit confirmation.

    Without ``confirmed=True`` the replacement is refused as a
    state failure (reported, not raised) and the clip is left
    exactly as it was. With confirmation, the old Asset is
    recorded in ``replaced_from`` and the active Take is cleared,
    because a Take chosen for the old Asset is not a Take of
    the new one.
    """
    project = _copy(_project(project))
    clip = _clip(project, clip_id)
    _asset(project, new_asset_id, what="replacement asset")
    if confirmed is not True:
        return {
            "project": project,
            "applied": False,
            "code": "replacement_needs_confirmation",
            "detail": (
                f"replacing clip {clip_id!r} asset {clip['asset_id']!r} "
                f"with {new_asset_id!r} needs explicit confirmation; "
                "the clip was not changed"
            ),
        }
    clip["replaced_from"].append(clip["asset_id"])
    clip["asset_id"] = new_asset_id
    clip["original_asset_id"] = new_asset_id
    clip["active_take_id"] = None
    return {"project": project, "applied": True, "code": None, "detail": ""}


# ------------------------------------------------------------------ A3 takes

def add_take(
    project: Any,
    clip_id: Any,
    take_id: Any,
    asset_id: Any,
    *,
    duration_sec: Any,
    source: Any,
) -> dict[str, Any]:
    """Add one Take (an alternative Asset) to a clip slot."""
    project = _copy(_project(project))
    clip = _clip(project, clip_id)
    if not isinstance(take_id, str) or not take_id:
        _fail("take_id must be a non-empty string")
    if any(take["take_id"] == take_id for take in clip["takes"]):
        _fail(f"take already exists on clip {clip_id!r}: {take_id!r}")
    _asset(project, asset_id)
    if not _is_num(duration_sec) or float(duration_sec) <= 0:
        _fail("take duration_sec must be a positive number")
    if source not in TAKE_SOURCES:
        _fail(f"take source must be one of {sorted(TAKE_SOURCES)}, got {source!r}")
    clip["takes"].append(
        {
            "take_id": take_id,
            "clip_id": clip_id,
            "asset_id": asset_id,
            "duration_sec": float(duration_sec),
            "source": source,
            "status": "ready",
        }
    )
    return project


def effective_asset_id(project: Any, clip_id: Any) -> str:
    """The Asset a clip actually shows: its active Take, else its pin."""
    clip = _clip(_project(project), clip_id)
    active = clip["active_take_id"]
    if active is None:
        return str(clip["asset_id"])
    take = next(t for t in clip["takes"] if t["take_id"] == active)
    return str(take["asset_id"])


def activate_take(project: Any, clip_id: Any, take_id: Any) -> dict[str, Any]:
    """Activate a Take without moving the clip or losing the Original.

    A Take shorter than the clip slot is refused: activating it
    would leave a frozen tail frame in an export.
    """
    project = _copy(_project(project))
    clip = _clip(project, clip_id)
    take = next(
        (t for t in clip["takes"] if t["take_id"] == take_id), None
    )
    if take is None:
        _fail(f"unknown take on clip {clip_id!r}: {take_id!r}")
    if take["duration_sec"] + 1e-9 < clip["duration_sec"]:
        return {
            "project": project,
            "applied": False,
            "code": "take_too_short",
            "detail": (
                f"take {take_id!r} covers {take['duration_sec']}s, "
                f"shorter than clip {clip_id!r} slot "
                f"{clip['duration_sec']}s; activation refused"
            ),
        }
    clip["active_take_id"] = take_id
    return {"project": project, "applied": True, "code": None, "detail": ""}


def restore_original(project: Any, clip_id: Any) -> dict[str, Any]:
    """Restore the Original Asset: clear the active Take, keep the Takes."""
    project = _copy(_project(project))
    clip = _clip(project, clip_id)
    if clip["active_take_id"] is None:
        return {
            "project": project,
            "applied": False,
            "code": "no_active_take",
            "detail": f"clip {clip_id!r} has no active Take to restore from",
        }
    clip["active_take_id"] = None
    return {"project": project, "applied": True, "code": None, "detail": ""}


# ------------------------------------------------------- A4 lineage vs edges

def add_edge(project: Any, from_node: Any, to_node: Any) -> dict[str, Any]:
    """Add a visual canvas edge. It creates NO lineage entry."""
    project = _copy(_project(project))
    if not isinstance(from_node, str) or not from_node:
        _fail("edge from_node must be a non-empty string")
    if not isinstance(to_node, str) or not to_node:
        _fail("edge to_node must be a non-empty string")
    edge = {"from_node": from_node, "to_node": to_node}
    if edge in project["edges"]:
        _fail(f"edge already exists: {edge}")
    project["edges"].append(edge)
    return project


def remove_edge(project: Any, from_node: Any, to_node: Any) -> dict[str, Any]:
    """Remove a visual canvas edge. Lineage is untouched."""
    project = _copy(_project(project))
    edge = {"from_node": from_node, "to_node": to_node}
    if edge not in project["edges"]:
        _fail(f"unknown edge: {edge}")
    project["edges"] = [e for e in project["edges"] if e != edge]
    return project


# ------------------------------------------------------- revision / CAS path

def _apply_op(
    project: dict[str, Any], op: str, payload: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Run one incremental op. Returns (project, state-failure or None)."""
    if op == "register_asset":
        return (
            register_asset(
                project,
                payload.get("asset_id"),
                payload.get("kind"),
                generation_id=payload.get("generation_id"),
                derived_from=payload.get("derived_from"),
            ),
            None,
        )
    if op == "add_view_reference":
        return (
            add_view_reference(
                project,
                payload.get("view_id"),
                payload.get("kind"),
                payload.get("asset_id"),
            ),
            None,
        )
    if op == "remove_view_reference":
        return (
            remove_view_reference(project, payload.get("view_id")),
            None,
        )
    if op == "set_pinned_output":
        return (
            set_pinned_output(
                project, payload.get("generation_id"), payload.get("asset_id")
            ),
            None,
        )
    if op == "add_clip":
        return (
            add_clip(
                project,
                payload.get("clip_id"),
                payload.get("asset_id"),
                start_sec=payload.get("start_sec"),
                in_sec=payload.get("in_sec"),
                out_sec=payload.get("out_sec"),
                duration_sec=payload.get("duration_sec"),
            ),
            None,
        )
    if op == "replace_clip_asset":
        outcome = replace_clip_asset(
            project,
            payload.get("clip_id"),
            payload.get("new_asset_id"),
            confirmed=payload.get("confirmed", False),
        )
        if not outcome["applied"]:
            return outcome["project"], {
                "code": outcome["code"],
                "detail": outcome["detail"],
            }
        return outcome["project"], None
    if op == "add_take":
        return (
            add_take(
                project,
                payload.get("clip_id"),
                payload.get("take_id"),
                payload.get("asset_id"),
                duration_sec=payload.get("duration_sec"),
                source=payload.get("source"),
            ),
            None,
        )
    if op == "activate_take":
        outcome = activate_take(
            project, payload.get("clip_id"), payload.get("take_id")
        )
        if not outcome["applied"]:
            return outcome["project"], {
                "code": outcome["code"],
                "detail": outcome["detail"],
            }
        return outcome["project"], None
    if op == "restore_original":
        outcome = restore_original(project, payload.get("clip_id"))
        if not outcome["applied"]:
            return outcome["project"], {
                "code": outcome["code"],
                "detail": outcome["detail"],
            }
        return outcome["project"], None
    if op == "add_edge":
        return (
            add_edge(
                project, payload.get("from_node"), payload.get("to_node")
            ),
            None,
        )
    if op == "remove_edge":
        return (
            remove_edge(
                project, payload.get("from_node"), payload.get("to_node")
            ),
            None,
        )
    _fail(f"unknown editorial operation: {op!r}")


def apply_command(
    project: Any,
    command: Any,
    *,
    expected_revision: Any,
    idempotency_key: Any,
) -> dict[str, Any]:
    """Apply one incremental command under revision check + idempotency.

    ``command`` is ``{"op", "payload", "command_id"?}``. A replayed
    idempotency key returns the stored receipt and applies nothing.
    A stale expected revision is a conflict: nothing is applied.
    A whole-document replacement op is refused: nothing is
    applied. On success the revision advances by exactly one and
    a receipt is stored under the idempotency key. The input
    project is never mutated.
    """
    original = _project(project)
    if not isinstance(command, dict):
        _fail("command must be an object")
    op = command.get("op")
    if not isinstance(op, str) or not op:
        _fail("command op must be a non-empty string")
    payload = command.get("payload", {})
    if not isinstance(payload, dict):
        _fail("command payload must be an object")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        _fail("idempotency_key must be a non-empty string")
    if not isinstance(expected_revision, int) or isinstance(
        expected_revision, bool
    ):
        _fail("expected_revision must be an integer")

    if idempotency_key in original["receipts"]:
        return {
            "project": _copy(original),
            "applied": False,
            "replayed": True,
            "receipt": copy.deepcopy(original["receipts"][idempotency_key]),
            "code": None,
        }
    if op in _WHOLE_REPLACE_OPS:
        return {
            "project": _copy(original),
            "applied": False,
            "replayed": False,
            "code": "whole_replace_refused",
            "detail": (
                f"operation {op!r} replaces the whole document and is "
                "refused; writes must be incremental operations"
            ),
        }
    if expected_revision != original["revision"]:
        return {
            "project": _copy(original),
            "applied": False,
            "replayed": False,
            "code": "revision_conflict",
            "current_revision": original["revision"],
            "expected_revision": expected_revision,
            "detail": (
                f"expected revision {expected_revision}, current is "
                f"{original['revision']}; nothing was applied"
            ),
        }
    updated, failure = _apply_op(_copy(original), op, payload)
    if failure is not None:
        return {
            "project": _copy(original),
            "applied": False,
            "replayed": False,
            "code": failure["code"],
            "detail": failure["detail"],
        }
    updated["revision"] = original["revision"] + 1
    receipt = {
        "idempotency_key": idempotency_key,
        "command_id": command.get("command_id"),
        "op": op,
        "revision": updated["revision"],
    }
    updated["receipts"][idempotency_key] = receipt
    updated["history"].append(
        {
            "revision": updated["revision"],
            "op": op,
            "command_id": command.get("command_id"),
        }
    )
    return {
        "project": updated,
        "applied": True,
        "replayed": False,
        "receipt": receipt,
        "code": None,
    }


_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "project_id": {"type": "string"},
        "project": {"type": "object"},
        "commands": {"type": "array"},
    },
    "required": ["project_id", "commands"],
    "additionalProperties": False,
}


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    project = params.get("project")
    if project is None:
        project = create_project(str(params["project_id"]))
    outcomes: list[dict[str, Any]] = []
    for raw in params["commands"]:
        if not isinstance(raw, dict):
            _fail("commands must be objects")
        outcome = apply_command(
            project,
            {"op": raw.get("op"), "payload": raw.get("payload", {}),
             "command_id": raw.get("command_id")},
            expected_revision=raw.get("expected_revision", project["revision"]),
            idempotency_key=str(raw.get("idempotency_key", "")),
        )
        project = outcome["project"]
        outcomes.append(
            {
                "op": raw.get("op"),
                "applied": outcome["applied"],
                "replayed": outcome.get("replayed", False),
                "code": outcome.get("code"),
                "revision": project["revision"],
            }
        )
    report = {"project": project, "outcomes": outcomes}
    report_path = out_dir / "editorial_project_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "revision": project["revision"],
            "applied": sum(1 for o in outcomes if o["applied"]),
            "refused": [o for o in outcomes if not o["applied"]],
        },
    )


def register_editorial_project_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="edit.editorial_project",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Editorial project model: Asset-first references, "
                "clips pinned to concrete Assets, Takes with "
                "Original restore, lineage stored separately from "
                "canvas edges, and a revision-checked, idempotent "
                "incremental write path that refuses whole-document "
                "replacement. Model only; no rendering, no export, "
                "no provider calls."
            ),
            line="edit",
        )
    )
    return ["edit.editorial_project"]


register_editorial_project_capabilities_once()
