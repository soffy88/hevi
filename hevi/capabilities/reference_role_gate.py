"""Reference role gate (``qa.reference_role_gate``).

Clean-room rewrite of the *method* in ``hevi-vs-video-workflow-7steps.md``
step 2 ("references have jobs"): at most four reference images per
generation round, and each image does exactly one job:

* ``identity`` -- face, age, hairstyle. Governs who the person is.
* ``costume`` -- colour, fabric, pattern. Governs what they wear.
* ``pose`` -- the starting or key pose. Governs how they stand.
* ``scene`` -- background, light, space. Governs where they are.

Every image carries its role, a ``duty`` sentence naming what it
governs, a file binding (``file`` + ``sha256``), and a definition
review record (``reviewed`` exactly ``True``, plus ``reviewed_by``):
a definition image is reviewed before it enters a real shot, never
after. Two images sharing one role fail -- the jobs must not fight
each other -- and a fifth image fails: the cap is four, and the
round must choose.

Boundary with the H3 route (written into the verdict, not silently
merged): ``pipeline.scene_reference`` assembles H3 prompts under a
different budget -- 9 pictures / 3 voices, scene first, angles
next, cast last (``MAX_PICTURE_REFS`` / ``MAX_VOICES``). When a plan
declares ``route: "h3_scene_assembly"``, this gate does not apply
its four-image cap: it returns ``not_checked`` with the boundary
reason and the H3 budget cited, and the H3 gate remains the judge.
Any other route (including an absent route) is judged under the
four-image division of labour. The six-section H3 prompt structure
is not touched, redefined, or merged here.

This module judges plans only. It reads no image bytes and calls
no generator.
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

ROLES = ("identity", "costume", "pose", "scene")

MAX_REFERENCE_IMAGES = 4


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_reference_roles(plan: Any) -> dict[str, Any]:
    """Judge one reference round. Returns a report; never raises for a bad plan."""
    from hevi.capabilities.scene_reference import MAX_PICTURE_REFS, MAX_VOICES

    boundary = {
        "route": "generation",
        "h3_picture_budget": MAX_PICTURE_REFS,
        "h3_voice_budget": MAX_VOICES,
        "note": "Four-image division of labour applies. The H3 scene "
                "assembly budget (9 pictures / 3 voices) governs only "
                "plans that declare route 'h3_scene_assembly'.",
    }
    if not isinstance(plan, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "boundary": boundary,
            "roles": {},
            "issues": [{
                "code": "plan_not_object",
                "detail": "qa.reference_role_gate: reference plan must be "
                         "an object",
            }],
        }
    route = plan.get("route", "generation")
    if route == "h3_scene_assembly":
        return {
            "ok": True,
            "verdict": "not_checked",
            "boundary": {
                "route": route,
                "h3_picture_budget": MAX_PICTURE_REFS,
                "h3_voice_budget": MAX_VOICES,
                "note": "Boundary: this plan assembles an H3 scene prompt, "
                        "so the H3 slot budget (9 pictures / 3 voices, "
                        "scene first, angles next, cast last) governs and "
                        "the four-image division of labour does not apply. "
                        "Judged by pipeline.scene_reference, not here.",
            },
            "roles": {},
            "issues": [],
        }

    issues: list[dict[str, Any]] = []
    images = plan.get("images")
    roles: dict[str, dict[str, Any]] = {}
    if not isinstance(images, list) or not images:
        issues.append({
            "code": "images_missing",
            "detail": "qa.reference_role_gate: reference plan needs a "
                     "non-empty 'images' list; an unreferenced generation "
                     "round has no definition to hold",
        })
        return {"ok": False, "verdict": "fail", "boundary": boundary,
                "roles": roles, "issues": issues}
    if len(images) > MAX_REFERENCE_IMAGES:
        issues.append({
            "code": "too_many_images",
            "detail": f"qa.reference_role_gate: {len(images)} reference "
                     f"images exceed the cap of {MAX_REFERENCE_IMAGES}; "
                     "one round may carry at most four, each doing one job",
        })
    for index, image in enumerate(images):
        label = f"image {index + 1}"
        if not isinstance(image, dict):
            issues.append({
                "code": "image_not_object",
                "detail": f"qa.reference_role_gate: {label} must be an object",
            })
            continue
        role = image.get("role")
        if role not in ROLES:
            issues.append({
                "code": "bad_role",
                "detail": f"qa.reference_role_gate: {label} role must be one "
                         f"of {', '.join(ROLES)}, not {role!r}",
            })
            continue
        if role in roles:
            issues.append({
                "code": "duplicate_role",
                "detail": f"qa.reference_role_gate: role '{role}' is "
                         f"claimed by two images; one job, one image -- "
                         "the jobs must not fight each other",
            })
            continue
        entry: dict[str, Any] = {"role": role}
        if not _is_nonempty_str(image.get("duty")):
            issues.append({
                "code": f"missing_duty_{role}",
                "detail": f"qa.reference_role_gate: {label} (role '{role}') "
                         "needs a non-empty 'duty' naming what it governs",
            })
        else:
            entry["duty"] = str(image["duty"]).strip()
        if not _is_nonempty_str(image.get("file")):
            issues.append({
                "code": f"missing_file_{role}",
                "detail": f"qa.reference_role_gate: {label} (role '{role}') "
                         "needs a 'file' binding",
            })
        else:
            entry["file"] = str(image["file"]).strip()
        if not _is_nonempty_str(image.get("sha256")):
            issues.append({
                "code": f"missing_sha256_{role}",
                "detail": f"qa.reference_role_gate: {label} (role '{role}') "
                         "needs a 'sha256' binding so the file is the file "
                         "that was reviewed",
            })
        else:
            entry["sha256"] = str(image["sha256"]).strip()
        if image.get("reviewed") is not True:
            issues.append({
                "code": f"unreviewed_{role}",
                "detail": f"qa.reference_role_gate: {label} (role '{role}') "
                         "is a definition image that has not been reviewed; "
                         "definition images are reviewed before they enter "
                         "a real shot, never after (reviewed must be "
                         "exactly true)",
            })
        elif not _is_nonempty_str(image.get("reviewed_by")):
            issues.append({
                "code": f"missing_reviewer_{role}",
                "detail": f"qa.reference_role_gate: {label} (role '{role}') "
                         "was reviewed but names no reviewer; a review "
                         "without a reviewer is not a record",
            })
        else:
            entry["reviewed_by"] = str(image["reviewed_by"]).strip()
        roles[role] = entry
    # Roles are a closed menu, not a mandatory set: a round may
    # carry fewer than four images, but every image it carries must
    # claim exactly one role. An image with no role fails above
    # (bad_role); an absent role is simply a job this round does
    # not ask a reference image to do.
    ok = not issues
    return {"ok": ok, "verdict": "pass" if ok else "fail",
            "boundary": boundary, "roles": roles, "issues": issues}


def authorize_reference_roles(plan: Any) -> dict[str, Any]:
    """Approve a reference round, or refuse it loudly (raises CapabilityError)."""
    report = check_reference_roles(plan)
    if not report["ok"]:
        raise CapabilityError(
            "qa.reference_role_gate: reference round refused: "
            + "; ".join(i["detail"] for i in report["issues"])
        )
    return report


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = authorize_reference_roles(params.get("plan"))
    report_path = out_dir / "reference_role_gate.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_reference_role_gate_capabilities_once() -> list[str]:
    """Register ``qa.reference_role_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.reference_role_gate",
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
                "Reference role gate: at most four reference images per "
                "generation round, each doing exactly one job "
                "(identity / costume / pose / scene), each with a duty "
                "sentence, a file+sha256 binding, and a definition "
                "review record. Plans declaring the H3 scene assembly "
                "route are left not_checked under the H3 slot budget "
                "instead of this cap. Judges plans only."
            ),
            line="qa",
        )
    )
    return ["qa.reference_role_gate"]


register_reference_role_gate_capabilities_once()
