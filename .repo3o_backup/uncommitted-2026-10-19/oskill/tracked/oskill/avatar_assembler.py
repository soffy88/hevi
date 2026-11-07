"""oskill.avatar_assembler — Per-shot avatar video assembly.

Example:
    >>> from oskill.avatar_assembler import avatar_assembler
    >>> videos = await avatar_assembler(shots=plans, portrait_path=Path("face.png"), ...)

Raises:
    AvatarAssemblerError: Assembly failed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from oskill._schemas import ShotPlan


class AvatarAssemblerError(Exception):
    """Avatar assembly failed."""


async def avatar_assembler(
    *,
    shots: list[ShotPlan],
    portrait_path: Path,
    tts_provider: str,
    avatar_provider: str,
    output_dir: Path,
    concurrency: int = 2,
) -> list[Path]:
    """Assemble avatar videos for each shot (TTS + avatar generation).

    Args:
        shots: List of ShotPlan with tts_text.
        portrait_path: Face/portrait image for avatar.
        tts_provider: TTS provider name.
        avatar_provider: Avatar provider name.
        output_dir: Directory for output mp4 files.
        concurrency: Max concurrent tasks (GPU-limited).

    Returns:
        List of output video paths.

    Raises:
        AvatarAssemblerError: On validation failure or generation error.

    Example:
        >>> videos = await avatar_assembler(shots=plans, portrait_path=Path("face.png"), ...)
    """
    if not shots:
        raise AvatarAssemblerError("shots must not be empty")

    if not portrait_path.exists():
        raise AvatarAssemblerError(f"Portrait not found: {portrait_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    from oprim import avatar_generate
    from oprim.tts_synthesize import tts_synthesize

    sem = asyncio.Semaphore(concurrency)

    async def _process(shot: ShotPlan, idx: int) -> Path:
        async with sem:
            audio_path = output_dir / f"{shot.shot_id}_audio.wav"
            video_path = output_dir / f"{shot.shot_id}.mp4"

            await tts_synthesize(
                provider=tts_provider,
                text=shot.tts_text,
                voice="zh-CN-XiaoxiaoNeural",
                output_path=audio_path,
            )
            await avatar_generate(
                provider=avatar_provider,
                portrait_image=portrait_path,
                audio_path=audio_path,
                output_path=video_path,
            )
            return video_path

    tasks = [_process(shot, i) for i, shot in enumerate(shots)]
    results: list[Path] = []

    for coro in asyncio.as_completed(tasks):
        try:
            results.append(await coro)
        except Exception as exc:
            raise AvatarAssemblerError(f"Avatar assembly failed: {exc}") from exc

    return sorted(results)
