"""Word-timing warp contract, fake layer
(``video.word_timing_warp_contract``).

Contract-only warp for shot timing when a narration take is
replaced: the reference word timings (``words_ref``) are the
timing authority for the shots, and a new take with the same
words warps the shots onto the new timings without re-cutting.
The rule is strict: the word sequence must be identical in
both takes. If the script changed, the reference file is
deleted and the shots are re-timed; warping across different
words fails closed. Shot boundaries must fall on word
boundaries of the reference take. No audio is aligned, no
timing model is bundled or invoked, and no take is rendered:
``executed_here`` is always false, ``audio_rendered`` is
always false, and ``output_file`` is always null.

Language honesty: English-only timing models are never
presented as Chinese support. A plan that pairs a non-English
language with an English-only timing model fails, and the
Parakeet model named in the reviewed kit is refused for any
non-English language outright. Chinese word timing belongs
to hevi's separate Chinese alignment stack and is not
claimed here. See ANIMATION_SKILLS_ATTRIBUTION.md.
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

_EPS = 1e-3

# Known English-only timing model from the reviewed kit.
# Refused for any non-English language, whatever its
# english_only flag says.
_ENGLISH_ONLY_MODELS: frozenset[str] = frozenset({"parakeet"})


def _fail(message: str) -> None:
    raise CapabilityError(message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_words(words: Any, what: str) -> list[dict[str, Any]]:
    if not isinstance(words, list) or not words:
        _fail(f"{what} must be a non-empty list of timed words")
    checked: list[dict[str, Any]] = []
    previous_end: float | None = None
    for index, entry in enumerate(words):
        if not isinstance(entry, dict):
            _fail(f"{what}[{index}] must be an object")
        word = entry.get("word")
        if not isinstance(word, str) or not word.strip():
            _fail(f"{what}[{index}] must name a word")
        start = entry.get("start_s")
        end = entry.get("end_s")
        if not _is_number(start) or not _is_number(end):
            _fail(f"{what}[{index}] needs numeric start_s and end_s")
        if start < 0 or not start < end:
            _fail(f"{what}[{index}] needs 0 <= start_s < end_s")
        if previous_end is not None and start < previous_end - _EPS:
            _fail(f"{what} timings must not overlap or run backwards")
        previous_end = float(end)
        checked.append(
            {"word": word, "start_s": float(start), "end_s": float(end)}
        )
    return checked


def _map_time(
    ref_time: float,
    ref_words: list[dict[str, Any]],
    new_words: list[dict[str, Any]],
) -> float:
    """Map a reference time onto the new take, word by word.

    Times inside a word span scale linearly within the
    corresponding new word span; boundary times map to the
    corresponding boundary. Times before the first word map
    to the new take's first start, times after the last word
    to its last end.
    """
    if ref_time <= ref_words[0]["start_s"] + _EPS:
        return new_words[0]["start_s"]
    if ref_time >= ref_words[-1]["end_s"] - _EPS:
        return new_words[-1]["end_s"]
    for ref_word, new_word in zip(ref_words, new_words):
        if ref_word["start_s"] - _EPS <= ref_time <= ref_word["end_s"] + _EPS:
            span = ref_word["end_s"] - ref_word["start_s"]
            if span <= 0:
                return new_word["start_s"]
            ratio = (ref_time - ref_word["start_s"]) / span
            return new_word["start_s"] + ratio * (
                new_word["end_s"] - new_word["start_s"]
            )
    # Between words: hold at the next word's start.
    for ref_word, new_word in zip(ref_words, new_words):
        if ref_time < ref_word["start_s"]:
            return new_word["start_s"]
    return new_words[-1]["end_s"]


def compile_word_timing_warp_contract(plan: Any) -> dict[str, Any]:
    """Compile a word-timing warp contract from a plan.

    Raises :class:`CapabilityError` when the word sequences
    differ, when a shot boundary misses a word boundary, or
    when an English-only timing model is paired with a
    non-English language. The returned contract always
    carries ``executed_here: false`` and
    ``output_file: null``.
    """
    if not isinstance(plan, dict):
        _fail("word-timing warp plan must be a JSON object")
    language = plan.get("language")
    if not isinstance(language, str) or not language.strip():
        _fail("warp plan must declare a language")
    language = language.strip().lower()
    timing_model = plan.get("timing_model")
    if not isinstance(timing_model, dict):
        _fail("warp plan must declare a timing_model object")
    model_name = timing_model.get("name")
    if not isinstance(model_name, str) or not model_name.strip():
        _fail("timing_model must declare a name")
    english_only = timing_model.get("english_only")
    if not isinstance(english_only, bool):
        _fail("timing_model must declare english_only as true/false")
    if language != "en" and (
        english_only or model_name.strip().lower() in _ENGLISH_ONLY_MODELS
    ):
        _fail(
            "an English-only timing model cannot stand in for "
            f"{language} support; Chinese word timing belongs "
            "to hevi's separate Chinese alignment stack"
        )
    ref_words = _check_words(plan.get("reference_words"), "reference_words")
    new_words = _check_words(plan.get("new_take_words"), "new_take_words")
    if [w["word"] for w in ref_words] != [w["word"] for w in new_words]:
        _fail(
            "word sequences differ: the script changed, so the "
            "reference file must be deleted and shots re-timed; "
            "warping across different words is refused"
        )
    boundaries: set[float] = set()
    for word in ref_words:
        boundaries.add(word["start_s"])
        boundaries.add(word["end_s"])
    span_start = ref_words[0]["start_s"]
    span_end = ref_words[-1]["end_s"]

    def _on_boundary(value: float) -> bool:
        return any(abs(value - boundary) <= _EPS for boundary in boundaries)

    shots = plan.get("shots")
    if not isinstance(shots, list) or not shots:
        _fail("warp plan must declare a non-empty shots list")
    shots_out: list[dict[str, Any]] = []
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            _fail(f"shots[{index}] must be an object")
        shot_id = shot.get("id")
        if not isinstance(shot_id, str) or not shot_id.strip():
            _fail(f"shots[{index}] must declare an id")
        ref_start = shot.get("ref_start_s")
        ref_end = shot.get("ref_end_s")
        if not _is_number(ref_start) or not _is_number(ref_end):
            _fail(f"shots[{index}] needs numeric ref_start_s/ref_end_s")
        if not ref_start < ref_end:
            _fail(f"shots[{index}] needs ref_start_s < ref_end_s")
        if ref_start < span_start - _EPS or ref_end > span_end + _EPS:
            _fail(f"shots[{index}] lies outside the reference word span")
        if not _on_boundary(float(ref_start)) or not _on_boundary(float(ref_end)):
            _fail(
                f"shots[{index}] boundaries must fall on reference "
                "word boundaries"
            )
        shots_out.append(
            {
                "id": shot_id,
                "ref_start_s": float(ref_start),
                "ref_end_s": float(ref_end),
                "new_start_s": _map_time(float(ref_start), ref_words, new_words),
                "new_end_s": _map_time(float(ref_end), ref_words, new_words),
            }
        )
    return {
        "language": language,
        "timing_model": {"name": model_name, "english_only": english_only},
        "words_unchanged": True,
        "word_count": len(ref_words),
        "shots": shots_out,
        "timing_model_note": (
            "no timing model is bundled or invoked here; "
            "Chinese timing is a separate hevi alignment-stack case"
        ),
        "executed_here": False,
        "audio_rendered": False,
        "output_file": None,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_word_timing_warp_contract(params.get("plan"))
    contract_path = out_dir / "word_timing_warp_contract.json"
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={"contract_json": str(contract_path), "executed_here": False},
    )


def register_word_timing_warp_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.word_timing_warp_contract",
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
            layer="obase",
            description=(
                "Word-timing warp contract (contract only): "
                "shots re-timed onto a replacement take with "
                "identical words; script changes, off-boundary "
                "shots, and English-only models for other "
                "languages are refused."
            ),
        )
    )
    return ["video.word_timing_warp_contract"]


__all__ = [
    "compile_word_timing_warp_contract",
    "register_word_timing_warp_contract_capabilities_once",
]
