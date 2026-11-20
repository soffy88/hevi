"""Multilingual subtitle workflow gate (``qa.multilingual_subtitle_workflow_gate``).

Clean-room restatement of the one-stop transcribe, translate,
format, deliver workflow of alwaysmavs/agent-skills
``video-subtitle-translator`` (see
``VIDEO_SKILLS_10_ATTRIBUTION.md``); no upstream code appears
in this gate.

hevi already owns the pieces: ASR (``audio.asr_transcribe``),
forced alignment (``audio.forced_align``), and the subtitle
contracts (``qa.whisperx_subtitle_contract``,
``edit.word_subtitle_contract``, ``image.native_subtitle_stitch``).
This gate owns only the workflow that strings them together:
transcribe, then translate, then format, then deliver, with a
declared source and target language, at least one of SRT/VTT/ASS,
a burn-in or soft-subtitle delivery, and CJK typesetting
whenever a CJK language is involved. The workflow runs on
hevi's own ASR plus LLM; the OO CLI (oomol) route is never
accepted.
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

STAGES = ("transcribe", "translate", "format", "deliver")
FORMATS = ("srt", "vtt", "ass")
CJK_LANGUAGES = ("zh", "zh-CN", "zh-TW", "ja", "ko")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _subsequence(stages: list[str]) -> bool:
    cursor = 0
    for wanted in STAGES:
        while cursor < len(stages) and stages[cursor] != wanted:
            cursor += 1
        if cursor >= len(stages):
            return False
        cursor += 1
    return True


def check_multilingual_subtitle_workflow(plan: Any) -> dict[str, Any]:
    """Validate a multilingual subtitle workflow plan.

    Verdicts are ``pass`` / ``fail`` only. A plan fails when
    it is not an object, when source or target language is
    missing or the two are equal, when the stages do not run
    transcribe, translate, format, deliver in that order, when
    no subtitle format is declared, when delivery is neither
    burn nor soft, when the ASR engine is not declared, when a
    CJK language is involved without CJK typesetting, or when
    the plan names the OO CLI route.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(plan, dict):
        return fail("plan_not_object", "subtitle workflow plan must be a JSON object")
    if (
        "oo_cli" in json.dumps(plan, ensure_ascii=False).lower()
        or "oomol" in json.dumps(plan, ensure_ascii=False).lower()
    ):
        return fail(
            "oo_cli_not_accepted",
            "the OO CLI (oomol) route is never accepted; the workflow "
            "runs on hevi's own ASR plus LLM",
        )
    for field in (
        "source_language",
        "target_language",
        "stages",
        "formats",
        "delivery",
        "asr_engine",
    ):
        if field not in plan:
            return fail("plan_field_missing", f"subtitle workflow plan must carry {field!r}")
    source = plan["source_language"]
    target = plan["target_language"]
    if not isinstance(source, str) or not source:
        return fail("source_language_missing", "source_language must be a non-empty string")
    if not isinstance(target, str) or not target:
        return fail("target_language_missing", "target_language must be a non-empty string")
    if source == target:
        return fail(
            "languages_equal",
            "source_language and target_language must differ",
        )
    stages = plan["stages"]
    if not isinstance(stages, list) or not all(isinstance(s, str) for s in stages):
        return fail("stages_not_list", "stages must be a list of stage names")
    if not _subsequence(stages):
        return fail(
            "stages_out_of_order",
            "stages must run transcribe, translate, format, deliver in that order",
        )
    formats = plan["formats"]
    if not isinstance(formats, list) or not formats:
        return fail("formats_empty", "formats needs at least one subtitle format")
    if any(fmt not in FORMATS for fmt in formats):
        return fail(
            "format_unknown",
            "formats must be a subset of: " + ", ".join(FORMATS),
        )
    if plan["delivery"] not in ("burn", "soft"):
        return fail(
            "delivery_unknown",
            "delivery must be burn (burned in) or soft (soft subtitles)",
        )
    if not isinstance(plan["asr_engine"], str) or not plan["asr_engine"]:
        return fail("asr_engine_missing", "asr_engine must be a non-empty string")
    if (source in CJK_LANGUAGES or target in CJK_LANGUAGES) and plan.get(
        "cjk_typesetting"
    ) is not True:
        return fail(
            "cjk_typesetting_missing",
            "a CJK language is involved, so cjk_typesetting must be declared true",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_multilingual_subtitle_workflow(params.get("plan"))
    report_path = out_dir / "multilingual_subtitle_workflow_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_multilingual_subtitle_workflow_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.multilingual_subtitle_workflow_gate",
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
            layer="oskill",
            description=(
                "Multilingual subtitle workflow gate: transcribe, translate, "
                "format, deliver in order, SRT/VTT/ASS, burn or soft delivery, "
                "CJK typesetting when a CJK language is involved; runs on "
                "hevi's own ASR plus LLM, never the OO CLI route."
            ),
        )
    )
    return ["qa.multilingual_subtitle_workflow_gate"]


__all__ = [
    "FORMATS",
    "STAGES",
    "check_multilingual_subtitle_workflow",
    "register_multilingual_subtitle_workflow_gate_capabilities_once",
]
