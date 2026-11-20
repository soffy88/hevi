"""Xiaoya avatar asset gate (``qa.xiaoya_avatar_asset_gate``).

A fixed host needs one declared face, one declared motion
source, and one declared name. The branch under review keeps
two avatar keys: ``xiaoya_d`` (an AI-generated face with no
real-person portrait) and ``xiaoya_e`` (an AI-generated face
supplied by the owner, the runtime default). A third key,
``v1``, is the Pexels live-action control group. Motion clips
come from Pexels live-action footage under the Pexels License
(free commercial use, no attribution required) and carry no
model release, so they are a grey area as the fixed host's
motion source. A same-named practice feature elsewhere is a
different thing and must never be mistaken for this host.

Clean-room restatement of the method found in the
``live-parity`` branch checkout (see
``DIGITAL_HOST_IMPROVEMENT_ATTRIBUTION.md``). This gate judges
the shape of an asset declaration only; it never loads a
video, an image, or a weight file, and it never starts a
stream. The banned name below appears only as a refused
literal: the name is not revived here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# Avatar keys kept by the branch under review.
AVATAR_KEYS: frozenset[str] = frozenset({"xiaoya_d", "xiaoya_e", "v1"})

# The runtime default when no key is set. The gate still
# requires an explicit key: a default is not a declaration.
DEFAULT_AVATAR_KEY = "xiaoya_e"

# Face sources the gate accepts. A real person's photo is
# refused outright: no impersonation of a real person.
FACE_SOURCES: frozenset[str] = frozenset({"ai_generated", "provided"})

# Motion sources the gate accepts.
MOTION_SOURCES: frozenset[str] = frozenset({"pexels", "ai_generated"})

# Refused as a host name. It appears here only to be refused;
# the host is called by its plain name, never by this one.
BANNED_NAME = "赛博小雅"

# A same-named practice feature in another product: different
# thing, never this host.
WRONG_ORIGIN = "mneme_xiaoya_practice"


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_xiaoya_avatar_asset(asset: Any) -> dict[str, Any]:
    """Validate a Xiaoya avatar asset declaration.

    Verdicts are ``pass`` / ``fail`` only. The asset fails
    when it is not an object, when its avatar key is missing
    or outside the closed set, when its face source is a real
    person's photo or unknown, when the ``xiaoya_e`` face
    source is unconfirmed, when it claims the same-named
    practice feature as its origin, when Pexels motion is
    used as the fixed host's motion source without a model
    release, or when it uses the banned name.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(asset, dict):
        return fail("asset_not_object", "asset must be a JSON object")
    avatar_key = asset.get("avatar_key")
    if not isinstance(avatar_key, str) or avatar_key not in AVATAR_KEYS:
        return fail(
            "unknown_avatar_key",
            "avatar_key must be one of xiaoya_d, xiaoya_e, v1; "
            "the runtime default is xiaoya_e but the gate needs "
            "an explicit key",
        )
    face_source = asset.get("face_source")
    if face_source == "real_person_photo":
        return fail(
            "real_person_portrait_banned",
            "a real person's photo is never a host face",
        )
    if face_source not in FACE_SOURCES:
        return fail(
            "face_source_unknown",
            "face_source must be ai_generated or provided",
        )
    if avatar_key == "xiaoya_e" and asset.get("face_source_confirmed") is not True:
        return fail(
            "face_source_unconfirmed",
            "the xiaoya_e face source must be confirmed by the owner "
            "before it is used as the fixed host face",
        )
    if asset.get("origin") == WRONG_ORIGIN:
        return fail(
            "wrong_xiaoya",
            "mneme xiaoya_practice is a same-named practice feature, not this host",
        )
    motion_source = asset.get("motion_source")
    if motion_source not in MOTION_SOURCES:
        return fail(
            "motion_source_unknown",
            "motion_source must be pexels or ai_generated",
        )
    if (
        motion_source == "pexels"
        and asset.get("is_fixed_host") is True
        and asset.get("model_release") is not True
    ):
        return fail(
            "motion_release_gap",
            "Pexels motion carries no model release: usable for a "
            "demo, not as the fixed host's motion source",
        )
    if asset.get("name_used") == BANNED_NAME:
        return fail(
            "banned_name",
            "that host name is not revived here; use the plain name",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
        "avatar_key": avatar_key,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_xiaoya_avatar_asset(params.get("asset"))
    report_path = out_dir / "xiaoya_avatar_asset_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_xiaoya_avatar_asset_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.xiaoya_avatar_asset_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "asset": {"type": "object"},
                },
                "required": ["asset"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "xiaoya avatar asset gate: closed avatar keys, "
                "AI-generated or owner-provided face only, Pexels "
                "motion release gap as fixed host, banned name refused."
            ),
        )
    )
    return ["qa.xiaoya_avatar_asset_gate"]


__all__ = [
    "AVATAR_KEYS",
    "BANNED_NAME",
    "DEFAULT_AVATAR_KEY",
    "FACE_SOURCES",
    "MOTION_SOURCES",
    "WRONG_ORIGIN",
    "check_xiaoya_avatar_asset",
    "register_xiaoya_avatar_asset_gate_capabilities_once",
]
