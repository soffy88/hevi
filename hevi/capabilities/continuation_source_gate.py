"""Continuation source gate (``qa.continuation_source_gate``).

Clean-room restatement of the "do not invent a reference"
discipline behind the PrefixStream relay method (see
``PREFIXSTREAM_ATTRIBUTION.md``): a continuation segment may only
carry over context that really exists -- the previous segment's
produced latent tail, last frame, or multi-frame reference,
identified by a real product id and its sha256. A source that is
missing, guessed, placeholder-shaped, or self-referential fails.
In particular, a generated first frame must never be silently
promoted into a new reference: references are declared, never
improvised.

One field is actively refused because it does not exist in the
reference implementation: the upstream Clip Bin documentation
mentions a ``tags`` filter, but its record type carries no tags
field anywhere in code. A plan that declares ``tags`` fails here
rather than passing on a field no executor can honour.

This module judges plans only. It never generates, never calls a
model, never touches a budget, and it never reads latent bytes --
the sha256 values it checks are caller-supplied declarations
whose format it validates, not contents it verifies.
"""

from __future__ import annotations

import json
import re
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

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PLACEHOLDER_WORDS = ("placeholder", "todo", "example", "sample", "xxx", "tbd")
_SOURCE_KINDS = ("latent_tail", "last_frame", "multi_frame_ref")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.continuation_source_gate: {detail}"}
    issue.update(extra)
    return issue


def _looks_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(word in lowered for word in _PLACEHOLDER_WORDS)


def check_continuation_source(plan: Any) -> dict[str, Any]:
    """Judge the context sources of a continuation plan.

    ``plan`` is an object with ``segments`` in play order. The
    first segment may declare no source (a fresh start). Every
    later segment must declare ``context_source`` with
    ``source_clip_id`` (non-empty, not placeholder-shaped, not
    its own clip id), ``source_sha256`` (64 lowercase hex digits,
    not all zeros), and ``kind`` (one of ``latent_tail`` /
    ``last_frame`` / ``multi_frame_ref``). Any ``tags`` key on a
    segment or its context source fails, and
    ``auto_reference_from_generated`` true fails.
    Returns ``ok`` / ``issues`` / ``segments``.
    """
    issues: list[dict[str, Any]] = []
    segments_out: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "ok": False,
            "issues": [
                _issue("plan_not_object", "continuation plan must be an object")
            ],
            "segments": segments_out,
        }
    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        return {
            "ok": False,
            "issues": [
                _issue(
                    "segments_missing",
                    "plan must declare a non-empty 'segments' list",
                )
            ],
            "segments": segments_out,
        }
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            issues.append(
                _issue(
                    "segment_not_object",
                    f"segment {index} must be an object",
                    segment_index=index,
                )
            )
            segments_out.append({"segment_index": index, "source_ok": False})
            continue
        entry: dict[str, Any] = {"segment_index": index}
        if "tags" in segment:
            issues.append(
                _issue(
                    "tags_field_unimplemented",
                    f"segment {index}: 'tags' is declared, but no "
                    "tags field exists in the reference record type "
                    "(documentation mention only); declare no tags",
                    segment_index=index,
                )
            )
        if segment.get("auto_reference_from_generated"):
            issues.append(
                _issue(
                    "auto_reference_from_generated",
                    f"segment {index}: a generated first frame must "
                    "not be silently promoted into a new reference; "
                    "references are declared, never improvised",
                    segment_index=index,
                )
            )
        source = segment.get("context_source")
        if index == 0:
            if source is None:
                entry["source_ok"] = True
                entry["fresh_start"] = True
                segments_out.append(entry)
                continue
        if source is None:
            issues.append(
                _issue(
                    "context_source_missing",
                    f"segment {index}: a continuation segment must "
                    "declare 'context_source' with a real product id "
                    "and sha256",
                    segment_index=index,
                )
            )
            entry["source_ok"] = False
            segments_out.append(entry)
            continue
        if not isinstance(source, dict):
            issues.append(
                _issue(
                    "context_source_not_object",
                    f"segment {index}: 'context_source' must be an object",
                    segment_index=index,
                )
            )
            entry["source_ok"] = False
            segments_out.append(entry)
            continue
        if "tags" in source:
            issues.append(
                _issue(
                    "tags_field_unimplemented",
                    f"segment {index}: 'tags' is declared on the "
                    "context source, but no tags field exists in the "
                    "reference record type",
                    segment_index=index,
                )
            )
        source_ok = True
        clip_id = source.get("source_clip_id")
        if not isinstance(clip_id, str) or not clip_id.strip():
            issues.append(
                _issue(
                    "source_clip_id_missing",
                    f"segment {index}: 'source_clip_id' must be a "
                    "non-empty string",
                    segment_index=index,
                )
            )
            source_ok = False
        else:
            if _looks_placeholder(clip_id):
                issues.append(
                    _issue(
                        "source_clip_id_placeholder",
                        f"segment {index}: 'source_clip_id' looks like "
                        f"a placeholder ({clip_id!r}); only a real "
                        "product id passes",
                        segment_index=index,
                    )
                )
                source_ok = False
            own_id = segment.get("clip_id")
            if isinstance(own_id, str) and own_id and clip_id == own_id:
                issues.append(
                    _issue(
                        "source_is_self",
                        f"segment {index}: context source must not be "
                        "the segment itself",
                        segment_index=index,
                    )
                )
                source_ok = False
        sha = source.get("source_sha256")
        if not isinstance(sha, str) or not _SHA256_RE.match(sha):
            issues.append(
                _issue(
                    "source_sha256_malformed",
                    f"segment {index}: 'source_sha256' must be 64 "
                    "lowercase hex digits",
                    segment_index=index,
                )
            )
            source_ok = False
        elif sha == "0" * 64:
            issues.append(
                _issue(
                    "source_sha256_zero",
                    f"segment {index}: 'source_sha256' is all zeros; "
                    "a real product hash is required",
                    segment_index=index,
                )
            )
            source_ok = False
        kind = source.get("kind")
        if kind not in _SOURCE_KINDS:
            issues.append(
                _issue(
                    "source_kind_unknown",
                    f"segment {index}: 'kind' must be one of "
                    f"{', '.join(_SOURCE_KINDS)}, got {kind!r}",
                    segment_index=index,
                )
            )
            source_ok = False
        entry["source_ok"] = source_ok
        segments_out.append(entry)
    return {"ok": not issues, "issues": issues, "segments": segments_out}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_continuation_source(params.get("plan"))
    report_path = out_dir / "continuation_source_gate.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path),
            "verdict": "pass" if report["ok"] else "fail"},
    )


def register_continuation_source_gate_capabilities_once() -> list[str]:
    """Register ``qa.continuation_source_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.continuation_source_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Continuation source gate: every continuation "
                "segment must name a real context source (product "
                "id + sha256 + kind); placeholder, self, or "
                "invented sources fail, as do the unimplemented "
                "'tags' field and auto-promoted references. "
                "Judges plans only; no generation, no keys."
            ),
            line="qa",
        )
    )
    return ["qa.continuation_source_gate"]


register_continuation_source_gate_capabilities_once()
