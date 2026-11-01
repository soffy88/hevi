"""Clip lineage schema (``qa.clip_lineage_schema``).

Clean-room restatement of the clip-bin record discipline behind
the PrefixStream relay method (see
``PREFIXSTREAM_ATTRIBUTION.md``): every produced clip is recorded
with its prompt, its shape, a human rating, and -- when it
continues another clip -- its parent. A branch is a *selection*:
any recorded clip may be chosen as the relay source of a later
one, so the lineage forms a DAG of parent links. It is never a
version fork: there is no forked storage, no divergent copy, and
no claim that two children of one parent are versions of each
other.

Rating is human only. The record carries a 1-5 star rating plus
``rating_source`` which must read ``"manual"``; an absent source
fails (an unmarked rating could be anything), and an automatic
source fails outright -- there is no automatic quality score in
this discipline, and none may be smuggled in under the rating
field.

This module judges records only. It stores no latent, no preview
image, and no media; the execution-side bin (B2) waits on a GPU
and a ComfyUI install. No author-reported number lives here as a
default: the 1-5 range is the discipline's own scale, and every
value is caller-declared.
"""

from __future__ import annotations

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

_RATING_MIN = 1
_RATING_MAX = 5


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.clip_lineage_schema: {detail}"}
    issue.update(extra)
    return issue


def lineage_chain(records: list[dict[str, Any]], clip_id: str) -> list[str]:
    """Follow ``parent_clip_id`` links from ``clip_id`` to a root.

    Returns the chain of clip ids, starting at ``clip_id``. Stops
    at a record whose parent is null, at a missing parent (the
    caller judges that separately), or at a repeated id (a cycle).
    """
    by_id = {r.get("clip_id"): r for r in records if isinstance(r, dict)}
    chain: list[str] = []
    seen: set[str] = set()
    current: Any = clip_id
    while isinstance(current, str) and current and current not in seen:
        seen.add(current)
        chain.append(current)
        record = by_id.get(current)
        if record is None:
            break
        current = record.get("parent_clip_id")
    return chain


def check_clip_lineage(records: Any) -> dict[str, Any]:
    """Judge a list of clip records against the lineage schema.

    Each record needs ``clip_id`` (non-empty, unique), ``prompt``
    (non-empty), ``rating`` (an integer 1-5) with
    ``rating_source`` exactly ``"manual"``, and ``shape`` (positive
    ``frames`` / ``width`` / ``height`` / ``fps``). ``parent_clip_id``
    must be null for a root or name a record in the same list; a
    cycle fails. A record that declares a branch must declare
    ``branch_semantics`` ``"dag_selection"``; ``"version_fork"``
    (or any other fork wording) fails.
    Returns ``ok`` / ``issues`` / ``records`` (each annotated with
    its lineage chain).
    """
    issues: list[dict[str, Any]] = []
    records_out: list[dict[str, Any]] = []
    if not isinstance(records, list) or not records:
        return {
            "ok": False,
            "issues": [
                _issue(
                    "records_missing",
                    "a non-empty list of clip records is required",
                )
            ],
            "records": records_out,
        }
    ids: list[str] = []
    for record in records:
        if isinstance(record, dict) and isinstance(record.get("clip_id"), str):
            ids.append(record["clip_id"])
    id_set = set(ids)
    seen_ids: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            issues.append(
                _issue(
                    "record_not_object",
                    f"record {index} must be an object",
                    record_index=index,
                )
            )
            records_out.append({"record_index": index, "chain": []})
            continue
        clip_id = record.get("clip_id")
        entry: dict[str, Any] = {"record_index": index, "clip_id": clip_id}
        if not isinstance(clip_id, str) or not clip_id.strip():
            issues.append(
                _issue(
                    "clip_id_missing",
                    f"record {index}: 'clip_id' must be a non-empty string",
                    record_index=index,
                )
            )
        elif clip_id in seen_ids:
            issues.append(
                _issue(
                    "clip_id_duplicate",
                    f"record {index}: clip_id {clip_id!r} is declared twice",
                    record_index=index,
                )
            )
        seen_ids.add(clip_id) if isinstance(clip_id, str) else None
        prompt = record.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            issues.append(
                _issue(
                    "prompt_missing",
                    f"record {index}: 'prompt' must be a non-empty string",
                    record_index=index,
                )
            )
        rating = record.get("rating")
        if (
            not isinstance(rating, int)
            or isinstance(rating, bool)
            or rating < _RATING_MIN
            or rating > _RATING_MAX
        ):
            issues.append(
                _issue(
                    "rating_out_of_range",
                    f"record {index}: 'rating' must be an integer "
                    f"{_RATING_MIN}-{_RATING_MAX}, got {rating!r}",
                    record_index=index,
                )
            )
        rating_source = record.get("rating_source")
        if rating_source is None:
            issues.append(
                _issue(
                    "rating_source_missing",
                    f"record {index}: 'rating_source' must be declared "
                    "as 'manual'; an unmarked rating could be anything",
                    record_index=index,
                )
            )
        elif rating_source != "manual":
            issues.append(
                _issue(
                    "rating_not_manual",
                    f"record {index}: rating is human only; "
                    f"'rating_source' must be 'manual', got "
                    f"{rating_source!r}",
                    record_index=index,
                )
            )
        shape = record.get("shape")
        if not isinstance(shape, dict):
            issues.append(
                _issue(
                    "shape_missing",
                    f"record {index}: 'shape' must be an object with "
                    "frames/width/height/fps",
                    record_index=index,
                )
            )
        else:
            for field in ("frames", "width", "height", "fps"):
                value = shape.get(field)
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or float(value) <= 0
                ):
                    issues.append(
                        _issue(
                            "shape_field_invalid",
                            f"record {index}: shape '{field}' must be a "
                            f"positive number, got {value!r}",
                            record_index=index,
                        )
                    )
        parent = record.get("parent_clip_id")
        if parent is not None:
            if not isinstance(parent, str) or not parent.strip():
                issues.append(
                    _issue(
                        "parent_clip_id_invalid",
                        f"record {index}: 'parent_clip_id' must be null "
                        "or a non-empty string",
                        record_index=index,
                    )
                )
            elif parent not in id_set:
                issues.append(
                    _issue(
                        "parent_clip_id_unknown",
                        f"record {index}: parent {parent!r} names no "
                        "record in this list",
                        record_index=index,
                    )
                )
            elif parent == clip_id:
                issues.append(
                    _issue(
                        "parent_is_self",
                        f"record {index}: a clip must not be its own parent",
                        record_index=index,
                    )
                )
        if record.get("branch") is not None or "branch_from" in record:
            semantics = record.get("branch_semantics")
            if semantics != "dag_selection":
                issues.append(
                    _issue(
                        "branch_semantics_not_dag",
                        f"record {index}: a branch is a DAG selection "
                        "-- any recorded clip may be chosen as a relay "
                        "source -- not a version fork; "
                        "'branch_semantics' must be 'dag_selection', "
                        f"got {semantics!r}",
                        record_index=index,
                    )
                )
        chain = (
            lineage_chain(
                [r for r in records if isinstance(r, dict)], clip_id
            )
            if isinstance(clip_id, str) and clip_id
            else []
        )
        # A cycle is a parent walk that revisits an id: lineage_chain
        # stops at the revisit, so re-walk and look for it.
        by_id = {
            r.get("clip_id"): r for r in records if isinstance(r, dict)
        }
        walked: set[str] = set()
        current: Any = clip_id
        while isinstance(current, str) and current and current in by_id:
            if current in walked:
                issues.append(
                    _issue(
                        "lineage_cycle",
                        f"record {index}: parent links form a cycle "
                        f"at {current!r}",
                        record_index=index,
                    )
                )
                break
            walked.add(current)
            current = by_id[current].get("parent_clip_id")
        entry["chain"] = chain
        records_out.append(entry)
    return {"ok": not issues, "issues": issues, "records": records_out}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_clip_lineage(params.get("records"))
    report_path = out_dir / "clip_lineage_schema.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path),
            "verdict": "pass" if report["ok"] else "fail"},
    )


def register_clip_lineage_schema_capabilities_once() -> list[str]:
    """Register ``qa.clip_lineage_schema`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.clip_lineage_schema",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "records": {"type": "array"},
                },
                "required": ["records"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Clip lineage schema: judge clip records for "
                "parent_clip_id lineage, prompt, human 1-5 rating "
                "marked manual, and shape; branches are DAG "
                "selections, never version forks. Judges records "
                "only; stores no media, no generation, no keys."
            ),
            line="qa",
        )
    )
    return ["qa.clip_lineage_schema"]


register_clip_lineage_schema_capabilities_once()
