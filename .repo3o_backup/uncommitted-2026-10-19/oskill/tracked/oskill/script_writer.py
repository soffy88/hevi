"""oskill.script_writer — LLM-based video script generation.

Example:
    >>> from oskill.script_writer import script_writer
    >>> script = await script_writer(topic="AI history", target_duration_s=180, llm=llm)

Raises:
    ScriptWriterError: Script generation failed.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

from oskill._schemas import Chapter, ChapterScript, Script, SpeakerLine, SubjectRef


class ScriptWriterError(Exception):
    """Script writing failed."""


def _narration_words_target(duration_s: float, *, words_per_min: int = 150) -> int:
    """按语速估算目标旁白字数(B8:治旁白过薄 —— LLM 需被明确告知要写多少)。

    此前 prompt 只给 target duration、不给字数量级,LLM 常严重欠写(如 1-5min 只出 ~7s
    旁白 → 成片被压缩)。据此给出 ~字数目标写进 prompt。
    """
    return max(20, int(duration_s / 60.0 * words_per_min))


async def script_writer(
    *,
    topic: str,
    target_duration_s: float = 180.0,
    llm: Any,
    template_prompt: str | None = None,
    language: str = "zh",
    subjects: list[SubjectRef] | None = None,
    chapter_mode: bool = False,
    num_characters: int = 1,
) -> Script | ChapterScript:
    """Generate a video script using LLM.

    Args:
        topic: Video topic/subject.
        target_duration_s: Target video duration in seconds. Default 180.
        llm: LLMCaller protocol instance.
        template_prompt: Optional industry template prompt to inject.
        language: Output language code.
        subjects: Optional character/subject references. When provided, each
            subject's name and description are appended to the system prompt.
            Default None — identical behaviour to all prior versions (backward compatible).
        chapter_mode: When True, return a ChapterScript with chapters and
            per-chapter SpeakerLine dialogues. Defaults to False (legacy
            behaviour — all existing callers are unaffected).
        num_characters: Number of speaking characters for multi-role dialogue
            (chapter_mode=True only; ignored when chapter_mode=False).

    Returns:
        Script (chapter_mode=False) or ChapterScript (chapter_mode=True).

    Raises:
        ScriptWriterError: On empty topic, LLM failure, or invalid response.

    Example:
        >>> script = await script_writer(topic="cats", target_duration_s=60, llm=llm)
        >>> from oskill._schemas import SubjectRef
        >>> script = await script_writer(
        ...     topic="cats", target_duration_s=60, llm=llm,
        ...     subjects=[SubjectRef(subject_id="c1", name="Whiskers", description="主角")],
        ... )
        >>> chapter_script = await script_writer(
        ...     topic="AI history", target_duration_s=600, llm=llm,
        ...     chapter_mode=True, num_characters=2,
        ... )
    """
    if not topic:
        raise ScriptWriterError("topic must not be empty")

    if chapter_mode:
        return await _script_writer_chapter(
            topic=topic,
            target_duration_s=target_duration_s,
            llm=llm,
            language=language,
            num_characters=num_characters,
        )

    # ── Legacy / chapter_mode=False path (backward compatible) ──────────────

    system = template_prompt or (
        f"You are a video script writer. Write in {language}. "
        f"Target duration: {target_duration_s}s. "
        "Return valid JSON with keys: title, description, scenes, estimated_duration_s. "
        "Each scene has: index, narration, duration_s, visual_description."
    )
    if template_prompt is None:
        # B8: 给出目标旁白字数,避免 LLM 欠写。
        _words = _narration_words_target(target_duration_s)
        system += (
            f" Write enough narration to fill ~{target_duration_s:.0f}s of speech "
            f"(aim for ~{_words} words total across all scenes); do not under-write."
        )

    if subjects:
        char_lines = "\n".join(
            f"{s.name}: {s.description}" if s.description else s.name for s in subjects
        )
        system = system + f"\n以下角色将出现在视频中:\n{char_lines}"

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Write a video script about: {topic}"},
    ]

    result = llm(messages=messages)
    if inspect.isawaitable(result):
        result = await result
    content = result.get("content", "")

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ScriptWriterError(f"LLM returned invalid JSON: {content[:200]}") from exc

    try:
        return Script.model_validate(data)
    except Exception as exc:
        raise ScriptWriterError(f"Script validation failed: {exc}") from exc


async def _script_writer_chapter(
    *,
    topic: str,
    target_duration_s: float,
    llm: Any,
    language: str,
    num_characters: int,
) -> ChapterScript:
    """chapter_mode=True implementation: multi-chapter + per-chapter dialogues."""
    num_chapters = _chapters_for_duration(target_duration_s)
    char_ids = [f"speaker_{i}" for i in range(num_characters)]

    system = (
        f"You are a long-form video script writer. Write in {language}. "
        f"Target total duration: {target_duration_s}s. "
        f"Divide into {num_chapters} chapters. "
        f"Characters: {', '.join(char_ids)}. "
        'Return JSON: {"chapters": [{"chapter_id", "title", "scenes": [...], '
        '"dialogues": [{"speaker_id", "text"}]}], '
        '"total_duration_s": float, "characters": [str]}. '
        "Each dialogue item has speaker_id (one of the characters) and text."
    )
    # B8: 给出目标旁白字数(总量 + 每章),避免 LLM 欠写导致成片被压缩。
    _words = _narration_words_target(target_duration_s)
    _per_ch = max(1, _words // max(1, num_chapters))
    system += (
        f" Write enough dialogue to fill ~{target_duration_s:.0f}s of speech "
        f"(~{_words} words total, ~{_per_ch} per chapter); do not under-write."
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Write a multi-chapter video script about: {topic}"},
    ]

    result = llm(messages=messages)
    if inspect.isawaitable(result):
        result = await result
    content = result.get("content", "")

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ScriptWriterError(
            f"LLM returned invalid JSON for chapter script: {content[:200]}"
        ) from exc

    try:
        chapters = [
            Chapter(
                chapter_id=ch.get("chapter_id", f"ch_{i}"),
                title=ch.get("title", f"Chapter {i + 1}"),
                scenes=ch.get("scenes", []),
                dialogues=[
                    SpeakerLine(
                        speaker_id=d.get("speaker_id", "speaker_0"),
                        text=d.get("text", ""),
                    )
                    for d in ch.get("dialogues", [])
                ],
            )
            for i, ch in enumerate(data.get("chapters", []))
        ]
        return ChapterScript(
            chapters=chapters,
            total_duration_s=float(data.get("total_duration_s", target_duration_s)),
            characters=list(data.get("characters", char_ids)),
        )
    except Exception as exc:
        raise ScriptWriterError(f"ChapterScript validation failed: {exc}") from exc


def _chapters_for_duration(duration_s: float) -> int:
    """Adaptive chapter count by duration archetype."""
    if duration_s < 300:  # < 5 min
        return 2
    if duration_s < 900:  # 5–15 min
        return 4
    if duration_s < 2700:  # 15–45 min
        return 8
    return 16  # 45+ min
