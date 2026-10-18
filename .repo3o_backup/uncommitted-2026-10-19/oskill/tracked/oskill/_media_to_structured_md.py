"""K-2: media_to_structured_md — LLM-structured markdown from a video transcript.

Composes:
- LLMCaller (injected): converts transcript into structured markdown
- Formatting logic: inserts timestamp anchors in [MM:SS](source_url?t=N) format

Output spec:
- Semantic sub-headings per topic (## Heading)
- Bullet points for key ideas per section
- Timestamp anchors [MM:SS](source_url?t=SECONDS) for time-referenced points
- No model essay or direct rewrite of the original transcript
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from oprim._media_types import TranscriptResult


async def media_to_structured_md(
    *,
    transcript: TranscriptResult | str,
    title: str,
    source_url: str,
    llm: Any,
) -> str:
    """Convert a video transcript into structured markdown via LLM.

    Args:
        transcript: TranscriptResult (uses segments for timestamps) or plain str.
        title: Video title — used as the markdown H1 heading.
        source_url: Source video URL — embedded in timestamp anchor links.
        llm: LLM caller conforming to LLMCaller protocol.

    Returns:
        Structured markdown string with headings, bullets, and timestamp anchors.

    Raises:
        ValueError: transcript is empty (empty text) or title is empty.
        Any exception from llm propagates as-is.
    """
    if not title.strip():
        raise ValueError("title must not be empty")

    if isinstance(transcript, TranscriptResult):
        if not transcript.text.strip():
            raise ValueError("transcript.text must not be empty")
        transcript_text = _format_transcript_with_timestamps(transcript)
        has_timestamps = bool(transcript.segments)
    else:
        if not str(transcript).strip():
            raise ValueError("transcript must not be empty")
        transcript_text = str(transcript)
        has_timestamps = False

    prompt = _build_prompt(
        transcript_text=transcript_text,
        title=title,
        source_url=source_url,
        has_timestamps=has_timestamps,
    )
    messages = [{"role": "user", "content": prompt}]

    coro_or_result = llm(messages=messages, max_tokens=4096)
    if asyncio.iscoroutine(coro_or_result):
        response = await coro_or_result
    else:
        response = coro_or_result

    md = _extract_text(response).strip()
    if not md:
        md = f"# {title}\n\n{transcript_text}"

    # Ensure H1 heading is present
    if not md.startswith("#"):
        md = f"# {title}\n\n{md}"

    # Post-process: ensure timestamp anchors use correct format [MM:SS](url?t=N)
    md = _fix_timestamp_anchors(md, source_url=source_url)

    return md


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_transcript_with_timestamps(tr: TranscriptResult) -> str:
    """Format segments as '[MM:SS] text' lines for LLM input."""
    lines = []
    for seg in tr.segments:
        start = int(seg.get("start", 0))
        mm, ss = divmod(start, 60)
        lines.append(f"[{mm:02d}:{ss:02d}] {seg.get('text', '').strip()}")
    return "\n".join(lines) if lines else tr.text


def _build_prompt(
    *,
    transcript_text: str,
    title: str,
    source_url: str,
    has_timestamps: bool,
) -> str:
    ts_instruction = (
        "Each section should include relevant timestamp anchors in the format "
        f"[MM:SS]({source_url}?t=SECONDS) where SECONDS is the integer seconds from the transcript. "
        "Place anchors after the relevant bullet point text."
        if has_timestamps
        else "No timestamps are available in this transcript."
    )

    return (
        f"You are a knowledge structuring assistant. Convert the following video transcript "
        f"into well-structured markdown notes.\n\n"
        f"Video title: {title}\n"
        f"Source URL: {source_url}\n\n"
        f"Requirements:\n"
        f"1. Start with a single # H1 heading using the video title.\n"
        f"2. Group content into semantic ## H2 sections by topic.\n"
        f"3. Use bullet points for key ideas within each section.\n"
        f"4. {ts_instruction}\n"
        f"5. Do NOT include the full transcript verbatim. Summarise and structure.\n"
        f"6. Write in the same language as the transcript.\n\n"
        f"Transcript:\n{transcript_text}"
    )


def _extract_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    if not isinstance(response, dict):
        return str(response)
    content = response.get("content", "")
    if isinstance(content, str):
        return content
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text", "")
    return ""


def _fix_timestamp_anchors(md: str, *, source_url: str) -> str:
    """Convert bare [MM:SS] markers to proper markdown links if source_url is available."""
    if not source_url:
        return md

    def _replace(m: re.Match) -> str:
        label = m.group(1)  # "MM:SS"
        parts = label.split(":")
        try:
            total_sec = int(parts[0]) * 60 + int(parts[1])
        except (IndexError, ValueError):
            return m.group(0)
        return f"[{label}]({source_url}?t={total_sec})"

    # Only replace bare [MM:SS] not already inside a link [MM:SS](...)
    return re.sub(r"\[(\d{2}:\d{2})\](?!\()", _replace, md)
