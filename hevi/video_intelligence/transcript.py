"""Transcript ingestion accepts existing evidence; it never invents speech."""

from __future__ import annotations

from .models import StrictModel


class TranscriptSegment(StrictModel):
    segment_id: str
    start_ms: int
    end_ms: int
    speaker: str | None = None
    text: str
    source: str
    confidence: float | None = None


def validate_transcript_alignment(segments: list[TranscriptSegment], duration_ms: int) -> list[str]:
    errors: list[str] = []
    previous_end = 0
    for segment in segments:
        if segment.end_ms <= segment.start_ms:
            errors.append(f"TRANSCRIPT_ALIGNMENT_FAILED:{segment.segment_id}")
        if segment.start_ms < previous_end:
            errors.append(f"TRANSCRIPT_OVERLAP:{segment.segment_id}")
        if segment.end_ms > duration_ms:
            errors.append(f"TRANSCRIPT_OUT_OF_RANGE:{segment.segment_id}")
        previous_end = segment.end_ms
    return errors
