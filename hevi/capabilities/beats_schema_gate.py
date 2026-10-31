"""Beats schema gate (``qa.beats_schema_gate``).

Strong validation for creator-style-kit beats JSON, learned
from the kit's own ``compose.py`` (threeaus/creator-style-kit,
MIT; field requirements read from that file, no code copied).
A beat with a wrong field name used to die deep inside the
kit's planner with ``KeyError: 'head'`` wrapped in a truncated
traceback. This gate fails *before* scaffolding, naming the
beat index, the beat type and the missing or malformed field.

Schemas (from ``compose.py::plan_beats``):

* ``chapter``: ``title`` is required (``num`` / ``sub`` optional).
* ``list``: ``head`` is required; ``items`` is a list whose
  entries are ``[label]`` or ``[label, value]`` pairs -- a bare
  string item is accepted but reported as a warning, because
  the template renders its value slot as ``0`` (see the
  data-journal finding in ``hevi-vs-hyperframes-deepdive.md``
  §4). A non-string first element fails.
* ``stat``: ``value`` is required (``unit`` / ``note`` /
  ``max`` / ``suffix`` optional).
* Every beat: ``type`` must be one of chapter/list/stat;
  ``dur``, when present, must be a positive number.

Failure contract: a malformed content object (not a JSON
object, missing ``beats`` list, beat not an object) raises
:class:`CapabilityError`. A well-formed content object with
schema violations returns ``verdict: "fail"`` with one issue
per violation, each naming beat index, type and field.
"""

from __future__ import annotations

from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    register,
)

_Registered = False

BEAT_TYPES = ("chapter", "list", "stat")
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "chapter": ("title",),
    "list": ("head",),
    "stat": ("value",),
}


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "message": message}
    issue.update(extra)
    return issue


def check_beats(content: Any) -> dict[str, Any]:
    """Validate a beats content object before scaffolding."""
    if not isinstance(content, dict):
        raise CapabilityError("beats content must be a JSON object")
    beats = content.get("beats")
    if not isinstance(beats, list):
        raise CapabilityError("beats content requires a 'beats' list")
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for index, beat in enumerate(beats):
        if not isinstance(beat, dict):
            raise CapabilityError(f"beat {index} must be a JSON object")
        beat_type = beat.get("type")
        if beat_type not in BEAT_TYPES:
            issues.append(
                _issue(
                    "unknown_beat_type",
                    f"beat {index}: unknown type {beat_type!r} "
                    f"(chapter | list | stat)",
                    beat_index=index,
                    beat_type=beat_type,
                )
            )
            continue
        for field in REQUIRED_FIELDS[beat_type]:
            if field not in beat or beat[field] is None or beat[field] == "":
                issues.append(
                    _issue(
                        "missing_field",
                        f"beat {index} ({beat_type}): missing required "
                        f"field {field!r}",
                        beat_index=index,
                        beat_type=beat_type,
                        field=field,
                    )
                )
        if beat_type == "list" and "items" in beat:
            items = beat["items"]
            if not isinstance(items, list):
                issues.append(
                    _issue(
                        "items_not_list",
                        f"beat {index} (list): 'items' must be a list",
                        beat_index=index,
                        beat_type=beat_type,
                    )
                )
            else:
                for item_index, item in enumerate(items):
                    if isinstance(item, str):
                        warnings.append(
                            _issue(
                                "bare_string_item",
                                f"beat {index} (list): item {item_index} is a "
                                "bare string; the template renders its "
                                "value slot as 0 -- use [label, value]",
                                beat_index=index,
                                beat_type=beat_type,
                                item_index=item_index,
                            )
                        )
                    elif isinstance(item, list):
                        if not item or not isinstance(item[0], str):
                            issues.append(
                                _issue(
                                    "item_label_invalid",
                                    f"beat {index} (list): item {item_index} "
                                    "must start with a string label",
                                    beat_index=index,
                                    beat_type=beat_type,
                                    item_index=item_index,
                                )
                            )
                    else:
                        issues.append(
                            _issue(
                                "item_invalid",
                                f"beat {index} (list): item {item_index} must "
                                "be a string or [label, value] list",
                                beat_index=index,
                                beat_type=beat_type,
                                item_index=item_index,
                            )
                        )
        dur = beat.get("dur")
        if dur is not None:
            if not isinstance(dur, (int, float)) or isinstance(dur, bool) or dur <= 0:
                issues.append(
                    _issue(
                        "dur_invalid",
                        f"beat {index} ({beat_type}): 'dur' must be a "
                        "positive number",
                        beat_index=index,
                        beat_type=beat_type,
                        dur=dur,
                    )
                )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "beats_checked": len(beats),
        "issues": issues,
        "warnings": warnings,
    }


def _render(params: dict[str, Any]) -> CapabilityResult:
    result = check_beats(params.get("content"))
    return CapabilityResult(ok=result["verdict"] == "pass", output=result, files=[])


def register_beats_schema_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.beats_schema_gate",
            kind="line",
            aspects=["9:16"],
            params_schema={
                "type": "object",
                "properties": {"content": {}},
                "required": ["content"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Beats schema gate: validates creator-style-kit beats "
                "JSON before scaffolding -- chapter needs 'title', "
                "list needs 'head' with [label, value] items, stat "
                "needs 'value'; violations fail naming beat index, "
                "type and field instead of dying with KeyError "
                "inside the planner."
            ),
            line="qa",
        )
    )
    return ["qa.beats_schema_gate"]
