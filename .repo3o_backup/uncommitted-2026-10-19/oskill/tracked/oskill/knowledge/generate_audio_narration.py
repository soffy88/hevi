"""Generate audio narration for a substrate via oprim.tts_synthesize (edge-tts v1.1+)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from oprim._logging import log
from oprim.meta_db import open_meta_db
from oprim.tts_synthesize import tts_synthesize

from oskill.knowledge._context import meta_db_path, stratum_home

_CHUNK_WORDS = 120


@dataclass
class AudioNarrationResult:
    substrate_id: str
    audio_asset_id: str
    audio_path: str
    duration_seconds: float
    chunk_count: int
    cost_usd: float = 0.0


async def generate_audio_narration(
    substrate_id: str,
    voice: str = "default",
    speed: float = 1.0,
    chunk_words: int = _CHUNK_WORDS,
) -> AudioNarrationResult:
    """Generate audio narration for a substrate via edge-tts (oprim.tts_synthesize).

    Uses obase.ProviderRegistry("tts", "edge_tts") — requires register_default_providers()
    to have been called at application startup.

    Args:
        substrate_id: Target substrate ULID.
        voice: TTS voice name. "default" maps to zh-CN-XiaoxiaoNeural.
               Pass any edge-tts locale voice ID (e.g. "en-US-JennyNeural").
        speed: Speech rate multiplier. 1.0=normal, 1.2=+20%, 0.8=-20%.
        chunk_words: Unused (kept for API compatibility; edge-tts handles long text natively).

    Returns:
        AudioNarrationResult with path to generated .mp3 file.
    """
    text = _fetch_substrate_text(substrate_id)
    if not text:
        raise ValueError(f"substrate {substrate_id} has no text content")

    # Map "default" to Mandarin female voice; pass through explicit voice IDs unchanged.
    voice_id = "zh-CN-XiaoxiaoNeural" if voice == "default" else voice

    # Convert speed multiplier to edge-tts rate string (+/-N%)
    rate_pct = round((speed - 1.0) * 100)
    rate = f"+{rate_pct}%" if rate_pct >= 0 else f"{rate_pct}%"

    log.info(
        "generate_audio_narration.start",
        substrate_id=substrate_id,
        voice=voice_id,
        rate=rate,
        text_chars=len(text),
    )

    audio_dir = stratum_home() / "data" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    from python_ulid import ULID

    asset_id = str(ULID())
    out_path = audio_dir / f"{asset_id}.mp3"

    await tts_synthesize(
        provider="edge_tts",
        text=text,
        voice=voice_id,
        output_path=out_path,
        rate=rate,
    )

    audio_bytes = out_path.stat().st_size
    duration = _estimate_duration(out_path.read_bytes())

    _save_audio_asset(
        asset_id=asset_id,
        substrate_id=substrate_id,
        file_path=str(out_path),
        duration_seconds=duration,
        voice=voice_id,
        speed=speed,
        byte_size=audio_bytes,
    )

    log.info(
        "generate_audio_narration.done",
        substrate_id=substrate_id,
        asset_id=asset_id,
        duration_seconds=duration,
    )
    return AudioNarrationResult(
        substrate_id=substrate_id,
        audio_asset_id=asset_id,
        audio_path=str(out_path),
        duration_seconds=duration,
        chunk_count=1,
        cost_usd=0.0,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _fetch_substrate_text(substrate_id: str) -> str:
    """Fetch plaintext content from substrate derivative or source file."""
    db_path = meta_db_path()
    if not db_path.exists():
        return ""
    try:
        db = open_meta_db(db_path)
        # Prefer plaintext derivative
        rows = db.fetchall(
            "SELECT content FROM derivative WHERE substrate_id = ? AND kind = 'plaintext' LIMIT 1",
            [substrate_id],
        )
        if rows and rows[0][0]:
            db.close()
            return rows[0][0]
        # Fall back to markdown derivative
        rows = db.fetchall(
            "SELECT content FROM derivative WHERE substrate_id = ? AND kind = 'markdown' LIMIT 1",
            [substrate_id],
        )
        if rows and rows[0][0]:
            import re

            db.close()
            return re.sub(r"[#*`\[\]_]", "", rows[0][0]).strip()
        # Fall back to source_path
        rows = db.fetchall("SELECT source_path FROM substrates WHERE id = ?", [substrate_id])
        db.close()
        if rows and rows[0][0]:
            p = Path(rows[0][0])
            if p.exists() and p.suffix in {".txt", ".md"}:
                return p.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        log.warning("generate_audio_narration.fetch_text_failed", error=str(exc))
    return ""


def _chunk_text(text: str, max_words: int) -> list[str]:
    """Split text into word-count-bounded chunks at sentence boundaries."""
    import re

    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for sentence in sentences:
        words = len(sentence.split())
        if current_words + words > max_words and current:
            chunks.append(" ".join(current))
            current = [sentence]
            current_words = words
        else:
            current.append(sentence)
            current_words += words

    if current:
        chunks.append(" ".join(current))
    return [c for c in chunks if c.strip()]


def _concat_audio_parts(parts: list[bytes]) -> bytes:
    """Concatenate WAV parts. Simple raw concatenation — caller should use ffmpeg for production."""
    if len(parts) == 1:
        return parts[0]
    return b"".join(parts)


def _estimate_duration(audio_bytes: bytes) -> float:
    """Estimate audio duration from WAV byte size (rough: 16kHz mono 16-bit = 32000 B/s)."""
    return round(len(audio_bytes) / 32000.0, 2)


def _save_audio_asset(
    asset_id: str,
    substrate_id: str,
    file_path: str,
    duration_seconds: float,
    voice: str,
    speed: float,
    byte_size: int,
) -> None:
    db_path = meta_db_path()
    if not db_path.exists():
        return
    try:
        db = open_meta_db(db_path)
        meta = json.dumps({"voice": voice, "speed": speed})
        db.execute(
            """
            INSERT INTO audio_assets
                (id, substrate_id, file_path, duration_seconds, voice, speed, byte_size, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [asset_id, substrate_id, file_path, duration_seconds, voice, speed, byte_size, meta],
        )
        db.close()
    except Exception as exc:
        log.warning("generate_audio_narration.save_asset_failed", error=str(exc))
