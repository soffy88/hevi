"""Xiaoya half-body lipsync gate (``qa.xiaoya_halfbody_lipsync_gate``).

The branch under review drives a half-body avatar with a
Wav2Lip ONNX model on CPU and measured, on its own sample
(23.25 s): talk render 20.68 fps, a talk realtime factor of
1.034, a lipsync correlation of 0.278, and a lag of -1 frame.
An RMS-driven geometric placeholder card is not lipsync and
must never be presented as one. The gate judges a render
report against those measured numbers only; it never runs a
model and never loads a weight file.

Clean-room restatement of the method found in the
``live-parity`` branch checkout (see
``DIGITAL_HOST_IMPROVEMENT_ATTRIBUTION.md``).
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

# The only lipsync engine with a measured run behind it.
ENGINE = "wav2lip_onnx_cpu"

# Model files the measured run loads.
MODEL_FILES: tuple[str, ...] = ("wav2lip_gan_96", "yoloface_8n", "silero_vad_v6")

# Bars taken from the measured run. Render fps and realtime
# factor use the run's own target (20 fps, realtime); the
# correlation bar is only "positive and recorded" because the
# measured 0.278 is weak and no stronger bar was ever measured.
MIN_TALK_RENDER_FPS = 20.0
MIN_REALTIME_FACTOR_TALK = 1.0
MAX_ABS_LAG_FRAMES = 2

# Measured values, kept as reference data in the report.
MEASURED_TALK_RENDER_FPS = 20.68
MEASURED_REALTIME_FACTOR_TALK = 1.034
MEASURED_LIPSYNC_CORR = 0.278
MEASURED_LIPSYNC_LAG_FRAMES = -1


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_xiaoya_halfbody_lipsync(report: Any) -> dict[str, Any]:
    """Validate a half-body lipsync render report.

    Verdicts are ``pass`` / ``fail`` only. The report fails
    when it is not an object, when its engine is not the
    measured Wav2Lip ONNX CPU engine, when any model file is
    missing, when it is really the RMS placeholder card, when
    talk render fps is below the measured bar, when the talk
    realtime factor is below 1, when no positive lipsync
    correlation is recorded, when the lag is outside two
    frames, or when no sample duration is recorded.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(report, dict):
        return fail("report_not_object", "report must be a JSON object")
    if report.get("engine") != ENGINE:
        return fail(
            "engine_unsupported",
            "only the measured wav2lip_onnx_cpu engine is accepted; "
            "any other engine is an unmeasured claim",
        )
    model_files = report.get("model_files")
    if not isinstance(model_files, dict) or any(
        model_files.get(name) is not True for name in MODEL_FILES
    ):
        return fail(
            "model_files_missing",
            "all three model files must be present: wav2lip_gan_96, yoloface_8n, silero_vad_v6",
        )
    if report.get("uses_placeholder_card") is True:
        return fail(
            "placeholder_not_lipsync",
            "an RMS-driven geometric placeholder card is not lipsync",
        )
    talk_fps = report.get("talk_render_fps")
    if not _is_number(talk_fps) or talk_fps < MIN_TALK_RENDER_FPS:
        return fail(
            "render_fps_below_bar",
            "talk render fps must be at least 20 (measured 20.68)",
        )
    realtime_factor = report.get("realtime_factor_talk")
    if not _is_number(realtime_factor) or realtime_factor < MIN_REALTIME_FACTOR_TALK:
        return fail(
            "not_realtime",
            "talk realtime factor must be at least 1 (measured 1.034)",
        )
    corr = report.get("lipsync_corr")
    if not _is_number(corr) or corr <= 0:
        return fail(
            "lipsync_corr_missing",
            "a positive lipsync correlation must be recorded "
            "(measured 0.278, weak; the value is recorded, not hidden)",
        )
    lag = report.get("lipsync_lag_frames")
    if not isinstance(lag, int) or isinstance(lag, bool) or abs(lag) > MAX_ABS_LAG_FRAMES:
        return fail(
            "lag_out_of_tolerance",
            "lipsync lag must be within two frames (measured -1)",
        )
    duration = report.get("sample_duration_s")
    if not _is_number(duration) or duration <= 0:
        return fail(
            "sample_duration_missing",
            "a sample duration in seconds must be recorded",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
        "talk_render_fps": talk_fps,
        "realtime_factor_talk": realtime_factor,
        "lipsync_corr": corr,
        "lipsync_lag_frames": lag,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_xiaoya_halfbody_lipsync(params.get("report"))
    report_path = out_dir / "xiaoya_halfbody_lipsync_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_xiaoya_halfbody_lipsync_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.xiaoya_halfbody_lipsync_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "report": {"type": "object"},
                },
                "required": ["report"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "xiaoya half-body lipsync gate: measured Wav2Lip ONNX "
                "CPU run only, model files present, realtime factor "
                "at least 1, positive lipsync correlation recorded, "
                "placeholder card refused."
            ),
        )
    )
    return ["qa.xiaoya_halfbody_lipsync_gate"]


__all__ = [
    "ENGINE",
    "MAX_ABS_LAG_FRAMES",
    "MEASURED_LIPSYNC_CORR",
    "MEASURED_LIPSYNC_LAG_FRAMES",
    "MEASURED_REALTIME_FACTOR_TALK",
    "MEASURED_TALK_RENDER_FPS",
    "MIN_REALTIME_FACTOR_TALK",
    "MIN_TALK_RENDER_FPS",
    "MODEL_FILES",
    "check_xiaoya_halfbody_lipsync",
    "register_xiaoya_halfbody_lipsync_gate_capabilities_once",
]
