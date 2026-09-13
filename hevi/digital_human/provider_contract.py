"""Provider contract boundary for optional digital-human runtimes."""

from __future__ import annotations

from pathlib import Path

from hevi.digital_human.duix_service import DuixUnavailable


async def generate_duix_avatar(
    *,
    reference: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    """Invoke the optional Duix adapter without exposing its runtime module."""
    from hevi.digital_human.duix_offline import generate_silent_duix

    try:
        return await generate_silent_duix(reference=reference, audio_path=audio_path, output_path=output_path)
    except DuixUnavailable:
        raise


def extract_duix_reference(reference: Path, destination: Path) -> Path:
    from hevi.digital_human.duix_offline import extract_reference_still

    return extract_reference_still(reference, destination)
