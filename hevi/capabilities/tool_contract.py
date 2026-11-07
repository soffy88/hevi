"""Tool-boundary readback verification for canvas / executor tools.

Hard rule, stated once and enforced by ``execute_tool``:

* Every write operation (edit the timeline, change state, write a
  file) MUST be verified by reading back through the tool boundary
  after the write. If the readback disagrees with what the write
  claimed, the tool raises and the caller gets an error -- never a
  success response for a write that did not land.
* A success response is therefore never proof of completion; the
  readback state is. Handlers return what they claim (``expected_after``);
  the readback function reports what is actually there; the two must
  agree on every key the handler claimed.
* A write tool with no readback function is refused at execution
  time: an unverifiable write is not executed at all.

Granularity: tools are split by category, never one big tool:

* ``read_state`` -- reads only, no readback required, must not mutate.
* ``edit_timeline`` -- appends / changes timeline entries.
* ``generate`` -- runs a registered generator, then registers its
  output on the timeline (same readback rule as any write).
* ``export`` -- writes a file, then reads that file back and
  compares it with the in-memory state.
* ``undo`` -- removes the last entry; verified like any write.

Machine contract vs UI copy: a ``ToolSpec`` carries ``params_schema``
(JSON Schema, machine-readable, types and constraints only) and a
separate ``ui`` dict (label, hint, confirm text). UI copy is never
embedded in the schema, and the schema is never used as display text;
``tool_descriptor`` returns both side by side so a UI can render one
and a validator can enforce the other.

This module is written from scratch for hevi. It wraps the pure
timeline state from ``timeline_register`` (no network, no generation
API, no desktop UI) so the rule can be tested offline, including the
failure case where a handler claims success but the store disagrees.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from hevi.capabilities.errors import CapabilityError

TOOL_CATEGORIES = ("read_state", "edit_timeline", "generate", "export", "undo")
WRITE_CATEGORIES = ("edit_timeline", "generate", "export", "undo")


class ToolVerificationError(CapabilityError):
    """A write whose readback disagrees with its claim. Never a success."""


@dataclass
class ToolSpec:
    """One tool: machine schema, UI copy, handler, readback -- kept apart."""

    name: str
    category: str
    params_schema: dict[str, Any]
    ui: dict[str, str]
    handler: Callable[[dict[str, Any], Any], dict[str, Any]]
    readback: Callable[[dict[str, Any], Any, dict[str, Any]], dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self.category not in TOOL_CATEGORIES:
            raise CapabilityError(
                f"tool_contract: unknown tool category {self.category!r}; "
                f"want one of {', '.join(TOOL_CATEGORIES)}"
            )
        if not isinstance(self.params_schema, dict) or self.params_schema.get("type") != "object":
            raise CapabilityError(
                f"tool_contract: tool {self.name!r} params_schema must be a JSON Schema object"
            )
        if not isinstance(self.ui, dict) or not self.ui.get("label"):
            raise CapabilityError(
                f"tool_contract: tool {self.name!r} requires ui.label (UI copy lives in ui, not in the schema)"
            )


def validate_params(spec: ToolSpec, params: dict[str, Any]) -> dict[str, Any]:
    """Validate params against the tool's machine schema; refuse, don't wave through."""
    try:
        import jsonschema
    except Exception as exc:  # pragma: no cover - jsonschema is present in CI
        raise CapabilityError(f"tool_contract: cannot validate params, jsonschema unavailable: {exc}") from exc
    try:
        jsonschema.validate(instance=params, schema=spec.params_schema)
    except Exception as exc:
        raise CapabilityError(f"tool_contract: tool {spec.name!r} params invalid: {exc}") from exc
    return params


def execute_tool(spec: ToolSpec, params: dict[str, Any], store: Any) -> dict[str, Any]:
    """Run one tool through the boundary, with readback for every write.

    Returns the handler result plus ``verified_state`` (the readback
    observation). For write categories, a missing readback, a missing
    ``expected_after`` claim, or any claimed key that the readback
    does not match raises ToolVerificationError -- the caller must
    treat that as "the write did not happen", whatever the handler
    printed before failing.
    """
    validate_params(spec, params)
    if spec.category in WRITE_CATEGORIES and spec.readback is None:
        raise ToolVerificationError(
            f"tool_contract: write tool {spec.name!r} ({spec.category}) has no "
            "readback function and is refused: an unverifiable write is "
            "never executed"
        )
    result = spec.handler(params, store)
    if not isinstance(result, dict):
        raise ToolVerificationError(f"tool_contract: tool {spec.name!r} handler must return a dict result")
    if spec.category == "read_state":
        return dict(result)
    expected = result.get("expected_after")
    if not isinstance(expected, dict) or not expected:
        raise ToolVerificationError(
            f"tool_contract: write tool {spec.name!r} returned no expected_after "
            "claim, so there is nothing to verify against; treated as failure"
        )
    observed = spec.readback(params, store, result)  # type: ignore[misc]
    if not isinstance(observed, dict):
        raise ToolVerificationError(f"tool_contract: tool {spec.name!r} readback must return a dict")
    mismatches = {k: {"expected": v, "observed": observed.get(k, "<absent>")} for k, v in expected.items() if observed.get(k) != v}
    if mismatches:
        raise ToolVerificationError(
            f"tool_contract: tool {spec.name!r} readback mismatch (write did NOT "
            f"land as claimed): {json.dumps(mismatches, ensure_ascii=False, sort_keys=True)}"
        )
    out = dict(result)
    out["verified_state"] = observed
    return out


def tool_descriptor(spec: ToolSpec) -> dict[str, Any]:
    """Machine contract and UI copy, side by side but never merged."""
    return {
        "name": spec.name,
        "category": spec.category,
        "params_schema": copy.deepcopy(spec.params_schema),
        "ui": dict(spec.ui),
    }


# ---------------------------------------------------------------------------
# Built-in tools over a timeline state dict (see timeline_register.py).
# The store is the timeline state dict itself; export tools additionally
# write one JSON file whose path comes from params.
# ---------------------------------------------------------------------------

_GENERATORS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def register_generator(name: str, fn: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
    """Register an in-process generator for the generate tool (tests and
    offline callers supply fakes; no real generation API is called here)."""
    _GENERATORS[name] = fn


def _timeline_readback(_params: dict[str, Any], store: Any, _result: dict[str, Any]) -> dict[str, Any]:
    from hevi.capabilities.timeline_register import read_timeline

    snap = read_timeline(store)
    return {
        "clip_ids": [c["clip_id"] for c in snap["clips"]],
        "clip_count": snap["clip_count"],
        "last_end_sec": max((float(c["timeline_end_sec"]) for c in snap["clips"]), default=0.0),
    }


def _read_handler(params: dict[str, Any], store: Any) -> dict[str, Any]:
    from hevi.capabilities.timeline_register import read_timeline

    return {"action": "read", "timeline": read_timeline(store)}


def _append_handler(params: dict[str, Any], store: Any) -> dict[str, Any]:
    from hevi.capabilities.timeline_register import register_generation

    new_state, entry = register_generation(store, {
        "clip_id": params["clip_id"],
        "file": params["file"],
        "duration_sec": params["duration_sec"],
        "track": params.get("track"),
        "source_model": params.get("source_model"),
        "source_capability": params.get("source_capability"),
        "estimated_cost_usd": params.get("estimated_cost_usd"),
    })
    store.clear()
    store.update(new_state)
    snap_ids = [c["clip_id"] for c in new_state["clips"]]
    return {
        "action": "append",
        "entry": entry,
        "expected_after": {
            "clip_ids": snap_ids,
            "clip_count": len(snap_ids),
            "last_end_sec": float(entry["timeline_end_sec"]),
        },
    }


def _undo_handler(params: dict[str, Any], store: Any) -> dict[str, Any]:
    clips = store.get("clips", [])
    if not clips:
        raise CapabilityError("tool_contract: undo on an empty timeline")
    track = params.get("track")
    candidates = [c for c in clips if track is None or c["track"] == track]
    if not candidates:
        raise CapabilityError(f"tool_contract: undo found no clip on track {track!r}")
    removed = candidates[-1]
    remaining = [c for c in clips if c["clip_id"] != removed["clip_id"]]
    store["clips"] = remaining
    if remaining:
        store["last_track"] = remaining[-1]["track"]
    return {
        "action": "undo",
        "removed_clip_id": removed["clip_id"],
        "expected_after": {
            "clip_ids": [c["clip_id"] for c in remaining],
            "clip_count": len(remaining),
            "last_end_sec": max((float(c["timeline_end_sec"]) for c in remaining), default=0.0),
        },
    }


def _export_handler(params: dict[str, Any], store: Any) -> dict[str, Any]:
    from hevi.capabilities.timeline_register import read_timeline

    path = Path(str(params["path"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = read_timeline(store)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return {
        "action": "export",
        "path": str(path),
        "expected_after": {"exported_clip_count": snapshot["clip_count"]},
    }


def _export_readback(params: dict[str, Any], _store: Any, _result: dict[str, Any]) -> dict[str, Any]:
    data = json.loads(Path(str(params["path"])).read_text(encoding="utf-8"))
    return {"exported_clip_count": int(data["clip_count"])}


def _generate_handler(params: dict[str, Any], store: Any) -> dict[str, Any]:
    from hevi.capabilities.timeline_register import register_generation

    name = str(params["generator"])
    fn = _GENERATORS.get(name)
    if fn is None:
        raise CapabilityError(f"tool_contract: unknown generator {name!r}; register one with register_generator first")
    clip = fn(params)
    if not isinstance(clip, dict):
        raise CapabilityError(f"tool_contract: generator {name!r} must return a clip dict")
    new_state, entry = register_generation(store, clip)
    store.clear()
    store.update(new_state)
    return {
        "action": "generate",
        "entry": entry,
        "expected_after": {
            "clip_ids": [c["clip_id"] for c in new_state["clips"]],
            "clip_count": len(new_state["clips"]),
            "last_end_sec": float(entry["timeline_end_sec"]),
        },
    }


def builtin_tools() -> list[ToolSpec]:
    """The five granularity-split tools, one per category."""
    clip_schema_extra = {
        "track": {"type": "string"},
        "source_model": {"type": "string"},
        "source_capability": {"type": "string"},
        "estimated_cost_usd": {"type": ["number", "null"]},
    }
    return [
        ToolSpec(
            name="timeline.read",
            category="read_state",
            params_schema={"type": "object", "properties": {}, "additionalProperties": False},
            ui={"label": "查看时间线", "hint": "只读，不改动任何内容。"},
            handler=_read_handler,
        ),
        ToolSpec(
            name="timeline.append",
            category="edit_timeline",
            params_schema={
                "type": "object",
                "properties": {
                    "clip_id": {"type": "string", "minLength": 1},
                    "file": {"type": "string", "minLength": 1},
                    "duration_sec": {"type": "number", "exclusiveMinimum": 0},
                    **clip_schema_extra,
                },
                "required": ["clip_id", "file", "duration_sec"],
                "additionalProperties": False,
            },
            ui={"label": "把生成结果入轨", "hint": "生成产物追加到时间线末尾，写入后立即读回核对。"},
            handler=_append_handler,
            readback=_timeline_readback,
        ),
        ToolSpec(
            name="timeline.generate",
            category="generate",
            params_schema={
                "type": "object",
                "properties": {
                    "generator": {"type": "string", "minLength": 1},
                    "prompt": {"type": "string"},
                },
                "required": ["generator"],
                "additionalProperties": True,
            },
            ui={"label": "生成并入轨", "hint": "先生成，再把产物登记进时间线；读回不一致即报错。"},
            handler=_generate_handler,
            readback=_timeline_readback,
        ),
        ToolSpec(
            name="timeline.export",
            category="export",
            params_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "minLength": 1}},
                "required": ["path"],
                "additionalProperties": False,
            },
            ui={"label": "导出时间线", "hint": "写出 JSON 后重新读回文件核对，数量不一致即报错。"},
            handler=_export_handler,
            readback=_export_readback,
        ),
        ToolSpec(
            name="timeline.undo",
            category="undo",
            params_schema={
                "type": "object",
                "properties": {"track": {"type": "string"}},
                "additionalProperties": False,
            },
            ui={"label": "撤销上一条", "hint": "移除时间线最后一条，写入后立即读回核对。"},
            handler=_undo_handler,
            readback=_timeline_readback,
        ),
    ]


def builtin_tool_map() -> dict[str, ToolSpec]:
    return {spec.name: spec for spec in builtin_tools()}
