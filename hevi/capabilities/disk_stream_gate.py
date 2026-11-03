"""Disk stream gate (``qa.disk_stream_gate``).

Clean-room restatement of the disk-stream discipline behind the
PrefixStream relay method (see ``PREFIXSTREAM_ATTRIBUTION.md``):
a long video is written to disk segment by segment, tracked by a
manifest, and only assembled at the end by concatenation. The
whole film's frames are never held in memory at once. Two
boundaries are policed hard:

1. Geometry is a hard cut. A segment whose geometry (fps, size,
   sample rate, channels) differs from the stream's must be
   *rejected* -- the plan must say so. Appending it anyway fails.
2. The disk stream is a hard cut, not a seam treatment. Seam
   effects (brightness matching, cross-fades, waveform alignment)
   belong to a stitcher-style post step, declared separately.
   A plan that credits the disk stream itself with seam handling
   fails.

This module judges plans only. It never writes media, never
calls ffmpeg, never touches a budget. The execution-side stream
(B1/B2) waits on a GPU and a ComfyUI install.
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

_GEOMETRY_FIELDS = ("fps", "width", "height", "sample_rate", "channels")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.disk_stream_gate: {detail}"}
    issue.update(extra)
    return issue


def check_disk_stream_plan(plan: Any) -> dict[str, Any]:
    """Judge one long-video output plan against the disk-stream rules.

    ``plan`` declares ``output_mode`` (``"disk_stream"`` /
    ``"segmented_disk"``), ``manifest`` true, ``concat`` with
    ``mode`` ``"copy"``, ``in_memory_all_frames`` false,
    ``geometry`` (the stream geometry), ``segments`` (each with
    its own ``geometry`` and ``on_mismatch``), and
    ``seam_handling`` (``"stitcher"`` or ``"hard_cut_declared"``).
    A segment whose geometry differs and whose ``on_mismatch``
    is not ``"reject"`` fails; a plan that holds all frames in
    memory fails; a plan that credits the disk stream with seam
    handling fails. Returns ``ok`` / ``issues`` / ``segments``.
    """
    issues: list[dict[str, Any]] = []
    segments_out: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "ok": False,
            "issues": [
                _issue("plan_not_object", "output plan must be an object")
            ],
            "segments": segments_out,
        }
    mode = plan.get("output_mode")
    if mode not in ("disk_stream", "segmented_disk"):
        issues.append(
            _issue(
                "output_mode_not_disk_stream",
                f"output_mode must be 'disk_stream' or "
                f"'segmented_disk', got {mode!r}",
            )
        )
    if plan.get("manifest") is not True:
        issues.append(
            _issue(
                "manifest_missing",
                "a disk-stream plan must declare 'manifest': true "
                "(segment files plus a manifest, assembled only at "
                "the end)",
            )
        )
    concat = plan.get("concat")
    if not isinstance(concat, dict) or concat.get("mode") != "copy":
        issues.append(
            _issue(
                "concat_not_copy",
                "final assembly must be declared as a copy concat "
                "(no re-encode at assembly time); got "
                f"{concat!r}",
            )
        )
    if plan.get("in_memory_all_frames") is not False:
        issues.append(
            _issue(
                "all_frames_in_memory",
                "holding the whole film's frames in memory at once "
                "fails the disk-stream discipline; segments must be "
                "written to disk as they are produced",
            )
        )
    seam = plan.get("seam_handling")
    if seam in ("disk_stream", "concat", "disk_stream_seam"):
        issues.append(
            _issue(
                "seam_claimed_by_disk_stream",
                "the disk stream is a hard cut: seam effects belong "
                "to a stitcher-style post step and must not be "
                "credited to the disk stream",
            )
        )
    elif seam not in ("stitcher", "hard_cut_declared"):
        issues.append(
            _issue(
                "seam_handling_undeclared",
                "'seam_handling' must be declared as 'stitcher' "
                "(seam effects in a separate post step) or "
                "'hard_cut_declared' (the cut is declared hard); "
                f"got {seam!r}",
            )
        )
    geometry = plan.get("geometry")
    if not isinstance(geometry, dict):
        issues.append(
            _issue(
                "stream_geometry_missing",
                "the stream geometry (fps/width/height/sample_rate/"
                "channels) must be declared",
            )
        )
        geometry = {}
    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        issues.append(
            _issue(
                "segments_missing",
                "plan must declare a non-empty 'segments' list",
            )
        )
        segments = segments if isinstance(segments, list) else []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            issues.append(
                _issue(
                    "segment_not_object",
                    f"segment {index} must be an object",
                    segment_index=index,
                )
            )
            segments_out.append({"segment_index": index, "geometry_ok": False})
            continue
        seg_geometry = segment.get("geometry")
        entry: dict[str, Any] = {"segment_index": index}
        if not isinstance(seg_geometry, dict):
            issues.append(
                _issue(
                    "segment_geometry_missing",
                    f"segment {index}: 'geometry' must be declared",
                    segment_index=index,
                )
            )
            entry["geometry_ok"] = False
            segments_out.append(entry)
            continue
        mismatched = [
            field
            for field in _GEOMETRY_FIELDS
            if field in geometry
            and field in seg_geometry
            and seg_geometry[field] != geometry[field]
        ]
        entry["geometry_mismatch"] = mismatched
        if mismatched:
            on_mismatch = segment.get("on_mismatch")
            if on_mismatch != "reject":
                issues.append(
                    _issue(
                        "geometry_mismatch_not_rejected",
                        f"segment {index}: geometry differs in "
                        f"{', '.join(mismatched)} and must be "
                        "rejected ('on_mismatch': 'reject'); "
                        f"got {on_mismatch!r}",
                        segment_index=index,
                    )
                )
                entry["geometry_ok"] = False
            else:
                entry["geometry_ok"] = True
        else:
            entry["geometry_ok"] = True
        segments_out.append(entry)
    return {"ok": not issues, "issues": issues, "segments": segments_out}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_disk_stream_plan(params.get("plan"))
    report_path = out_dir / "disk_stream_gate.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path),
            "verdict": "pass" if report["ok"] else "fail"},
    )


def register_disk_stream_gate_capabilities_once() -> list[str]:
    """Register ``qa.disk_stream_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.disk_stream_gate",
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
                "Disk stream gate: judge a long-video output plan "
                "for segmented disk writes plus a manifest, copy "
                "concat assembly, geometry-mismatch rejection, and "
                "no whole-film memory hold; seam effects must be "
                "declared as a separate stitcher step, never "
                "credited to the disk stream. Judges plans only."
            ),
            line="qa",
        )
    )
    return ["qa.disk_stream_gate"]


register_disk_stream_gate_capabilities_once()
