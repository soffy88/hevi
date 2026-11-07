"""Virtual-clock recording contract (``qa.virtual_clock_contract``).

Clean-room rewrite of the *discipline* described in
``hevi-vs-open-3d-skills.md`` section 2.8 (frame-capture): a page is
recordable only when it declares that every time source has been
replaced by a virtual clock, CSS motion is pinned, timed work runs
through a ``later`` queue, a ready flag is exposed, recording hides
its UI, and the renderer preserves its drawing buffer. This module
judges recording *plans* and declarations only; it performs no
browser capture and no encoding (see ``video.virtual_clock_recorder``
for the executor).

The virtual clock changes only the *time source*: page code still
reads time through ``performance.now`` / ``requestAnimationFrame``
timestamps, but those reads return virtual time. It does not change
the settle discipline: a recording must still pass the ``__hf``
settle confirmation (``qa.frame_adapter_contract``) and two runs
must produce identical frame hashes
(``qa.deterministic_render_gate``). A plan that describes the
capture as BeginFrame capture fails: this contract is not a
BeginFrame capture, and the wording must not claim otherwise.

No author-reported number is used here: no frame rate, no stall
rate, and no timing default appears in this module. The output
frame rate is a caller-supplied render parameter of the recorder,
not a threshold of this gate.

Failure contract: a malformed plan (not a JSON object, missing
``recording`` section) raises :class:`CapabilityError`. A
well-formed plan that omits a required declaration returns
``verdict: "fail"`` with named issues; it never raises.
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


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "message": message}
    issue.update(extra)
    return issue


def _is_obj(value: Any) -> bool:
    return isinstance(value, dict)


def check_virtual_clock_plan(plan: Any) -> dict[str, Any]:
    """Judge one recording plan against the virtual-clock contract."""
    if not _is_obj(plan):
        raise CapabilityError(
            "qa.virtual_clock_contract: plan must be a JSON object"
        )
    recording = plan.get("recording")
    if not _is_obj(recording):
        raise CapabilityError(
            "qa.virtual_clock_contract: plan requires a 'recording' object"
        )
    issues: list[dict[str, Any]] = []

    clock = recording.get("time_source_replacement")
    if not _is_obj(clock):
        issues.append(
            _issue(
                "time_source_replacement_missing",
                "recording must declare a 'time_source_replacement' object "
                "stating how performance.now, Date.now and rAF are replaced",
            )
        )
        clock = {}
    for field, label in (
        ("performance_now_replaced", "performance.now"),
        ("date_now_replaced", "Date.now"),
        ("raf_uses_virtual_time", "requestAnimationFrame"),
    ):
        if clock.get(field) is not True:
            issues.append(
                _issue(
                    "time_source_not_replaced",
                    f"recording must declare {label} replaced by the "
                    f"virtual clock ({field}=true); an undeclared time "
                    "source is not recordable",
                    field=field,
                )
            )
    if recording.get("css_pinned") is not True:
        issues.append(
            _issue(
                "css_not_pinned",
                "recording must declare CSS animations/transitions pinned "
                "(css_pinned=true); unpinned CSS motion runs on wall time",
            )
        )
    video_handling = recording.get("video_handling")
    if video_handling not in ("seek_per_frame", "no_video"):
        issues.append(
            _issue(
                "video_handling_missing",
                "recording must declare video_handling as "
                "'seek_per_frame' (each output frame seeks each video) "
                "or 'no_video' (the page contains no video element)",
                video_handling=video_handling,
            )
        )
    if recording.get("record_frame_hook") is not True:
        issues.append(
            _issue(
                "record_frame_hook_missing",
                "recording must declare a __recordFrame hook "
                "(record_frame_hook=true) for page-driven choreography",
            )
        )
    if recording.get("later_queue") is not True:
        issues.append(
            _issue(
                "later_queue_missing",
                "recording must declare a later() queue for timed work "
                "(later_queue=true); setTimeout/setInterval choreography "
                "runs on wall time and is not recordable",
            )
        )
    ready_flag = recording.get("ready_flag")
    if not isinstance(ready_flag, str) or not ready_flag.strip():
        issues.append(
            _issue(
                "ready_flag_missing",
                "recording must name a ready flag expression "
                "(ready_flag, e.g. 'window.__hfReady === true') that the "
                "recorder waits for before frame 0",
            )
        )
    if recording.get("hide_ui_during_recording") is not True:
        issues.append(
            _issue(
                "hide_ui_during_recording_missing",
                "recording must declare that recording-only UI is hidden "
                "during capture (hide_ui_during_recording=true)",
            )
        )
    if recording.get("preserve_drawing_buffer") is not True:
        issues.append(
            _issue(
                "preserve_drawing_buffer_missing",
                "recording must declare preserveDrawingBuffer: true on "
                "the WebGL renderer, or the captured frame may be blank",
            )
        )
    settle = recording.get("settle")
    if not _is_obj(settle):
        issues.append(
            _issue(
                "settle_missing",
                "recording must declare a 'settle' block: the __hf settle "
                "confirmation plus a two-run hash check",
            )
        )
    else:
        if settle.get("confirmation") != "__hf":
            issues.append(
                _issue(
                    "settle_not_hf",
                    "settle confirmation must be '__hf' (the __hf settle "
                    "confirmation of qa.frame_adapter_contract); a fixed "
                    "wait is not a confirmation",
                    confirmation=settle.get("confirmation"),
                )
            )
        if settle.get("two_runs_hash_identical") is not True:
            issues.append(
                _issue(
                    "settle_hash_check_missing",
                    "settle must declare two_runs_hash_identical=true: two "
                    "recordings of the same page must hash identically",
                )
            )
    capture_method = recording.get("capture_method")
    if isinstance(capture_method, str) and "beginframe" in capture_method.lower().replace("-", "").replace("_", ""):
        issues.append(
            _issue(
                "beginframe_mislabel",
                "the virtual clock only replaces the time source; it is "
                "not BeginFrame capture, and the plan must not describe "
                "it as BeginFrame capture",
                capture_method=capture_method,
            )
        )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "issues": issues,
        "note": (
            "The virtual clock replaces the time source only. A passing "
            "plan still requires __hf settle confirmation and two runs "
            "with identical frame hashes; this gate performs no capture."
        ),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_virtual_clock_plan(params.get("plan"))
    report_path = out_dir / "virtual_clock_contract.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"],
            "ok": report["verdict"] == "pass"},
    )


def register_virtual_clock_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.virtual_clock_contract",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {"plan": {"type": "object"}},
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Virtual-clock recording contract (open-3d-skills "
                "frame-capture discipline, clean-room): a recording plan "
                "must declare time-source replacement, pinned CSS, video "
                "seek handling, a __recordFrame hook, a later() queue, a "
                "ready flag, hidden recording UI, and "
                "preserveDrawingBuffer; the clock replaces the time "
                "source only and the recording must still pass __hf "
                "settle plus two-run hash identity. Judges plans only; "
                "never BeginFrame capture. See "
                "OPEN_3D_SKILLS_ATTRIBUTION.md."
            ),
            line="qa",
        )
    )
    return ["qa.virtual_clock_contract"]


register_virtual_clock_contract_capabilities_once()
