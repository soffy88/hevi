"""Publish planning with a dry-run-only result writeback (``edit.publish_plan``).

Clean-room method intake: a publish plan (title, description,
platforms, thumbnail spec, schedule, clips) is validated once,
then result writeback is only accepted as caller-supplied
evidence. This capability never posts to TikTok, Instagram or
YouTube: there are no accounts and no keys in scope, so every
platform starts at ``awaiting_credentials`` and the overall
status is ``dry_run_not_posted`` until the caller records a
real post id for every platform.

Thumbnail spec: text (at most 30 characters, no claim is made
about the image itself) plus an optional image reference. If
no image reference is supplied, the thumbnail is marked
``image_pending`` rather than treated as ready.
Schedule: ``scheduled_at`` must be a parseable ISO-8601
timestamp when supplied; this module does not compare it to
wall-clock time, so a test plan stays deterministic. A plan
with no schedule is ``unscheduled``, not silently scheduled.

Result writeback (``record_publish_result``): the caller
supplies ``platform``, ``post_id`` and ``posted_at``. Only that
platform moves to ``posted``; other platforms stay put. The
overall status becomes ``posted`` only when every planned
platform has a recorded post id. Nothing here contacts a
platform API, and a recorded post id is caller evidence, not
proof this module verified it on the platform.

Failure contract: empty title, title over 100 characters,
description over 5000 characters, unknown or duplicate
platforms, duplicate clip ids, clips with no id, an
unparseable schedule, or a writeback for an unplanned
platform / without a post id all raise CapabilityError.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
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
_PLATFORMS = ("tiktok", "instagram", "youtube")


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"edit.publish_plan: {what} must be a non-empty string")
    return value.strip()


def _parse_schedule(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError("edit.publish_plan: scheduled_at must be an ISO-8601 string")
    text = value.strip()
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CapabilityError("edit.publish_plan: scheduled_at is not a parseable ISO-8601 timestamp") from exc
    return text


def build_publish_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise CapabilityError("edit.publish_plan: plan must be a JSON object")
    title = _require_str(plan.get("title"), "title")
    if len(title) > 100:
        raise CapabilityError("edit.publish_plan: title must be at most 100 characters")
    description = plan.get("description", "")
    if not isinstance(description, str):
        raise CapabilityError("edit.publish_plan: description must be a string")
    if len(description) > 5000:
        raise CapabilityError("edit.publish_plan: description must be at most 5000 characters")
    platforms = plan.get("platforms")
    if not isinstance(platforms, list) or not platforms:
        raise CapabilityError("edit.publish_plan: platforms must be a non-empty list")
    seen: set[str] = set()
    for p in platforms:
        if p not in _PLATFORMS:
            raise CapabilityError(f"edit.publish_plan: unknown platform {p!r}")
        if p in seen:
            raise CapabilityError(f"edit.publish_plan: duplicate platform {p!r}")
        seen.add(p)
    clips_raw = plan.get("clips", [])
    if not isinstance(clips_raw, list) or not clips_raw:
        raise CapabilityError("edit.publish_plan: clips must be a non-empty list")
    clip_ids: set[str] = set()
    clips: list[dict[str, Any]] = []
    for c in clips_raw:
        if not isinstance(c, dict):
            raise CapabilityError("edit.publish_plan: each clip must be a JSON object")
        cid = _require_str(c.get("clip_id"), "clip.clip_id")
        if cid in clip_ids:
            raise CapabilityError(f"edit.publish_plan: duplicate clip_id {cid!r}")
        clip_ids.add(cid)
        clips.append({"clip_id": cid, "file": c.get("file")})
    thumb = plan.get("thumbnail", {})
    if not isinstance(thumb, dict):
        raise CapabilityError("edit.publish_plan: thumbnail must be a JSON object")
    thumb_text = thumb.get("text", "")
    if not isinstance(thumb_text, str):
        raise CapabilityError("edit.publish_plan: thumbnail.text must be a string")
    if len(thumb_text) > 30:
        raise CapabilityError("edit.publish_plan: thumbnail.text must be at most 30 characters")
    thumb_image = thumb.get("image_ref")
    if thumb_image is not None and not isinstance(thumb_image, str):
        raise CapabilityError("edit.publish_plan: thumbnail.image_ref must be a string")
    scheduled_at = _parse_schedule(plan.get("scheduled_at"))
    fingerprint = hashlib.sha256(json.dumps(
        {"title": title, "platforms": platforms, "clips": sorted(clip_ids)},
        ensure_ascii=False, sort_keys=True,
    ).encode("utf-8")).hexdigest()[:12]
    return {
        "plan_id": f"pub_{fingerprint}",
        "title": title,
        "description": description,
        "platforms": list(platforms),
        "clips": clips,
        "thumbnail": {
            "text": thumb_text,
            "image_ref": thumb_image,
            "status": "ready" if thumb_image else "image_pending",
        },
        "scheduled_at": scheduled_at,
        "schedule_status": "scheduled_pending" if scheduled_at else "unscheduled",
        "per_platform": [
            {"platform": p, "status": "awaiting_credentials", "post_id": None, "posted_at": None}
            for p in platforms
        ],
        "publish_status": "dry_run_not_posted",
        "posted_note": "No post was made by this capability; platforms await credentials.",
    }


def record_publish_result(plan: dict[str, Any], platform: str, post_id: str, posted_at: str) -> dict[str, Any]:
    """Mark one platform posted from caller-supplied evidence only."""
    if not isinstance(plan, dict) or not isinstance(plan.get("per_platform"), list):
        raise CapabilityError("edit.publish_plan: plan must be a built publish plan")
    if platform not in [p["platform"] for p in plan["per_platform"]]:
        raise CapabilityError(f"edit.publish_plan: platform {platform!r} is not in this plan")
    post_id = _require_str(post_id, "post_id")
    posted_at = _parse_schedule(posted_at)
    if posted_at is None:
        raise CapabilityError("edit.publish_plan: posted_at must be an ISO-8601 timestamp")
    out = json.loads(json.dumps(plan, ensure_ascii=False))
    for entry in out["per_platform"]:
        if entry["platform"] == platform:
            entry["status"] = "posted"
            entry["post_id"] = post_id
            entry["posted_at"] = posted_at
    out["publish_status"] = "posted" if all(e["status"] == "posted" for e in out["per_platform"]) else "partially_posted"
    out["posted_note"] = "Post ids are caller-supplied evidence; this capability did not verify them on any platform."
    return out


def _render_publish_plan(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = build_publish_plan(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "publish_plan.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={
            "report_json": str(report),
            "plan_id": result["plan_id"],
            "publish_status": result["publish_status"],
        },
    )


def register_publish_plan_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="edit.publish_plan",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "properties": {"plan": {"type": "object"}},
            "required": ["plan"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render_publish_plan,
        has_media_output=False,
        description=(
            "Publish planning, dry-run only (clean-room): validated title, "
            "description, platforms, thumbnail spec, schedule and clips, "
            "with a caller-evidence result writeback. Never posts to any "
            "platform; all platforms start awaiting_credentials."
        ),
        line="edit",
    ))
    return ["edit.publish_plan"]


register_publish_plan_capabilities_once()
