"""Supplementary multimodal audio-video review (``qa.multimodal_review``).

This is a supplement to ``qa.final_qc_gate`` only. It never
replaces that gate: a deterministic gate result is required
input, it is carried through verbatim in the first column of
the report, and this module adds no gate verdict of its own.

Method borrowed from the BeefTV audio-video check shape
(a model watches the finished film and comments on cuts and
captions, with the source documentation itself warning that
the model can miss cut points and miswrite homophones),
rewritten from scratch for hevi; see
PRODUCTIZATION_ATTRIBUTION.md. No upstream text is used here.

Report shape, two columns and nothing else:

* Column one, ``deterministic_gate_result``: the caller's
  ``qa.final_qc_gate`` report, copied verbatim. When the
  caller supplies no such result, this module refuses rather
  than reviewing alone -- a supplement with nothing to
  supplement is not a review.
* Column two, ``model_reference_opinion``: reference opinion
  only, never a gate result. It is always labelled with the
  two known failure modes (the model may miss cut points and
  may miswrite homophones) and with ``requires_human_check``
  set true. Captions, picture and local text layout in the
  opinion still need a human check before delivery.

The model is injected by the caller as ``model_fn``. This
module builds in no model, reads no credentials from anywhere
and makes no network call: when no model function is
injected, when it returns nothing usable, or when it raises,
the report contains only the deterministic column plus a
plain ``model_unavailable`` status and reason. An opinion is
never invented to fill the second column.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

DISCLAIMER = (
    "模型检查仅为参考意见：模型可能漏报剪点、可能写错同音词，"
    "字幕、画面与局部文字排版仍需人工核对；本意见不改变确定性门结果。"
)


def _fail(message: str) -> None:
    raise CapabilityError(f"qa.multimodal_review: {message}")


def _wrap_opinion(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        content = copy.deepcopy(raw)
    elif isinstance(raw, str):
        content = {"text": raw}
    else:
        return {}
    return {
        "model_raw": content,
        "may_miss_cut_points": True,
        "may_miswrite_homophones": True,
        "requires_human_check": True,
        "disclaimer": DISCLAIMER,
    }


def review(
    *,
    deterministic_result: dict[str, Any] | None,
    model_fn: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Build the two-column supplement report.

    ``deterministic_result`` must be a non-empty
    ``qa.final_qc_gate`` report supplied by the caller.
    ``model_fn``, when given, is called with no arguments and
    must return a dict (or a plain text opinion); anything
    else leaves the second column empty, honestly labelled.
    """
    if not isinstance(deterministic_result, dict) or not deterministic_result:
        _fail(
            "a qa.final_qc_gate result is required; this module is "
            "only a supplement to that gate and cannot replace it"
        )
    opinion: dict[str, Any] | None = None
    model_status = "unavailable"
    unavailable_reason: str | None = None
    if model_fn is None:
        unavailable_reason = (
            "no model function injected by the caller; only the "
            "deterministic gate result is reported, no opinion invented"
        )
    else:
        try:
            raw = model_fn()
        except Exception as exc:
            unavailable_reason = f"model call failed: {exc}"
            raw = None
        if unavailable_reason is None:
            if raw is None:
                unavailable_reason = (
                    "model function returned no opinion; only the "
                    "deterministic gate result is reported"
                )
            else:
                wrapped = _wrap_opinion(raw)
                if wrapped:
                    opinion = wrapped
                    model_status = "provided"
                else:
                    unavailable_reason = (
                        "model function returned an unusable opinion; "
                        "it was discarded, not rewritten into one"
                    )
    report: dict[str, Any] = {
        "capability": "qa.multimodal_review",
        "role": "supplement_to_qa.final_qc_gate",
        "does_not_replace": "qa.final_qc_gate",
        "human_check_required": True,
        "columns": {
            "deterministic_gate_result": copy.deepcopy(deterministic_result),
            "model_reference_opinion": opinion,
        },
        "model_status": model_status,
    }
    if unavailable_reason is not None:
        report["model_unavailable_reason"] = unavailable_reason
    return report


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
             aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # The registry path injects no model: it honestly yields the
    # deterministic column only, never an invented opinion.
    result: dict[str, Any] = {
        "capability": "qa.multimodal_review",
        **review(deterministic_result=params.get("deterministic_result")),
    }
    report_path = out_dir / "multimodal_review_report.json"
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "result": result},
    )


def register_multimodal_review_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.multimodal_review",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "deterministic_result": {"type": "object"},
                },
                "required": ["deterministic_result"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Supplementary multimodal audio-video review, only "
                "as a supplement to qa.final_qc_gate, never a "
                "replacement: the report has exactly two columns, "
                "the deterministic gate result carried through "
                "verbatim and a model reference opinion that is "
                "labelled as possibly missing cut points and "
                "miswriting homophones and still needing a human "
                "check; when no model is injected by the caller "
                "only the deterministic column is reported and no "
                "opinion is invented. This module builds in no "
                "model and performs no model call itself."
            ),
            line="qa",
        )
    )
    return ["qa.multimodal_review"]


register_multimodal_review_capabilities_once()
