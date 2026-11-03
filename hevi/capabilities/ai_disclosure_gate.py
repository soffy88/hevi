"""AI disclosure gate (``qa.ai_disclosure_gate``).

Clean-room rewrite of a *method* only: AI-generated pictures are
labelled as such; an illustrative picture of a historical person is
marked illustrative; and the face of a living real person is never
generated. No text, code, or asset from any outside repository is
copied here. See VIBE_KNOWLEDGE_ATTRIBUTION.md.

The living-person rule is a hard refusal with no exception path:
no flag, no caller override, and no "with consent" parameter can
turn it into a pass. Consent handling for real likenesses lives
elsewhere; this gate refuses the generation outright.
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


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_ai_disclosure(plan: Any) -> dict[str, Any]:
    """Judge one AI disclosure plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []
    frames_out: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue("plan_not_object", "disclosure plan must be a JSON object")
            ],
            "frames": [],
        }
    frames = plan.get("frames")
    if not isinstance(frames, list) or not frames:
        issues.append(
            _issue("frames_missing", "plan must declare a non-empty frames list")
        )
        frames = frames if isinstance(frames, list) else []
    for index, frame in enumerate(frames):
        label = f"frames[{index}]"
        entry: dict[str, Any] = {"index": index, "ok": True, "issues": []}
        if not isinstance(frame, dict):
            entry["ok"] = False
            entry["issues"].append(
                _issue(f"{label}:not_object", "each frame must be an object")
            )
            frames_out.append(entry)
            continue
        depicts_real = frame.get("depicts_real_person") is True
        depicts_face = frame.get("depicts_face") is True
        status = frame.get("person_status")
        if depicts_real and depicts_face and status == "living":
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:living_person_face",
                    "the face of a living real person must never be "
                    "generated; this frame is refused with no exception",
                )
            )
        if depicts_real and status == "historical":
            if frame.get("illustrative_marker") is not True:
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:historical_unmarked",
                        "a picture of a historical person must carry "
                        "illustrative_marker=true",
                    )
                )
        if status is not None and status not in (
            "living",
            "historical",
            "fictional",
        ):
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:person_status_unknown",
                    "person_status must be one of living, historical, "
                    "fictional",
                )
            )
        if frame.get("ai_generated") is True:
            if not _is_nonempty_str(frame.get("disclosure")):
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:disclosure_missing",
                        "an AI-generated frame must carry a non-empty "
                        "disclosure label",
                    )
                )
        if entry["issues"]:
            entry["ok"] = False
            issues.extend(entry["issues"])
        frames_out.append(entry)
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "frames": frames_out,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_ai_disclosure(params.get("plan"))
    report_path = out_dir / "ai_disclosure.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_ai_disclosure_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.ai_disclosure_gate",
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
                "AI disclosure gate: AI-generated frames carry a "
                "disclosure label, historical persons are marked "
                "illustrative, and the face of a living real person is "
                "never generated."
            ),
        )
    )
    return ["qa.ai_disclosure_gate"]


__all__ = [
    "check_ai_disclosure",
    "register_ai_disclosure_gate_capabilities_once",
]
