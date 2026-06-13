from pathlib import Path
from typing import Any

from oprim import SpeakerLine, vibevoice_synthesize


async def synthesize_dialogue(
    *,
    config: Any,
    script: list[SpeakerLine],
    output_path: Path,
    watermark: bool = True,  # 强制默认 True (safety, 微软要求)
) -> Path:
    """Multi-speaker TTS wrapper for VibeVoice.

    Single speaker = script of length 1.
    Watermark is forced to True by default for Responsible AI compliance.
    """
    if not script:
        raise ValueError("Script cannot be empty")

    return await vibevoice_synthesize(  # type: ignore[no-any-return, operator]
        config=config,
        script=script,
        output_path=output_path,
        watermark=watermark,
    )
