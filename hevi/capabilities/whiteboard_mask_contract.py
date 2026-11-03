"""Whiteboard reveal mask contract (``video.whiteboard_mask_contract``).

Clean-room restatement of the method in ``hevi-vs-explainer-skills-9.md``
section 2 item 9 (Whiteboard Explainer): a finished drawing is
revealed row by row under a snake-shaped mask, paced by word-level
timestamps, with a hand riding the mask tip. This module is the
contract for that engine -- it is NOT the engine:

* ``hyperframes_connected`` is always ``False`` in every record this
  module emits. hevi has no HyperFrames engine; the name ``hyperframes``
  elsewhere in hevi is a Ken Burns routing alias and must never be
  read as the reveal engine. This module must never claim the engine
  is connected.
* The fake fixture computes reveal coverage arithmetically from the
  declared element areas and the word timestamps. It renders no
  pixels and reads no image bytes.

The contract a real engine would have to satisfy: every element
reveals in word-timestamp order, the mask tip position is a function
of the current word, the hand is visible only while a stroke is
being drawn, and camera moves never coincide with a reveal.
"""

from __future__ import annotations

import hashlib
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

HYPERFRAMES_CONNECTED = False


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _engine_mark() -> dict[str, Any]:
    return {
        "hyperframes_connected": HYPERFRAMES_CONNECTED,
        "hyperframes_not_connected": True,
        "engine": "fake_fixture_only",
    }


def check_reveal_contract(plan: Any) -> dict[str, Any]:
    """Judge one reveal plan against the contract. Never raises for a plan.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []

    def issue(code: str, detail: str) -> dict[str, Any]:
        return {"code": code, "detail": detail}

    elements: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [issue("plan_not_object", "plan must be a JSON object")],
            "elements": [],
            **_engine_mark(),
        }
    raw_elements = plan.get("elements")
    if not isinstance(raw_elements, list) or not raw_elements:
        issues.append(
            issue("elements_missing", "plan must declare a non-empty elements list")
        )
        raw_elements = raw_elements if isinstance(raw_elements, list) else []
    previous_end: float | None = None
    for index, element in enumerate(raw_elements):
        if not isinstance(element, dict):
            issues.append(
                issue("element_not_object", f"elements[{index}] must be an object")
            )
            continue
        if not _is_nonempty_str(element.get("id")):
            issues.append(
                issue("element_id_missing", f"elements[{index}] must declare an id")
            )
        area = element.get("area")
        if not _is_number(area) or area <= 0:
            issues.append(
                issue(
                    "element_area_missing",
                    f"element {element.get('id')!r} must declare a positive area",
                )
            )
        start = element.get("reveal_start_s")
        end = element.get("reveal_end_s")
        if not _is_number(start) or not _is_number(end) or end <= start:
            issues.append(
                issue(
                    "reveal_window_invalid",
                    f"element {element.get('id')!r} must declare "
                    "reveal_start_s < reveal_end_s",
                )
            )
        elif previous_end is not None and float(start) < previous_end:
            issues.append(
                issue(
                    "reveal_order_broken",
                    f"element {element.get('id')!r} starts before the "
                    "previous element finished revealing",
                )
            )
        if _is_number(end):
            previous_end = float(end)
        hand = element.get("hand")
        if hand is not None and hand != "visible_during_stroke_only":
            issues.append(
                issue(
                    "hand_contract_broken",
                    f"element {element.get('id')!r} hand must be "
                    "'visible_during_stroke_only'",
                )
            )
        elements.append({"id": element.get("id"), "area": area})
    word_times = plan.get("word_times")
    if not isinstance(word_times, list) or not word_times:
        issues.append(
            issue(
                "word_times_missing",
                "plan must declare word-level timestamps as its only time source",
            )
        )
    else:
        for position, stamp in enumerate(word_times):
            if not isinstance(stamp, dict) or not _is_nonempty_str(
                stamp.get("word")
            ) or not _is_number(stamp.get("t_s")):
                issues.append(
                    issue(
                        "word_time_invalid",
                        f"word_times[{position}] must declare word and t_s",
                    )
                )
    camera = plan.get("camera_moves")
    if isinstance(camera, list):
        for move in camera:
            if isinstance(move, dict) and move.get("during_reveal") is True:
                issues.append(
                    issue(
                        "camera_during_reveal",
                        "camera moves must never coincide with a reveal",
                    )
                )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "elements": elements,
        **_engine_mark(),
    }


def reveal_fake(plan: Any) -> dict[str, Any]:
    """Run the fake reveal fixture: arithmetic coverage, no pixels.

    Raises ``CapabilityError`` when the plan fails the contract, so a
    fake record can never be produced for a failing plan.
    """
    report = check_reveal_contract(plan)
    if not report["ok"]:
        raise CapabilityError(
            "video.whiteboard_mask_contract: plan fails the reveal "
            "contract: "
            + "; ".join(f"{item['code']}: {item['detail']}" for item in report["issues"])
        )
    total_area = sum(
        float(element["area"]) for element in report["elements"]
    )
    canonical = json.dumps(report["elements"], ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "backend": "fake",
        "coverage": 1.0,
        "total_area": total_area,
        "element_count": len(report["elements"]),
        "fixture_sha256": digest,
        **_engine_mark(),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    record = reveal_fake(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    record_path = out_dir / "whiteboard_mask_contract_record.json"
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(record_path),
        qa={
            "report_json": str(record_path),
            "ok": True,
            "backend": "fake",
            **_engine_mark(),
        },
    )


def register_whiteboard_mask_contract_capabilities_once() -> list[str]:
    """Register the contract on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.whiteboard_mask_contract",
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
                "Whiteboard reveal mask contract: word-timestamp-ordered "
                "reveal, hand visible only during strokes, camera never "
                "moving during a reveal. Fake arithmetic fixture only; "
                "the HyperFrames engine is NOT connected and is never "
                "claimed to be."
            ),
            line="video",
        )
    )
    return ["video.whiteboard_mask_contract"]


register_whiteboard_mask_contract_capabilities_once()
