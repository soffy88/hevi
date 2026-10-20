"""Cross-line review-sheet capability (``qa.review_sheet``).

Wraps :func:`hevi.quality.review_sheet.build_review_sheet` — the
generic "structured review comments + frame grab at each comment's
timestamp + assembled sheet" tool — as one registry capability,
following the ``export_qa.py`` registration pattern.

Unlike ``qa.export_gate`` (a pass/fail verdict on a finished export),
this capability *produces the review record itself*: it normalises a
comment list or folds an append-only event log, grabs one frame per
comment, and writes ``review_sheet.json`` + ``review.md`` under
``out_dir``.  ``CapabilityResult.mp4`` points back at the source media
(the export_gate convention for analysis capabilities: the report is
*on* the input artefact, no new media is rendered).  Invalid records
— including any comment timestamp past the media duration — raise
``CapabilityError`` and the whole sheet is rejected; nothing is
silently clamped or skipped.
"""

from __future__ import annotations

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


def _render_review_sheet(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.quality.review_sheet import ReviewSheetError, build_review_sheet

    media_path = Path(params["media_path"])
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not media_path.is_file():
        raise CapabilityError(f"qa.review_sheet: media file not found: {media_path}")

    comments = params.get("comments")
    events = params.get("events")
    if (comments is None) == (events is None):
        raise CapabilityError(
            "qa.review_sheet: provide exactly one of 'comments' / 'events'"
        )
    payload: Any = events if events is not None else comments

    try:
        report = build_review_sheet(media_path, payload, out_dir)
    except ReviewSheetError as exc:
        raise CapabilityError(f"qa.review_sheet: {exc}") from exc
    except Exception as exc:
        raise CapabilityError(f"qa.review_sheet failed: {exc}") from exc

    probe = report.get("probe") or {}
    return CapabilityResult(
        mp4=str(media_path),
        duration_s=float(probe.get("duration_s") or 0.0),
        sha256=compute_sha256(media_path),
        qa={
            "report": str(out_dir / "review_sheet.json"),
            "sheet_md": str(out_dir / "review.md"),
            "comments": int(report["count"]),
            "comment_count": int(report["count"]),
            "by_status": report["by_status"],
            "pass": bool(report["pass"]),
        },
    )


def register_review_sheet_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    registered: list[str] = []

    register(
        Capability(
            name="qa.review_sheet",
            kind="video",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "media_path": {
                        "type": "string",
                        "description": "Local media file the comments refer to",
                    },
                    "comments": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Comment records: {film, shot, "
                        "timestamp_s, scene, element, comment, status?}; "
                        "status defaults to pending, id is derived "
                        "deterministically when omitted",
                    },
                    "events": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Append-only event log folded into "
                        "comments: {type: comment|claim|done|reopen|cancel, "
                        "id, note, ...comment fields on comment events}",
                    },
                },
                "required": ["media_path"],
                "anyOf": [
                    {"required": ["comments"]},
                    {"required": ["events"]},
                ],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.5,
            render=_render_review_sheet,
            description=(
                "Generic cross-line review sheet (local, offline): takes "
                "review comments on a media file — either a comment list "
                "({film, shot, timestamp_s, scene, element, comment, "
                "status in pending|working|done|reopened|cancelled}) or "
                "an append-only event log (comment|claim|done|reopen|"
                "cancel, folded in order into current status + thread) — "
                "grabs one frame per comment at its timestamp_s, and "
                "writes review_sheet.json (ffprobe info + normalised "
                "records with frame paths) plus a human review.md sheet "
                "under out_dir. Any invalid record or a timestamp past "
                "the media duration rejects the whole sheet with "
                "CapabilityError (no silent clamping). Result mp4 "
                "points back at the source media; qa carries the report "
                "paths, comment count, by_status counts and pass."
            ),
            line="qa",
        )
    )
    registered.append("qa.review_sheet")

    return registered
